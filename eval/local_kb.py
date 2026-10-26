"""Run the frozen benchmark on real BGE/KE and real cloud Agent loops."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

import httpx

from eval.pipelines import UsageLLM
from eval.local_kb_metrics import bootstrap_mean, generation_scores, latency_summary, retrieval_scores, summarize_retrieval
from eval.local_kb_setup import BASE_URL, COLLECTION, DATABASE, ROOT, STATE, audit, environment, read_dataset, save_json


def apply_paced_profile(config, questions):
    profile = json.loads((ROOT / "eval/benchmarks/local_kb_v1/paced.json").read_text(encoding="utf-8"))
    selected = []
    for language, category, count in profile["strata"]:
        group = sorted((q for q in questions if q["language"] == language and q["category"] == category),
                       key=lambda q: hashlib.sha256((profile["selection_seed"] + ":" + q["id"]).encode()).hexdigest())
        selected.extend(q["id"] for q in group[:count])
    if selected != profile["agent_question_ids"] or len(set(selected)) != 24:
        raise ValueError("Frozen paced selection does not match deterministic strata")
    return {**config, "paced_profile": profile, "agent_question_ids": selected,
            "concurrency": profile["concurrency"], "llm_min_interval_seconds": profile["llm_min_interval_seconds"],
            "budget": {**config["budget"], "deadline_seconds": profile["deadline_seconds"]}}


def agent_questions(config, questions):
    ids = config.get("agent_question_ids")
    return [q for q in questions if ids is None or q["id"] in ids]


class CallPacer:
    """One shared start-time interval across both variants, including failed attempts."""
    def __init__(self, interval, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.next_start = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            delay = self.next_start - self.clock()
            if delay > 0:
                await self.sleep(delay)
            self.next_start = self.clock() + self.interval


def append(path, row):
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def scrub(text):
    for key, value in os.environ.items():
        if value and ("API_KEY" in key or "API_SECRET" in key or key == "CONFIG_ENCRYPTION_KEY"):
            text = text.replace(value, "[REDACTED]")
    return text


def validate_run_identity(meta, previous=None):
    if meta["working_tree_dirty"]:
        raise ValueError("Commit the measured code before every formal execution, including resume")
    if previous is not None:
        for key in ("dataset_sha256", "freeze_sha256", "git_revision", "llm", "embedding", "chunks_sha256", "bindings_sha256", "qdrant_payload_sha256", "config"):
            if previous[key] != meta[key]:
                raise ValueError("Cannot resume a run after frozen data, model or code changes")


def metadata(config):
    from importlib.metadata import version
    sys.path.insert(0, str(ROOT / "researcher/deep_research_system"))
    from app.services.cloud_config_service import CloudConfigService
    cfg = CloudConfigService().resolve("llm")
    weights = Path(os.environ["EMBEDDING_MODEL_PATH"]) / "model.safetensors"
    with weights.open("rb") as stream:
        weights_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "mode": "live", "created_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "dataset_sha256": config["questions_sha256"],
        "freeze_sha256": hashlib.sha256((ROOT / "eval/benchmarks/local_kb_v1/freeze.json").read_bytes()).hexdigest(),
        "corpus": config["documents"], "database": DATABASE, "collection": COLLECTION,
        "embedding": {"model": os.environ["EMBEDDING_MODEL"], "revision": os.environ.get("EMBEDDING_MODEL_VERSION"), "dimension": 768, "weights_sha256": weights_hash},
        "llm": {"provider": cfg["provider"], "model": cfg["model"], "base_url": cfg["base_url"]},
        "packages": {name: version(name) for name in ["torch", "transformers", "sentence-transformers", "qdrant-client", "httpx"]},
        "hardware": {"platform": platform.platform(), "processor": platform.processor(), "logical_cores": os.cpu_count(), "embedding_device": "cpu"},
        "python": sys.version, "config": config, "human_verified": 0,
        "currency_cost_unknown": True, "currency_cost": None,
        "latency_policy": f"warmed sequential mixed retrieval HTTP; AgentLoop execution under concurrency={config['concurrency']}, includes cloud pacing, excludes task queue and runtime construction",
    }


def retrieval(config, questions, bindings, output):
    path = output / "retrieval.jsonl"
    existing = {(r["question_id"], r["repeat"], r["channel"]) for r in read_rows(path)}
    with httpx.Client(base_url=BASE_URL, timeout=90) as client:
        # Warm model and clients separately, never mix loading time into measured p95.
        warm_start = time.perf_counter()
        response = client.post("/api/v1/query/retrieve", json={"query": "benchmark model warmup", "top_k": 1, "filters": {"doc_type": ["law", "standard"]}, "debug": True})
        response.raise_for_status()
        save_json(output / "warmup.json", {"elapsed_ms": (time.perf_counter() - warm_start) * 1000})
        for repeat in range(config["retrieval_repeats"]):
            order = list(questions)
            random.Random(20261026 + repeat).shuffle(order)
            for i, question in enumerate(order, 1):
                keys = {(question["id"], repeat, channel) for channel in ("keyword", "vector", "hybrid")}
                if keys <= existing:
                    continue
                started = time.perf_counter()
                error = ""
                try:
                    response = client.post("/api/v1/query/retrieve", json={"query": question["question"], "top_k": 10, "filters": {"doc_type": ["law", "standard"]}, "debug": True})
                    response.raise_for_status()
                    payload = response.json()
                    ranked = {"hybrid": payload["chunks"], "vector": payload["debug"]["vector_results"], "keyword": payload["debug"]["keyword_results"]}
                except Exception as exc:
                    ranked = {channel: [] for channel in ("keyword", "vector", "hybrid")}
                    error = type(exc).__name__
                elapsed = (time.perf_counter() - started) * 1000
                for channel, chunks in ranked.items():
                    key = (question["id"], repeat, channel)
                    if key in existing:
                        continue
                    row = {"question_id": question["id"], "repeat": repeat, "channel": channel,
                           "status": "error" if error else "ok", "error": error, "http_elapsed_ms": elapsed,
                           "ranked_chunks": chunks, "scores": retrieval_scores(question, chunks, bindings)}
                    append(path, row)
                if i % 10 == 0:
                    print(f"Retrieval repeat {repeat + 1}: {i}/{len(order)}", flush=True)


class CorpusKBTool:
    name = "kb_search"

    def __init__(self, inner):
        self.inner = inner

    async def execute(self, call_id, **kwargs):
        # Same whole-corpus scope for every question; no gold document/title filters.
        kwargs["doc_type"] = ["law", "standard"]
        return await self.inner.execute(call_id, **kwargs)


class PacedLLM(UsageLLM):
    """Pace before counting dispatch, preserving the shared runner usage contract."""
    def __init__(self, inner, pacer):
        super().__init__(inner)
        self.pacer = pacer

    async def generate(self, messages, metadata=None):
        await self.pacer.wait()
        return await super().generate(messages, metadata)


class CappedLLM:
    def __init__(self, inner, budget, config):
        self.inner, self.budget, self.config = inner, budget, config

    async def generate(self, messages, metadata=None):
        remaining = max(1, self.budget.max_tokens - self.budget.tokens)
        params = {**(metadata or {}), "temperature": self.config["temperature"],
                  "max_tokens": min(remaining, self.config["max_output_tokens_per_call"])}
        return await self.inner.generate(messages, params)


class RecordingExecutor:
    """Keep actual tool attempts even when the loop later raises a provider error."""
    def __init__(self, inner):
        self.inner = inner
        self.events = []

    @property
    def tool_names(self):
        return self.inner.tool_names

    async def execute(self, name, **kwargs):
        self.events.append({"type": "tool_call", "tool": name, "args": kwargs})
        try:
            result = await self.inner.execute(name, **kwargs)
        except BaseException as exc:
            self.events.append({"type": "tool_result", "tool": name, "status": "error", "error_code": type(exc).__name__})
            raise
        self.events.append({"type": "tool_result", "tool": name, "status": result.status,
                            "call_id": result.call_id, "error_code": result.error.code if result.error else "",
                            "provider": result.meta.provider, "latency_ms": result.meta.latency_ms})
        return result


def finalize_result(result, budget, executor):
    result.tool_trace = list(executor.events)
    result.budget_report = budget.report()
    if result.status == "error" and not result.stop_reason:
        result.stop_reason = "execution_error"


async def agents(config, questions, bindings, output):
    sys.path.insert(0, str(ROOT / "researcher/deep_research_system"))
    from app.model_pool.endpoint_guard import validate_model_endpoint
    from app.services.cloud_config_service import CloudConfigService
    from agent.budget import Budget
    from agent.loop import AgentLoop, SemanticVerifier
    from evidence.store import EvidenceStore
    from eval.compare_agents import reference_module
    from eval.pipelines import RunResult, UsageLLM, run_condition
    from providers.llm.deepseek import DeepSeekLLMProvider
    from tools import EvidenceReadTool, KBSearchTool, ToolExecutor

    cloud = CloudConfigService()
    cfg = cloud.resolve("llm")
    allowed, reason = cloud.check_outbound("llm")
    if not allowed or not cfg["api_key"]:
        raise RuntimeError("LLM outbound/config unavailable: " + reason)
    endpoint = validate_model_endpoint(cfg["provider"], cfg["base_url"])
    reference_config = json.loads((ROOT / "eval/baseline/agent-improvement.freeze.json").read_text(encoding="utf-8"))
    reference = reference_module(reference_config).AgentLoop
    path = output / "agents.jsonl"
    existing = {(r["question_id"], r["variant"]) for r in read_rows(path)}
    semaphore = asyncio.Semaphore(config["concurrency"])
    completed = len(existing)
    pacer = CallPacer(config.get("llm_min_interval_seconds", 0))

    async def one(question, variant):
        nonlocal completed
        if (question["id"], variant) in existing:
            return
        async with semaphore:
            store = EvidenceStore()
            budget = Budget(**config["budget"])
            provider = DeepSeekLLMProvider(api_key=cfg["api_key"], model=cfg["model"], base_url=endpoint,
                                          provider_name=cfg["provider"], timeout_seconds=30, max_retries=0)
            llm = PacedLLM(CappedLLM(provider, budget, config), pacer)
            kb = KBSearchTool(base_url=BASE_URL, store=store)
            executor = RecordingExecutor(ToolExecutor(tools=[CorpusKBTool(kb), EvidenceReadTool(store=store)]))
            # Scoring fields never enter a model prompt.
            prompt_question = {"id": question["id"], "question": "Only use the fixed local knowledge base and cite its evidence. Do not use web search or prior memory. If it cannot establish the requested facts, refuse explicitly. 仅依据固定知识库，证据不足时拒答。\n" + question["question"]}
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(run_condition("C", prompt_question, llm=llm,
                    checker=SemanticVerifier(llm, budget=budget), corpus=None, store=store, executor=executor,
                    budget=budget, loop_factory=reference if variant == "reference" else AgentLoop),
                    timeout=config["budget"]["deadline_seconds"] + 5)
            except Exception as exc:
                result = RunResult(question_id=question["id"], condition="C", status="error", error=type(exc).__name__, stop_reason="deadline_exceeded" if isinstance(exc, TimeoutError) else "execution_error",
                                   latency_ms=(time.perf_counter() - started) * 1000,
                                   usage={"prompt_tokens": llm.prompt_tokens, "completion_tokens": llm.completion_tokens, "llm_calls": llm.calls}, cost_unknown=True)
            finally:
                await provider.close()
                await kb._client.aclose()
            finalize_result(result, budget, executor)
            result_dict = asdict(result)
            evidence = [asdict(ev) for ev in store.all()]
            row = {**result_dict, "variant": variant, "scores": generation_scores(question, result_dict, evidence, bindings), "full_evidence": evidence}
            # Provider errors can contain response snippets; never persist credentials.
            append(path, json.loads(scrub(json.dumps(row, ensure_ascii=False))))
            completed += 1
            reason = result.refusal_reason or result.error.split(":", 1)[0]
            print(f"Agent {completed}/{len(questions) * 2}: {variant} {question['id']} {result.status} {scrub(reason)}", flush=True)

    order = list(questions)
    random.Random(20261026).shuffle(order)
    jobs = []
    for i, question in enumerate(order):
        variants = config["agent_variants"] if i % 2 == 0 else list(reversed(config["agent_variants"]))
        jobs.extend(one(question, variant) for variant in variants)
    await asyncio.gather(*jobs)


def summarize(output, config, questions):
    retrieval_rows = read_rows(output / "retrieval.jsonl")
    agent_rows = read_rows(output / "agents.jsonl")
    retrieval_keys = {(q["id"], i, c) for q in questions for i in range(config["retrieval_repeats"]) for c in ("keyword", "vector", "hybrid")}
    selected_questions = agent_questions(config, questions)
    positive_count = sum(q["expected"] == "answered" for q in selected_questions)
    negative_count = len(selected_questions) - positive_count
    agent_keys = {(q["id"], v) for q in selected_questions for v in config["agent_variants"]}
    actual_agents = [(r["question_id"], r["variant"]) for r in agent_rows]
    if len(actual_agents) != len(set(actual_agents)):
        raise ValueError("Duplicate Agent run")
    actual_retrieval = {(r["question_id"], r["repeat"], r["channel"]) for r in retrieval_rows}
    if actual_retrieval - retrieval_keys or set(actual_agents) - agent_keys:
        raise ValueError("Unexpected benchmark run key")
    summary = {"retrieval": summarize_retrieval(retrieval_rows, questions, expected_repeats=config["retrieval_repeats"]), "agents": {},
               "retrieval_http_latency": latency_summary([r["http_elapsed_ms"] for r in retrieval_rows if r["channel"] == "hybrid"]),
               "expected_agent_rows": len(agent_keys), "retrieval_rows": len(retrieval_rows), "agent_rows": len(agent_rows), "human_verified": 0, "answer_semantic_accuracy": None,
               "complete": actual_retrieval == retrieval_keys and set(actual_agents) == agent_keys}
    lookup = {q["id"]: q for q in questions}
    for variant in config["agent_variants"]:
        rows = [r for r in agent_rows if r["variant"] == variant]
        positive = [r for r in rows if lookup[r["question_id"]]["expected"] == "answered"]
        negative = [r for r in rows if lookup[r["question_id"]]["expected"] == "refused"]
        claims = sum(r["scores"]["claim_count"] for r in rows)
        summary["agents"][variant] = {
            "n": len(rows), "expected_positive": positive_count, "expected_negative": negative_count, "statuses": dict(Counter(r["status"] for r in rows)),
            "refusal_reasons": dict(Counter(r["refusal_reason"] for r in rows if r["status"] == "refused")),
            "positive_answer_rate": sum(r["scores"]["answered"] for r in positive) / positive_count if positive_count else None,
            "false_refusal_rate": sum(r["scores"]["false_refusal"] for r in positive) / positive_count if positive_count else None,
            "gold_fact_citation_recall": bootstrap_mean([next((r["scores"]["gold_fact_citation_recall"] for r in positive if r["question_id"] == q["id"]), 0.0) for q in selected_questions if q["expected"] == "answered"]),
            "negative_refusal_rate": sum(r["scores"]["negative_refused"] for r in negative) / negative_count if negative_count else None,
            "negative_refusal_without_operational_failure_rate": sum(r["scores"]["negative_refused_without_operational_failure"] for r in negative) / negative_count if negative_count else None,
            "operational_failures": sum(r["scores"]["operational_failure"] for r in rows),
            "identity_valid_claim_rate": sum(r["scores"]["identity_valid_claims"] for r in rows) / claims if claims else None,
            "claims": claims, "latency": latency_summary([r["latency_ms"] for r in rows]),
            "usage": {key: sum(r.get("usage", {}).get(key, 0) for r in rows) for key in ("prompt_tokens", "completion_tokens", "llm_calls")},
            "unknown_usage_runs": sum(r["cost_unknown"] for r in rows), "currency_cost": None,
            "tool_errors": sum(t.get("type") == "tool_result" and t.get("status") == "error" for r in rows for t in r.get("tool_trace", [])),
            "observed_token_budget_exceeded": sum(r.get("budget_report", {}).get("tokens", 0) > config["budget"]["max_tokens"] for r in rows),
        }
    save_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["retrieval", "agents", "all", "summary"], default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=["original", "paced"], default="original")
    args = parser.parse_args()
    environment()
    config, questions = read_dataset()
    if args.profile == "paced":
        config = apply_paced_profile(config, questions)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    meta_file = output / "metadata.json"
    meta = metadata(config)
    current_audit = audit()
    meta["chunks_sha256"] = current_audit["chunks_sha256"]
    meta["qdrant_payload_sha256"] = current_audit["qdrant_payload_sha256"]
    meta["bindings_sha256"] = hashlib.sha256((STATE / "bindings.json").read_bytes()).hexdigest()
    if current_audit["unmapped_facts"]:
        raise ValueError("Gold facts do not map to actual indexed chunks; resolve before measuring")
    if meta_file.exists():
        previous = json.loads(meta_file.read_text(encoding="utf-8"))
        validate_run_identity(meta, previous)
    else:
        validate_run_identity(meta)
        save_json(meta_file, meta)
        save_json(output / "audit.json", current_audit)
    bindings = json.loads((STATE / "bindings.json").read_text(encoding="utf-8"))
    if args.phase in ("retrieval", "all"):
        retrieval(config, questions, bindings, output)
    if args.phase in ("agents", "all"):
        asyncio.run(agents(config, agent_questions(config, questions), bindings, output))
    post_audit = audit()
    save_json(output / "post_audit.json", post_audit)
    if any(meta[key] != post_audit[key] for key in ("chunks_sha256", "qdrant_payload_sha256")):
        save_json(output / "integrity_error.json", {"error": "Corpus changed during the measured phase"})
        raise ValueError("Corpus changed during measurement; results are retained but invalid")
    summary = summarize(output, config, questions)
    print("Report:", output, "complete:", summary["complete"])


if __name__ == "__main__":
    main()
