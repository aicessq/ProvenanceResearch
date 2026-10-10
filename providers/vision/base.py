"""Vision Provider 统一接口（P3b）。

图中文字、可观察内容与推断必须分开记录（design.md §7）：
`text_in_image`（图内文字转录）/`observation`（可观察事实）/`inference`（推断），
绑定 asset_id、原资产 hash、页/bbox、模型与 prompt 版本。置信度无可靠来源为 None。
视觉结论必须可回看原资产/区域，不能仅用同模型的文字描述自证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

OBSERVATION_KINDS = ("text_in_image", "observation", "inference")


@dataclass(frozen=True)
class VisionObservation:
    text: str
    kind: str  # text_in_image / observation / inference
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in OBSERVATION_KINDS:
            raise ValueError(f"非法 vision 观察类型: {self.kind}")


@dataclass(frozen=True)
class VisionAssetResult:
    asset_id: str
    observations: tuple[VisionObservation, ...]
    provider: str
    model: str
    prompt_version: str
    asset_hash: str = ""
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    raw_response_ref: str | None = None

    @property
    def transcribed_text(self) -> str:
        return "\n".join(o.text for o in self.observations if o.kind == "text_in_image")

    @property
    def inferences(self) -> tuple[VisionObservation, ...]:
        return tuple(o for o in self.observations if o.kind == "inference")


class VisionProvider(Protocol):
    """vision 统一协议：图像 → 文字转录 + 可观察 + 推断（分开标注）。"""

    provider_name: str

    async def analyze(
        self,
        image: bytes,
        *,
        asset_id: str,
        question: str,
        page_number: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> VisionAssetResult: ...
