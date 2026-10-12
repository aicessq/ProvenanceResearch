"""P4 baseline 机械验收（tests_bridge）。

覆盖：指标纯函数（Recall/MRR/gold 命中/引用准确率/拒答与误拒/答案机械分/聚合 CI）、
本地确定性检索（同查询同排名、kb_chunk 身份齐全、gold 页可召回）、
A/B/C 流水线 fake 端到端（生成→闸门→answered/refused）、安全样例全部拒绝、
冻结件指纹校验与 live 模式缺配置显式失败。全部无凭证、不联网。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.budget import Budget  # noqa: E402
from eval import metrics  # noqa: E402
from eval.corpus_search import CorpusIndex  # noqa: E402
from eval.pipelines import RunResult, UsageLLM, run_condition  # noqa: E402
from eval.runner import (  # noqa: E402
    FakeEvalLLM,
    YesChecker,
    build_executor,
    load_questions,
    require_live_config,
    run_safety_suite,
    verify_freeze,
)
from evidence.store import EvidenceStore  # noqa: E402

FREEZE = json.loads((REPO_ROOT / "eval" / "baseline" / "round1.freeze.json").read_text(encoding="utf-8"))
QUESTIONS = load_questions(FREEZE)


@pytest.fixture(scope="module")
def corpus() -> CorpusIndex:
    return CorpusIndex(REPO_ROOT / "eval" / "corpus")


# ---------------- 指标纯函数 ----------------

GOLD_CORPUS = [{"doc_id": "d1", "page": 3}]
GOLD_ARXIV = [{"external": True, "url": "https://arxiv.org/abs/1706.03762", "arxiv_id": "1706.03762", "version": "v7"}]
GOLD_WEB = [{"external": True, "url": "https://www.rfc-editor.org/info/rfc5246"}]


def _ref(cid="K1", **kw):
    base = {"citation_id": cid, "doc_id": None, "page": None, "arxiv_id": None, "arxiv_version": None, "url": None, "source_type": "web"}
    base.update(kw)
    return base


def test_gold_hit_rules() -> None:
    assert metrics.gold_hit(_ref(doc_id="d1", page=3), GOLD_CORPUS[0])
    assert not metrics.gold_hit(_ref(doc_id="d1", page=4), GOLD_CORPUS[0])
    assert metrics.gold_hit(_ref(arxiv_id="1706.03762", arxiv_version="v7"), GOLD_ARXIV[0])
    assert not metrics.gold_hit(_ref(arxiv_id="1706.03762", arxiv_version="v6"), GOLD_ARXIV[0])  # 版本不误并
    assert metrics.gold_hit(_ref(url="https://www.rfc-editor.org/rfc/rfc5246"), GOLD_WEB[0])
    assert not metrics.gold_hit(_ref(url="https://evil.example/rfc5246"), GOLD_WEB[0])  # host 必须一致


def test_recall_and_mrr_with_no_gold_is_na() -> None:
    assert metrics.recall_at_k([_ref()], [], 10) is None
    assert metrics.mrr([_ref()], []) is None
    ranked = [_ref(doc_id="d9"), _ref(doc_id="d1", page=3)]
    assert metrics.recall_at_k(ranked, GOLD_CORPUS, 1) == 0.0
    assert metrics.recall_at_k(ranked, GOLD_CORPUS, 2) == 1.0
    assert metrics.mrr(ranked, GOLD_CORPUS) == 0.5


def test_answer_correctness_and_forbidden() -> None:
    q = {"expected_behavior": "answered", "required_points": ["留存相关的网络日志不少于六个月"], "forbidden_points": ["不少于七个月"]}
    ok = RunResult(question_id="q", condition="A", status="answered", answer_text="应当 留存相关的网络日志不少于六个月。")
    assert metrics.answer_correctness_mechanical(ok, q) == 1.0
    partial = RunResult(question_id="q", condition="A", status="answered", answer_text="留存相关的网络日志不少于六个月；另一条 required。")
    assert metrics.answer_correctness_mechanical(partial, q) == 1.0
    bad = RunResult(question_id="q", condition="A", status="answered", answer_text="留存相关的网络日志不少于七个月。")
    assert metrics.answer_correctness_mechanical(bad, q) == 0.0  # forbidden 命中即 0
    refused = RunResult(question_id="q", condition="A", status="refused")
    assert metrics.answer_correctness_mechanical(refused, q) == 0.0


def test_citation_metrics_and_aggregate() -> None:
    result = RunResult(
        question_id="q",
        condition="A",
        status="answered",
        claims=[{"claim": "a", "citations": ["K1"], "scope": "fulltext"}, {"claim": "b", "citations": [], "scope": "fulltext"}],
        ranked_refs=[_ref("K1", doc_id="d1", page=3)],
    )
    assert metrics.citation_accuracy(result, GOLD_CORPUS) == 0.5
    assert metrics.citation_coverage(result) == 0.5

    agg = metrics.aggregate([1.0, 0.0, 1.0, 0.0])
    assert agg["n"] == 4 and agg["mean"] == 0.5
    assert agg["std"] > 0 and agg["ci95"][0] < 0.5 < agg["ci95"][1]
    assert metrics.aggregate([])["mean"] is None


def test_tool_termination_compliance() -> None:
    good = RunResult(question_id="q", condition="C", status="answered", stop_reason="sufficient_evidence", budget_report={"tool_calls": 2}, trace_types=["meta", "done"])
    assert metrics.tool_termination_compliance(good, {"max_tool_calls": 12})
    over = RunResult(question_id="q", condition="C", status="answered", stop_reason="sufficient_evidence", budget_report={"tool_calls": 99}, trace_types=["done"])
    assert not metrics.tool_termination_compliance(over, {"max_tool_calls": 12})
    no_terminal = RunResult(question_id="q", condition="C", status="answered", stop_reason="sufficient_evidence", budget_report={"tool_calls": 1}, trace_types=["meta", "plan"])
    assert not metrics.tool_termination_compliance(no_terminal, {"max_tool_calls": 12})


# ---------------- 本地检索 ----------------

def test_corpus_search_deterministic_and_identity_complete(corpus) -> None:
    q = QUESTIONS["q001"]["question"]
    first = [(h.doc_id, h.page) for h in corpus.search(q, 5)]
    second = [(h.doc_id, h.page) for h in corpus.search(q, 5)]
    assert first == second  # 同查询同排名（可复现）
    assert first[0] == ("zh_cybersec_2025", 3)  # gold 页 rank1

    store = EvidenceStore()
    ev = corpus.build_evidence(corpus.search(q, 1)[0], store, "test-idx")
    assert ev.source_type == "kb_chunk"
    assert ev.citation_id.startswith("K")
    assert ev.provenance.doc_id == "zh_cybersec_2025"
    assert ev.provenance.doc_version and ev.provenance.chunk_id
    assert ev.provenance.index_identity == "test-idx"
    assert ev.locator.page == 3


# ---------------- 流水线端到端（fake） ----------------

def test_condition_a_answers_with_cited_evidence(corpus) -> None:
    async def scenario():
        store = EvidenceStore()
        llm = UsageLLM(FakeEvalLLM())
        return await run_condition(
            "A",
            QUESTIONS["q001"],
            llm=llm,
            checker=YesChecker(),
            corpus=corpus,
            store=store,
            budget=Budget(),
            index_identity="test-idx",
        )

    result = asyncio.run(scenario())
    assert result.status == "answered"
    assert result.citations and result.claims
    assert metrics.citation_accuracy(result, QUESTIONS["q001"]["expected_locator"]) == 1.0
    assert metrics.recall_at_k(result.ranked_refs, QUESTIONS["q001"]["expected_locator"], 5) == 1.0
    assert result.usage["llm_calls"] >= 1
    assert result.trace_types[-1] == "done"


def test_condition_b_pulls_external_evidence(corpus) -> None:
    async def scenario():
        store = EvidenceStore()
        executor = build_executor("fake", corpus, store, "test-idx")
        return await run_condition(
            "B",
            QUESTIONS["q031"],  # external_only：语料无解，须外部源
            llm=UsageLLM(FakeEvalLLM()),
            checker=YesChecker(),
            corpus=corpus,
            store=store,
            executor=executor,
            budget=Budget(),
            index_identity="test-idx",
        )

    result = asyncio.run(scenario())
    sources = {r["source_type"] for r in result.ranked_refs}
    assert "web" in sources or "paper" in sources  # 固定混合真的拉了外部证据


def test_condition_c_agentic_loop_registers_evidence_via_tool(corpus) -> None:
    async def scenario():
        store = EvidenceStore()
        executor = build_executor("fake", corpus, store, "test-idx")
        return await run_condition(
            "C",
            QUESTIONS["q001"],
            llm=UsageLLM(FakeEvalLLM()),
            checker=YesChecker(),
            corpus=corpus,
            store=store,
            executor=executor,
            budget=Budget(),
            index_identity="test-idx",
        )

    result = asyncio.run(scenario())
    assert result.status == "answered"
    assert "tool_call" in result.trace_types and "tool_result" in result.trace_types
    assert result.budget_report["tool_calls"] >= 1


def test_condition_refuses_when_writer_gives_no_claims(corpus) -> None:
    """fake LLM 脚本输出空 claims → 引用不足 → 拒答（不是空答案冒充成功）。"""
    empty_claims = json.dumps({"answer": "x", "claims": []}, ensure_ascii=False)

    async def scenario():
        store = EvidenceStore()
        return await run_condition(
            "A",
            QUESTIONS["q001"],
            llm=UsageLLM(FakeEvalLLM([empty_claims, empty_claims])),
            checker=YesChecker(),
            corpus=corpus,
            store=store,
            budget=Budget(),
            index_identity="test-idx",
        )

    result = asyncio.run(scenario())
    assert result.status == "refused"
    assert result.refusal_reason == "citation_gate_failed"


# ---------------- 安全样例 / 冻结件 / live 门 ----------------

def test_safety_samples_all_rejected() -> None:
    suite = asyncio.run(run_safety_suite())
    assert suite["passed"], suite["samples"]
    assert all(s["status"] == "refused" for s in suite["samples"])
    over_budget = next(s for s in suite["samples"] if s["name"] == "over_budget_calls")
    assert over_budget["tool_calls"] <= 1  # 超预算续调被阻止且计费封顶


def test_freeze_hash_mismatch_blocks_run() -> None:
    verify_freeze(FREEZE)  # 真实冻结件通过
    tampered = json.loads(json.dumps(FREEZE))
    tampered["dataset"]["questions_sha256"] = "0" * 64
    with pytest.raises(SystemExit):
        verify_freeze(tampered)


def test_live_mode_requires_cloud_config_and_outbound_approval(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    for var in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        require_live_config(["A"])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(SystemExit):
        require_live_config(["B"])  # B/C 还需 TAVILY_API_KEY
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    with pytest.raises(SystemExit) as gate_blocked:
        require_live_config(["A", "B", "C"])  # 凭证齐了但出站未授权 → 仍拒绝（凭证不等于授权）
    assert "出站未授权" in str(gate_blocked.value)

    from app.services.outbound_gate import OutboundGate

    monkeypatch.setenv("CLOUD_DATA_UPLOAD_ALLOWED", "true")
    gate = OutboundGate.from_env()
    approvals = {
        "llm": gate.expected_fingerprint("llm", "deepseek", "unset", "deepseek-chat"),
        "search:web": gate.expected_fingerprint("search:web", "tavily", "https://api.tavily.com", ""),
        "search:arxiv": gate.expected_fingerprint("search:arxiv", "arxiv", "https://export.arxiv.org", ""),
    }
    monkeypatch.setenv("CLOUD_DATA_APPROVALS_JSON", json.dumps(approvals))
    require_live_config(["A", "B", "C"])  # 授权齐备则放行


def test_freeze_questions_all_resolve() -> None:
    assert set(QUESTIONS) == set(FREEZE["dataset"]["question_ids"])
    assert len(QUESTIONS) == 18
    assert sum(1 for q in QUESTIONS.values() if q["expected_behavior"] == "refused") == 4
