"""P3b 真实适配器契约（fake/recorded，无凭证不联网）。

覆盖：百度 OCR（token 缓存、location 归一化、错误六分类、缺配置显式失败）
与 OpenAI 兼容 VLM（结构化输出解析、转录/观察/推断分离、非法输出拒绝、https-only）。
"""

from __future__ import annotations

import asyncio
import json
import struct

import httpx
import pytest

from providers.errors import ProviderError, ProviderErrorCode
from providers.ocr.baidu import BaiduOCRProvider
from providers.vision.openai_vlm import OpenAICompatVLMProvider


def png_bytes(width: int = 100, height: int = 50) -> bytes:
    ihdr = struct.pack(">II", width, height)
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + ihdr + b"\x00" * 20


def baidu_token_response(token: str = "tok-1") -> httpx.Response:
    return httpx.Response(200, json={"access_token": token, "expires_in": 3600})


def baidu_ocr_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "log_id": "log-1",
            "words_result_num": 2,
            "words_result": [
                {"words": "留存网络日志不少于六个月", "location": {"left": 10, "top": 5, "width": 80, "height": 10}, "probability": 0.97},
                {"words": "第二款", "location": {"left": 10, "top": 25, "width": 30, "height": 8}},
            ],
        },
    )


def test_baidu_ocr_normalizes_location_and_keeps_confidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth/2.0/token" in str(request.url):
            return baidu_token_response()
        return baidu_ocr_response()

    provider = BaiduOCRProvider(
        api_key="ak", secret_key="sk", client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    )
    result = asyncio.run(provider.recognize(png_bytes(100, 50), page_number=3, rotation_degrees=90.0))
    assert result.page_number == 3 and result.rotation_degrees == 90.0
    assert result.blocks[0].text == "留存网络日志不少于六个月"
    assert result.blocks[0].bbox == (0.1, 0.1, 0.8, 0.2)  # 像素 → 0–1 归一化
    assert result.blocks[0].confidence == 0.97
    assert result.blocks[1].confidence is None  # 不伪造置信度
    assert result.text.splitlines()[0].startswith("留存")


def test_baidu_ocr_token_cached_and_errors_classified() -> None:
    calls = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth/2.0/token" in str(request.url):
            calls["token"] += 1
            return baidu_token_response()
        return httpx.Response(200, json={"error_code": 111, "error_msg": "token invalid"})

    provider = BaiduOCRProvider(
        api_key="ak", secret_key="sk", client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    )
    with pytest.raises(ProviderError) as first:
        asyncio.run(provider.recognize(png_bytes(), page_number=1))
    assert first.value.code == ProviderErrorCode.AUTH_FAILED
    with pytest.raises(ProviderError):
        asyncio.run(provider.recognize(png_bytes(), page_number=2))
    assert calls["token"] == 1  # token 缓存，不重复取


def test_baidu_ocr_missing_config_refuses() -> None:
    provider = BaiduOCRProvider(api_key="", secret_key="")
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.recognize(png_bytes(), page_number=1))
    assert exc.value.code == ProviderErrorCode.CONFIG_MISSING


def test_vlm_separates_transcript_observation_inference() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            {
                "transcript": ["图内一行字"],
                "observations": ["折线随时间上升"],
                "inferences": ["可能与政策有关"],
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"id": "c1", "choices": [{"message": {"content": content}}]})

    provider = OpenAICompatVLMProvider(
        api_key="vk",
        model="glm-4v",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    result = asyncio.run(provider.analyze(png_bytes(), asset_id="fig-1", question="读图", page_number=2))
    kinds = {o.kind for o in result.observations}
    assert kinds == {"text_in_image", "observation", "inference"}
    assert result.transcribed_text == "图内一行字"
    assert result.inferences and result.inferences[0].text == "可能与政策有关"
    assert result.prompt_version == "v1"


def test_vlm_rejects_bad_config_and_unstructured_output() -> None:
    with pytest.raises(ProviderError) as exc:
        asyncio.run(OpenAICompatVLMProvider(api_key="k", model="m", base_url="http://insecure.example/v1").analyze(png_bytes(), asset_id="a", question="q"))
    assert exc.value.code == ProviderErrorCode.CONFIG_MISSING  # https-only

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "这不是 JSON"}}]})

    provider = OpenAICompatVLMProvider(
        api_key="vk", model="glm-4v", base_url="https://open.bigmodel.cn/api/paas/v4",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.analyze(png_bytes(), asset_id="a", question="q"))
    assert exc.value.code == ProviderErrorCode.INVALID_RESPONSE
