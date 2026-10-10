"""云模型 Provider 统一错误分类（P3a）。

六类错误码是跨 provider 的稳定契约，上层（retry / fallback / refusal）
只依赖错误码决策，不解析各家厂商的错误文本：

    CONFIG_MISSING   缺配置（api_key / base_url / model 未配置），不应重试
    AUTH_FAILED      401/403，不应重试
    RATE_LIMIT       429，可重试
    SERVER_ERROR     5xx / 传输错误，可重试
    TIMEOUT          超时，可重试
    INVALID_RESPONSE 响应结构非法（坏 JSON / 缺字段），不应重试

生产路径不得下载或加载本地权重（AGENTS.md）；本包只做云协议适配。
"""

from __future__ import annotations

from enum import Enum


class ProviderErrorCode(str, Enum):
    CONFIG_MISSING = "CONFIG_MISSING"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMIT = "RATE_LIMIT"
    SERVER_ERROR = "SERVER_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"


RETRYABLE_CODES = frozenset(
    {
        ProviderErrorCode.RATE_LIMIT,
        ProviderErrorCode.SERVER_ERROR,
        ProviderErrorCode.TIMEOUT,
    }
)


class ProviderError(RuntimeError):
    """统一的 provider 异常；携带稳定错误码与是否可重试。"""

    def __init__(self, code: ProviderErrorCode, message: str, *, provider: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.retryable = code in RETRYABLE_CODES


def classify_http_status(status: int) -> ProviderErrorCode:
    """HTTP 状态码 → 错误码。401/403→AUTH_FAILED，429→RATE_LIMIT，
    5xx→SERVER_ERROR，其余（其他 4xx/3xx）→INVALID_RESPONSE。"""
    if status in (401, 403):
        return ProviderErrorCode.AUTH_FAILED
    if status == 429:
        return ProviderErrorCode.RATE_LIMIT
    if status >= 500:
        return ProviderErrorCode.SERVER_ERROR
    return ProviderErrorCode.INVALID_RESPONSE
