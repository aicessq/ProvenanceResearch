"""OCR Provider 统一接口（P3b）。

云 OCR 返回转录、阅读顺序、block/bbox 与可用置信度（design.md §7）：
bbox 为旋转校正后页面左上角原点的 0–1 坐标，rotation 单独保留以回指原 PDF；
置信度没有可靠来源时为 None，禁止伪造数值。缺配置显式失败，失败不伪造转录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OCRBlock:
    text: str
    bbox: tuple[float, float, float, float]  # x, y, w, h（旋转校正后 0–1）
    reading_order: int
    confidence: float | None = None


@dataclass(frozen=True)
class OCRPageResult:
    page_number: int  # 1 起始
    blocks: tuple[OCRBlock, ...]
    provider: str
    model: str
    rotation_degrees: float = 0.0
    raw_response_ref: str | None = None

    @property
    def text(self) -> str:
        """按阅读顺序拼接的页转录。"""
        return "\n".join(b.text for b in sorted(self.blocks, key=lambda b: b.reading_order))

    @property
    def min_confidence(self) -> float | None:
        values = [b.confidence for b in self.blocks if b.confidence is not None]
        return min(values) if values else None


class OCRProvider(Protocol):
    """OCR 统一协议：image bytes → 页转录 + blocks/bbox/置信度。"""

    provider_name: str

    async def recognize(self, image: bytes, *, page_number: int, rotation_degrees: float = 0.0) -> OCRPageResult: ...
