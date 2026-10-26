"""No cloud/DB calls: scoring must reject wrong sources and retain failures."""
from eval.local_kb_metrics import generation_scores, retrieval_scores, summarize_retrieval
from eval.local_kb_setup import read_dataset
import pytest


def fixture():
    question = {"id": "q", "expected": "answered", "language": "en", "category": "multi_source",
                "facts": [{"doc_id": "a", "quote": "Access is granted per-session."}, {"doc_id": "b", "quote": "No replay guarantee."}]}
    bindings = {"a": {"document_id": "uuid-a"}, "b": {"document_id": "uuid-b"}}
    chunks = [{"document_id": "uuid-a", "chunk_text": "Access is granted per-session."},
              {"document_id": "wrong", "chunk_text": "No replay guarantee."}]
    return question, bindings, chunks


def test_fact_recall_requires_source_and_all_fact_denominator():
    question, bindings, chunks = fixture()
    scores = retrieval_scores(question, chunks, bindings)
    assert scores["recall@5"] == .5
    assert scores["all_facts@5"] == 0
    assert scores["mrr@10"] == 1
    assert retrieval_scores(question, [], bindings)["recall@5"] == 0


def test_errors_and_missing_questions_remain_in_query_level_denominator():
    question, _, _ = fixture()
    other = {**question, "id": "missing"}
    rows = [{"question_id": "q", "repeat": 0, "channel": "vector", "status": "ok", "scores": {"recall@5": 1}},
            {"question_id": "q", "repeat": 1, "channel": "vector", "status": "error", "scores": {}}]
    summary = summarize_retrieval(rows, [question, other], expected_repeats=2)["vector"]
    assert summary["all"]["recall@5"]["mean"] == .25
    assert summary["all"]["recall@5"]["n"] == 2
    assert summary["errors"] == 1


def test_operational_refusal_is_not_counted_as_valid_negative_refusal():
    question, bindings, _ = fixture()
    question = {**question, "expected": "refused", "facts": []}
    result = {"status": "refused", "refusal_reason": "invalid_planner_output", "claims": []}
    scores = generation_scores(question, result, [], bindings)
    assert scores["negative_refused"]
    assert scores["operational_failure"]
    assert not scores["negative_refused_without_operational_failure"]
    result["status"] = "error"
    assert not generation_scores(question, result, [], bindings)["negative_refused"]


@pytest.mark.parametrize("stop", ["budget_exhausted", "deadline_exceeded"])
def test_real_no_evidence_stop_shape_is_operational(stop):
    question, bindings, _ = fixture()
    question = {**question, "expected": "refused", "facts": []}
    result = {"status": "refused", "refusal_reason": "no_evidence", "stop_reason": stop, "claims": []}
    scores = generation_scores(question, result, [], bindings)
    assert scores["operational_failure"]
    assert not scores["negative_refused_without_operational_failure"]


def test_missing_repeats_are_zero_and_duplicates_rejected():
    question, _, _ = fixture()
    row = {"question_id": "q", "repeat": 0, "channel": "vector", "status": "ok", "scores": {"recall@5": 1}}
    summary = summarize_retrieval([row], [question], expected_repeats=3)["vector"]
    assert summary["all"]["recall@5"]["mean"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_retrieval([row, row], [question])


def test_resume_rejects_dirty_source_and_model_drift():
    from eval.local_kb import validate_run_identity
    with pytest.raises(ValueError, match="Commit"):
        validate_run_identity({"working_tree_dirty": True}, {})
    meta = {"working_tree_dirty": False, "dataset_sha256": "a", "freeze_sha256": "b", "git_revision": "c", "llm": {"model": "one"}, "embedding": {}, "chunks_sha256": "d", "bindings_sha256": "e", "qdrant_payload_sha256": "f"}
    with pytest.raises(ValueError, match="resume"):
        validate_run_identity(meta, {**meta, "llm": {"model": "other"}})


def test_server_ownership_requires_matching_live_identity():
    from eval.local_kb_setup import validate_server_identity
    expected = {"nonce": "unique", "database": "evaluation", "collection": "test", "source_fingerprint": "abc"}
    validate_server_identity(expected, dict(expected))
    with pytest.raises(RuntimeError, match="identity"):
        validate_server_identity(expected, {**expected, "database": "user-production"})


def test_tool_error_then_provider_exception_keeps_trace_and_budget():
    import asyncio
    from agent.budget import Budget
    from evidence.store import EvidenceStore
    from eval.local_kb import RecordingExecutor, finalize_result
    from eval.pipelines import UsageLLM, run_condition
    from providers.llm.base import LLMResult
    from tools import ToolExecutor
    from tools.base import ToolError, ToolResult

    class BrokenTool:
        name = "kb_search"
        async def execute(self, call_id, **kwargs):
            return ToolResult(call_id=call_id, status="error", error=ToolError("provider_unavailable", "offline"))
    class FailingAfterPlan:
        calls = 0
        async def generate(self, messages, metadata=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResult(text='{"tool_calls":[{"tool":"kb_search","args":{"query":"policy"}}]}', provider="fixture", model="fixture", prompt_tokens=5, completion_tokens=5)
            raise RuntimeError("provider failed")
    budget = Budget()
    executor = RecordingExecutor(ToolExecutor(tools=[BrokenTool()]))
    result = asyncio.run(run_condition("C", {"id":"q", "question":"policy"}, llm=UsageLLM(FailingAfterPlan()), checker=None,
                                      corpus=None, store=EvidenceStore(), executor=executor, budget=budget))
    finalize_result(result, budget, executor)
    assert result.status == "error"
    assert result.stop_reason == "execution_error"
    assert result.budget_report["tool_calls"] == 1
    assert any(t["type"] == "tool_result" and t["error_code"] == "provider_unavailable" for t in result.tool_trace)
    assert result.usage["llm_calls"] == 2


def test_frozen_dataset_is_complete_and_does_not_claim_human_gold():
    config, questions = read_dataset()
    assert len(questions) == 60
    assert len(config["documents"]) == 16
    assert len({q["id"] for q in questions}) == 60
    assert sum(q["expected"] == "answered" for q in questions) == 48
    assert all(not q["human_verified"] for q in questions)
    assert all(q["facts"] for q in questions if q["expected"] == "answered")
