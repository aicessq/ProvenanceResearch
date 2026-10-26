"""Strict source-span metrics for the real local KB benchmark."""
from __future__ import annotations

import random
import math
import re
import statistics
import unicodedata


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())


def fact_hit(fact: dict, chunk: dict, bindings: dict) -> bool:
    return (
        chunk.get("document_id") == bindings[fact["doc_id"]]["document_id"]
        and normalize(fact["quote"]) in normalize(chunk.get("chunk_text", ""))
    )


def retrieval_scores(question: dict, chunks: list, bindings: dict) -> dict:
    facts = question["facts"]
    if question["expected"] != "answered":
        return {}
    if not facts:
        raise ValueError("Answerable question requires grounded facts")
    scores = {}
    for k in (1, 5, 10):
        hits = [any(fact_hit(fact, chunk, bindings) for chunk in chunks[:k]) for fact in facts]
        scores[f"recall@{k}"] = sum(hits) / len(facts)
        scores[f"all_facts@{k}"] = float(all(hits))
    rank = next((i for i, chunk in enumerate(chunks, 1) if any(fact_hit(f, chunk, bindings) for f in facts)), None)
    scores["mrr@10"] = 1 / rank if rank and rank <= 10 else 0.0
    return scores


def bootstrap_mean(values: list[float], *, samples: int = 2000) -> dict:
    if not values:
        return {"n": 0, "mean": None, "ci95": [None, None]}
    rng = random.Random(20261026)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return {"n": len(values), "mean": statistics.mean(values), "ci95": [means[int(.025 * samples)], means[min(samples - 1, int(.975 * samples))]]}


def latency_summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {"n": len(values), "p50_ms": statistics.median(ordered), "p95_ms": ordered[max(0, math.ceil(len(ordered) * .95) - 1)]}


def summarize_retrieval(rows: list, questions: list, *, expected_repeats: int = 3) -> dict:
    keys = [(r["question_id"], r["repeat"], r["channel"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate retrieval run")
    answerable = [q for q in questions if q["expected"] == "answered"]
    summary = {}
    for channel in ("keyword", "vector", "hybrid"):
        channel_rows = [r for r in rows if r["channel"] == channel]
        groups = {"all": answerable, "en": [q for q in answerable if q["language"] == "en"], "zh": [q for q in answerable if q["language"] == "zh"], "single": [q for q in answerable if q["category"] == "single"], "multi_source": [q for q in answerable if q["category"] == "multi_source"]}
        summary[channel] = {}
        for group, selected in groups.items():
            stats = {}
            for metric in ("recall@1", "recall@5", "recall@10", "all_facts@5", "mrr@10"):
                values = []
                for q in selected:
                    runs = {r["repeat"]: r for r in channel_rows if r["question_id"] == q["id"]}
                    # Missing / failed attempts are zeros, never removed from the denominator.
                    values.append(statistics.mean([runs.get(i, {}).get("scores", {}).get(metric, 0.0) for i in range(expected_repeats)]))
                stats[metric] = bootstrap_mean(values)
            summary[channel][group] = stats
        summary[channel]["errors"] = sum(r.get("status") != "ok" for r in channel_rows)
        complete_runs = [[r for r in channel_rows if r["question_id"] == q["id"]] for q in questions]
        complete_runs = [runs for runs in complete_runs if len(runs) == expected_repeats and all(r["status"] == "ok" for r in runs)]
        summary[channel]["repeat_consistency"] = {"complete_queries": len(complete_runs), "scheduled_queries": len(questions),
            "identical_top10_queries": sum(len({tuple(c["chunk_id"] for c in r.get("ranked_chunks", [])[:10]) for r in runs}) == 1 for runs in complete_runs)}
    return summary


OPERATIONAL_REFUSALS = {"invalid_planner_output", "budget_exhausted", "deadline_exceeded"}


def generation_scores(question: dict, result: dict, evidence: list, bindings: dict) -> dict:
    answered = result["status"] == "answered"
    operational = (result["status"] == "error" or result.get("refusal_reason") in OPERATIONAL_REFUSALS
                   or (result["status"] == "refused" and result.get("stop_reason") in {"budget_exhausted", "deadline_exceeded"}))
    refs = {ev["citation_id"]: ev for ev in evidence}
    claims = result.get("claims", [])
    cited = []
    valid_claims = 0
    for claim in claims:
        ids = claim.get("citations") or []
        if ids and all(cid in refs and all(refs[cid].get("provenance", {}).get(field) for field in ("doc_id", "doc_version", "chunk_id", "index_identity")) for cid in ids):
            valid_claims += 1
        for cid in ids:
            if cid in refs:
                ev = refs[cid]
                cited.append({"document_id": ev["provenance"]["doc_id"], "chunk_text": ev["raw_text"]})
    facts = question["facts"]
    return {
        "answered": answered,
        "operational_failure": operational,
        "negative_refused": question["expected"] == "refused" and result["status"] == "refused",
        "negative_refused_without_operational_failure": question["expected"] == "refused" and result["status"] == "refused" and not operational,
        "false_refusal": question["expected"] == "answered" and result["status"] == "refused",
        "claim_count": len(claims), "identity_valid_claims": valid_claims,
        "gold_fact_citation_recall": sum(any(fact_hit(f, c, bindings) for c in cited) for f in facts) / len(facts) if facts and answered else 0.0,
    }
