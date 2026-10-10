"""OCR Provider 子包（P3b）：统一协议 + fake（测试）+ 百度真实适配器。"""

from providers.ocr.base import OCRBlock, OCRPageResult, OCRProvider
from providers.ocr.baidu import BaiduOCRProvider
from providers.ocr.fake import FakeOCRProvider

__all__ = ["OCRBlock", "OCRPageResult", "OCRProvider", "BaiduOCRProvider", "FakeOCRProvider"]
