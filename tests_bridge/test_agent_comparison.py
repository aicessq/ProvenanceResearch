"""对照评测自身的契约：固定真实旧源码、共享来源、缺配置拒绝及逐题明细。"""
import asyncio
from dataclasses import replace
import json

import pytest

from agent.loop import AgentLoop
from agent.tests.test_budget_reader import _ev
from evidence.store import EvidenceStore
from eval.compare_agents import (DEFAULT_FREEZE, SnapshotExecutor, compare, load_config,
                                 mechanisms, reference_module)
from eval.pipelines import RunResult
from tools.base import ToolResult


def test_reference_is_pinned_old_loop_not_current_class():
    config, _ = load_config(DEFAULT_FREEZE)
    module = reference_module(config)
    assert module.AgentLoop is not AgentLoop
    assert module.AgentLoop.__module__.endswith(config["reference_revision"])
    with pytest.raises(ValueError, match="源码指纹"):
        reference_module({**config, "reference_loop_sha256": "0" * 64})


def test_external_snapshot_replays_same_evidence_into_new_task_store():
    async def run():
        stores = [EvidenceStore(), EvidenceStore()]
        cache, log, calls = {}, [], []
        ev = _ev("snapshot")
        ev = replace(ev, citation_id=ev.make_citation_id())

        class Tool:
            async def execute(self, name, **args):
                calls.append(args)
                stores[0].register(ev)
                return ToolResult("first", "ok", evidence=[ev])

        one = await SnapshotExecutor(Tool(), stores[0], cache, log).execute("web_search", query="same")
        two = await SnapshotExecutor(Tool(), stores[1], cache, log).execute("web_search", query="same")
        assert len(calls) == 1
        assert one.call_id != two.call_id
        assert stores[1].get(ev.citation_id) == ev
        assert [r["cache_hit"] for r in log] == [False, True]

    asyncio.run(run())


def test_fake_comparison_has_three_variants_and_no_quality_conclusion():
    config, base = load_config(DEFAULT_FREEZE)
    # 单题 fixture 只测试报告结构，不写正式评测结果。
    base["dataset"]["question_ids"] = ["q001"]
    report = asyncio.run(compare(config, base, mode="fake", runs=1))
    assert set(report["conditions"]) == {"baseline", "gaps", "feedback"}
    assert report["not_a_conclusion"] is True
    assert report["thresholds"]["evaluated"] is False
    assert report["safety"]["passed"] is True
    assert len(report["paired"]) == 1
    for variant in report["conditions"]:
        assert len(report["details"][variant]) == 1
        assert report["details"][variant][0]["status"] != "error"
        assert report["details"][variant][0]["budget_report"]["max_tokens"] == 20000


def test_live_comparison_missing_keys_rejects_before_any_run(monkeypatch):
    config, base = load_config(DEFAULT_FREEZE)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="需要 LLM_API_KEY"):
        asyncio.run(compare(config, base, mode="live", runs=1))


def test_mechanism_rates_distinguish_no_gaps_and_closed_gaps():
    result = RunResult("q", "C", "answered", gaps=[{"status": "resolved"}, {"status": "unresolved"}],
                       limitations=["未解决"], tool_trace=[
                           {"type": "tool_call", "tool": "web_search", "args": {"query": "q"}}] * 2)
    measured = mechanisms([result])
    assert measured["gap_closure_rate"]["mean"] == 0.5
    assert measured["duplicate_search_rate"]["mean"] == 0.5
    assert measured["partial_answer_rate"]["mean"] == 1.0
    assert mechanisms([RunResult("q", "C", "refused")])["gap_closure_rate"]["mean"] is None
