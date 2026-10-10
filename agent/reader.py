"""Reader：确定性 RRF 融合（execution-plan Phase 3 / decisions 2026-09-17）。

固定参数：RRF k=60；来源权重 w(kb_chunk)=1.0、w(web/paper)=0.7；
池上限 KB top20、External top10；输出 top8。

融合规则（decisions 2026-09-18）：每个 channel 维护去重后的排名列表，
多次查询按确定规则合并，**同一工具的重复调用不计成多张独立赞成票**；
RRF 与原始分另存（Score.rrf），不跨供应商比较原始分。
"""

from __future__ import annotations

from dataclasses import replace

from evidence.schema import Evidence, Score

RRF_K = 60
CHANNEL_WEIGHTS = {"kb": 1.0, "web": 0.7, "arxiv": 0.7}
EXTERNAL_WEIGHT = 0.7
KB_POOL = 20
EXTERNAL_POOL = 10
OUTPUT_TOP = 8


def _dedupe_ranked(items: list[Evidence]) -> list[Evidence]:
    """同 channel 内按 citation_id 去重，保留最好名次。"""
    seen: dict[str, Evidence] = {}
    order: list[str] = []
    for ev in items:
        if ev.citation_id not in seen:
            seen[ev.citation_id] = ev
            order.append(ev.citation_id)
    return [seen[cid] for cid in order]


def _rrf_scores(channels: dict[str, list[Evidence]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for channel, items in channels.items():
        weight = CHANNEL_WEIGHTS.get(channel, EXTERNAL_WEIGHT)
        for rank, ev in enumerate(_dedupe_ranked(items), start=1):
            scores[ev.citation_id] = scores.get(ev.citation_id, 0.0) + weight / (RRF_K + rank)
    return scores


def fuse(channels: dict[str, list[Evidence]], *, output_top: int = OUTPUT_TOP) -> list[Evidence]:
    """多 channel 融合：池截断（KB20/外部10）→ 加权 RRF → 输出 top N。

    channels: channel 名（kb/web/arxiv/…）→ 该 channel 的排名列表（最优在前）。
    """
    deduped = {name: _dedupe_ranked(items) for name, items in channels.items()}

    # 池截断：KB 按自身名次 top20；外部（web/arxiv）合并后按外部 RRF top10
    kb_pool = [ev for ev in deduped.get("kb", [])][:KB_POOL]
    external_channels = {name: items for name, items in deduped.items() if name != "kb"}
    external_scores = _rrf_scores(external_channels)
    external_pool = sorted(
        (ev for items in external_channels.values() for ev in items),
        key=lambda ev: (-external_scores.get(ev.citation_id, 0.0), ev.citation_id),
    )[:EXTERNAL_POOL]

    scores = _rrf_scores({**deduped})
    pool_by_id = {ev.citation_id: ev for ev in [*kb_pool, *external_pool]}

    ranked = sorted(
        pool_by_id.values(),
        key=lambda ev: (-scores.get(ev.citation_id, 0.0), ev.citation_id),
    )
    result: list[Evidence] = []
    for ev in ranked[:output_top]:
        # 加权 RRF 已在 _rrf_scores 内完成（w/(k+rank) 累加），此处只记录
        result.append(
            replace(
                ev,
                score=Score(
                    raw=ev.score.raw if ev.score else None,
                    raw_channel=ev.score.raw_channel if ev.score else None,
                    rrf=round(scores.get(ev.citation_id, 0.0), 6),
                    rerank=ev.score.rerank if ev.score else None,
                ),
            )
        )
    return result
