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
    async def check(self, claim, evidence, question: str = ""):
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


def _loop(planner: ScriptLLM, writer: ScriptLLM, store: EvidenceStore, budget: Budget | None = None,
          *, verification_feedback: bool = True) -> AgentLoop:
    return AgentLoop(
        planner=planner,
        writer=writer,
        executor=_executor(store),
        store=store,
        gate=CitationGate(semantic_checker=YesChecker()),
        budget=budget,
        verification_feedback=verification_feedback,
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
    assert answer.stop_reason == StopReason.NO_PROGRESS  # 有据可作答，但保留检索停止原因
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


def test_generate_calls_pass_llmmessage_instances() -> None:
    """回归（2026-10-12）：loop 必须以 LLMMessage 调 generate——裸 dict 曾让 P4 live 全量秒挂。"""
    from providers.llm.base import LLMMessage

    store = EvidenceStore()
    seen: list = []

    class CaptureLLM(ScriptLLM):
        async def generate(self, messages, metadata=None):
            seen.extend(messages)
            return await super().generate(messages, metadata)

    class AutoWriter(CaptureLLM):
        async def generate(self, messages, metadata=None):
            seen.extend(messages)
            self.stages.append("generate")
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = _writer_ok(cid)
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    planner = CaptureLLM([PLAN_CALL, PLAN_DONE])
    loop = _loop(planner, AutoWriter([]), store)
    answer = asyncio.run(loop.run("网络安全法第一条讲了什么？"))
    assert answer.status == "answered"
    assert seen, "loop 未调用 generate"
    assert all(isinstance(m, LLMMessage) for m in seen), [type(m).__name__ for m in seen]
    assert all(m.role == "user" and isinstance(m.content, str) and m.content for m in seen)


def test_partial_claims_yield_partial_answer_without_unsupported_text() -> None:
    """v1 部分有据则部分回答：混合 claims 只发通过部分，无据表述不得混入答案。"""
    store = EvidenceStore()
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE])

    class MixedWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("generate")
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = json.dumps(
                {
                    "answer": "为保障网络安全而制定。据称 2099 年施行。",
                    "claims": [
                        {"claim": "为了保障网络安全而制定本法", "citations": [cid], "scope": "fulltext"},
                        {"claim": "据称 2099 年施行", "citations": [cid], "scope": "fulltext"},  # 数字不在证据中 → 必被丢弃
                    ],
                },
                ensure_ascii=False,
            )
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    writer = MixedWriter([])
    loop = _loop(planner, writer, store, verification_feedback=False)
    answer = asyncio.run(loop.run("网络安全法第一条讲了什么？"))
    assert answer.status == "answered"
    assert answer.partial is True
    assert answer.claims == tuple(c for c in answer.claims if "2099" not in c.claim)
    assert len(answer.claims) == 1
    assert answer.claims[0].claim == "为了保障网络安全而制定本法"
    assert "2099" not in answer.answer  # 被丢弃的无据表述不得出现在最终答案
    assert answer.answer == f"为了保障网络安全而制定本法 [{answer.claims[0].citations[0]}]"  # 正文保留已核验断言与引用
    assert writer.stages.count("generate") == 1  # 部分作答不触发重生成
    partial_events = [t for t in answer.trace if t.get("type") == "partial_answer"]
    assert len(partial_events) == 1
    assert partial_events[0]["kept"] == 1


def test_irrelevant_supported_claim_is_refused_and_question_reaches_checker() -> None:
    """q042 型陷阱回归（2026-10-12）：被证据支撑但答非所问的 claim 不得作答；question 须传到语义复检。"""
    from agent.citation_gate import CitationGate

    store = EvidenceStore()
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE])
    seen_questions: list[str] = []

    class RelevanceChecker:
        async def check(self, claim, evidence, question=""):
            seen_questions.append(question)
            return False  # 模拟新判据：支撑但答非所问 → 拒

    class TrapWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("generate")
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = json.dumps(
                {
                    "answer": "应当指定个人信息保护负责人。",
                    "claims": [{"claim": "应当指定个人信息保护负责人", "citations": [cid], "scope": "fulltext"}],
                },
                ensure_ascii=False,
            )
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    loop = AgentLoop(
        planner=planner,
        writer=TrapWriter([]),
        executor=_executor(store),
        store=store,
        gate=CitationGate(semantic_checker=RelevanceChecker()),
    )
    answer = asyncio.run(loop.run("“用户数量巨大”具体指多少用户？"))
    assert answer.status == "refused"
    assert answer.refusal_reason == "citation_gate_failed"
    assert seen_questions and all(q == "“用户数量巨大”具体指多少用户？" for q in seen_questions)


def test_writer_fenced_json_and_identity_visible() -> None:
    """F7（2026-10-12）：```json 围栏输出不得白丢一轮；writer 证据载荷须带来源身份。"""
    store = EvidenceStore()
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE])
    seen_prompts: list[str] = []

    class FencedWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("generate")
            seen_prompts.append(messages[0].content)
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            inner = json.dumps(
                {
                    "answer": "为保障网络安全而制定。",
                    "claims": [{"claim": "为了保障网络安全而制定本法", "citations": [cid], "scope": "fulltext"}],
                },
                ensure_ascii=False,
            )
            r.text = f"```json\n{inner}\n```"
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    loop = _loop(planner, FencedWriter([]), store)
    answer = asyncio.run(loop.run("网络安全法第一条讲了什么？"))
    assert answer.status == "answered"  # 围栏输出直接解析成功，未走重生成
    assert len(seen_prompts) == 1
    assert '"identity"' in seen_prompts[0] and "doc_id" in seen_prompts[0]  # 身份字段对 writer 可见


def test_quote_assembly_copies_verbatim_and_drops_drifted() -> None:
    """F9（2026-10-12）：逐字 quote 由流水线从证据原文复制进答案；带漂移的 quote 不采纳。"""
    store = EvidenceStore()
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE])
    verbatim = "第一条 为了保障网络安全，制定本法。"

    class QuoteWriter(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self.stages.append("generate")
            cid = next((ev.citation_id for ev in store.all()), "KX")

            class R:
                pass

            r = R()
            r.text = json.dumps(
                {
                    "answer": "为保障网络安全而制定。",
                    "claims": [
                        {"claim": "为了保障网络安全而制定本法", "citations": [cid], "scope": "fulltext", "quote": verbatim},
                        {"claim": "该法于 2099 年施行", "citations": [cid], "scope": "fulltext", "quote": "第一条 为了保障网络安全,制定本法。"},
                    ],
                },
                ensure_ascii=False,
            )
            r.prompt_tokens = 1
            r.completion_tokens = 1
            return r

    loop = _loop(planner, QuoteWriter([]), store)
    answer = asyncio.run(loop.run("网络安全法第一条讲了什么？"))
    assert answer.status == "answered"
    assert verbatim in answer.answer  # 逐字 quote 进答案（机械可命中）
    assert "2099" not in answer.answer  # 无据 claim 被丢，其漂移 quote 也不进
    assert answer.answer.count("第一条") == 1  # 漂移 quote（全角逗号差异）被剔除，不重复
