"""Source Registry（P3c）：来源登记、去重与发现 provenance。

去重键（docs/design.md §3）：
- 论文：arXiv ID + 版本（可用 DOI），**不同版本不可静默合并**；
- 私库：doc/version/chunk；
- 网页：规范化 URL + 抓取内容 hash。

同一论文被 Tavily 与 arXiv 同时命中时：合并为同一 Source，
但保留两条发现 provenance（discovered_via），不靠改 URL 多次计分。

ProviderRegistry 维护 provider 能力、启用状态、凭证要求、健康与限额。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


class SourceConflictError(ValueError):
    """同 id 登记了不同内容/版本（禁止静默改写）。"""


@dataclass
class Discovery:
    """一次发现记录：谁、用什么查询、何时。"""

    provider: str
    query: str
    discovered_at: str


@dataclass
class Source:
    """登记的来源。id 稳定、内容 hash 与版本不可变。"""

    id: str
    type: str  # kb_chunk / web / paper
    url: str
    hash: str
    version: str
    metadata: dict = field(default_factory=dict)
    discovered_via: list[Discovery] = field(default_factory=list)


_ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)


def normalize_web_url(url: str) -> str:
    """网页 URL 规范化：scheme/host 小写、去 fragment、去默认端口、去尾斜杠。"""
    normalized = url.strip().split("#", 1)[0]
    scheme, sep, rest = normalized.partition("://")
    if not sep:
        return normalized.rstrip("/")
    scheme = scheme.lower()
    host, slash, path = rest.partition("/")
    host = host.lower()
    for default_port in (":443", ":80"):
        if host.endswith(default_port):
            host = host[: -len(default_port)]
            break
    return f"{scheme}://{host}{slash}{path}".rstrip("/")


def extract_arxiv_identity(url: str) -> tuple[str, str] | None:
    """从 URL 抽取 (arxiv_id, version)；无版本信息返回 (id, '')。"""
    match = _ARXIV_ID_RE.search(url)
    if not match:
        return None
    return match.group(1), match.group(2) or ""


class SourceRegistry:
    """来源登记表：同身份只留一份，合并发现 provenance。"""

    def __init__(self) -> None:
        self._by_id: dict[str, Source] = {}
        self._key_to_id: dict[str, str] = {}

    @staticmethod
    def dedup_key(source_type: str, *, url: str = "", content_hash: str = "", version: str = "", metadata: dict | None = None) -> str:
        """按类型生成去重键：论文 arxiv_id+version、KB doc/version/chunk、web 规范 URL+hash。"""
        meta = metadata or {}
        if source_type == "paper":
            arxiv_id = meta.get("arxiv_id") or ""
            arxiv_version = meta.get("arxiv_version") or ""
            if not arxiv_id:
                identity = extract_arxiv_identity(url)
                if identity:
                    arxiv_id, arxiv_version = identity
            return f"paper:{arxiv_id}:{arxiv_version}"
        if source_type == "kb_chunk":
            return f"kb:{meta.get('doc_id')}:{meta.get('doc_version')}:{meta.get('chunk_id')}"
        return f"web:{normalize_web_url(url)}:{content_hash}"

    def register(self, source: Source) -> Source:
        """登记来源；同身份合并发现 provenance，同 id 异内容抛冲突。"""
        key = self.dedup_key(
            source.type,
            url=source.url,
            content_hash=source.hash,
            version=source.version,
            metadata=source.metadata,
        )
        existing_id = self._key_to_id.get(key)
        if existing_id is not None:
            existing = self._by_id[existing_id]
            existing.discovered_via.extend(source.discovered_via)
            return existing

        existing = self._by_id.get(source.id)
        if existing is not None:
            if existing.hash != source.hash or existing.version != source.version:
                raise SourceConflictError(
                    f"source id {source.id!r} 已登记不同内容/版本，禁止静默改写"
                )
            existing.discovered_via.extend(source.discovered_via)
            return existing

        self._by_id[source.id] = source
        self._key_to_id[key] = source.id
        return source

    def get(self, source_id: str) -> Source | None:
        return self._by_id.get(source_id)

    def all(self) -> list[Source]:
        return list(self._by_id.values())


@dataclass
class ProviderStatus:
    """provider 能力/启用/凭证/健康/限额。"""

    name: str
    capabilities: tuple[str, ...]
    enabled: bool = True
    requires_api_key: bool = True
    healthy: bool = True
    rate_limit_per_minute: int | None = None


class ProviderRegistry:
    """provider 注册表：工具执行前查能力与健康，不硬编码到 Agent。"""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderStatus] = {}

    def register(self, status: ProviderStatus) -> None:
        self._providers[status.name] = status

    def get(self, name: str) -> ProviderStatus | None:
        return self._providers.get(name)

    def require_enabled(self, name: str, capability: str) -> ProviderStatus:
        status = self._providers.get(name)
        if status is None:
            raise KeyError(f"未注册 provider: {name}")
        if not status.enabled:
            raise RuntimeError(f"provider 已禁用: {name}")
        if not status.healthy:
            raise RuntimeError(f"provider 不健康: {name}")
        if capability not in status.capabilities:
            raise RuntimeError(f"provider {name} 不具备能力 {capability}")
        return status


def content_hash(text: str) -> str:
    """内容 hash：raw_text 的 sha256（hex）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
