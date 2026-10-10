"""ingest 包（P3b）：PDF/图像 → Evidence 的多模态入库流水线。"""

from ingest.pipeline import (
    DocumentOutcome,
    PageAsset,
    PageOutcome,
    ingest_pages,
)

__all__ = ["DocumentOutcome", "PageAsset", "PageOutcome", "ingest_pages"]
