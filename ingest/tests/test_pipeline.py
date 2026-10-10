"""P3b 入库流水线验收（roadmap P3b：原生/扫描/混合/旋转/含图 fixture + 发布门）。

覆盖：文本层与 OCR 不重复；OCR blocks/bbox/置信度进 Evidence；
OCR 失败 → vision 兜底且转录/观察/推断分开；失败页显式报告且必需页失败不发布；
rotation/asset hash/图注-资产关联从 parser 保留到 Evidence。
"""

from __future__ import annotations

import asyncio

from evidence.store import EvidenceStore
from ingest.pipeline import PageAsset, ingest_pages
from providers.errors import ProviderError, ProviderErrorCode
from providers.ocr.fake import FakeOCRProvider, page_of
from providers.vision.fake import FakeVisionProvider


def test_native_page_skips_ocr_and_keeps_rotation() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider()
        page = PageAsset(page_number=2, text_layer="第一条 为了保障网络安全……", rotation_degrees=90.0)
        return await ingest_pages(
            [page],
            doc_id="doc-1",
            doc_title="测试法",
            doc_version="v1",
            index_identity="idx",
            store=store,
            ocr=ocr,
        ), store, ocr

    outcome, store, ocr = asyncio.run(scenario())
    assert outcome.publishable and not outcome.failure_report
    assert outcome.pages[0].method == "native_text"
    assert ocr.calls == []  # 文本层页不调 OCR（不重复）
    ev = outcome.pages[0].evidence[0]
    assert ev.raw_text.startswith("第一条")
    assert ev.locator.page == 2 and ev.locator.rotation == 90.0  # 旋转保留
    assert ev.extraction.method == "native_text"


def test_scanned_page_ocr_blocks_bbox_confidence() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider(script={1: page_of(["扫描行一", "扫描行二"], confidence=0.93)})
        page = PageAsset(page_number=1, image=b"\x89PNG fake")
        return await ingest_pages(
            [page], doc_id="doc-2", doc_title="扫描件", doc_version="v1", index_identity="idx", store=store, ocr=ocr
        ), store

    outcome, store = asyncio.run(scenario())
    assert outcome.pages[0].method == "ocr" and outcome.publishable
    evs = outcome.pages[0].evidence
    parent = next(e for e in evs if e.content_scope == "fulltext")
    blocks = [e for e in evs if e.content_scope == "region"]
    assert parent.raw_text == "扫描行一\n扫描行二"
    assert parent.extraction.confidence == 0.93
    assert len(blocks) == 2 and blocks[0].locator.bbox == (0.1, 0.1, 0.8, 0.08)  # bbox 不丢
    assert blocks[1].locator.bbox[1] == 0.2


def test_ocr_failure_falls_back_to_vision_separating_inference() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider(script={1: ProviderError(ProviderErrorCode.SERVER_ERROR, "OCR down")})
        vision = FakeVisionProvider()
        page = PageAsset(page_number=1, image=b"\x89PNG fake", asset_id="fig-1", asset_hash="abc123")
        return await ingest_pages(
            [page], doc_id="doc-3", doc_title="含图件", doc_version="v1", index_identity="idx", store=store, ocr=ocr, vision=vision
        ), store, vision

    outcome, store, vision = asyncio.run(scenario())
    assert outcome.pages[0].method == "vision" and outcome.publishable
    assert vision.calls == ["fig-1"]
    ev = outcome.pages[0].evidence[0]
    assert ev.source_type == "asset"
    assert ev.extraction.method == "vision"
    assert ev.locator.asset_id == "fig-1" and ev.locator.asset_hash == "abc123"
    assert ev.raw_text and "转录" in ev.raw_text  # 只有图内文字转录进 raw_text
    assert ev.derived_observations and all(
        d.startswith("[observation]") or d.startswith("[inference]") for d in ev.derived_observations
    )  # 观察/推断分开标注
    assert any(d.startswith("[inference]") for d in ev.derived_observations)


def test_required_page_failure_blocks_publication_and_reports() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider(script={2: ProviderError(ProviderErrorCode.TIMEOUT, "ocr timeout")})
        vision = FakeVisionProvider(script={"doc-4:p2": ProviderError(ProviderErrorCode.SERVER_ERROR, "vision down")})
        pages = [
            PageAsset(page_number=1, text_layer="第一页文本"),
            PageAsset(page_number=2, image=b"\x89PNG fake"),  # OCR 与 vision 都失败
            PageAsset(page_number=3, text_layer="第三页文本"),
        ]
        return await ingest_pages(
            pages, doc_id="doc-4", doc_title="混合件", doc_version="v1", index_identity="idx", store=store, ocr=ocr, vision=vision
        )

    outcome = asyncio.run(scenario())
    assert outcome.publishable is False  # 必需页失败不发布"完整"版本
    assert [f["page_number"] for f in outcome.failure_report] == [2]
    tried = {t["stage"] for t in outcome.failure_report[0]["tried"]}
    assert tried == {"ocr", "vision", "page"}  # 失败页与原因显式报告
    assert outcome.pages[0].method == "native_text" and outcome.pages[2].method == "native_text"  # 其他页不受拖垮


def test_optional_page_failure_still_publishable_but_reported() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider(script={2: ProviderError(ProviderErrorCode.TIMEOUT, "ocr timeout")})
        pages = [
            PageAsset(page_number=1, text_layer="第一页文本"),
            PageAsset(page_number=2, image=b"\x89PNG fake"),
        ]
        return await ingest_pages(
            pages,
            doc_id="doc-5",
            doc_title="选择性必需",
            doc_version="v1",
            index_identity="idx",
            store=store,
            ocr=ocr,
            require_pages={1},
        )

    outcome = asyncio.run(scenario())
    assert outcome.publishable is True  # 失败页不在必需集合
    assert [f["page_number"] for f in outcome.failure_report] == [2]  # 但仍报告


def test_caption_asset_link_preserved_on_native_page() -> None:
    async def scenario():
        store = EvidenceStore()
        page = PageAsset(
            page_number=4,
            text_layer="图 1 展示了趋势",
            asset_id="fig-1",
            asset_hash="asset-hash-1",
            asset_bbox=(0.2, 0.3, 0.5, 0.4),
            caption="图 1：2019–2025 年专利申请趋势",
        )
        return await ingest_pages(
            [page], doc_id="doc-6", doc_title="论文", doc_version="v2", index_identity="idx", store=store
        )

    outcome = asyncio.run(scenario())
    asset_ev = next(e for e in outcome.pages[0].evidence if e.source_type == "asset")
    assert asset_ev.locator.asset_id == "fig-1"
    assert asset_ev.locator.asset_hash == "asset-hash-1"
    assert asset_ev.locator.bbox == (0.2, 0.3, 0.5, 0.4)
    assert asset_ev.raw_text and "趋势" in asset_ev.raw_text  # 图注与资产绑定在同一证据


def test_low_quality_ocr_is_flagged_not_hidden() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider(script={1: page_of(["模糊文字"], confidence=0.2)})
        return await ingest_pages(
            [PageAsset(page_number=1, image=b"\x89PNG fake")],
            doc_id="doc-7",
            doc_title="低质量",
            doc_version="v1",
            index_identity="idx",
            store=store,
            ocr=ocr,
        )

    outcome = asyncio.run(scenario())
    assert outcome.pages[0].low_quality is True
    assert outcome.failure_report and outcome.failure_report[0].get("low_quality") is True
    parent = next(e for e in outcome.pages[0].evidence if e.content_scope == "fulltext")
    assert parent.extraction.confidence == 0.2  # 真实置信度保留，不伪造
