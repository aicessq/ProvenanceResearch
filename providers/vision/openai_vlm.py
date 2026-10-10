"""OpenAI 兼容 VLM 适配器（P3b 第一个真实 vision provider）。

适用 GLM-4V / Qwen-VL / MiniCPM-V 等提供 OpenAI 兼容 `chat/completions` 且支持
image 输入的模型（供应商由用户选择；协议是真实协议，不假设全部供应商兼容）。
要求模型输出结构化 JSON，转录/可观察/推断分开；解析不出结构即 INVALID_RESPONSE，
不把整段模型描述冒充转录。密钥只发配置绑定 host（base_url https-only）。
"""

from __future__ import annotations

import base64
import json
import re

import httpx

from providers.errors import ProviderError, ProviderErrorCode, classify_http_status
from providers.vision.base import VisionAssetResult, VisionObservation

_PROMPT = (
    "你是文档图像阅读器。请只依据图像内容输出 JSON：\n"
    '{"transcript": ["图中文字逐行转录"], '
    '"observations": ["可直接观察到的事实"], '
    '"inferences": ["推断（必须明确是推断）"]} '
    "不要输出 JSON 以外的内容。"
)


class OpenAICompatVLMProvider:
    provider_name = "openai_compat_vlm"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        prompt_version: str = "v1",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._base_url = (base_url or "").strip().rstrip("/")
        self._prompt_version = prompt_version
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)

    def _require_config(self) -> None:
        if not self._api_key or not self._model or not self._base_url:
            raise ProviderError(
                ProviderErrorCode.CONFIG_MISSING,
                "vision 需要 VISION_API_KEY/VISION_MODEL/VISION_BASE_URL；拒绝空凭证出站",
                provider=self.provider_name,
            )
        if not self._base_url.startswith("https://"):
            raise ProviderError(
                ProviderErrorCode.CONFIG_MISSING,
                "VISION_BASE_URL 必须是 https",
                provider=self.provider_name,
            )

    async def analyze(
        self,
        image: bytes,
        *,
        asset_id: str,
        question: str,
        page_number: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> VisionAssetResult:
        self._require_config()
        if not image:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "空图像无法识别", provider=self.provider_name)
        data_url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{_PROMPT}\n任务：{question}"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        try:
            resp = await self._client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorCode.TIMEOUT, "vision 调用超时", provider=self.provider_name) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorCode.SERVER_ERROR, f"vision 调用失败: {type(exc).__name__}", provider=self.provider_name) from exc
        if resp.status_code != 200:
            raise ProviderError(classify_http_status(resp.status_code), f"vision HTTP {resp.status_code}", provider=self.provider_name)
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "vision 响应结构非法", provider=self.provider_name) from exc

        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "vision 输出不是结构化 JSON", provider=self.provider_name)
        try:
            parsed = json.loads(match.group(0))
        except ValueError as exc:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "vision 输出 JSON 解析失败", provider=self.provider_name) from exc

        observations: list[VisionObservation] = []
        for line in parsed.get("transcript") or []:
            if str(line).strip():
                observations.append(VisionObservation(text=str(line), kind="text_in_image"))
        for line in parsed.get("observations") or []:
            if str(line).strip():
                observations.append(VisionObservation(text=str(line), kind="observation"))
        for line in parsed.get("inferences") or []:
            if str(line).strip():
                observations.append(VisionObservation(text=str(line), kind="inference"))
        if not observations:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "vision 输出无任何内容", provider=self.provider_name)

        return VisionAssetResult(
            asset_id=asset_id,
            observations=tuple(observations),
            provider=self.provider_name,
            model=self._model,
            prompt_version=self._prompt_version,
            page_number=page_number,
            bbox=bbox,
            raw_response_ref=f"vlm:{data.get('id', '')}",
        )
