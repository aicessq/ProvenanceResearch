"""模型端点出站防护（SSRF）。

只允许把请求（携带 API key）发往已登记 provider 的官方 HTTPS 主机；
拒绝 localhost / 私网 IP / IP 字面量 / file:// 等任意 URL（P2.5-0.1）。
密钥只发绑定主机、不跨重定向发送，见 docs/decisions.md 2026-09-18。
"""

from __future__ import annotations

import ipaddress

from app.core.errors import EndpointNotAllowedError

# provider → 允许的官方主机名（精确匹配，不做后缀通配）
ALLOWED_PROVIDER_HOSTS: dict[str, tuple[str, ...]] = {
    "deepseek": ("api.deepseek.com",),
    "zhipu": ("open.bigmodel.cn",),
    "kimi": ("api.moonshot.cn",),
    "doubao": ("ark.cn-beijing.volces.com",),
    "ernie": ("aip.baidubce.com",),
    # 2026-10-12 用户核准：阿里云百炼 MaaS 租户端点（精确主机匹配，兄弟租户主机仍拒绝）
    "qwen": ("dashscope.aliyuncs.com", "llm-pbhfa5rmunurn3vb.cn-beijing.maas.aliyuncs.com"),
    "openai": ("api.openai.com",),
    "anthropic": ("api.anthropic.com",),
    # 2026-10-12 用户核准：opencode.ai 网关（会话头 x-opencode-session 由 LLM 适配层注入）
    "opencode": ("opencode.ai",),
}

FORBIDDEN_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "metadata",
        "metadata.google.internal",
    }
)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_model_endpoint(provider: str, api_base: str) -> str:
    """校验 provider 与 api_base，返回规范化 base_url。

    不合法一律抛 EndpointNotAllowedError，且保证发生在任何出站请求之前：
    - provider 必须在允许列表（provider 为空时按主机反查，反查不到即拒绝）；
    - 仅允许 https、禁止 URL userinfo、端口仅 443/默认；
    - 主机必须精确命中该 provider 的官方主机；localhost / 私网 IP / IP 字面量一律拒绝。
    """
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider and normalized_provider not in ALLOWED_PROVIDER_HOSTS:
        raise EndpointNotAllowedError(
            f"非允许 provider: {provider}",
            details={"provider": provider},
        )

    raw = (api_base or "").strip()
    if not raw:
        raise EndpointNotAllowedError("api_base 不能为空", details={"api_base": api_base})

    from urllib.parse import urlsplit

    parts = urlsplit(raw)
    if parts.scheme != "https":
        raise EndpointNotAllowedError(
            f"仅允许 https 端点，拒绝 scheme={parts.scheme or '(空)'}",
            details={"api_base": raw},
        )
    if parts.username or parts.password:
        raise EndpointNotAllowedError(
            "URL 不得包含 userinfo",
            details={"api_base": raw},
        )

    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise EndpointNotAllowedError("api_base 缺少主机名", details={"api_base": raw})
    if host in FORBIDDEN_HOSTNAMES or _is_ip_literal(host):
        raise EndpointNotAllowedError(
            f"禁止指向本机/内网/IP 字面量主机: {host}",
            details={"host": host},
        )
    if parts.port not in (None, 443):
        raise EndpointNotAllowedError(
            f"禁止非标准端口: {parts.port}",
            details={"host": host, "port": parts.port},
        )

    if normalized_provider:
        allowed_hosts = ALLOWED_PROVIDER_HOSTS[normalized_provider]
        if host not in allowed_hosts:
            raise EndpointNotAllowedError(
                f"主机 {host} 不属于 provider {normalized_provider} 的允许列表",
                details={"provider": normalized_provider, "host": host},
            )
    else:
        matched = [name for name, hosts in ALLOWED_PROVIDER_HOSTS.items() if host in hosts]
        if not matched:
            raise EndpointNotAllowedError(
                f"非允许 provider 端点: {host}",
                details={"host": host},
            )

    return f"https://{host}{parts.path.rstrip('/')}"
