"""AgentLoop 事件 sink 契约（P3d 后半：SSE v1 事件源）。

覆盖：sink 与 trace 同构且保序；异步 sink 可 await；
token_delta 覆盖 plan/generate/verify 三阶段且 verify 计入共享预算；
tool_result 带 call_id/provider、evidence 带 call_id（P3d 验收：工具结果与引用关联 call_id）。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from agent.budget import Budget
from agent.citation_gate import CitationGate
from agent.loop import AgentLoop, SemanticVerifier
from evidence.store import EvidenceStore
from tools import KBSearchTool, ToolExecutor

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

PLAN_CALL = json.dumps(
    {"tool_calls": [{"tool": "kb_search", "args": {"query": "网络安全法 第一条"}}]},
    ensure_ascii=False,
)
PLAN_DONE = json.dumps({"tool_calls": []}, ensure_ascii=False)


class ScriptLLM:
    def __init__(self, responses: list[str], *, prompt_tokens: int = 3, completion_tokens: int = 5) -> None:
        self._responses = list(responses)
        self._pt = prompt_tokens
        self._ct = completion_tokens

    async def generate(self, messages, metadata=None):
        text = self._responses.pop(0) if self._responses else "{}"

        class R:
            pass

        r = R()
        r.text = text
        r.prompt_tokens = self._pt
        r.completion_tokens = self._ct
        return r


class AutoWriter(ScriptLLM):
    """生成器：引用 store 里真实 citation_id，保证闸门可通过。"""

    def __init__(self, store: EvidenceStore, *, prompt_tokens: int = 7, completion_tokens: int = 11) -> None:
        super().__init__([], prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        self._store = store

    async def generate(self, messages, metadata=None):
        cid = next((ev.citation_id for ev in self._store.all()), "KX")
        self._responses = [
            json.dumps(
                {
                    "answer": "为保障网络安全而制定。",
                    "claims": [{"claim": "为了保障网络安全而制定本法", "citations": [cid], "scope": "fulltext"}],
                },
                ensure_ascii=False,
            )
        ]
        return await super().generate(messages, metadata)


class YesChecker:
    async def check(self, claim, evidence):
        return True


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


def _run(store: EvidenceStore, planner: ScriptLLM, writer: ScriptLLM, on_event, gate=None) -> tuple:
    budget = Budget()
    loop = AgentLoop(
        planner=planner,
        writer=writer,
        executor=_executor(store),
        store=store,
        gate=gate or CitationGate(semantic_checker=YesChecker()),
        budget=budget,
        on_event=on_event,
    )
    answer = asyncio.run(loop.run("网络安全法为何制定？"))
    return answer, budget


def test_sink_events_match_trace_in_order() -> None:
    received: list[dict] = []
    store = EvidenceStore()

    def sink(entry: dict) -> None:
        received.append(entry)

    answer, _ = _run(store, ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store), sink)

    assert answer.status == "answered"
    assert [e["type"] for e in received] == [t["type"] for t in answer.trace]
    assert received == [dict(t) for t in answer.trace]
    assert received[0]["type"] == "meta"
    assert received[-1] == {"type": "done", "status": "answered"}


def test_async_sink_is_awaited() -> None:
    received: list[dict] = []
    store = EvidenceStore()

    async def sink(entry: dict) -> None:
        received.append(entry)

    answer, _ = _run(store, ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store), sink)

    assert answer.status == "answered"
    assert received and received[-1]["type"] == "done"


def test_token_delta_covers_plan_and_generate_stages() -> None:
    received: list[dict] = []
    store = EvidenceStore()
    planner = ScriptLLM([PLAN_CALL, PLAN_DONE], prompt_tokens=3, completion_tokens=5)

    answer, budget = _run(store, planner, AutoWriter(store), received.append)

    deltas = [e for e in received if e["type"] == "token_delta"]
    stages = [d["stage"] for d in deltas]
    assert stages.count("plan") == 2
    assert stages.count("generate") == 1
    assert deltas[0]["prompt_tokens"] == 3 and deltas[0]["completion_tokens"] == 5
    assert budget.tokens == 2 * (3 + 5) + (7 + 11)


def test_semantic_verifier_charges_shared_budget_and_emits_token_delta() -> None:
    budget = Budget()
    received: list[dict] = []
    verifier = SemanticVerifier(ScriptLLM(["yes"], prompt_tokens=2, completion_tokens=4), budget=budget, on_event=received.append)

    class FakeClaim:
        claim = "x"
        citations = ("K1",)

    ok = asyncio.run(verifier.check(FakeClaim(), []))
    assert ok is True
    assert budget.tokens == 6
    assert received == [{"type": "token_delta", "stage": "verify", "prompt_tokens": 2, "completion_tokens": 4}]


def test_tool_result_and_evidence_carry_call_id() -> None:
    received: list[dict] = []
    store = EvidenceStore()

    answer, _ = _run(store, ScriptLLM([PLAN_CALL, PLAN_DONE]), AutoWriter(store), received.append)

    tool_results = [e for e in received if e["type"] == "tool_result"]
    evidences = [e for e in received if e["type"] == "evidence"]
    assert tool_results and tool_results[0]["call_id"]
    assert tool_results[0]["provider"]  # 来源状态可派生
    assert evidences and evidences[0]["call_id"] == tool_results[0]["call_id"]
