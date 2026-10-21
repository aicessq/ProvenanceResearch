"""失败运行不能从成本和质量统计中消失。"""
import asyncio
from types import SimpleNamespace

import pytest

from eval.metrics import score_condition
from eval.pipelines import RunResult, UsageLLM


def test_failed_model_call_is_counted_and_usage_becomes_unknown():
    class Provider:
        calls = 0

        async def generate(self, messages, metadata=None):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("provider unavailable")
            return SimpleNamespace(prompt_tokens=13, completion_tokens=2)

    llm = UsageLLM(Provider())

    async def run():
        await llm.generate([])
        with pytest.raises(RuntimeError):
            await llm.generate([])

    asyncio.run(run())
    assert llm.calls == 2
    assert llm.prompt_tokens == 13
    assert llm.reported_usage is False


def test_error_keeps_known_usage_and_scores_zero_instead_of_disappearing():
    run = RunResult("q", "C", "error", cost_unknown=True,
                    usage={"prompt_tokens": 13, "completion_tokens": 2, "llm_calls": 2})
    metrics = score_condition({"q": [run]}, {"q": {"expected_behavior": "answered",
                                                          "required_points": ["fact"]}})
    assert metrics["answers"]["answer_correctness_mechanical"]["mean"] == 0.0
    assert metrics["runtime"]["tool_termination_compliance"]["mean"] == 0.0
    assert metrics["runtime"]["provider_failures"] == 1
    assert metrics["cost"]["prompt_tokens"] == 13
    assert metrics["cost"]["llm_calls"] == 2
    assert metrics["cost"]["cost_unknown"] is True
