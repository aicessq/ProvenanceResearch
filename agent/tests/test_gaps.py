"""缺口闭环：真实 loop 关联证据、反馈失败并验证闭合条件。"""
import asyncio
import json
from dataclasses import replace

from agent.budget import StopReason
from agent.citation_gate import CitationGate
from agent.loop import AgentLoop
from agent.tests.test_budget_reader import _ev
from agent.tests.test_loop import ScriptLLM, YesChecker
from evidence.store import EvidenceStore
from tools import ToolExecutor
from tools.base import ToolError, ToolResult


def gap(cid=None, *, status="open", scope="fulltext"):
    return {"gap_id": "method", "question": "方法是什么", "required_scope": scope,
            "completion_criterion": "采用检索方法", "status": status,
            "supporting_citation_ids": [cid] if cid else []}


class CapturePlanner(ScriptLLM):
    def __init__(self, responses):
        super().__init__(responses)
        self.inputs = []

    async def generate(self, messages, metadata=None):
        self.inputs.append(messages[0].content)
        return await super().generate(messages, metadata)


def test_missing_fulltext_reads_registered_source_and_closes_gap():
    store = EvidenceStore()
    abstract = replace(_ev("abstract", text="摘要提到检索"), content_scope="abstract")
    full = _ev("full", text="采用检索方法")
    full = replace(full, citation_id=full.make_citation_id())
    abstract = store.register(replace(abstract, citation_id=abstract.make_citation_id()))

    class Fetch:
        name = "source_fetch"

        async def execute(self, call_id, **args):
            assert args == {"source_id": abstract.source_id}
            store.register(full)
            return ToolResult(call_id, "ok", evidence=[full])

    planner = CapturePlanner([
        json.dumps({"gaps": [gap()], "tool_calls": [{"tool": "source_fetch",
                    "args": {"source_id": abstract.source_id}, "gap_ids": ["method"]}]}),
        json.dumps({"gaps": [gap(full.citation_id, status="resolved")], "tool_calls": []})])
    writer = ScriptLLM([json.dumps({"answer": "采用检索方法", "claims": [
        {"claim": "采用检索方法", "citations": [full.citation_id]}]})])
    loop = AgentLoop(planner=planner, writer=writer, store=store, executor=ToolExecutor([Fetch()]),
                     gate=CitationGate(semantic_checker=YesChecker()))
    answer = asyncio.run(loop.run("方法是什么"))
    assert answer.status == "answered"
    assert answer.gaps[0]["status"] == "resolved"
    assert answer.gaps[0]["attempts"][0]["call_id"]
    assert answer.gaps[0]["attempts"][0]["evidence_ids"] == [full.citation_id]
    assert abstract.source_id in planner.inputs[0]
    assert "fulltext" in planner.inputs[1]


def test_abstract_cannot_close_fulltext_gap_even_if_model_says_done():
    store = EvidenceStore()
    ev = replace(_ev("abstract", text="采用检索方法"), content_scope="abstract")
    ev = store.register(replace(ev, citation_id=ev.make_citation_id()))
    planner = CapturePlanner([json.dumps({"gaps": [gap(ev.citation_id, status="resolved")],
                                         "tool_calls": []})])
    writer = ScriptLLM([json.dumps({"answer": "摘要描述方法", "claims": [
        {"claim": "采用检索方法", "citations": [ev.citation_id], "scope": "abstract"}]})])
    loop = AgentLoop(planner=planner, writer=writer, store=store, executor=ToolExecutor([]),
                     gate=CitationGate(semantic_checker=YesChecker()))
    answer = asyncio.run(loop.run("方法是什么"))
    assert answer.gaps[0]["status"] == "unresolved"
    assert answer.stop_reason == StopReason.NO_PROGRESS


def test_failed_tool_is_visible_to_next_plan_and_not_evidence():
    store = EvidenceStore()

    class Fail:
        name = "web_search"

        async def execute(self, call_id, **args):
            return ToolResult(call_id, "error", error=ToolError("rate_limited", "secret free"))

    planner = CapturePlanner([
        json.dumps({"gaps": [gap()], "tool_calls": [{"tool": "web_search",
                    "args": {"query": "方法"}, "gap_ids": ["method"]}]}),
        json.dumps({"gaps": [gap()], "tool_calls": []})])
    answer = asyncio.run(AgentLoop(planner=planner, writer=ScriptLLM([]), store=store,
                                  executor=ToolExecutor([Fail()]), gate=CitationGate()).run("方法是什么"))
    assert "rate_limited" in planner.inputs[1]
    assert "方法" in planner.inputs[1]
    assert answer.gaps[0]["status"] == "unresolved"
    assert not answer.evidence


def test_deleting_gap_does_not_close_it_and_redefinition_is_rejected():
    async def run(second):
        from agent.gaps import GapLedger
        ledger = GapLedger()
        await ledger.update([gap()], EvidenceStore(), CitationGate())
        await ledger.update(second, EvidenceStore(), CitationGate())
        return ledger

    ledger = asyncio.run(run([]))
    assert ledger.open_ids == ["method"]
    import pytest
    with pytest.raises(ValueError, match="不能改写"):
        asyncio.run(run([{**gap(), "completion_criterion": "更容易满足的条件"}]))


def test_forged_or_semantically_unsupported_citation_cannot_close_gap():
    from agent.gaps import GapLedger

    class NoChecker:
        async def check(self, claim, evidence):
            return False

    async def run():
        ledger = GapLedger()
        store = EvidenceStore()
        ev = _ev("full", text="采用检索方法")
        ev = store.register(replace(ev, citation_id=ev.make_citation_id()))
        gate = CitationGate(semantic_checker=NoChecker())
        await ledger.update([gap("Kforged", status="resolved")], store, gate)
        assert ledger.open_ids == ["method"]
        await ledger.update([gap(ev.citation_id, status="resolved")], store, gate)
        assert ledger.open_ids == ["method"]

    asyncio.run(run())


def test_search_evidence_can_be_fetched_without_separate_registry_seed():
    import httpx
    from evidence.registry import SourceRegistry, content_hash
    from evidence.schema import Provenance
    from tools import SourceFetchTool

    store = EvidenceStore()
    ev = replace(_ev("web"), source_id="web:registered", source_type="web", content_scope="snippet",
                 provenance=Provenance(provider="tavily", content_hash=content_hash("摘录"),
                                       canonical_url="https://www.rfc-editor.org/rfc/rfc5246",
                                       fetched_at="2026-10-21T00:00:00Z"))
    ev = store.register(replace(ev, citation_id=ev.make_citation_id()))
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, text="正文内容", headers={"content-type": "text/plain"})))
    tool = SourceFetchTool(registry=SourceRegistry(), store=store, client=client)
    result = asyncio.run(ToolExecutor([tool]).execute("source_fetch", source_id=ev.source_id))
    assert result.status == "ok"
    assert result.evidence[0].content_scope == "fulltext"
    assert result.evidence[0].raw_text == "正文内容"
