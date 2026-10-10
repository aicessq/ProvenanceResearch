"""Budget 与 Reader RRF 契约（P3d：有界执行 + 确定性融合）。"""

from __future__ import annotations

from agent.budget import Budget, StopReason
from agent.reader import RRF_K, fuse
from evidence.schema import Evidence, Extraction, Locator, Provenance


def _ev(cid: str, source_type: str = "kb_chunk", text: str = "t", channel: str = "kb") -> Evidence:
    prefix = {"kb_chunk": "K", "web": "W", "paper": "A"}[source_type]
    prov = Provenance(
        provider="p",
        content_hash=f"h-{cid}",
        doc_id="doc-1",
        doc_version="ver-1",
        chunk_id=cid,
        index_identity="idx",
    )
    return Evidence(
        citation_id=f"{prefix}{cid}",
        source_id=f"src-{cid}",
        source_type=source_type,
        modality="text",
        content_scope="fulltext",
        raw_text=text,
        provenance=prov,
        locator=Locator(page=1),
        extraction=Extraction(method="native_text"),
    )


# ---- Budget ----


def test_budget_defaults_match_plan() -> None:
    b = Budget()
    assert b.max_rounds == 3
    assert b.max_tool_calls == 12
    assert b.max_tokens == 20000
    assert b.deadline_seconds == 180.0


def test_budget_tool_call_limit() -> None:
    b = Budget(max_tool_calls=2)
    b.charge_tool_call()
    assert b.exceeded() is None
    b.charge_tool_call()
    assert b.exceeded() == StopReason.BUDGET_EXHAUSTED


def test_budget_token_limit() -> None:
    b = Budget(max_tokens=100)
    b.charge_tokens(60)
    assert b.exceeded() is None
    assert b.remaining_tokens() == 40
    b.charge_tokens(40)
    assert b.exceeded() == StopReason.BUDGET_EXHAUSTED


def test_budget_deadline_precedes_amount() -> None:
    clock = {"now": 0.0}

    b = Budget(deadline_seconds=10.0, clock=lambda: clock["now"])
    b.started_at = 0.0
    b.charge_tool_call()
    clock["now"] = 11.0
    assert b.exceeded() == StopReason.DEADLINE_EXCEEDED


def test_budget_round_limit() -> None:
    b = Budget(max_rounds=1)
    b.begin_round()
    assert b.exceeded() is None
    b.begin_round()
    assert b.exceeded() == StopReason.BUDGET_EXHAUSTED


# ---- Reader ----


def test_reader_rrf_prefers_consensus_across_channels() -> None:
    """同一证据被多 channel 命中 → RRF 更高；权重 kb=1.0 > 外部 0.7。"""
    a = _ev("a", "kb_chunk")
    b = _ev("b", "web")
    ranked = fuse({"kb": [a, b], "web": [b, a]})
    assert ranked[0].citation_id == a.citation_id  # a: kb 1/(60+1) + web 0.7/(60+2) > b
    ids = [ev.citation_id for ev in ranked]
    assert set(ids) == {"Ka", "Wb"}
    assert all(ev.score is not None and ev.score.rrf is not None for ev in ranked)


def test_reader_same_tool_repeat_not_double_voted() -> None:
    """同一 channel 的重复调用按去重排名，不计成多张赞成票。"""
    a = _ev("a")
    b = _ev("b")
    once = fuse({"kb": [a, b]})
    repeated = fuse({"kb": [a, b, a, a]})  # 重复出现不改变排名
    assert [ev.citation_id for ev in once] == [ev.citation_id for ev in repeated]
    assert once[0].score.rrf == repeated[0].score.rrf


def test_reader_pool_caps_and_output_top() -> None:
    kb_items = [_ev(f"k{i:02d}") for i in range(25)]
    web_items = [_ev(f"w{i:02d}", "web") for i in range(15)]
    ranked = fuse({"kb": kb_items, "web": web_items})
    assert len(ranked) == 8  # 输出 top8
    # KB 池 20、外部池 10：超出池的候选不会出现在结果
    result_ids = {ev.citation_id for ev in ranked}
    assert "Kk24" not in result_ids
    assert "Ww14" not in result_ids


def test_reader_rrf_formula_uses_k60() -> None:
    a = _ev("a")
    ranked = fuse({"kb": [a]})
    assert ranked[0].score.rrf == round(1.0 / (RRF_K + 1), 6)
