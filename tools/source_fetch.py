"""source_fetch：获取已登记来源的正文（P3c）。

只接受 Source Registry 已登记的来源，可用来源 ID、登记的 URL 或证据 ID；
逐跳 SSRF 校验、大小/MIME 限制（fetch_guard）；
成功获取的正文为 content_scope=fulltext——摘要不得冒充全文，
未成功获取/解析全文时标记缺口（status=error），由上层决定拒答。
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from datetime import datetime, timezone
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from typing import Any

import httpx

from evidence.registry import Source, SourceRegistry, content_hash
from evidence.schema import Evidence, Extraction, Locator, Provenance, Score
from evidence.store import EvidenceStore, register_with_computed_id
from tools.base import ToolError, ToolMeta, ToolResult, validate_args
from tools.fetch_guard import (
    FetchBlockedError,
    FetchPolicy,
    enforce_size,
    validate_content_type,
    validate_fetch_url,
)

ALLOWED_ARGS = {"source_id": str, "content_scope": str}
REQUIRED_ARGS = ("source_id",)


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "nav", "footer", "noscript"):
            self.hidden.append(tag)
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "article") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _text_parts(body: bytes, mime: str) -> list[tuple[int | None, str, str]]:
    if mime == "application/pdf":
        import pymupdf

        with pymupdf.open(stream=body, filetype="pdf") as pdf:
            if pdf.is_encrypted or pdf.page_count > 150:
                raise FetchBlockedError("PDF 加密或页数超过上限")
            pages = [(index, "", page.get_text().strip()) for index, page in enumerate(pdf, 1)]
            return [part for part in pages if part[2]]
    text = body.decode("utf-8", errors="replace")
    if mime == "text/html":
        parser = _PageText()
        parser.feed(text)
        text = "".join(parser.parts)
    paragraphs = [line.strip() for line in re.split(r"\n+", text) if line.strip()]
    return [(None, f"paragraph-{index}", paragraph)
            for index, paragraph in enumerate(paragraphs[:300], 1)]


@dataclass(frozen=True)
class FetchedDocument:
    mime: str
    url: str
    size: int
    parts: list[tuple[int | None, str, str]]


class SourceFetchTool:
    name = "source_fetch"

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        client: httpx.AsyncClient | None = None,
        store: EvidenceStore | None = None,
        policy: FetchPolicy | None = None,
    ) -> None:
        self._registry = registry
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False)
        self._pin_addresses = client is None
        self._store = store or EvidenceStore()
        self._policy = policy or FetchPolicy()
        self._fetched: dict[str, FetchedDocument | ToolError] = {}
        self._fetch_locks: dict[str, asyncio.Lock] = {}

    @property
    def store(self) -> EvidenceStore:
        return self._store

    async def _request_target(self, target: str) -> tuple[str, dict, dict]:
        if not self._pin_addresses:
            return target, {}, {}
        url = httpx.URL(target)
        if url.port not in (None, 80, 443):
            raise FetchBlockedError("仅允许标准 HTTP/HTTPS 端口")
        port = url.port or (443 if url.scheme == "https" else 80)
        try:
            resolved = await asyncio.get_running_loop().getaddrinfo(
                url.host, port, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise FetchBlockedError("无法解析来源主机") from exc
        addresses = [ipaddress.ip_address(entry[4][0]) for entry in resolved]
        if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
            raise FetchBlockedError("来源必须解析到公网地址")
        # Dial the vetted address directly while preserving the original TLS and HTTP host.
        return (str(url.copy_with(host=str(addresses[0]))),
                {"Host": url.netloc.decode("ascii"), "Connection": "close"},
                {"sni_hostname": url.host})

    async def _download(self, url: str) -> tuple[bytes, str, str]:
        target = validate_fetch_url(url)
        for hop in range(self._policy.max_redirects + 1):
            address, headers, extensions = await self._request_target(target)
            async with self._client.stream("GET", address, headers=headers, extensions=extensions) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location or hop == self._policy.max_redirects:
                        raise FetchBlockedError("重定向缺少地址或超过上限")
                    next_target = validate_fetch_url(urljoin(target, location))
                    if urlsplit(target).scheme == "https" and urlsplit(next_target).scheme != "https":
                        raise FetchBlockedError("禁止 HTTPS 重定向降级")
                    target = next_target
                    continue
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                mime = content_type.split(";", 1)[0].strip().lower()
                if mime != "application/pdf":
                    mime = validate_content_type(content_type)
                body = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    enforce_size(len(body) + len(chunk), self._policy)
                    body.extend(chunk)
                return bytes(body), mime, target
        raise FetchBlockedError("重定向超过上限")

    async def _read_document(self, url: str) -> FetchedDocument | ToolError:
        try:
            body, mime, final_url = await self._download(url)
            try:
                parts = await asyncio.to_thread(_text_parts, body, mime)
            except (ImportError, RuntimeError, ValueError) as exc:
                raise FetchBlockedError("文档正文解析失败") from exc
            if not parts:
                raise FetchBlockedError("没有提取到可引用的正文")
        except FetchBlockedError as exc:
            return ToolError("fetch_blocked", str(exc), retryable=False)
        except httpx.HTTPError as exc:
            return ToolError("provider_unavailable", f"获取正文失败: {type(exc).__name__}", retryable=True)
        return FetchedDocument(mime, final_url, len(body), parts)

    async def execute(self, call_id: str, **kwargs: Any) -> ToolResult:
        args = validate_args(self.name, kwargs, ALLOWED_ARGS, REQUIRED_ARGS)
        source_id = args["source_id"]
        content_scope = args.get("content_scope", "fulltext")
        if content_scope not in ("fulltext", "snippet"):
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("invalid_params", f"content_scope 仅支持 fulltext/snippet: {content_scope}"),
                meta=ToolMeta(provider="source_fetch"),
            )
        source = self._registry.get(source_id)
        if source is None and source_id.startswith(("https://", "http://")):
            source = next((item for item in self._registry.all() if item.url == source_id), None)
        elif source is None and (evidence := self._store.get(source_id)) is not None:
            source = self._registry.get(evidence.source_id)
        if source is None:
            # 搜索产出的已登记 Evidence 是可信的来源身份入口，模型仍不能提交任意 URL。
            found = next((ev for ev in self._store.all() if ev.source_id == source_id
                          and ev.source_type in ("web", "paper")), None)
            if found is not None:
                p = found.provenance
                url = p.fulltext_url or p.canonical_url or found.locator.url or ""
                source = self._registry.register(Source(
                    id=source_id, type=found.source_type, url=url, hash=p.content_hash,
                    version=p.arxiv_version or "", metadata={"title": p.title, "arxiv_id": p.arxiv_id,
                                                              "arxiv_version": p.arxiv_version}))
        if source is None:
            return ToolResult(
                call_id=call_id,
                status="error",
                error=ToolError("source_not_registered", f"source_id 未登记: {source_id}"),
                meta=ToolMeta(provider="source_fetch"),
            )

        if source.type == "paper" and "/abs/" in source.url and content_scope == "fulltext":
            return ToolResult(call_id=call_id, status="error", meta=ToolMeta(provider="source_fetch"),
                              error=ToolError("fulltext_unavailable", "论文摘要页面不能冒充正文"))

        started = time.perf_counter()
        try:
            url = str(httpx.URL(validate_fetch_url(source.url)).copy_with(fragment=None))
        except (FetchBlockedError, httpx.InvalidURL, ValueError) as exc:
            return ToolResult(call_id=call_id, status="error",
                              error=ToolError("fetch_blocked", str(exc)),
                              meta=ToolMeta(provider="source_fetch"))
        async with self._fetch_locks.setdefault(url, asyncio.Lock()):
            document = self._fetched.get(url)
            cached = document is not None
            if document is None:
                document = await self._read_document(url)
                self._fetched[url] = document

        error = document if isinstance(document, ToolError) else None
        if error is None and source.type == "paper" and document.mime != "application/pdf" and content_scope == "fulltext":
            error = ToolError("fetch_blocked", "未取得可解析的论文 PDF")
        if error is not None:
            return ToolResult(call_id=call_id, status="error", error=error,
                              meta=ToolMeta(provider="source_fetch", cached=cached))

        final_url = document.url
        provenance = Provenance(
            provider="source_fetch",
            title=source.metadata.get("title", ""),
            canonical_url=final_url,
            fetched_at=source.metadata.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
            arxiv_id=source.metadata.get("arxiv_id"),
            arxiv_version=source.metadata.get("arxiv_version"),
            fulltext_url=final_url if source.type == "paper" else None,
        )
        registered = [
            register_with_computed_id(self._store, Evidence(
                citation_id="", source_id=source.id, source_type=source.type, modality="text",
                content_scope=content_scope, raw_text=text,
                provenance=replace(provenance, content_hash=content_hash(text)),
                locator=Locator(url=final_url, page=page, section=section or None),
                extraction=Extraction(method="native_text", provider="source_fetch"), score=Score(),
            ))
            for page, section, text in document.parts
        ]
        latency = (time.perf_counter() - started) * 1000
        return ToolResult(
            call_id=call_id,
            status="ok",
            evidence=registered,
            meta=ToolMeta(
                provider="source_fetch",
                latency_ms=round(latency, 2),
                usage={"bytes": 0 if cached else document.size},
                cached=cached,
                coverage=content_scope,
            ),
        )
