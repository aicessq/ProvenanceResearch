"""远程内容获取防护（逐跳 SSRF，design.md §3/§7）。

限制：仅 HTTP(S)、大小上限、MIME 白名单、重定向上限；
每一跳都重新校验主机（拒绝 localhost / 私网 IP / IP 字面量 / userinfo）；
不把凭证发往非绑定 host。检索内容是不可信数据，不得提升成系统指令。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_REDIRECTS = 3
MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2MB
ALLOWED_MIME_PREFIXES = ("text/", "application/json", "application/xml")

FORBIDDEN_HOSTNAMES = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "metadata", "metadata.google.internal"}
)


class FetchBlockedError(ValueError):
    """目标不满足获取策略（SSRF/大小/MIME/重定向）。"""


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validate_fetch_url(url: str) -> str:
    """单跳 URL 校验：http(s)、无 userinfo、非内网/本机/IP 字面量。"""
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise FetchBlockedError(f"仅允许 http/https: {parts.scheme or '(空)'}")
    if parts.username or parts.password:
        raise FetchBlockedError("URL 不得包含 userinfo")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise FetchBlockedError("URL 缺少主机名")
    if host in FORBIDDEN_HOSTNAMES or _is_ip_literal(host):
        raise FetchBlockedError(f"禁止指向本机/内网/IP 字面量主机: {host}")
    return raw


def validate_content_type(content_type: str) -> str:
    """MIME 白名单（参数部分忽略）。"""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if not any(mime.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise FetchBlockedError(f"不允许的 MIME 类型: {mime or '(空)'}")
    return mime


@dataclass(frozen=True)
class FetchPolicy:
    max_redirects: int = MAX_REDIRECTS
    max_bytes: int = MAX_CONTENT_BYTES


def enforce_size(size: int, policy: FetchPolicy) -> None:
    if size > policy.max_bytes:
        raise FetchBlockedError(f"内容超过大小上限 {policy.max_bytes}B（实际 {size}B）")
