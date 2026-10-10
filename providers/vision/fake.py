"""Fake Vision Provider（脚本化，仅限测试）：可编排转录/观察/推断与失败。"""

from __future__ import annotations

from providers.errors import ProviderError, ProviderErrorCode
from providers.vision.base import VisionAssetResult, VisionObservation


class FakeVisionProvider:
    provider_name = "fake_vision"

    def __init__(self, script: dict[str, VisionAssetResult | Exception] | None = None) -> None:
        self._script = dict(script or {})
        self.calls: list[str] = []

    async def analyze(
        self,
        image: bytes,
        *,
        asset_id: str,
        question: str,
        page_number: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> VisionAssetResult:
        self.calls.append(asset_id)
        outcome = self._script.get(asset_id)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        if not image:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "空图像无法识别", provider=self.provider_name)
        return VisionAssetResult(
            asset_id=asset_id,
            observations=(
                VisionObservation(text="图内文字转录（fake）", kind="text_in_image", confidence=0.9),
                VisionObservation(text="图中可见一条折线随时间上升", kind="observation"),
                VisionObservation(text="该趋势可能与政策实施有关（推断，未经验证）", kind="inference"),
            ),
            provider=self.provider_name,
            model="fake-vision-1",
            prompt_version="v1",
            asset_hash="",
            page_number=page_number,
            bbox=bbox,
        )
