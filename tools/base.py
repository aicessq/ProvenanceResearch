"""工具契约（docs/design.md §3）。

工具返回 `call_id / status / evidence / meta / error`：
- status: ok / empty / error
- meta: provider、耗时、索引/模型身份、用量与覆盖范围
- error: 脱敏、稳定 code、retryable

工具执行器负责参数白名单校验；模型不能提供任意函数名或任意访问地址。
单源失败不取消健康来源；provider 异常/模拟数据不得当成功证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evidence.schema import Evidence


@dataclass(frozen=True)
class ToolMeta:
    provider: str = ""
    latency_ms: float = 0.0
    index_identity: str = ""     # EmbeddingIdentity.key() 或索引名
    model_identity: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    coverage: str = ""           # 摘要/全文/页范围等覆盖说明


@dataclass(frozen=True)
class ToolError:
    code: str                    # 稳定错误码（如 provider_unavailable / invalid_params）
    message: str                 # 脱敏后的信息
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: str                  # ok / empty / error
    evidence: list[Evidence] = field(default_factory=list)
    meta: ToolMeta = field(default_factory=ToolMeta)
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if self.status not in ("ok", "empty", "error"):
            raise ValueError(f"非法 status: {self.status}")
        if self.status == "error" and self.error is None:
            raise ValueError("status=error 必须携带 error")
        if self.status != "error" and self.error is not None:
            raise ValueError("非 error 状态不得携带 error")


class ToolArgError(ValueError):
    """参数不在白名单/不满足约束。"""


def validate_args(name: str, args: dict[str, Any], allowed: dict[str, type], required: tuple[str, ...] = ()) -> dict[str, Any]:
    """参数白名单校验：未知参数拒绝、必填缺失拒绝、类型不符拒绝。"""
    unknown = set(args) - set(allowed)
    if unknown:
        raise ToolArgError(f"{name} 不接受参数: {sorted(unknown)}")
    missing = [key for key in required if key not in args]
    if missing:
        raise ToolArgError(f"{name} 缺少必填参数: {missing}")
    for key, value in args.items():
        expected = allowed[key]
        if expected is float:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ToolArgError(f"{name}.{key} 应为数字，得到 {type(value).__name__}")
        elif not isinstance(value, expected):
            raise ToolArgError(f"{name}.{key} 应为 {expected.__name__}，得到 {type(value).__name__}")
    return args
