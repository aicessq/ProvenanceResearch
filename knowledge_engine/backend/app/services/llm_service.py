"""LLM 调用封装（chat/completion 走 API）。

Phase 7 开始需要一个统一的大模型调用入口，供 safety_guard / intent_classifier /
query_rewriter 等模块在“规则不足以判断”时扩展使用。

当前实现目标：
- 提供统一配置入口；
- 保持服务层封装边界；
- 在未配置真实 API key 时给出明确异常；
- 不强制当前 Phase 7 主链路依赖真实远程调用。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import get_settings


class LLMServiceError(RuntimeError):
    """LLM 服务异常。"""


@dataclass(slots=True)
class LLMResponse:
    """统一的 LLM 文本响应。"""

    content: str
    model: str


class LLMService:
    """统一的大模型 API 封装。"""

    def __init__(self, *, api_key: str | None, base_url: str | None, model: str = "gpt-5.4") -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @classmethod
    def from_settings(cls) -> "LLMService":
        """从全局配置构造 LLM 服务。"""
        settings = get_settings()
        api_key = getattr(settings, "llm_api_key", None)
        base_url = getattr(settings, "llm_base_url", None)
        return cls(api_key=api_key, base_url=base_url)

    def complete(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """发送一次简化的 chat/completion 请求。"""
        if not self.api_key or not self.base_url:
            raise LLMServiceError("LLM API key 或 base_url 未配置，无法执行远程 LLM 调用")

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001 - 统一转为业务异常
            raise LLMServiceError("远程 LLM 调用失败") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMServiceError("LLM 响应结构不符合预期") from exc
        return LLMResponse(content=str(content), model=self.model)
