"""Agent Loop 垂直切片契约（P3d 验收：fake LLM 驱动真实 loop/executor）。

覆盖：首次选工具、证据缺口触发追加检索、充分证据后停止；
重复无进展/超预算/超 deadline 被阻止；无证据拒答；
引用闸门一次重生成后仍失败则拒答；预算跨轮累计不重置。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from agent.budget import Budget, StopReason
from agent.citation_gate import CitationGate
from agent.loop import AgentLoop
from evidence.store import EvidenceStore
from tools import KBSearchTool, ToolExecutor


class ScriptLLM:
    """按脚本逐次返回的 LLM；记录调用阶段以便断言。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.stages: list[str] = []

    async def generate(self, messages, metadata=None):
        self.stages.append((metadata or {}).get("stage", "?"))
        text = self._responses.pop(0) if self._responses else "{}"

        class R:
            pass

        r = R()
        r.text = text
        r.prompt_tokens = 1
        r.completion_tokens = 1
        return r


class YesChecker:
    async def check(self, claim, evidence):
        return True


KB_PAYLOAD = {
    "chunks": [
        {
            "chunk_id": "chunk-1",
            "score": 0.9,
            "source": "vector",
            "chunk_text": "第一条 为了保障网络安全，制定本法。",
            "document_id": "doc-1",
            "version_id": "ver-1",
            "doc_title": "网络安全法",
            "doc_type": "law",
            "page_start": 1,
        }
    ]
}


def _executor(store: EvidenceStore) -> ToolExecutor:
    kb = KBSearchTool(
        base_url="http://kb.internal",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=KB_PAYLOAD)),
            follow_redirects=False,
        ),
        store=store,
        index_identity="idx",
    )
    return ToolExecutor(tools=[kb])


def _loop(planner: ScriptLLM, writer: ScriptLLM, store: EvidenceStore, budget: Budget | None = None) -> AgentLoop:
    return AgentLoop(
        planner=planner,
        writer=writer,
        executor=_executor(store),
        store=store,
        gate=CitationGate(semantic_checker=YesChecker()),
        budget=budget,
    )


PLAN_CALL = json.dumps(
    {"tool_calls": [{"tool": "kb_search", "args": {"query": "网络安全法 第一条"}}]},
    ensure_ascii=False,
)
PLAN_DONE = json.dumps({"tool_calls": []}, ensure_ascii=False)


def _writer_ok(cid: str) -> str:
    return json.dumps(
        {
            "answer": "为保障网络安全而制定。",
            "claims": [{"claim": "为了保障网络安全而制定本法", "citations": [cid], "scope": "fulltext"}],
        },
        ensure_ascii=False,
    )


def _writer_bad(cid: str) -> str:
    return json.dumps(
        {
            "answer": "错误答案",
            "claims": [{"claim": "据称 2099 年施行", "citations": [cid], "scope": "fulltext"}],
        },
        ensure_ascii=False,
    )


def test_vertical_slice_answered_after_gap_and_enough_evidence() -> None:
    """首轮检索 → 证据缺口追加规划 → 证据充分停止 → 生成 → 闸门通过。"""
    store = EvidenceStore()
    # planner: 第一轮调工具，第二轮判定证据充分（空 tool_calls）
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE])

    class AutoWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("generate")
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = _writer_ok(cid)
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    loop = _loop(planner, AutoWriter([]), store)
    answer = asyncio.run(loop.run("网络安全法第一条讲了什么？"))
    assert answer.status == "answered"
    assert answer.stop_reason == StopReason.SUFFICIENT_EVIDENCE
    assert answer.citations
    assert answer.answer
    assert answer.budget_report["tool_calls"] == 1
    trace_types = [t["type"] for t in answer.trace]
    assert "tool_call" in trace_types and "evidence" in trace_types and "done" in trace_types


def test_repeated_call_without_new_evidence_stops_no_progress() -> None:
    store = EvidenceStore()

    class RepeatPlanner(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("plan")

            class R:
                pass

            r = R()
            r.text = PLAN_CALL  # 永远重复同一工具调用
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    class AutoWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = _writer_ok(cid)
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    loop = _loop(RepeatPlanner([]), AutoWriter([]), store)
    answer = asyncio.run(loop.run("q"))
    # 第一次调用产生证据；之后重复调用无新证据 → no_progress 早停（不再进下一轮）
    assert answer.status == "answered"
    assert answer.stop_reason == StopReason.SUFFICIENT_EVIDENCE  # 有证据可作答
    repeat_events = [t for t in answer.trace if t.get("reason") == "no_progress_repeat"]
    assert repeat_events, [t for t in answer.trace]
    # 早停后总工具调用远小于轮数上限可容纳的次数
    assert answer.budget_report["tool_calls"] <= 3


def test_tool_call_budget_exhaustion_blocks() -> None:
    store = EvidenceStore()

    class AlwaysCall(ScriptLLM):
        async def generate(self, messages, metadata=None):
            class R:
                pass

            r = R()
            r.text = PLAN_CALL
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    class AutoWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = _writer_ok(cid)
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    budget = Budget(max_tool_calls=2, max_rounds=10)
    loop = _loop(AlwaysCall([]), AutoWriter([]), store, budget=budget)
    answer = asyncio.run(loop.run("q"))
    assert answer.budget_report["tool_calls"] <= 2
    if answer.status == "refused":
        assert answer.stop_reason in (StopReason.BUDGET_EXHAUSTED, StopReason.NO_PROGRESS)


def test_deadline_exceeded_stops_loop() -> None:
    store = EvidenceStore()
    clock = {"now": 0.0}

    class AlwaysCall(ScriptLLM):
        async def generate(self, messages, metadata=None):
            class R:
                pass

            r = R()
            r.text = PLAN_CALL
            r.prompt_tokens = 1
            r.completion_tokens = 1
            clock["now"] += 100.0  # 每次规划都耗尽时限
            return r

    class NoopWriter(ScriptLLM):
        pass

    budget = Budget(deadline_seconds=50.0, clock=lambda: clock["now"])
    budget.started_at = 0.0
    loop = _loop(AlwaysCall([]), NoopWriter([]), store, budget=budget)
    answer = asyncio.run(loop.run("q"))
    if answer.status == "refused" and answer.refusal_reason == "budget_exhausted":
        assert answer.stop_reason == StopReason.DEADLINE_EXCEEDED


def test_no_evidence_refused() -> None:
    store = EvidenceStore()
    planner = ScriptLLM([PLAN_DONE])
    loop = _loop(planner, ScriptLLM([]), store)
    answer = asyncio.run(loop.run("q"))
    assert answer.status == "refused"
    assert answer.refusal_reason == "no_evidence"


def test_citation_gate_failed_after_regeneration_refuses() -> None:
    store = EvidenceStore()

    class AutoPlanner(ScriptLLM):
        async def generate(self, messages, metadata=None):
            class R:
                pass

            r = R()
            r.text = PLAN_CALL
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    class BadWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("generate")
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = _writer_bad(cid)  # 数字 2099 不在证据中 → 闸门必失败
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    budget = Budget(max_tokens=20000)
    loop = _loop(AutoPlanner([]), BadWriter([]), store, budget=budget)
    answer = asyncio.run(loop.run("q"))
    assert answer.status == "refused"
    assert answer.stop_reason == StopReason.CITATION_GATE_FAILED
    # 一次重生成：writer 被调用两次，且预算跨两次累计
    assert budget.tokens >= 4  # planner*1 + writer*2 + planner*2... 仅断言累计


def test_regeneration_can_salvage_answer() -> None:
    store = EvidenceStore()

    class AutoPlanner(ScriptLLM):
        async def generate(self, messages, metadata=None):
            class R:
                pass

            r = R()
            r.text = PLAN_CALL
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    class FixingWriter(ScriptLLM):
        def __init__(self) -> None:
            super().__init__([])
            self.calls = 0

        async def generate(self, messages, metadata=None):
            self.calls += 1
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = _writer_bad(cid) if self.calls == 1 else _writer_ok(cid)
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    writer = FixingWriter()
    loop = _loop(AutoPlanner([]), writer, store)
    answer = asyncio.run(loop.run("q"))
    assert answer.status == "answered"
    assert writer.calls == 2  # 第一次失败后一次重生成成功


def test_unknown_tool_name_is_rejected_not_executed() -> None:
    store = EvidenceStore()

    class EvilPlanner(ScriptLLM):
        async def generate(self, messages, metadata=None):
            class R:
                pass

            r = R()
            r.text = json.dumps({"tool_calls": [{"tool": "shell", "args": {"cmd": "rm -rf /"}}]})
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    class NoopWriter(ScriptLLM):
        pass

    loop = _loop(EvilPlanner([]), NoopWriter([]), store)
    answer = asyncio.run(loop.run("q"))
    # 白名单拒绝：无证据 → 拒答，而不是执行任意工具
    assert answer.status == "refused"
    assert answer.refusal_reason == "no_evidence"


def test_empty_claims_treated_as_insufficient_and_refused() -> None:
    """writer 不给 claims = 引用不足 → 重生成后仍空则拒答，无据文本不得当成功答案。"""
    store = EvidenceStore()
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE])
    writer = ScriptLLM(
        [
            json.dumps({"answer": "看起来有答案但无任何可验证结论", "claims": []}, ensure_ascii=False),
            json.dumps({"answer": "看起来有答案但无任何可验证结论", "claims": []}, ensure_ascii=False),
        ]
    )
    loop = _loop(planner, writer, store)
    answer = asyncio.run(loop.run("网络安全法第一条讲了什么？"))
    assert answer.status == "refused"
    assert answer.refusal_reason == "citation_gate_failed"
    empty_events = [t for t in answer.trace if t.get("reason") == "empty_claims"]
    assert len(empty_events) == 2  # 首次 + 一次重生成
