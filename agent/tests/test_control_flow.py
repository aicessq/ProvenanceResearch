"""实际 loop 边界：非法规划不能冒充完成，停止原因不能被成功生成覆盖。"""
import asyncio
import json

import pytest

from agent.budget import Budget, StopReason
from agent.tests.test_loop import PLAN_CALL, PLAN_DONE, ScriptLLM, _loop, _writer_ok
from evidence.store import EvidenceStore


@pytest.mark.parametrize("raw", ['broken', '[]', '{}', '{"tool_calls": null}',
                                 '{"tool_calls": [{"tool": "kb_search", "args": []}]}'])
def test_invalid_plan_refuses_without_writer(raw):
    store = EvidenceStore()
    writer = ScriptLLM([])
    answer = asyncio.run(_loop(ScriptLLM([raw]), writer, store).run("q"))
    assert answer.status == "refused"
    assert answer.refusal_reason == "invalid_planner_output"
    assert answer.stop_reason == StopReason.NO_PROGRESS
    assert not writer.stages


def test_round_exhaustion_preserved_when_existing_evidence_answers():
    store = EvidenceStore()

    class Writer(ScriptLLM):
        async def generate(self, messages, metadata=None):
            self._responses = [_writer_ok(store.all()[0].citation_id)]
            return await super().generate(messages, metadata)

    answer = asyncio.run(_loop(ScriptLLM([PLAN_CALL]), Writer([]), store,
                              Budget(max_rounds=1)).run("q"))
    assert answer.status == "answered"
    assert answer.stop_reason == StopReason.BUDGET_EXHAUSTED


def test_expired_deadline_prevents_planner_call():
    planner = ScriptLLM([PLAN_DONE])
    budget = Budget(deadline_seconds=1, started_at=0, clock=lambda: 2)
    answer = asyncio.run(_loop(planner, ScriptLLM([]), EvidenceStore(), budget).run("q"))
    assert answer.stop_reason == StopReason.DEADLINE_EXCEEDED
    assert not planner.stages
