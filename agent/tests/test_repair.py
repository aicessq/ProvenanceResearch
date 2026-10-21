"""验证反馈、部分作答及跨阶段预算必须通过实际 loop。"""
import asyncio
import json
from dataclasses import replace

from agent.budget import Budget, StopReason
from agent.citation_gate import CitationGate
from agent.loop import AgentLoop, SemanticVerifier
from agent.tests.test_budget_reader import _ev
from agent.tests.test_gaps import CapturePlanner
from agent.tests.test_loop import PLAN_DONE, ScriptLLM, YesChecker
from evidence.store import EvidenceStore
from tools import ToolExecutor
from tools.base import ToolResult


def seed(store, text="采用检索方法", scope="fulltext"):
    ev = replace(_ev(text, text=text), content_scope=scope)
    return store.register(replace(ev, citation_id=ev.make_citation_id()))


def output(cid, *, mixed=False):
    claims = [{"claim": "采用检索方法", "citations": [cid], "scope": "fulltext"}]
    if mixed:
        claims.append({"claim": "提升 2099 倍", "citations": [cid]})
    return json.dumps({"answer": "采用检索方法，提升 2099 倍。此句未列入 claims。", "claims": claims})


def test_answer_is_rebuilt_from_verified_claims_not_unchecked_writer_prose():
    store = EvidenceStore()
    ev = seed(store)
    answer = asyncio.run(AgentLoop(planner=ScriptLLM([PLAN_DONE]),
        writer=ScriptLLM([output(ev.citation_id)]), store=store, executor=ToolExecutor([]),
        gate=CitationGate(semantic_checker=YesChecker())).run("方法是什么"))
    assert answer.status == "answered"
    assert "采用检索方法" in answer.answer
    assert "2099" not in answer.answer
    assert ev.citation_id in answer.answer


def test_partial_answer_drops_failed_claim_after_one_regeneration():
    store = EvidenceStore()
    ev = seed(store)
    writer = ScriptLLM([output(ev.citation_id, mixed=True)] * 2)
    answer = asyncio.run(AgentLoop(planner=ScriptLLM([PLAN_DONE, PLAN_DONE]), writer=writer,
        store=store, executor=ToolExecutor([]), gate=CitationGate(semantic_checker=YesChecker())).run("方法和提升"))
    assert answer.status == "answered"
    assert len(answer.claims) == 1
    assert "2099" not in answer.answer
    assert answer.limitations
    assert writer.stages == ["generate", "generate"]


def test_scope_failure_fetches_then_regenerates_with_feedback():
    store = EvidenceStore()
    abstract = seed(store, scope="abstract")
    full = _ev("full", text="采用检索方法")
    full = replace(full, citation_id=full.make_citation_id())

    class Fetch:
        name = "source_fetch"

        async def execute(self, call_id, **args):
            store.register(full)
            return ToolResult(call_id, "ok", evidence=[full])

    planner = CapturePlanner([PLAN_DONE, json.dumps({"tool_calls": [{"tool": "source_fetch",
        "args": {"source_id": abstract.source_id}}]}), PLAN_DONE])
    writer = ScriptLLM([output(abstract.citation_id), output(full.citation_id)])
    answer = asyncio.run(AgentLoop(planner=planner, writer=writer, store=store,
        executor=ToolExecutor([Fetch()]), gate=CitationGate(semantic_checker=YesChecker()),
        budget=Budget(max_rounds=3)).run("方法是什么"))
    assert answer.status == "answered"
    assert full.citation_id in answer.citations
    assert "insufficient_scope" in planner.inputs[1]
    assert answer.budget_report["tool_calls"] == 1


def test_verifier_cannot_start_after_token_budget_is_used():
    llm = ScriptLLM(["yes"])
    budget = Budget(max_tokens=1, tokens=1)
    from agent.citation_gate import Claim
    import pytest
    with pytest.raises(Exception, match="budget_exhausted"):
        asyncio.run(SemanticVerifier(llm, budget=budget).check(Claim("事实", ("K1",)), []))
    assert not llm.stages


def test_verification_token_overrun_cannot_return_answered():
    store = EvidenceStore()
    ev = seed(store)
    budget = Budget(max_tokens=5)
    llm = ScriptLLM(["yes"])
    answer = asyncio.run(AgentLoop(planner=ScriptLLM([PLAN_DONE]),
        writer=ScriptLLM([output(ev.citation_id)]), store=store, executor=ToolExecutor([]),
        gate=CitationGate(semantic_checker=SemanticVerifier(llm, budget=budget)), budget=budget).run("方法"))
    assert answer.status == "refused"
    assert answer.stop_reason == StopReason.BUDGET_EXHAUSTED
    assert answer.trace[-1]["type"] == "done"


def test_deadline_cancels_inflight_planner_and_emits_one_terminal():
    cancelled = []

    class Slow(ScriptLLM):
        async def generate(self, messages, metadata=None):
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.append(True)

    answer = asyncio.run(AgentLoop(planner=Slow([]), writer=ScriptLLM([]),
        store=EvidenceStore(), executor=ToolExecutor([]), gate=CitationGate(),
        budget=Budget(deadline_seconds=0.02)).run("q"))
    assert cancelled == [True]
    assert answer.stop_reason == StopReason.DEADLINE_EXCEEDED
    assert sum(e["type"] == "done" for e in answer.trace) == 1


def test_parent_cancellation_is_not_converted_to_refusal():
    async def run():
        started = asyncio.Event()

        class Slow(ScriptLLM):
            async def generate(self, messages, metadata=None):
                started.set()
                await asyncio.sleep(60)

        task = asyncio.create_task(AgentLoop(planner=Slow([]), writer=ScriptLLM([]),
            store=EvidenceStore(), executor=ToolExecutor([]), gate=CitationGate()).run("q"))
        await started.wait()
        task.cancel()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


def test_semantic_verifier_requires_unambiguous_yes():
    from agent.citation_gate import Claim
    verifier = SemanticVerifier(ScriptLLM(["not yes"]))
    assert asyncio.run(verifier.check(Claim("事实", ("K1",)), [])) is False
