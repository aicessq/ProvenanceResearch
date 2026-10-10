"""Vision Provider 子包（P3b）：统一协议 + fake（测试）+ OpenAI 兼容 VLM 真实适配器。"""

from providers.vision.base import VisionAssetResult, VisionObservation, VisionProvider
from providers.vision.fake import FakeVisionProvider
from providers.vision.openai_vlm import OpenAICompatVLMProvider

__all__ = ["VisionAssetResult", "VisionObservation", "VisionProvider", "FakeVisionProvider", "OpenAICompatVLMProvider"]
