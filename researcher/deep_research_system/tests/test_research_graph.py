"""Research graph contracts with external I/O replaced by deterministic fixtures."""

import asyncio
import json

import httpx
import pytest

from .test_agentic_service import KB_PAYLOAD, FakeStoreHolder, YesChecker, make_runtime, service_with, wait_terminal
from agent.budget import Budget, StopReason
from app.graphs.research_graph import Clarification, run_research
from evidence.registry import SourceRegistry
from providers.llm.base import LLMResult
from tools import ArxivSearchTool, EvidenceReadTool, KBSearchTool, SourceFetchTool, ToolExecutor, ToolResult, WebSearchTool


def call(tool, **args):
    return {"tool": tool, "args": args}


def result(payload, *, tokens=2):
    return LLMResult(json.dumps(payload, ensure_ascii=False), "test", "test", tokens)


def version_verdict(*inapplicable_conditions):
    return {"supported": True, "inapplicable_conditions": list(inapplicable_conditions)}


@pytest.mark.parametrize(("sufficient", "blocked", "local_enabled"), [
    (True, False, False), (False, False, False), (False, True, False), (False, True, True),
])
def test_same_question_reads_fulltext_only_when_search_needs_it(sufficient, blocked, local_enabled):
    async def scenario():
        store = FakeStoreHolder().store
        class Checker:
            async def check(self, claim, evidence, question=""):
                return "保障网络安全" in evidence[0].raw_text

        runtime = make_runtime(store, checker=Checker())
        registry = SourceRegistry()
        requests = []

        def search(request):
            requests.append("search")
            return httpx.Response(200, json={"results": [{
                "url": "https://example.org/doc", "title": "Research note",
                "content": "第一条 为了保障网络安全，制定本法。" if sufficient else "研究笔记摘要",
            }]})

        def fetch(request):
            requests.append("fetch")
            return httpx.Response(200, text="<p>第一条 为了保障网络安全，制定本法。</p>",
                                  headers={"content-type": "image/png" if blocked else "text/html"})

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(search)) as search_client,
            httpx.AsyncClient(transport=httpx.MockTransport(fetch)) as fetch_client,
        ):
            available_tools = [
                WebSearchTool(api_key="test", client=search_client, store=store),
                SourceFetchTool(registry=registry, client=fetch_client, store=store),
            ]
            if local_enabled:
                available_tools.append(KBSearchTool(
                    base_url="http://kb", index_identity="test", client=search_client, store=store,
                ))
            runtime.executor = ToolExecutor(available_tools, registry=registry)

            class Agent:
                async def generate(self, messages, metadata):
                    stage = metadata["stage"]
                    if stage == "scope":
                        return result({})
                    if stage == "generate":
                        evidence = json.loads(messages[-1].content)["evidence"][0]
                        return result({"claims": [{
                            "claim": "为了保障网络安全而制定本法",
                            "citations": [evidence["id"]], "scope": evidence["scope"],
                            "quote": evidence["text"],
                        }]})
                    data = json.loads(messages[-1].content)
                    outputs = data.get("untrusted_tool_results")
                    if outputs is None:
                        return result({"tool_calls": [call("web_search", query="网络安全法目的")]})
                    if outputs[0]["error"] == "fetch_blocked":
                        assert outputs[0]["error_detail"] == "不允许的 MIME 类型: image/png"
                        assert "web_search" in outputs[0]["hint"]
                        assert ("kb_search" in outputs[0]["hint"]) is local_enabled
                        return result({"tool_calls": [call("submit")]})
                    if any("保障网络安全" in ev["text"] for ev in outputs[0]["evidence"]):
                        return result({"tool_calls": [call("submit")]})
                    return result({"tool_calls": [call("source_fetch",
                                                       source_id=outputs[0]["evidence"][0]["citation_id"])]})

            runtime.llm = Agent()
            answer = await run_research("为什么制定网络安全法？", runtime, Budget(max_rounds=4))

        assert requests == (["search"] if sufficient else ["search", "fetch"])
        if blocked:
            assert answer.status == "refused"
            assert answer.search_summary[-1]["error_detail"] == "不允许的 MIME 类型: image/png"
            return
        assert answer.status == "answered"
        assert answer.claims[0].scope == ("snippet" if sufficient else "fulltext")
        if not sufficient:
            assert answer.evidence[0].locator.section == "paragraph-1"

    asyncio.run(scenario())


def test_parallel_search_reserves_allowance_and_coalesces_duplicates():
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store)
        started = []
        both = asyncio.Event()

        class Search:
            name = "web_search"

            async def execute(self, call_id, **kwargs):
                started.append(kwargs["query"])
                if len(started) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), timeout=0.5)
                return ToolResult(call_id, "empty")

        class Agent:
            async def generate(self, messages, metadata):
                return result({"tool_calls": [
                    call("web_search", query="a"), call("web_search", query="b"),
                    call("web_search", query="a", top_k=4), call("web_search", query="c"),
                ]}) if metadata["stage"] == "plan" else result({})

        runtime.executor = ToolExecutor([Search()])
        runtime.llm = Agent()
        answer = await run_research("研究问题", runtime, Budget(max_tool_calls=2))
        assert started == ["a", "b"]
        assert answer.stop_reason == StopReason.BUDGET_EXHAUSTED

    asyncio.run(scenario())


@pytest.mark.parametrize(("max_tokens", "view", "long_url"), [
    (36000, "preview", False), (22000, "metadata", False),
    (14000, "reference", False), (1_000_000, "reference", True),
])
def test_parallel_search_previews_leave_room_to_follow_up(max_tokens, view, long_url):
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store)
        snippet = "这是一段需要保留在证据库的长搜索结果。" * 20
        observed = []
        read = []

        def search(request):
            query = json.loads(request.content)["query"]
            path = "page/" * 140 if long_url else ""
            return httpx.Response(200, json={"results": [
                {"url": f"https://example.org/{query}/{path}{index}", "title": f"来源 {index}", "content": snippet}
                for index in range(8)
            ]})

        class Agent:
            async def generate(self, messages, metadata):
                if metadata["stage"] != "plan":
                    return result({})
                outputs = json.loads(messages[-1].content).get("untrusted_tool_results")
                if outputs is None:
                    return result({"tool_calls": [call("web_search", query=f"query{index}") for index in range(4)]})
                if outputs[0]["tool"] == "evidence_read":
                    read.append(outputs[0]["evidence"][0]["text"])
                    return result({"tool_calls": [call("submit")]})
                observed.extend(outputs)
                return result({"tool_calls": [
                    call("evidence_read", evidence_id=outputs[0]["evidence"][-1]["citation_id"]),
                ]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=store),
                                             EvidenceReadTool(store=store)])
            runtime.llm = Agent()
            answer = await run_research("研究问题", runtime, Budget(max_tokens=max_tokens))

        assert len(observed) == 4
        assert read == [snippet]
        actions = {event.get("action") for event in answer.trace}
        assert ("compact_tool_previews" in actions) == (view != "preview")
        assert ("compact_tool_references" in actions) == (view == "reference")
        for output in observed:
            previews = output["evidence"]
            assert len(previews) == 8
            assert [len(item.get("text", "")) for item in previews] == (
                [160] * 3 + [0] * 5 if view == "preview" else [0] * 8
            )
            if view == "reference":
                assert set(previews[-1]) == {"citation_id"}
            else:
                assert previews[-1]["title"] == "来源 7"
            assert store.get(previews[-1]["citation_id"]).raw_text == snippet

    asyncio.run(scenario())


def test_repeated_failed_search_warns_then_stops_without_another_request():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        reminders = []
        outgoing = []

        class Search:
            name = "web_search"

            async def execute(self, call_id, **kwargs):
                outgoing.append(kwargs)
                raise RuntimeError("test failure")

        class Agent:
            async def generate(self, messages, metadata):
                if metadata["stage"] == "scope":
                    return result({})
                prior = json.loads(messages[-1].content)
                if prior.get("reminder"):
                    reminders.append(prior)
                return result({"tool_calls": [call("web_search", query="same", top_k=len(messages))]})

        runtime.executor = ToolExecutor([Search()])
        runtime.llm = Agent()
        answer = await run_research("研究问题", runtime, Budget(max_rounds=8))
        assert answer.stop_reason == StopReason.NO_PROGRESS
        assert len(outgoing) == len(reminders) == 1
        assert reminders[0]["untrusted_tool_results"][0]["notice"] == "已查过"
        assert reminders[0]["untrusted_tool_results"][0]["error"] == "tool_crashed"

    asyncio.run(scenario())


def test_recent_web_lookup_has_separate_cache_from_unfiltered_lookup():
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store)
        requests = []
        cached = []

        def search(request):
            time_range = json.loads(request.content).get("time_range")
            requests.append(time_range)
            return httpx.Response(200, json={"results": [{
                "url": f"https://example.org/{time_range or 'all'}",
                "title": "资料", "content": f"时间查询结果 {time_range or 'all'}",
            }]})

        class Agent:
            async def generate(self, messages, metadata):
                if metadata["stage"] != "plan":
                    return result({})
                data = json.loads(messages[-1].content)
                outputs = data.get("untrusted_tool_results", [])
                if not outputs:
                    return result({"tool_calls": [call("web_search", query="法规全文")]})
                if requests == [None]:
                    return result({"tool_calls": [
                        call("web_search", query="法规全文", time_range="year"),
                        call("web_search", query="法规全文", time_range="y"),
                    ]})
                cached.extend(item.get("cached", False) for item in outputs)
                return result({"tool_calls": [call("submit")]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=store)])
            runtime.llm = Agent()
            await run_research("查现行法规全文", runtime, Budget(max_rounds=4))

        assert requests == [None, "year"]
        assert cached == [False, True]

    asyncio.run(scenario())


def test_unavailable_paper_search_guides_same_agent_to_local_evidence():
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store, checker=YesChecker())

        def respond(request):
            if request.url.host == "export.arxiv.org":
                return httpx.Response(429)
            chunk = dict(KB_PAYLOAD["chunks"][0], doc_title="Example Research (v1)",
                         chunk_text="The v1 experiment used the same corpus for both groups.")
            return httpx.Response(200, json={"chunks": [chunk]})

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({})
                if stage == "generate":
                    return result({"claims": [{
                        "claim": "两组使用同一语料", "citations": [data["evidence"][0]["id"]],
                    }]})
                outputs = data.get("untrusted_tool_results")
                if outputs is None:
                    return result({"tool_calls": [call("arxiv_search", query="Example Research v1")]})
                if outputs[0]["tool"] == "arxiv_search":
                    assert outputs[0]["error"] == "provider_unavailable"
                    assert "kb_search" in outputs[0]["hint"] and "具体版本" in outputs[0]["hint"]
                    return result({"tool_calls": [call("kb_search", query="Example Research v1")]})
                assert outputs[0]["evidence"][0]["scope"] == "fulltext"
                return result({"tool_calls": [call("submit")]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            runtime.executor = ToolExecutor([
                ArxivSearchTool(client=client, store=store),
                KBSearchTool(base_url="http://kb.internal", client=client, store=store, index_identity="idx"),
            ])
            runtime.llm = Agent()
            answer = await run_research("Example Research v1 的两组实验使用什么语料？", runtime, Budget())
        assert answer.answer == "两组使用同一语料"
        assert answer.budget_report["tool_calls"] == 2

    asyncio.run(scenario())


def test_exploration_refreshes_allowance_and_repeats_plan_only_when_edited():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        updates = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"questions": ["原问题"]})
                if stage != "plan":
                    return result({"claims": []})
                updates.append(data)
                if len(updates) == 1:
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if len(updates) == 2:
                    assert "questions" not in data and "missing" not in data
                    return result({"tool_calls": [
                        call("revise_plan", question_id="q1", question="收窄问题", reason="限定证据范围"),
                    ]})
                if len(updates) == 3:
                    assert data["questions"] == data["missing"] == {"q1": "收窄问题"}
                return result({"tool_calls": [call("submit")]})

        runtime.llm = Agent()
        answer = await run_research("原始请求", runtime, Budget(max_tool_calls=4, max_rounds=4))
        assert [item["remaining_tool_calls"] for item in updates[:3]] == [4, 3, 2]
        assert [item["remaining_exploration_turns"] for item in updates[:3]] == [4, 3, 2]
        assert all(left["remaining_exploration_tokens"] > right["remaining_exploration_tokens"]
                   for left, right in zip(updates[:2], updates[1:3]))
        assert answer.plan_changes[0]["question"] == "收窄问题"

    asyncio.run(scenario())


def test_task_can_resume_twice_and_rejects_a_stale_reply():
    async def scenario():
        class Agent:
            async def generate(self, messages, metadata):
                if metadata["stage"] != "scope":
                    return result({"tool_calls": []})
                replies = json.loads(messages[-1].content)["clarifications"]
                if len(replies) == 2:
                    assert [item["answer"] for item in replies] == ["中国", "现行版"]
                    return result({"questions": ["中国现行版有哪些规定？"], "clarification": "第三轮？",
                                   "assumptions": ["采用公开可查的文本"]})
                return result({"clarification": ["哪个法域？", "哪个版本？"][len(replies)]})

        def factory():
            runtime = make_runtime(FakeStoreHolder().store)
            runtime.llm = Agent()
            return runtime

        service = service_with(factory)
        task_id = (await service.create_task("规定是什么？"))["task_id"]
        subscription = service.subscribe(task_id)
        rounds = []
        async with asyncio.timeout(2):
            try:
                async for event in subscription:
                    if event.payload.get("action") == "clarification_requested":
                        ordinal = event.payload["round"]
                        rounds.append(ordinal)
                        if ordinal == 2:
                            assert await service.submit_clarification(task_id, 1, "过期") == "not_waiting"
                        reply = {1: "中国", 2: "现行版"}[ordinal]
                        assert await service.submit_clarification(task_id, ordinal, reply) == "accepted"
            finally:
                await subscription.aclose()
        outcome = (await wait_terminal(service, task_id))["answer"]
        assert rounds == [1, 2]
        assert outcome["missing_questions"] == ["中国现行版有哪些规定？"]
        assert outcome["assumptions"] == ["采用公开可查的文本"]

    asyncio.run(scenario())


@pytest.mark.parametrize("assumptions", [[], ["采用现行版"]])
def test_clarification_timeout_uses_only_explicit_assumptions(assumptions):
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        stages = []

        class Agent:
            async def generate(self, messages, metadata):
                stages.append(metadata["stage"])
                if stages[-1] == "scope":
                    return result({"clarification": "哪个版本？", "assumptions": assumptions})
                return result({"tool_calls": []})

        runtime.llm = Agent()
        budget = Budget(deadline_seconds=0.12)
        answer = await run_research("规定是什么？", runtime, budget, clarification=Clarification())
        assert answer.assumptions == tuple(assumptions)
        assert answer.refusal_reason == ("no_evidence" if assumptions else "clarification_required")
        assert stages[0] == "scope"
        assert ("plan" in stages) == bool(assumptions)

    asyncio.run(scenario())


def test_waiting_task_can_be_cancelled():
    async def scenario():
        class Agent:
            async def generate(self, messages, metadata):
                assert metadata["stage"] == "scope"
                return result({"clarification": "哪个版本？"})

        def factory():
            runtime = make_runtime(FakeStoreHolder().store)
            runtime.llm = Agent()
            return runtime

        service = service_with(factory)
        task_id = (await service.create_task("规定是什么？"))["task_id"]
        subscription = service.subscribe(task_id)
        async with asyncio.timeout(2):
            try:
                async for event in subscription:
                    if event.payload.get("action") == "clarification_requested":
                        assert await service.cancel_task(task_id) == "cancelled"
                    if event.is_terminal:
                        assert event.payload["task_status"] == "cancelled"
            finally:
                await subscription.aclose()
        assert (await wait_terminal(service, task_id))["status"] == "cancelled"
        assert await service.submit_clarification(task_id, 1, "晚到") == "not_waiting"

    asyncio.run(scenario())


@pytest.mark.parametrize("repair_passes", [True, False])
def test_repairs_use_finish_budget_and_never_recheck_unchanged_claims(repair_passes):
    async def scenario():
        checks = []
        drafts = 0
        store = FakeStoreHolder().store

        class Checker:
            async def check(self, claim, evidence, question=""):
                checks.append(claim.claim)
                return claim.claim != "错误结论"

        runtime = make_runtime(store, checker=Checker())

        class Agent:
            async def generate(self, messages, metadata):
                nonlocal drafts
                stage = metadata["stage"]
                if stage == "scope":
                    return result({"questions": ["为何制定？", "何时生效？"]})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if stage == "coverage":
                    return result({"missing": {}})
                drafts += 1
                citation = json.loads(messages[-1].content)["evidence"][0]["id"]
                return result({"claims": [
                    {"question_id": "q1", "claim": "保障网络安全", "citations": [citation]},
                    {"question_id": "q2", "claim": "缩小后的结论" if repair_passes and drafts > 1
                     else "错误结论", "citations": [citation]},
                ]})

        runtime.llm = Agent()
        answer = await run_research("法律规定", runtime, Budget(max_tool_calls=1))
        assert drafts == (2 if repair_passes else 3)
        assert answer.budget_report["tool_calls"] == 1
        assert checks.count("保障网络安全") == checks.count("错误结论") == 1
        assert "错误结论" not in answer.answer
        assert answer.partial is not repair_passes
        assert answer.missing_questions == (() if repair_passes else ("何时生效？",))

    asyncio.run(scenario())


@pytest.mark.parametrize("overall_gap", ["", "缺少指定版本的原文对照"])
@pytest.mark.parametrize("deliverables", [[], ["列出适用范围的条件和例外"]])
@pytest.mark.parametrize("first_draft_tokens", [2, 12000])
def test_missing_question_returns_to_original_exploration_context(overall_gap, deliverables, first_draft_tokens):
    async def scenario():
        store = FakeStoreHolder().store

        class Checker:
            async def check(self, claim, evidence, question=""):
                return True

        runtime = make_runtime(store, checker=Checker())
        turns = 0
        now = 0.0

        class Agent:
            async def generate(self, messages, metadata):
                nonlocal turns, now
                stage = metadata["stage"]
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"questions": ["为何制定？", "适用范围？"], "deliverables": deliverables})
                if stage == "coverage":
                    assert data["original_question"] == "法律规定"
                    if set(data["verified_claims"]) == {"q1"}:
                        assert data["deliverables"] == deliverables
                        return result({"missing": {"q2": "还需定位条文的主体条件与例外"}})
                    assert set(data["verified_claims"]) == {"q1", "q2"}
                    return result({"missing": {"overall": overall_gap} if overall_gap else {}})
                if stage == "generate":
                    if deliverables:
                        assert data["deliverables"] == deliverables
                    key = "q1" if "q1" in data["missing"] else "q2"
                    if key == "q1" and first_draft_tokens == 12000:
                        now = 145.0
                    return result({"claims": [{"question_id": key, "claim": "保障网络安全" if key == "q1" else "适用网络安全事项",
                                               "citations": [data["evidence"][0]["id"]]}]},
                                  tokens=first_draft_tokens if key == "q1" else 2)
                turns += 1
                if turns == 1:
                    return result({"tool_calls": [call("kb_search", query="制定目的")]})
                if turns == 3:
                    assert data["missing"] == {"q2": "适用范围？"}
                    ceiling = 8000 if first_draft_tokens == 12000 else 10000
                    assert ceiling - 100 < data["remaining_exploration_tokens"] < ceiling
                    assert data["remaining_exploration_seconds"] == (35 if first_draft_tokens == 12000 else 135)
                    if deliverables:
                        assert data["coverage_gaps"] == {"q2": "还需定位条文的主体条件与例外"}
                    assert any(message.role == "assistant" and "制定目的" in message.content
                               for message in messages)
                    return result({"tool_calls": [call("kb_search", query="适用范围")]})
                return result({"tool_calls": [call("submit")]})

        runtime.llm = Agent()
        answer = await run_research("法律规定", runtime, Budget(max_rounds=4, deadline_seconds=180,
                                                              clock=lambda: now, started_at=0))
        assert answer.status == "answered"
        assert answer.partial == bool(overall_gap)
        assert answer.missing_questions == ((overall_gap,) if overall_gap else ())
        assert [claim.claim for claim in answer.claims] == ["保障网络安全", "适用网络安全事项"]
        assert answer.budget_report["tool_calls"] == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("recovery", ["new_evidence", "repeat", "submit", "round_limit", "invalid_coverage"])
def test_coverage_gap_reopens_stalled_exploration_once(recovery):
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store, checker=YesChecker())
        stages = []
        planner_turns = 0
        queries = []

        def search(request):
            query = json.loads(request.content)["query"]
            queries.append(query)
            return httpx.Response(200, json={"results": [{
                "url": f"https://example.org/{query}", "title": query,
                "content": "保障网络安全" if query == "purpose" else "适用于网络安全事项",
            }]})

        class Agent:
            async def generate(self, messages, metadata):
                nonlocal planner_turns
                stage = metadata["stage"]
                stages.append(stage)
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"questions": ["为何制定？", "适用范围？"], "deliverables": ["列出适用范围"]})
                if stage == "coverage":
                    if recovery == "invalid_coverage":
                        return result({"missing": {"q2": []}})
                    return result({"missing": {} if "q2" in data["verified_claims"]
                                   else {"q2": "需查适用范围条文"}})
                if stage == "layout":
                    return result({})
                if stage == "generate":
                    pending = {"q1": "保障网络安全", "q2": "适用于网络安全事项"}
                    claims = [{"question_id": key, "claim": claim, "citations": [evidence["id"]],
                               "scope": evidence["scope"]}
                              for key, claim in pending.items() if key in data["missing"]
                              for evidence in data["evidence"] if claim in evidence["text"]]
                    return result({"claims": claims})
                planner_turns += 1
                if planner_turns == 5:
                    assert data["coverage_gaps"] == {"q2": "需查适用范围条文"}
                    assert any(message.role == "assistant" and "purpose" in message.content
                               for message in messages)
                if planner_turns == 5 and recovery == "new_evidence":
                    return result({"tool_calls": [call("web_search", query="scope")]})
                if (planner_turns == 6 and recovery == "new_evidence"
                        or planner_turns == 5 and recovery == "submit"):
                    return result({"tool_calls": [call("submit")]})
                return result({"tool_calls": [call("web_search", query="purpose")]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=store)])
            runtime.llm = Agent()
            answer = await run_research("法律规定", runtime, Budget(max_rounds=4 if recovery == "round_limit" else 12))

        complete = recovery == "new_evidence"
        assert answer.status == "answered"
        assert queries == (["purpose", "scope"] if complete else ["purpose"])
        assert answer.partial is not complete
        assert planner_turns == {
            "new_evidence": 6, "repeat": 7, "submit": 5, "round_limit": 4, "invalid_coverage": 4,
        }[recovery]
        assert stages.index("coverage") > stages.index("plan")
        if recovery in {"repeat", "submit", "invalid_coverage"}:
            assert answer.stop_reason == StopReason.NO_PROGRESS

    asyncio.run(scenario())


def test_targeted_research_uses_one_planning_round_and_shared_search_budget():
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store)
        stages = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                stages.append(stage)
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("targeted_research", question_id="q1", gap="缺少依据")]})
                if stage == "targeted":
                    return result({"tool_calls": [
                        call("targeted_research", question_id="q1", gap="不得递归"),
                        call("kb_search", query="制定目的"), call("kb_search", query="适用范围"),
                    ]})
                data = json.loads(messages[-1].content)
                return result({"claims": []}) if stage == "generate" and data["evidence"] else result({})

        runtime.llm = Agent()
        answer = await run_research("为何制定？", runtime, Budget(max_tool_calls=2))
        assert stages == ["scope", "plan", "targeted", "generate"]
        calls = [item["tool"] for item in answer.trace if item["type"] == "tool_call"]
        assert calls == ["targeted_research", "kb_search"]
        assert answer.budget_report["tool_calls"] == 2

    asyncio.run(scenario())


def test_out_of_scope_stops_before_any_research_and_keeps_reason():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)

        class Agent:
            async def generate(self, messages, metadata):
                assert metadata["stage"] == "scope"
                return result({"out_of_scope": True, "reason": "无法代为签署文件"})

        runtime.llm = Agent()
        answer = await run_research("请代我签署文件", runtime, Budget())
        assert answer.status == "refused"
        assert answer.refusal_reason == "out_of_scope"
        assert answer.refusal_detail == "无法代为签署文件"
        assert not answer.search_summary
        assert answer.budget_report["tool_calls"] == 0

    asyncio.run(scenario())


def test_slow_tool_expires_and_is_listed_in_no_conclusion():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        cancelled = asyncio.Event()

        class Search:
            name = "web_search"

            async def execute(self, call_id, **kwargs):
                try:
                    await asyncio.sleep(10)
                finally:
                    cancelled.set()

        class Agent:
            async def generate(self, messages, metadata):
                if metadata["stage"] == "scope":
                    return result({})
                return result({"tool_calls": [call("web_search", query="具体查询")]})

        runtime.executor = ToolExecutor([Search()])
        runtime.llm = Agent()
        async with asyncio.timeout(1):
            answer = await run_research("研究问题", runtime, Budget(deadline_seconds=0.16))
        assert cancelled.is_set()
        assert answer.status == "refused"
        assert answer.stop_reason == StopReason.DEADLINE_EXCEEDED
        assert answer.search_summary == ({"tool": "web_search", "query": "具体查询", "status": "timeout"},)

    asyncio.run(scenario())


def test_model_usage_overrun_discards_exploration_output():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        ran_tool = False

        class Search:
            name = "web_search"

            async def execute(self, call_id, **kwargs):
                nonlocal ran_tool
                ran_tool = True
                return ToolResult(call_id, "empty")

        class Agent:
            async def generate(self, messages, metadata):
                if metadata["stage"] == "scope":
                    return result({})
                return result({"tool_calls": [call("web_search", query="不应执行")]}, tokens=11_000)

        runtime.executor = ToolExecutor([Search()])
        runtime.llm = Agent()
        answer = await run_research("研究问题", runtime, Budget())
        assert not ran_tool
        assert answer.stop_reason == StopReason.BUDGET_EXHAUSTED
        assert answer.budget_report["tokens"] == 11_002
        assert answer.budget_report["tool_calls"] == 0
        assert [event["cause"] for event in answer.trace if event["type"] == "budget_check"] == ["reported_usage"]

    asyncio.run(scenario())


@pytest.mark.parametrize("read_earlier", [False, True])
def test_reader_and_verifier_receive_late_text_from_registered_source(read_earlier):
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store)
        registry = SourceRegistry()
        quote = "This section establishes the condition sought."
        earlier = "The authors measured the original effect in two groups."
        earlier_offset = 1000
        offset = 2200
        body = ("<p>" + ("x" * earlier_offset) + earlier
                + ("y" * (offset - earlier_offset - len(earlier))) + quote + "</p>")

        def search(_):
            return httpx.Response(200, json={"results": [{
                "url": "https://example.org/doc", "title": "Research note", "content": "Contents overview.",
            }]})

        def fetch(_):
            return httpx.Response(200, text=body, headers={"content-type": "text/html"})

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(search)) as search_client,
            httpx.AsyncClient(transport=httpx.MockTransport(fetch)) as fetch_client,
        ):
            runtime.executor = ToolExecutor([
                WebSearchTool(api_key="test", client=search_client, store=store),
                SourceFetchTool(registry=registry, client=fetch_client, store=store),
                EvidenceReadTool(store=store),
            ], registry=registry)

            class Agent:
                async def generate(self, messages, metadata):
                    stage = metadata["stage"]
                    data = json.loads(messages[-1].content)
                    if stage == "verify":
                        assert metadata["max_tokens"] >= 128
                        supported = data["claim"] in data["evidence"][0]["text"]
                        return LLMResult("yes" if supported else "no", "test", "test", 2)
                    if stage == "scope":
                        return result({})
                    if stage == "generate":
                        evidence = data["evidence"][0]
                        assert evidence["text"] == quote
                        assert evidence["text_offset"] == offset
                        other = evidence["other_excerpt"]
                        assert other["offset"] == (earlier_offset if read_earlier else 0)
                        assert len(evidence["text"]) + len(other["text"]) <= 700
                        if read_earlier:
                            assert earlier in other["text"]
                        return result({"claims": [
                            {"claim": text, "quote": text, "scope": "fulltext", "citations": [evidence["id"]]}
                            for text in ([earlier, quote] if read_earlier else [quote])
                        ]})
                    outputs = data.get("untrusted_tool_results")
                    if outputs is None:
                        return result({"tool_calls": [call("web_search", query="condition")]})
                    item = outputs[0]["evidence"][0]
                    if outputs[0]["tool"] == "web_search":
                        return result({"tool_calls": [call("source_fetch", source_id=item["source_id"])]})
                    offsets = [earlier_offset, offset] if read_earlier else [offset]
                    return result({"tool_calls": [
                        call("evidence_read", evidence_id=item["citation_id"], offset=start)
                        for start in offsets
                    ]})

            runtime.llm = Agent()
            answer = await run_research("What condition was established?", runtime, Budget())
        assert answer.status == "answered"
        assert [claim.quote for claim in answer.claims] == ([earlier, quote] if read_earlier else [quote])

    asyncio.run(scenario())


def test_new_read_excerpts_reset_guard_but_cached_reads_do_not():
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store)
        read_calls = []
        seen_excerpts = []

        class Agent:
            async def generate(self, messages, metadata):
                data = json.loads(messages[-1].content)
                if metadata["stage"] != "plan":
                    return result({"claims": []})
                outputs = data.get("untrusted_tool_results")
                if outputs is None:
                    return result({"tool_calls": [call("web_search", query="section")]})
                if outputs[0]["tool"] == "web_search":
                    cid = outputs[0]["evidence"][0]["citation_id"]
                    read_calls.extend(call("evidence_read", evidence_id=cid, offset=offset)
                                      for offset in (0, 7, 14))
                else:
                    seen_excerpts.extend(item["evidence"][0]["text"] for item in outputs
                                         if item.get("new_excerpt") and not item.get("cached"))
                return result({"tool_calls": read_calls})

        def search(_):
            return httpx.Response(200, json={"results": [{
                "url": "https://example.org/doc", "content": "First. Second. Third.", "title": "Note",
            }]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=store),
                                             EvidenceReadTool(store=store)])
            runtime.llm = Agent()
            answer = await run_research("Which sections are present?", runtime, Budget(max_rounds=6))
        assert seen_excerpts == ["First. Second. Third.", "Second. Third.", " Third."]
        assert answer.budget_report["tool_calls"] == 4
        assert answer.stop_reason == StopReason.NO_PROGRESS
        assert sum(item["type"] == "tool_result" and item.get("cached") is True
                   for item in answer.trace) == 3

    asyncio.run(scenario())


def test_forged_repair_does_not_turn_a_partial_answer_complete():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        drafts = []

        class Checker:
            async def check(self, claim, evidence, question=""):
                return claim.claim == "保障网络安全"

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                data = json.loads(messages[-1].content)
                citation = data["evidence"][0]["id"]
                drafts.append(data)
                claims = []
                if len(drafts) == 1:
                    claims.append({"claim": "保障网络安全", "citations": [citation]})
                claims.append({"claim": "未经支持的适用范围",
                               "citations": [citation if len(drafts) == 1 else "forged"]})
                return result({"claims": claims})

        runtime.semantic_checker = Checker()
        runtime.llm = Agent()
        answer = await run_research("为何制定网络安全法？", runtime, Budget(max_tool_calls=1))

        assert len(drafts) == 3
        assert drafts[-1]["failures"][0]["reason"] == "citation_not_in_draft_evidence"
        assert answer.partial
        assert answer.missing_questions == ("为何制定网络安全法？",)
        assert answer.answer == "保障网络安全"

    asyncio.run(scenario())


def test_plan_tools_observe_the_current_revision_and_keep_edit_limit():
    async def scenario():
        from app.graphs.research_graph import ResearchRun, _tool_batch

        runtime = make_runtime(FakeStoreHolder().store)
        await runtime.executor.execute("kb_search", query="网络安全法")
        citation = runtime.store.all()[0].citation_id
        questions = {"q1": "原问题", "q2": "另一问题"}
        run = ResearchRun("法律研究", runtime.llm, runtime.executor, runtime.store, Budget(),
                          questions=questions.copy(), initial_questions=questions.copy())

        async def invoke(name, **args):
            return (await _tool_batch(run, [(name, args)]))[0]

        edit = {"question_id": "q1", "question": "更窄的问题", "reason": "限制范围"}
        note = {"question_id": "q1", "citation_id": citation, "quote": "保障网络安全"}

        assert (await invoke("record_evidence", **note))["status"] == "ok"
        assert (await invoke("revise_plan", **edit))["status"] == "ok"
        assert "q1" not in run.evidence_notes
        assert (await invoke("record_evidence", **note))["status"] == "ok"
        assert run.evidence_notes["q1"] == {(citation, "保障网络安全")}
        assert (await invoke("revise_plan", question_id="q1", question="原问题", reason="恢复范围"))["status"] == "ok"
        assert (await invoke("revise_plan", **edit))["status"] == "ok"
        assert (await invoke("revise_plan", question_id="q2", remove=True, reason="删除重复问题"))[
            "status"
        ] == "invalid_plan_change"
        assert [change["previous"] for change in run.plan_changes] == ["原问题", "更窄的问题", "原问题"]

    asyncio.run(scenario())


def test_truncated_verification_never_releases_a_claim_and_charges_usage():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if stage == "verify":
                    return LLMResult("yes", "test", "test", 10, 512, finish_reason="length")
                data = json.loads(messages[-1].content)
                return result({"claims": [{
                    "claim": "保障网络安全", "citations": [data["evidence"][0]["id"]],
                }]})

        runtime.llm = Agent()
        answer = await run_research("为何制定网络安全法？", runtime, Budget(max_tool_calls=1))

        assert answer.status == "refused"
        assert not answer.claims
        assert answer.budget_report["tokens"] >= 522
        assert any(event.get("stage") == "verify" and event.get("finish_reason") == "length"
                   for event in answer.trace)

    asyncio.run(scenario())


def test_reasoning_model_can_emit_structured_plan_and_draft_within_shared_budget():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        stages = []

        class Agent:
            async def generate(self, messages, metadata):
                stage, cap = metadata["stage"], metadata["max_tokens"]
                stages.append(stage)
                if stage in {"scope", "plan", "generate"} and cap < 1100:
                    return LLMResult("", "test", "test", 40, cap, finish_reason="length")
                if stage == "scope":
                    return result({"questions": ["为何制定网络安全法？"]}, tokens=1000)
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]}, tokens=1000)
                if stage == "verify":
                    return LLMResult("yes", "test", "test", 40, 8)
                data = json.loads(messages[-1].content)
                return result({"claims": [{
                    "claim": "保障网络安全", "citations": [data["evidence"][0]["id"]],
                }]}, tokens=1000)

        runtime.llm = Agent()
        budget = Budget(max_tool_calls=1)
        answer = await run_research("为何制定网络安全法？", runtime, budget)

        assert stages == ["scope", "plan", "generate", "verify"]
        assert answer.answer == "保障网络安全"
        assert budget.tokens == 3048

    asyncio.run(scenario())


@pytest.mark.parametrize("recovers", [True, False])
def test_malformed_drafts_retry_after_search_budget_is_exhausted(recovers):
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store, checker=YesChecker())
        reasons = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                data = json.loads(messages[-1].content)
                reasons.append(data["draft_retry_reason"])
                if len(reasons) == 1:
                    assert metadata["max_tokens"] == 2500
                    return LLMResult("", "test", "test", 50, 2500, finish_reason="length")
                if len(reasons) == 2:
                    assert metadata["max_tokens"] >= 4000
                if not recovers:
                    return LLMResult("malformed", "test", "test", 50, 8)
                return result({"claims": [{
                    "claim": "保障网络安全", "citations": [data["evidence"][0]["id"]],
                }]})

        runtime.llm = Agent()
        answer = await run_research("为何制定网络安全法？", runtime, Budget(max_tool_calls=1))
        assert answer.budget_report["tool_calls"] == 1
        assert reasons == (["", "writer_output_truncated"] if recovers else [
            "", "writer_output_truncated", "invalid_writer_output",
        ])
        if recovers:
            assert answer.answer == "保障网络安全"
        else:
            assert answer.status == "refused"
            assert answer.refusal_reason == "invalid_writer_output"
            assert not answer.claims

    asyncio.run(scenario())


@pytest.mark.parametrize("draft_kind", ["length", "broken_tail", "bad_item"])
def test_damaged_draft_keeps_only_closed_claims_that_pass_verification(draft_kind):
    async def scenario():
        checked = []
        retries = []

        class Checker:
            async def check(self, claim, evidence, question=""):
                checked.append(claim.claim)
                return claim.claim == "保障网络安全"

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                data = json.loads(messages[-1].content)
                retries.append(data["draft_retry_reason"])
                if len(retries) > 1:
                    return LLMResult("malformed", "test", "test", 50, 8)
                citation = data["evidence"][0]["id"]
                completed = [
                    {"claim": "保障网络安全", "citations": [citation]},
                    {"claim": "不存在的格式", "citations": citation},
                    {"claim": "另一条未获支持的结论", "citations": [citation]},
                    {"claim": "没有出现在证据中的引用", "citations": ["not_in_evidence"]},
                ]
                if draft_kind == "bad_item":
                    return result({"claims": completed})
                text = '```json\n{"claims":' + json.dumps(completed, ensure_ascii=False)[:-1] + ',{"claim":"未闭合'
                finish_reason = "length" if draft_kind == "length" else "stop"
                return LLMResult(text, "test", "test", 50, 2500, finish_reason=finish_reason)

        runtime = make_runtime(FakeStoreHolder().store, checker=Checker())
        runtime.llm = Agent()
        answer = await run_research("为何制定网络安全法？", runtime, Budget(max_tool_calls=1))

        first_failure = {"length": "writer_output_truncated", "broken_tail": "invalid_writer_output", "bad_item": ""}
        assert retries == ["", first_failure[draft_kind], "invalid_writer_output"]
        assert checked == ["保障网络安全", "另一条未获支持的结论"]
        assert any(check["reason"] == "invalid_claim_shape" for event in answer.trace
                   for check in event.get("checks", []))
        assert answer.status == "answered"
        assert answer.partial
        assert answer.answer == "保障网络安全"
        assert answer.budget_report["tool_calls"] == 1

    asyncio.run(scenario())


def test_tight_writer_retry_compacts_context_and_retains_top_ranked_evidence():
    async def scenario():
        store = FakeStoreHolder().store
        runtime = make_runtime(store, checker=YesChecker())
        requests = []
        chunks = [
            dict(KB_PAYLOAD["chunks"][0], chunk_id=f"p{page}", page_start=page,
                 chunk_text="保障网络安全。" * 85, doc_title="长文档标题" * 20)
            for page in range(1, 9)
        ]

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                context = json.loads(messages[-1].content)
                evidence = context["evidence"]
                requests.append((metadata["max_tokens"], [item["id"] for item in evidence]))
                if len(requests) == 1:
                    return LLMResult("", "test", "test", 16700, 2500, finish_reason="length")
                return result({"claims": [{"claim": "保障网络安全", "citations": [evidence[0]["id"]]}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"chunks": chunks})
        )) as client:
            runtime.executor = ToolExecutor([KBSearchTool(
                base_url="http://kb", index_identity="test", client=client, store=store,
            )])
            runtime.llm = Agent()
            answer = await run_research("为何制定网络安全法？", runtime,
                                        Budget(max_tool_calls=1, max_tokens=24000))
        assert len(requests) == 2
        assert requests[1][0] >= 384
        sent = requests[0][1]
        narrowed = requests[1][1]
        assert 0 < len(narrowed) < len(sent) == 8
        assert narrowed == sent[:len(narrowed)]
        assert answer.citations == (narrowed[0],)
        assert all(store.get(cid).raw_text == chunks[0]["chunk_text"] for cid in sent)

    asyncio.run(scenario())


def test_enlarged_writer_limit_persists_across_citation_repairs():
    async def scenario():
        class Checker:
            async def check(self, claim, evidence, question=""):
                return claim.claim == "保障网络安全"

        runtime = make_runtime(FakeStoreHolder().store, checker=Checker())
        caps = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return LLMResult("", "test", "test", 30, 1500, finish_reason="length")
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                caps.append(metadata["max_tokens"])
                if len(caps) == 1:
                    return LLMResult("", "test", "test", 50, 2500, finish_reason="length")
                data = json.loads(messages[-1].content)
                return result({"claims": [{
                    "claim": "未经支持的范围" if len(caps) == 2 else "保障网络安全",
                    "citations": [data["evidence"][0]["id"]],
                }]})

        runtime.llm = Agent()
        answer = await run_research("为何制定网络安全法？", runtime, Budget(max_tool_calls=1))
        assert caps == [2500, 6000, 6000]
        assert answer.answer == "保障网络安全"
        assert any(event.get("action") == "scope_fallback" and event["reason"] == "scope_output_truncated"
                   for event in answer.trace)

    asyncio.run(scenario())


def test_truncated_scope_retries_within_exploration_budget():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        scopes = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    reason = json.loads(messages[-1].content)["retry_reason"]
                    scopes.append((reason, metadata["max_tokens"]))
                    if not reason:
                        return LLMResult("", "test", "test", 30, 1500, finish_reason="length")
                    return result({"questions": ["版本的关键差异是什么？", "如何验证差异？"]})
                return result({"tool_calls": []})

        runtime.llm = Agent()
        answer = await run_research("比较两个版本，提出验收方案。", runtime, Budget(max_rounds=1))
        assert scopes == [("", 1500), ("scope_output_truncated", 3000)]
        assert answer.missing_questions == ("版本的关键差异是什么？", "如何验证差异？")
        assert not any(event.get("action") == "scope_fallback" for event in answer.trace)
        assert answer.budget_report["tokens"] == 1534

    asyncio.run(scenario())


def test_multi_question_writer_preserves_distinct_documents_and_versions():
    async def scenario():
        from tools import KBSearchTool

        runtime = make_runtime(FakeStoreHolder().store)
        chunks = []
        for i, (doc_id, version) in enumerate(
            [("survey", "v1")] * 8 + [("specified", "v1"), ("specified", "v2"), ("comparison", "v1")]
        ):
            chunks.append({"chunk_id": f"chunk-{i}", "document_id": doc_id, "version_id": version,
                           "doc_title": doc_id, "chunk_text": f"文档原文第 {i + 1} 页",
                           "page_start": i + 1, "score": 1 - 0.01 * i})
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"chunks": chunks})
        )) as client:
            runtime.executor = ToolExecutor([KBSearchTool(
                base_url="http://kb", index_identity="test-index", client=client, store=runtime.store,
            )])

            class Agent:
                async def generate(self, messages, metadata):
                    stage = metadata["stage"]
                    if stage == "scope":
                        return result({"questions": ["指定论文两个版本差异？", "独立研究如何比较？"]})
                    if stage == "plan":
                        return result({"tool_calls": [call("kb_search", query="比较", top_k=11)]})
                    data = json.loads(messages[-1].content)
                    ids = [(e["identity"]["doc_id"], e["identity"]["version"]) for e in data["evidence"]]
                    assert ids[:4] == [("survey", "v1"), ("specified", "v1"),
                                       ("specified", "v2"), ("comparison", "v1")]
                    return result({"claims": []})

            runtime.llm = Agent()
            answer = await run_research("比较指定论文的版本和独立研究", runtime, Budget(max_tool_calls=1))
            assert answer.refusal_reason == "citation_gate_failed"

    asyncio.run(scenario())


def test_writer_keeps_high_ranked_pages_from_each_version_query():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        writer_pages = []

        def respond(request):
            version = json.loads(request.content)["query"]
            chunks = [
                dict(KB_PAYLOAD["chunks"][0], version_id=version, chunk_id=f"{version}-{page}",
                     chunk_text=f"{version} 第 {page} 页的实验结果", page_start=page, score=1.0 - page / 100)
                for page in range(1, 9)
            ]
            return httpx.Response(200, json={"chunks": chunks})

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({"questions": ["版本如何比较？", "哪些限制影响结论？"]})
                if stage == "plan":
                    return result({"tool_calls": [
                        call("kb_search", query="v1"), call("kb_search", query="v2"),
                    ]})
                evidence = json.loads(messages[-1].content)["evidence"]
                writer_pages.extend((item["identity"]["version"], item["identity"]["page"]) for item in evidence)
                return result({"claims": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            runtime.executor = ToolExecutor([KBSearchTool(
                base_url="http://kb", index_identity="test-index", client=client, store=runtime.store,
            )])
            runtime.llm = Agent()
            await run_research("比较论文两个版本的实验与局限", runtime, Budget(max_tool_calls=2))
        assert writer_pages == [(version, page) for page in range(1, 5) for version in ("v1", "v2")]

    asyncio.run(scenario())


def test_followup_writer_sees_new_pages_despite_eight_earlier_reads():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store, checker=YesChecker())
        writer_versions = []
        turns = 0

        def search(request):
            version = json.loads(request.content)["query"]
            pages = range(1, 9) if version == "v1" else range(4, 6)
            chunks = [
                dict(KB_PAYLOAD["chunks"][0], version_id=version, chunk_id=f"{version}-{page}",
                     chunk_text=f"{version} 第 {page} 页记录了实验结果", page_start=page,
                     score=1.0 - page / 100)
                for page in pages
            ]
            return httpx.Response(200, json={"chunks": chunks})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([
                KBSearchTool(base_url="http://kb", index_identity="test", client=client, store=runtime.store),
                EvidenceReadTool(store=runtime.store),
            ])

            class Agent:
                async def generate(self, messages, metadata):
                    nonlocal turns
                    data = json.loads(messages[-1].content)
                    stage = metadata["stage"]
                    if stage == "scope":
                        return result({"questions": ["初版发现？", "第二版发现？"], "deliverables": ["对照结果"]})
                    if stage == "coverage":
                        return result({"missing": {} if "q2" in data["verified_claims"]
                                       else {"q2": "缺少第二版结果页"}})
                    if stage == "generate":
                        evidence = data["evidence"]
                        writer_versions.append([item["identity"]["version"] for item in evidence])
                        key, version = ("q1", "v1") if len(writer_versions) == 1 else ("q2", "v2")
                        item = next(item for item in evidence if item["identity"]["version"] == version)
                        return result({"claims": [{"question_id": key, "claim": item["text"],
                                                   "citations": [item["id"]]}]})
                    turns += 1
                    if turns == 1:
                        return result({"tool_calls": [call("kb_search", query="v1", top_k=8)]})
                    if turns in {2, 3}:
                        start = 0 if turns == 2 else 6
                        return result({"tool_calls": [
                            call("evidence_read", evidence_id=ev.citation_id)
                            for ev in runtime.store.all()[start:start + 6]
                        ]})
                    if turns == 5:
                        assert data["coverage_gaps"] == {"q2": "缺少第二版结果页"}
                        return result({"tool_calls": [call("kb_search", query="v2")]})
                    return result({"tool_calls": [call("submit")]})

            runtime.llm = Agent()
            answer = await run_research("比较论文两个版本的实验结果", runtime, Budget(max_rounds=9))
        assert writer_versions == [["v1"] * 8, ["v2"] * 2 + ["v1"] * 6]
        assert answer.status == "answered"
        assert not answer.partial

    asyncio.run(scenario())


def test_verification_truncation_retries_with_budget_and_requires_complete_yes():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        verify_caps = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                if stage == "scope":
                    return result({})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if stage == "verify":
                    verify_caps.append(metadata["max_tokens"])
                    if len(verify_caps) == 1:
                        return LLMResult("", "test", "test", 15, 512, finish_reason="length")
                    return LLMResult("yes", "test", "test", 15, 850, finish_reason="stop")
                data = json.loads(messages[-1].content)
                return result({"claims": [{
                    "claim": "保障网络安全", "citations": [data["evidence"][0]["id"]],
                }]})

        runtime.llm = Agent()
        answer = await run_research("为何制定网络安全法？", runtime, Budget(max_tool_calls=1))
        assert verify_caps == [512, 2048]
        assert answer.answer == "保障网络安全"
        assert answer.budget_report["tokens"] == 1398

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid_batch", [False, True])
def test_new_official_version_rechecks_previously_accepted_claim(invalid_batch):
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        old_claim = "申报按上年累计口径"
        new_claim = "新规则改为当年累计口径"
        old_checks = []
        batches = []

        def search(request):
            query = json.loads(request.content)["query"]
            current = query == "现行规则"
            return httpx.Response(200, json={"results": [{
                "url": ("https://example.gov.cn/2024-03/22/current" if current
                        else "https://example.gov.cn/2022-07/02/old"),
                "title": "新规定" if current else "旧办法",
                "content": new_claim if current else old_claim,
            }]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=runtime.store)])
            turns = iter([
                [call("web_search", query="旧规则")], [call("submit")],
                [call("web_search", query="现行规则")], [call("submit")],
            ])

            class Agent:
                async def generate(self, messages, metadata):
                    stage = metadata["stage"]
                    data = json.loads(messages[-1].content)
                    if stage == "scope":
                        return result({"questions": ["现在怎样申报？", "新旧规则有何变化？"],
                                       "check_applicable_versions": True})
                    if stage == "plan":
                        return result({"tool_calls": next(turns)})
                    if stage == "verify":
                        if "claims" in data:
                            batches.append(data)
                            assert len(data["official_sources"]) == 2
                            assert len(data["evidence"]) == 2
                            assert [item["evidence_refs"] for item in data["claims"].values()] == [["e1"], ["e2"]]
                            if invalid_batch:
                                return result({"verdicts": {"c1": True}})
                            old_checks.append(True)
                            return result({"verdicts": {
                                "c2": version_verdict(), "c1": version_verdict("上年累计已被取代"),
                            }})
                        if data["claim"] != old_claim:
                            return result(version_verdict())
                        newer = any("current" in source["url"] for source in data["other_official_sources"])
                        old_checks.append(newer)
                        return result(version_verdict("上年累计已被取代") if newer else version_verdict())
                    if not data["failures"]:
                        current = next((item for item in data["evidence"] if item["text"] == new_claim), None)
                        ev = current or data["evidence"][0]
                        return result({"claims": [{
                            "question_id": "q2" if current else "q1", "claim": ev["text"],
                            "citations": [ev["id"]], "scope": "snippet",
                        }]})
                    return result({"claims": []})

            runtime.llm = Agent()
            answer = await run_research("核对现行法规，说明申报规则变化。", runtime, Budget(max_rounds=4))
        assert old_checks == [False, True]
        assert len(batches) == 1
        assert answer.answer == new_claim
        assert answer.partial
        assert "现在怎样申报？" in answer.missing_questions

    asyncio.run(scenario())


@pytest.mark.parametrize("layout_kind", ["tree", "duplicates", "unknown"])
def test_deliverable_claims_share_evidence_without_sharing_verdicts(layout_kind):
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        batches = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"questions": ["目的是什么？", "如何验收？"], "deliverables": ["验收步骤"]})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if stage == "verify":
                    batches.append(data)
                    assert [item["evidence_refs"] for item in data["claims"].values()] == [["e1"]] * 3
                    assert len(data["evidence"]) == 1 and not data["official_sources"]
                    return result({"verdicts": {"c3": True, "c2": False, "c1": True}})
                if stage == "coverage":
                    return result({"missing": {}})
                if stage == "layout":
                    assert list(data["verified_claims"].values()) == ["保障网络安全", "按网络安全目的验收"]
                    if layout_kind == "duplicates":
                        return result({"sections": [
                            {"section": 0, "style": "list", "items": [[1, 0]]},
                            {"section": 6, "style": "tree", "items": [[1, 0]]},
                        ]})
                    return result({"sections": [
                        {"section": 6, "style": "tree", "items": [[1, 0], [2 if layout_kind == "tree" else 3, 1]]},
                    ]})
                if data["failures"]:
                    return result({"claims": []})
                cid = data["evidence"][0]["id"]
                return result({"claims": [
                    {"question_id": "q1", "claim": "保障网络安全", "citations": [cid]},
                    {"question_id": "q1", "claim": "未经证据支持的目的", "citations": [cid]},
                    {"question_id": "q2", "claim": "按网络安全目的验收", "citations": [cid]},
                ]})

        runtime.llm = Agent()
        answer = await run_research("论证目的并给出验收步骤", runtime, Budget(max_tool_calls=1))
        assert len(batches) == 1
        assert [item.claim for item in answer.claims] == ["保障网络安全", "按网络安全目的验收"]
        assert not answer.partial
        assert answer.answer == {
            "tree": "条件分支\n• 保障网络安全\n  • 按网络安全目的验收",
            "duplicates": "条件分支\n• 保障网络安全\n\n已核验依据\n• 按网络安全目的验收",
            "unknown": "保障网络安全\n按网络安全目的验收",
        }[layout_kind]
        assert ("layout_fallback" in {item.get("action") for item in answer.trace}) == (layout_kind == "unknown")

    asyncio.run(scenario())


def test_project_threshold_is_published_as_proposal_and_its_premise_is_checked():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        checked = []

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"questions": ["如何设计验收？"], "deliverables": ["明确阈值"]})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if stage == "verify":
                    assert "拟用参数、阈值可由方案预先指定" in messages[0].content
                    if "claims" in data:
                        checked.extend(data["claims"].values())
                        return result({"verdicts": {key: True for key in data["claims"]}})
                    checked.append(data)
                    return LLMResult("yes", "test", "test", 2)
                if stage == "coverage":
                    return result({"missing": {}})
                if data["failures"]:
                    return result({"claims": []})
                cid = data["evidence"][0]["id"]
                return result({"claims": [
                    {"claim": "本项目拟用 97% 作为验收阈值。", "rationale": "制定本法的目的是保障网络安全。",
                     "citations": [cid]},
                    {"claim": "本项目拟用 97% 作为另一阈值。", "rationale": "原文报告提升 88.3%。",
                     "citations": [cid]},
                ]})

        runtime.llm = Agent()
        answer = await run_research("设计验收阈值。", runtime, Budget(max_tool_calls=1))
        assert len(checked) == 1 and checked[0]["rationale"] == "制定本法的目的是保障网络安全。"
        assert answer.answer.startswith("建议：本项目拟用 97%")
        assert "88.3" not in answer.answer

    asyncio.run(scenario())


def test_known_evidence_goes_directly_to_synthesis_after_search_limit():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store, checker=YesChecker())
        stages = []
        fact = "第一条说明制定本法的目的是保障网络安全。"
        proposal = "本项目拟用 97% 作为验收阈值。"
        gap = {"q1": "有依据，仍须指定项目验收阈值"}

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                stages.append(stage)
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"questions": ["如何设计验收？"], "deliverables": ["明确阈值"]})
                if stage == "plan":
                    return result({"tool_calls": [call("kb_search", query="网络安全法")]})
                if stage == "coverage":
                    assert any(source["scope"] == "fulltext" and "保障网络安全" in source["excerpt"]
                               for source in data["cited_sources"].values())
                    return result({"missing": {}, "synthesis": gap if stages.count("generate") == 1 else {}})
                if stage == "layout":
                    return result({})
                cid = data["evidence"][0]["id"]
                if stages.count("generate") == 1:
                    return result({"claims": [{"claim": fact, "citations": [cid]}]})
                assert data["synthesis_gaps"] == gap
                assert data["already_verified"] == {"q1": [fact]}
                return result({"claims": [{"claim": proposal, "rationale": fact, "citations": [cid]}]})

        runtime.llm = Agent()
        answer = await run_research("设计验收阈值。", runtime, Budget(max_tool_calls=1))
        assert stages == ["scope", "plan", "generate", "coverage", "generate", "coverage", "layout"]
        assert not answer.partial
        assert "建议：" + proposal in answer.answer

    asyncio.run(scenario())


def test_coverage_withdraws_conflicting_claim_and_keeps_historical_claim():
    async def scenario():
        current = "现行标准合同路径按当年累计。"
        history = "旧办法曾按上年累计。"
        conflict = "标准合同审核的事实输入包括上年累计出境人数。"
        checked = []
        review_calls = []

        class Checker:
            async def check(self, claim, evidence, question=""):
                checked.append(claim.claim)
                return True

        runtime = make_runtime(FakeStoreHolder().store, checker=Checker())

        def search(_):
            return httpx.Response(200, json={"results": [{
                "url": "https://example.gov.cn/2024-03/22/current",
                "title": "现行规定", "content": "第八条 按当年累计。",
            }, {
                "url": "https://example.gov.cn/2022-07/01/old",
                "title": "旧办法", "content": "第四条 按上年累计。",
            }]})

        class Agent:
            async def generate(self, messages, metadata):
                data = json.loads(messages[-1].content)
                stage = metadata["stage"]
                if stage == "scope":
                    return result({"questions": ["现行口径？", "原有口径？", "审核事实？"],
                                   "deliverables": ["法律审核路径"], "check_applicable_versions": True})
                if stage == "plan":
                    return result({"tool_calls": [call("web_search", query="适用口径")]})
                if stage == "coverage":
                    assert data["official_provisions"]
                    reviewed = {item["claim"]: item["id"] for items in data["verified_claims"].values()
                                for item in items}
                    review_calls.append(reviewed)
                    withdrawals = {}
                    if conflict in reviewed:
                        withdrawals = {
                            reviewed[conflict]: {"against": reviewed[history], "quote": current,
                                                 "reason": "上年口径不再适用当前审核"},
                            reviewed[history]: {"against": reviewed[current], "quote": "这一段内容不存在",
                                                "reason": "不能撤回有据的历史说明"},
                        }
                    return result({"withdraw": withdrawals, "missing": {
                        "q3": "缺当前审核事实清单", "deliverable": "缺完整审核树",
                    }})
                if stage == "layout":
                    assert conflict not in data["verified_claims"].values()
                    return result({})
                new_id, old_id = (item["id"] for item in data["evidence"][:2])
                claims = [
                    {"question_id": "q1", "claim": current, "citations": [new_id], "scope": "snippet"},
                    {"question_id": "q2", "claim": history, "citations": [old_id], "scope": "snippet"},
                    {"question_id": "q3", "claim": conflict, "citations": [old_id], "scope": "snippet"},
                ]
                return result({"claims": claims if not data["failures"] else claims[-1:]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=runtime.store)])
            runtime.llm = Agent()
            answer = await run_research("比较现行法规与历史口径并给出审核路径。", runtime, Budget(max_tool_calls=1))

        assert checked == [current, history, conflict]
        assert conflict in review_calls[0] and conflict not in review_calls[-1]
        assert [claim.claim for claim in answer.claims] == [current, history]
        assert conflict not in answer.answer
        assert answer.partial and set(answer.missing_questions) == {"缺当前审核事实清单", "缺完整审核树"}
        assert [(item["conflict_against"], item["conflict_quote"])
                for event in answer.trace for item in event.get("checks", []) if "conflict_quote" in item
                ] == [(review_calls[0][current], current)]

    asyncio.run(scenario())


def test_current_rule_text_reaches_writer_and_verifier_ahead_of_newer_explainers():
    async def scenario():
        runtime = make_runtime(FakeStoreHolder().store)
        current_clause = "第七条 自当年起累计。第十三条 此前规定与本规定不一致的，适用本规定。"
        primary_text = "根据2024年3月22日修正。" + ("其他条款。" * 200) + current_clause
        old_text = "第四条 按上年累计。"
        alternatives = "决策树应按数据性质、当年或上年累计出境数量及免予申报情形分叉。"
        current = "现行规定按当年累计。"
        history = "旧办法曾采用上年累计。"
        verifier_saw = []

        def search(_):
            explainers = [
                {"url": f"https://example.gov.cn/2026-09/{day:02}/faq", "title": "政策问答", "content": "相关背景"}
                for day in range(1, 9)
            ]
            reposts = [
                {"url": f"https://other.gov.cn/2026-09/{day:02}/repost",
                 "title": "《数据跨境流动规定》_转载",
                 "content": "第四条 此处为未标注修订的旧文本。"}
                for day in range(1, 5)
            ]
            return httpx.Response(200, json={"results": [*explainers, *reposts, {
                "url": "https://example.gov.cn/2024-03/22/current",
                "title": "数据跨境流动规定_发布机关", "content": primary_text,
            }, {
                "url": "https://example.gov.cn/2022-07/01/old",
                "title": "旧办法_发布机关", "content": old_text,
            }]})

        class Agent:
            async def generate(self, messages, metadata):
                stage = metadata["stage"]
                data = json.loads(messages[-1].content)
                if stage == "scope":
                    return result({"check_applicable_versions": True})
                if stage == "plan":
                    assert "不要把尚未核实的旧条号作为寻找现行版的查询条件" in messages[0].content
                    return result({"tool_calls": [call("web_search", query="现行规则")]})
                if stage == "verify":
                    verifier_saw.append(data)
                    sources = list(data["official_sources"].values())
                    assert current_clause in sources[0]["text"]
                    assert sources[1]["text"] == old_text
                    assert "不能把旧时点的规则与当前规则拼成同一选择" in messages[0].content
                    return result({"verdicts": {
                        key: version_verdict("上年累计只见于旧办法") if value["claim"] == alternatives
                        else version_verdict() for key, value in data["claims"].items()
                    }})
                if data["failures"]:
                    return result({"claims": []})
                new_id, old_id = (item["id"] for item in data["evidence"][:2])
                assert current_clause in data["evidence"][0]["text"]
                assert data["evidence"][0]["scope"] == "snippet"
                assert data["evidence"][1]["text"] == old_text
                return result({"claims": [
                    {"claim": current, "citations": [new_id], "scope": "snippet"},
                    {"claim": alternatives, "citations": [new_id, old_id], "scope": "snippet"},
                    {"claim": history, "citations": [old_id], "scope": "snippet"},
                ]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            runtime.executor = ToolExecutor([WebSearchTool(api_key="test", client=client, store=runtime.store)])
            runtime.llm = Agent()
            answer = await run_research("核对现行法规和历史原因", runtime, Budget(max_tool_calls=1))

        assert len(verifier_saw) == 1
        assert [claim.claim for claim in answer.claims] == [current, history]
        assert runtime.store.get(answer.claims[0].citations[0]).raw_text == primary_text

    asyncio.run(scenario())
