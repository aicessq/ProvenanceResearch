"""P4 指标（freeze.json scoring_rules 的机械实现）。

- 检索：Recall@5/10/20、MRR、来源覆盖——在融合 top-8 截断前的全序上计算。
- 回答：引用准确率/覆盖率、拒答准确率、误拒率、答案正确率（机械代理）。
- 运行：工具/终止合规、p50/p95 延迟、token/费用（缺用量标 cost_unknown）、provider 失败。
- 聚合：每条件 n 次 → 均值、样本标准差、95% CI（mean ± 1.96·std/√n）。
- OCR CER/WER、视觉正确率、页/区域引用准确率：P3b 前一律 n/a，不填 0。

答案正确率只是可复现的机械代理（required_points 归一化逐字覆盖、forbidden 命中记 0）；
最终裁决按人工评分规则，LLM 辅助不得单独裁决（freeze.json policy）。
"""

from __future__ import annotations

import math
from typing import Any, Iterable

LEGAL_STOP_REASONS = {
    "sufficient_evidence",
    "budget_exhausted",
    "deadline_exceeded",
    "no_progress",
    "citation_gate_failed",
}

_FW = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}
_FW[ord("　")] = ord(" ")


def normalize(text: str) -> str:
    """全角→半角、小写、去空白——与引用闸门/检索的字面匹配口径一致。"""
    return "".join((text or "").translate(_FW).lower().split())


def url_match(gold_url: str, ref_url: str) -> bool:
    """canonical_url 命中的机械口径：同 host 且尾段互含（忽略 scheme/www/末尾斜杠）。"""
    def norm(u: str) -> tuple[str, str]:
        u = (u or "").lower().rstrip("/")
        for prefix in ("https://", "http://"):
            if u.startswith(prefix):
                u = u[len(prefix):]
        u = u.removeprefix("www.")
        host = u.split("/", 1)[0]
        tail = u.rsplit("/", 1)[-1]
        return host, tail

    g_host, g_tail = norm(gold_url)
    r_host, r_tail = norm(ref_url)
    if not g_host or not r_host or g_host != r_host:
        return False
    return bool(g_tail) and (g_tail in ref_url.lower() or r_tail in (gold_url or "").lower())


def gold_hit(ref: dict, gold: dict) -> bool:
    """证据引用是否命中一个 gold locator（语料 doc_id+page / 论文 arxiv_id+版本 / URL）。"""
    if gold.get("external"):
        if gold.get("arxiv_id"):
            if ref.get("arxiv_id") != gold["arxiv_id"]:
                return False
            version = gold.get("version")
            return not version or ref.get("arxiv_version") in (version, f"v{version.lstrip('v')}")
        return url_match(gold.get("url") or "", ref.get("url") or "")
    return ref.get("doc_id") == gold.get("doc_id") and ref.get("page") == gold.get("page")


def _hit_rank(ranked_refs: list[dict], golds: list[dict]) -> int | None:
    for i, ref in enumerate(ranked_refs, start=1):
        if any(gold_hit(ref, g) for g in golds):
            return i
    return None


def recall_at_k(ranked_refs: list[dict], golds: list[dict], k: int) -> float | None:
    if not golds:
        return None  # 无 gold locator（如 topic_absent 应拒题）：检索 recall 不适用
    top = ranked_refs[:k]
    hits = sum(1 for g in golds if any(gold_hit(r, g) for r in top))
    return hits / len(golds)


def mrr(ranked_refs: list[dict], golds: list[dict]) -> float | None:
    if not golds:
        return None
    rank = _hit_rank(ranked_refs, golds)
    return 0.0 if rank is None else 1.0 / rank


def source_coverage(ranked_refs: list[dict], golds: list[dict]) -> float | None:
    return recall_at_k(ranked_refs, golds, k=len(ranked_refs) or 1)


def _refs_by_id(result: Any) -> dict[str, dict]:
    refs = {r["citation_id"]: r for r in result.ranked_refs}
    for ev in result.evidence:
        refs.setdefault(ev.get("citation_id", ""), ev)
    return refs


def citation_accuracy(result: Any, golds: list[dict]) -> float | None:
    """answered 题：至少一个引用指向 gold 证据的 claims 比例。"""
    if not result.claims:
        return None
    refs = _refs_by_id(result)
    hits = 0
    for claim in result.claims:
        cids = claim.get("citations") or []
        if any(any(gold_hit(refs.get(cid, {}), g) for g in golds) for cid in cids if cid in refs):
            hits += 1
    return hits / len(result.claims)


def citation_coverage(result: Any) -> float | None:
    if not result.claims:
        return None
    return sum(1 for c in result.claims if c.get("citations")) / len(result.claims)


def answer_correctness_mechanical(result: Any, question: dict) -> float | None:
    """required_points 归一化逐字覆盖；forbidden_points 命中即 0；拒答记 0。"""
    if question.get("expected_behavior") == "refused":
        return None  # 应拒题不计答案正确率（拒答准确率单列）
    if result.status != "answered":
        return 0.0
    answer = normalize(result.answer_text)
    required = [normalize(p) for p in question.get("required_points") or [] if normalize(p)]
    forbidden = [normalize(p) for p in question.get("forbidden_points") or [] if normalize(p)]
    if any(f in answer for f in forbidden):
        return 0.0
    if not required:
        return 1.0
    return sum(1 for r in required if r in answer) / len(required)


def tool_termination_compliance(result: Any, budget: dict | None = None) -> bool:
    if result.status == "error":
        return False
    if result.stop_reason not in LEGAL_STOP_REASONS:
        return False
    max_calls = (budget or {}).get("max_tool_calls")
    calls = int(result.budget_report.get("tool_calls", 0) or 0)
    if max_calls is not None and calls > max_calls:
        return False
    # 终态恰一次：trace 末尾即 done（error 诊断事件不计终态）
    return bool(result.trace_types) and result.trace_types[-1] == "done"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[idx]


def aggregate(values: Iterable[float]) -> dict:
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci95": [None, None]}
    mean = sum(vals) / n
    if n == 1:
        return {"n": 1, "mean": mean, "std": 0.0, "ci95": [mean, mean]}
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    half = 1.96 * std / math.sqrt(n)
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4), "ci95": [round(mean - half, 4), round(mean + half, 4)]}


def score_condition(runs_by_question: dict[str, list[Any]], questions: dict[str, dict], budget: dict | None = None) -> dict:
    """一个条件的完整指标包。runs_by_question: qid → 该题 n 次运行的 RunResult。"""
    recall5, recall10, recall20, mrrs, covers = [], [], [], [], []
    cites, cite_covs, answers = [], [], []
    refusals, false_refusals, compliances = [], [], []
    latencies, failures = [], 0
    prompt_tokens = completion_tokens = llm_calls = 0
    cost_unknown = False

    for qid, runs in runs_by_question.items():
        question = questions[qid]
        golds = question.get("expected_locator") or []
        expects_refusal = question.get("expected_behavior") == "refused"
        for run in runs:
            latencies.append(run.latency_ms)
            if run.status == "error":
                failures += 1
                continue
            r5, r10, r20 = recall_at_k(run.ranked_refs, golds, 5), recall_at_k(run.ranked_refs, golds, 10), recall_at_k(run.ranked_refs, golds, 20)
            rank = mrr(run.ranked_refs, golds)
            cov = source_coverage(run.ranked_refs, golds)
            if r5 is not None:
                recall5.append(r5)
                recall10.append(r10)
                recall20.append(r20)
                mrrs.append(rank)
                covers.append(cov)
            compliances.append(1.0 if tool_termination_compliance(run, budget) else 0.0)
            usage = run.usage or {}
            if run.cost_unknown or not usage:
                cost_unknown = True
            else:
                prompt_tokens += int(usage.get("prompt_tokens", 0))
                completion_tokens += int(usage.get("completion_tokens", 0))
                llm_calls += int(usage.get("llm_calls", 0))
            if expects_refusal:
                refusals.append(1.0 if run.status == "refused" else 0.0)
            else:
                false_refusals.append(1.0 if run.status == "refused" else 0.0)
                acc = citation_accuracy(run, golds)
                if acc is not None:
                    cites.append(acc)
                cov = citation_coverage(run)
                if cov is not None:
                    cite_covs.append(cov)
                ans = answer_correctness_mechanical(run, question)
                if ans is not None:
                    answers.append(ans)

    def safe_agg(vals):
        return aggregate(vals) if vals else {"n": 0, "mean": None, "std": None, "ci95": [None, None]}

    return {
        "retrieval": {
            "recall@5": safe_agg(recall5),
            "recall@10": safe_agg(recall10),
            "recall@20": safe_agg(recall20),
            "mrr": safe_agg(mrrs),
            "source_coverage": safe_agg(covers),
        },
        "answers": {
            "citation_accuracy": safe_agg(cites),
            "citation_coverage": safe_agg(cite_covs),
            "answer_correctness_mechanical": safe_agg(answers),
            "refusal_accuracy": safe_agg(refusals),
            "false_refusal_rate": safe_agg(false_refusals),
        },
        "runtime": {
            "tool_termination_compliance": safe_agg(compliances),
            "latency_ms_p50": round(percentile(latencies, 50), 2),
            "latency_ms_p95": round(percentile(latencies, 95), 2),
            "provider_failures": failures,
        },
        "cost": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "llm_calls": llm_calls,
            "cost_unknown": cost_unknown,
        },
        "multimodal": {  # P3b 前 n/a，不填 0
            "ocr_cer_wer": "n/a",
            "vision_accuracy": "n/a",
            "page_region_citation_accuracy": "n/a",
        },
    }
