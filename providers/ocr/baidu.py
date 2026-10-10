"""百度智能云通用文字识别适配器（P3b 第一个真实 OCR provider）。

协议（真实 REST，非假设）：
1. `POST aip.baidubce.com/oauth/2.0/token`（API Key/Secret Key → access_token，缓存至过期）
2. `POST aip.baidubce.com/rest/2.0/ocr/v1/general?location=true&probability=true`
   （表单 image=<base64>；返回 words_result[].words/location/probability）

location 为像素坐标，本适配器按图像宽高归一化到 0–1（旋转校正后的页面坐标约定见
providers/ocr/base.py）；probability 缺失时置信度为 None，不伪造。错误统一
ProviderError 六分类；密钥只发绑定 host（延续 P2.5 出站纪律）。
"""

from __future__ import annotations

import base64
import struct
import time

import httpx

from providers.errors import ProviderError, ProviderErrorCode, classify_http_status
from providers.ocr.base import OCRBlock, OCRPageResult

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general"

_AUTH_CODES = {4, 110, 111, 216101, 216201, 282000}
_RATE_CODES = {18, 19, 216102}


def _image_size(image: bytes) -> tuple[int, int] | None:
    """PNG/JPEG 尺寸探测（像素坐标归一化用）；未知格式返回 None。"""
    if image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) >= 24:
        width, height = struct.unpack(">II", image[16:24])
        return width, height
    if image[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(image):
            if image[i] != 0xFF:
                i += 1
                continue
            marker = image[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                height, width = struct.unpack(">HH", image[i + 5 : i + 9])
                return width, height
            length = struct.unpack(">H", image[i + 2 : i + 4])[0]
            i += 2 + length
    return None


class BaiduOCRProvider:
    provider_name = "baidu"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        model: str = "general",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._secret_key = (secret_key or "").strip()
        self._model = model
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _require_config(self) -> None:
        if not self._api_key or not self._secret_key:
            raise ProviderError(
                ProviderErrorCode.CONFIG_MISSING,
                "百度 OCR 需要 OCR_API_KEY/OCR_API_SECRET（或 API Key/Secret Key）；拒绝以空凭证出站",
                provider=self.provider_name,
            )

    async def _access_token(self) -> str:
        self._require_config()
        if self._token and time.monotonic() < self._token_expires_at - 60:
            return self._token
        try:
            resp = await self._client.post(
                TOKEN_URL,
                params={
                    "grant_type": "client_credentials",
                    "client_id": self._api_key,
                    "client_secret": self._secret_key,
                },
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorCode.TIMEOUT, "OCR 取 token 超时", provider=self.provider_name) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorCode.SERVER_ERROR, f"OCR 取 token 失败: {type(exc).__name__}", provider=self.provider_name) from exc
        if resp.status_code != 200:
            raise ProviderError(classify_http_status(resp.status_code), f"OCR 取 token HTTP {resp.status_code}", provider=self.provider_name)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "OCR token 响应非 JSON", provider=self.provider_name) from exc
        token = str(data.get("access_token") or "")
        if not token:
            code = int(data.get("error_code") or 0)
            raise ProviderError(
                ProviderErrorCode.AUTH_FAILED if code in _AUTH_CODES else ProviderErrorCode.INVALID_RESPONSE,
                f"OCR token 失败: {data.get('error_msg') or 'missing access_token'}",
                provider=self.provider_name,
            )
        self._token = token
        self._token_expires_at = time.monotonic() + float(data.get("expires_in") or 0)
        return token

    async def recognize(self, image: bytes, *, page_number: int, rotation_degrees: float = 0.0) -> OCRPageResult:
        token = await self._access_token()
        if not image:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "空图像无法 OCR", provider=self.provider_name)
        try:
            resp = await self._client.post(
                OCR_URL,
                params={"access_token": token, "location": "true", "probability": "true"},
                data={"image": base64.b64encode(image).decode("ascii")},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorCode.TIMEOUT, "OCR 调用超时", provider=self.provider_name) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorCode.SERVER_ERROR, f"OCR 调用失败: {type(exc).__name__}", provider=self.provider_name) from exc

        if resp.status_code != 200:
            raise ProviderError(classify_http_status(resp.status_code), f"OCR HTTP {resp.status_code}", provider=self.provider_name)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "OCR 响应非 JSON", provider=self.provider_name) from exc
        if "words_result" not in data:
            code = int(data.get("error_code") or 0)
            if code in _AUTH_CODES:
                raise ProviderError(ProviderErrorCode.AUTH_FAILED, f"OCR 认证失败: {data.get('error_msg')}", provider=self.provider_name)
            if code in _RATE_CODES:
                raise ProviderError(ProviderErrorCode.RATE_LIMIT, f"OCR 限流: {data.get('error_msg')}", provider=self.provider_name)
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, f"OCR 响应缺少 words_result: {data.get('error_msg')}", provider=self.provider_name)

        size = _image_size(image)
        blocks: list[OCRBlock] = []
        for order, item in enumerate(data.get("words_result") or []):
            text = str(item.get("words") or "")
            if not text:
                continue
            location = item.get("location") or {}
            bbox = (0.0, 0.0, 1.0, 0.0)
            if size and all(k in location for k in ("left", "top", "width", "height")):
                width, height = size
                if width > 0 and height > 0:
                    bbox = (
                        float(location["left"]) / width,
                        float(location["top"]) / height,
                        float(location["width"]) / width,
                        float(location["height"]) / height,
                    )
            probability = item.get("probability")
            confidence = float(probability) if isinstance(probability, (int, float)) else None
            blocks.append(OCRBlock(text=text, bbox=bbox, reading_order=order, confidence=confidence))

        return OCRPageResult(
            page_number=page_number,
            blocks=tuple(blocks),
            provider=self.provider_name,
            model=self._model,
            rotation_degrees=rotation_degrees,
            raw_response_ref=f"baidu-ocr:{data.get('log_id', '')}",
        )
