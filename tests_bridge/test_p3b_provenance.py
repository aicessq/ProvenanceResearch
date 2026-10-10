"""P3b 溯源验收（tests_bridge）：页码/bbox/hash 从 parser 到 citation 不丢。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evidence.store import EvidenceStore  # noqa: E402
from ingest.pipeline import PageAsset, ingest_pages  # noqa: E402
from providers.ocr.fake import FakeOCRProvider, page_of  # noqa: E402


def test_page_bbox_hash_survive_to_citation() -> None:
    async def scenario():
        store = EvidenceStore()
        ocr = FakeOCRProvider(
            script={3: page_of(["关键数字 90 日", "第二款文本"], confidence=0.9, page_number=3)}
        )
        page = PageAsset(
            page_number=3,
            image=b"\x89PNG fake",
            rotation_degrees=90.0,
            asset_id="fig-9",
            asset_hash="asset-hash-9",
            asset_bbox=(0.1, 0.2, 0.3, 0.4),
            caption="图 9：对比",
        )
        outcome = await ingest_pages(
            [page], doc_id="doc-p", doc_title="溯源件", doc_version="v3", index_identity="idx-p", store=store, ocr=ocr
        )
        return outcome, store

    outcome, store = asyncio.run(scenario())
    evs = outcome.pages[0].evidence
    block = next(e for e in evs if e.content_scope == "region" and e.raw_text == "关键数字 90 日")
    asset_ev = next(e for e in evs if e.source_type == "asset")

    # 页码/rotation/bbox 进 locator
    assert block.locator.page == 3 and block.locator.rotation == 90.0
    assert block.locator.bbox == (0.1, 0.1, 0.8, 0.08)
    assert asset_ev.locator.asset_id == "fig-9" and asset_ev.locator.asset_hash == "asset-hash-9"

    # citation 由完整身份生成且稳定（同身份重登记同 id）
    assert block.citation_id.startswith("K") and asset_ev.citation_id[:1] != "K"
    resolved = store.get(block.citation_id)
    assert resolved is not None and resolved.locator.bbox == (0.1, 0.1, 0.8, 0.08)
    assert resolved.provenance.content_hash  # 内容 hash 在 provenance 里

    # 再次入库同身份页 → citation_id 一致（不重复登记/不换 id）
    again = asyncio.run(_reingest_same(store))
    assert again == block.citation_id


async def _reingest_same(store: EvidenceStore) -> str:
    ocr = FakeOCRProvider(script={3: page_of(["关键数字 90 日", "第二款文本"], confidence=0.9, page_number=3)})
    outcome = await ingest_pages(
        [PageAsset(page_number=3, image=b"\x89PNG fake", rotation_degrees=90.0)],
        doc_id="doc-p",
        doc_title="溯源件",
        doc_version="v3",
        index_identity="idx-p",
        store=store,
        ocr=ocr,
    )
    block = next(e for e in outcome.pages[0].evidence if e.content_scope == "region" and e.raw_text == "关键数字 90 日")
    return block.citation_id
