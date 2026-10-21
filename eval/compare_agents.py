"""前后对照：固定旧 loop、gap-only、完整反馈；不复制三套生产实现。

python -m eval.compare_agents --mode fake
python -m eval.compare_agents --mode live
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, replace
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import types
import uuid
import httpx

from agent.budget import Budget
from agent.loop import AgentLoop, SemanticVerifier
from evidence.store import EvidenceStore
from eval.corpus_search import CorpusIndex, RETRIEVER_VERSION
from eval.metrics import aggregate, score_condition
from eval.pipelines import UsageLLM, run_condition
from eval.runner import (FakeEvalLLM, YesChecker, _live_llm, _mock_http_client, build_executor, evaluate_thresholds,
                         load_questions, require_live_config, run_safety_suite, verify_freeze)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FREEZE = ROOT / "eval/baseline/agent-improvement.freeze.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_fingerprint() -> str:
    return digest(b"".join(p.name.encode() + b"\0" + p.read_bytes().replace(b"\r\n", b"\n")
                           for p in sorted((ROOT / "eval/corpus/text").glob("*.pages.jsonl"))))


def reference_module(config: dict):
    """仅离线评测加载本仓库固定 SHA 的源码；hash 不符不执行，生产从不走此入口。"""
    revision = config["reference_revision"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("reference_revision 必须为完整固定提交 SHA")
    source = subprocess.check_output(["git", "show", f"{revision}:agent/loop.py"], cwd=ROOT)
    if digest(source) != config["reference_loop_sha256"]:
        raise ValueError("旧 Agent 源码指纹不符")
    name = f"eval._reference_{revision}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, f"{revision}:agent/loop.py", "exec"), module.__dict__)
    return module


def load_config(path: Path) -> tuple[dict, dict]:
    config = json.loads(path.read_text(encoding="utf-8"))
    base_path = (ROOT / config["base_freeze"]).resolve()
    if not base_path.is_relative_to(ROOT):
        raise ValueError("base freeze 必须在仓库内")
    if digest(base_path.read_bytes().replace(b"\r\n", b"\n")) != config["base_freeze_sha256"]:
        raise ValueError("基础冻结件指纹不符")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    verify_freeze(base)
    if text_fingerprint() != config["corpus_text_sha256"]:
        raise ValueError("页级文本指纹不符")
    if config["budget"] != base["budget"]:
        raise ValueError("对照预算必须等于原冻结预算")
    if set(config["variants"]) != {"baseline", "gaps", "feedback"}:
        raise ValueError("未知实验组")
    return config, base


class GapEvalLLM(FakeEvalLLM):
    """结构化 gap 的离线机械驱动，不用于判断模型研究能力。"""

    async def generate(self, messages, metadata=None):
        if (metadata or {}).get("stage") == "plan":
            prompt = messages[0].content
            query = re.search(r"问题：([^\n]+)", prompt).group(1)
            observations = json.loads(re.search(r"已有证据：([^\n]+)", prompt).group(1))
            supported = next((ev for ev in observations if ev["content_scope"] == "fulltext"), None)
            gap = {"gap_id": "question", "question": query, "required_scope": "fulltext",
                   "completion_criterion": "存在支撑当前问题的证据", "status": "resolved" if supported else "open",
                   "supporting_citation_ids": [supported["citation_id"]] if supported else []}
            self._responses = [json.dumps({"gaps": [gap], "tool_calls": [] if supported else [
                {"tool": "kb_search", "args": {"query": query, "top_k": 5}, "gap_ids": ["question"]}]})]
        return await super().generate(messages, metadata)


class SnapshotExecutor:
    """跨实验组按相同请求复用首个外部结果；本地读始终走当前证据池。"""

    def __init__(self, inner, store, cache, log, context=None):
        self.inner, self.store, self.cache, self.log = inner, store, cache, log
        self.context = context or {}

    @property
    def tool_names(self):
        return self.inner.tool_names

    async def execute(self, name, **args):
        if name not in ("web_search", "arxiv_search", "source_fetch"):
            return await self.inner.execute(name, **args)
        key = json.dumps({"tool": name, "args": args}, sort_keys=True, ensure_ascii=False)
        hit = key in self.cache
        if not hit:
            self.cache[key] = await self.inner.execute(name, **args)
        result = self.cache[key]
        for ev in result.evidence:
            self.store.register(ev)
        self.log.append({**self.context, "request": json.loads(key), "cache_hit": hit, "status": result.status})
        return replace(result, call_id=uuid.uuid4().hex[:12])


def mechanisms(results: list) -> dict:
    gap_rates, duplicate_rates, partial_rates = [], [], []
    for result in results:
        if result.gaps:
            gap_rates.append(sum(g["status"] == "resolved" for g in result.gaps) / len(result.gaps))
        keys = [json.dumps({"tool": t["tool"], "args": t["args"]}, sort_keys=True)
                for t in result.tool_trace if t["type"] == "tool_call"]
        duplicate_rates.append((len(keys) - len(set(keys))) / len(keys) if keys else 0)
        partial_rates.append(float(result.status == "answered" and bool(result.limitations)))
    return {"gap_closure_rate": aggregate(gap_rates), "duplicate_search_rate": aggregate(duplicate_rates),
            "partial_answer_rate": aggregate(partial_rates)}


async def compare(config: dict, base: dict, *, mode: str, runs: int) -> dict:
    if mode == "live":
        require_live_config(["C"])  # 先验配置/授权；不因导入旧 loop 绕过生产出站门。
    reference = reference_module(config)
    corpus = CorpusIndex(ROOT / "eval/corpus")
    questions = load_questions(base)
    factories = {"baseline": reference.AgentLoop,
                 "gaps": partial(AgentLoop, verification_feedback=False), "feedback": AgentLoop}
    grouped = {variant: {qid: [] for qid in questions} for variant in factories}
    cache, snapshot_log = {}, []
    index_identity = base["dataset"]["corpus_manifest_sha256"][:12] + "+" + RETRIEVER_VERSION
    for qid, question in questions.items():
        for repeat in range(runs):
            order = list(factories)
            random.Random(f"{qid}:{repeat}").shuffle(order)
            for variant in order:
                store = EvidenceStore()
                budget = Budget(**config["budget"])
                async with (_mock_http_client() if mode == "fake" else httpx.AsyncClient(follow_redirects=False)) as client:
                    llm = UsageLLM((_live_llm(client=client) if mode == "live" else
                                    FakeEvalLLM() if variant == "baseline" else GapEvalLLM()))
                    verifier = reference.SemanticVerifier if variant == "baseline" else SemanticVerifier
                    checker = YesChecker() if mode == "fake" else verifier(llm, budget=budget)
                    executor = build_executor(mode, corpus, store, index_identity, include_read_tools=True, client=client)
                    result = await run_condition("C", question, llm=llm, checker=checker, corpus=corpus,
                    store=store, executor=SnapshotExecutor(executor, store, cache, snapshot_log,
                        {"variant": variant, "question_id": qid, "run": repeat}),
                        budget=budget, index_identity=index_identity, loop_factory=factories[variant])
                    result.usage = {"prompt_tokens": llm.prompt_tokens, "completion_tokens": llm.completion_tokens,
                                    "llm_calls": llm.calls}
                    result.cost_unknown = not llm.reported_usage
                    grouped[variant][qid].append(result)
    conditions, details = {}, {}
    for variant, by_question in grouped.items():
        conditions[variant] = score_condition(by_question, questions, budget=config["budget"])
        results = [r for values in by_question.values() for r in values]
        conditions[variant]["mechanisms"] = mechanisms(results)
        details[variant] = [asdict(r) for r in results]
        conditions[variant]["refusal_reasons"] = dict(Counter(r.refusal_reason for r in results if r.status == "refused"))
        conditions[variant]["tool_failures"] = sum(t.get("status") == "error" for r in results for t in r.tool_trace
                                                    if t["type"] == "tool_result")
        conditions[variant]["external_requests"] = sum(not r["cache_hit"] for r in snapshot_log if r["variant"] == variant)
        conditions[variant]["external_cache_hits"] = sum(r["cache_hit"] for r in snapshot_log if r["variant"] == variant)
    safety_by_variant = {name: await run_safety_suite(loop_factory=factory) for name, factory in factories.items()}
    safety = {"passed": all(s["passed"] for s in safety_by_variant.values()), "variants": safety_by_variant}
    paired = []
    from eval.metrics import answer_correctness_mechanical
    for qid, question in questions.items():
        scores = {v: aggregate(s for r in grouped[v][qid]
                               if (s := answer_correctness_mechanical(r, question)) is not None)["mean"]
                  for v in factories}
        paired.append({"question_id": qid, "mechanical_scores": scores,
                       "feedback_vs_baseline": (None if scores["baseline"] is None or scores["feedback"] is None
                                                  else round(scores["feedback"] - scores["baseline"], 4))})
    thresholds = evaluate_thresholds(base, {"mode": mode, "conditions": conditions, "safety": safety})
    scores = {v: conditions[v]["answers"]["answer_correctness_mechanical"]["mean"] for v in factories}
    thresholds["non_regression"] = {v: (None if mode != "live" or scores[v] is None or scores["baseline"] is None
        else scores[v] >= scores["baseline"] - config["mechanical_score_non_regression_tolerance"])
        for v in ("gaps", "feedback")}
    effective_identity = ({"provider": "scripted-fixture", "model": "fake"} if mode == "fake" else {
        "provider": os.environ.get("LLM_PROVIDER") or "deepseek",
        "model": os.environ.get("LLM_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat",
        "endpoint": os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com"})
    return {"mode": mode, "not_a_conclusion": mode != "live" or runs != config["runs_per_condition"]
                or not all(q.get("verified") for q in questions.values()),
            "verified_gold": sum(bool(q.get("verified")) for q in questions.values()),
            "experiment": config, "runs_per_condition": runs,
            "runtime_identity": effective_identity, "currency_cost_unknown": True,
            "conditions": conditions, "details": details, "paired": paired, "safety": safety,
            "thresholds": thresholds,
            "external_snapshots": [{"request": json.loads(key), "result": asdict(value)} for key, value in cache.items()],
            "snapshot_usage": snapshot_log}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent 改进前后对照（fake 不是质量结论）")
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--runs", type=int, default=0)
    parser.add_argument("--out", type=Path, default=ROOT / "eval/results")
    args = parser.parse_args(argv)
    config, base = load_config(args.freeze)
    runs = args.runs or config["runs_per_condition"]
    if runs < 1:
        raise SystemExit("runs 必须为正数")
    report = asyncio.run(compare(config, base, mode=args.mode, runs=runs))
    report["code_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    report["working_tree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    source_files = [p for folder in ("agent", "tools", "providers", "evidence", "eval")
                    for p in (ROOT / folder).rglob("*.py") if "tests" not in p.parts]
    report["source_fingerprints"] = {str(p.relative_to(ROOT)).replace("\\", "/"):
                                   digest(p.read_bytes().replace(b"\r\n", b"\n")) for p in sorted(source_files)}
    args.out.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    path = args.out / f"agent-improvement.{args.mode}.{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {path}\nmode={args.mode}; not_a_conclusion={report['not_a_conclusion']}; safety={report['safety']['passed']}")
    if not report["safety"]["passed"] or any(c["runtime"]["provider_failures"] for c in report["conditions"].values()):
        raise SystemExit("安全/运行检查失败；报告已保存，不得作质量结论")


if __name__ == "__main__":
    main()
