"""Fake OCR Provider（脚本化，仅限测试）：成功/低置信度/失败/部分失败均可编排。"""

from __future__ import annotations

from providers.errors import ProviderError, ProviderErrorCode
from providers.ocr.base import OCRBlock, OCRPageResult


class FakeOCRProvider:
    provider_name = "fake_ocr"

    def __init__(self, script: dict[int, OCRPageResult | Exception] | None = None, *, default_confidence: float | None = 0.98) -> None:
        self._script = dict(script or {})
        self._default_confidence = default_confidence
        self.calls: list[int] = []

    async def recognize(self, image: bytes, *, page_number: int, rotation_degrees: float = 0.0) -> OCRPageResult:
        self.calls.append(page_number)
        outcome = self._script.get(page_number)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        if not image:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "空图像无法 OCR", provider=self.provider_name)
        return OCRPageResult(
            page_number=page_number,
            blocks=(
                OCRBlock(text=f"fake-ocr 转录（第 {page_number} 页）", bbox=(0.1, 0.1, 0.8, 0.1), reading_order=0, confidence=self._default_confidence),
            ),
            provider=self.provider_name,
            model="fake-ocr-1",
            rotation_degrees=rotation_degrees,
        )


def page_of(texts: list[str], *, confidence: float | None = 0.98, page_number: int = 1) -> OCRPageResult:
    """测试辅助：按行构造带 bbox 的 OCR 页结果。"""
    return OCRPageResult(
        page_number=page_number,
        blocks=tuple(
            OCRBlock(text=text, bbox=(0.1, 0.1 + 0.1 * i, 0.8, 0.08), reading_order=i, confidence=confidence)
            for i, text in enumerate(texts)
        ),
        provider="fake_ocr",
        model="fake-ocr-1",
    )
