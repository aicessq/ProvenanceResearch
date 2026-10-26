"""五个工具的行为契约（P3c 验收：Question → Evidence[]，来源身份齐全）。"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from evidence.registry import Discovery, Source, SourceRegistry, content_hash
from evidence.store import EvidenceStore
from tools import (
    ArxivSearchTool,
    EvidenceReadTool,
    KBSearchTool,
    SourceFetchTool,
    ToolExecutor,
    WebSearchTool,
)
from tools.fetch_guard import FetchBlockedError, validate_fetch_url


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


# ---- kb_search ----


def test_kb_search_maps_identity_fields() -> None:
    payload = {
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "score": 0.9,
                "source": "vector",
                "chunk_text": "第一条 为了保障网络安全，制定本法。",
                "document_id": "doc-1",
                "version_id": "ver-1",
                "doc_title": "网络安全法",
                "doc_type": "law",
                "page_start": 1,
                "section": "第一章",
            }
        ]
    }
    tool = KBSearchTool(
        base_url="http://kb.internal",
        client=_client(lambda req: httpx.Response(200, json=payload)),
        index_identity="fake:fake-embedding:8:v0",
    )
    result = asyncio.run(tool.execute("c1", query="网络安全法"))
    assert result.status == "ok"
    ev = result.evidence[0]
    assert ev.source_type == "kb_chunk"
    assert ev.provenance.doc_id == "doc-1"
    assert ev.provenance.doc_version == "ver-1"
    assert ev.provenance.chunk_id == "chunk-1"
    assert ev.provenance.index_identity == "fake:fake-embedding:8:v0"
    assert ev.citation_id.startswith("K")
    assert ev.raw_text


def test_kb_search_failure_is_structured_error_not_fake() -> None:
    def handler(req):
        raise httpx.ConnectError("kb down")

    tool = KBSearchTool(base_url="http://kb.internal", client=_client(handler))
    result = asyncio.run(tool.execute("c1", query="q"))
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "provider_unavailable"
    assert result.error.retryable is True
    assert result.evidence == []


def test_kb_search_empty_when_no_chunks() -> None:
    tool = KBSearchTool(
        base_url="http://kb.internal",
        client=_client(lambda req: httpx.Response(200, json={"chunks": []})),
    )
    assert asyncio.run(tool.execute("c1", query="q")).status == "empty"


# ---- web_search ----


def test_web_search_maps_url_and_fetched_at() -> None:
    payload = {
        "results": [
            {"title": "T", "url": "https://Example.org/a#frag", "content": "text", "published_date": "2026-01-01"}
        ]
    }
    tool = WebSearchTool(api_key="k", client=_client(lambda req: httpx.Response(200, json=payload)))
    result = asyncio.run(tool.execute("c1", query="q"))
    assert result.status == "ok"
    ev = result.evidence[0]
    assert ev.source_type == "web"
    assert ev.provenance.canonical_url == "https://example.org/a"
    assert ev.provenance.fetched_at
    assert ev.citation_id.startswith("W")


def test_web_search_missing_key_is_config_error() -> None:
    tool = WebSearchTool(api_key="", client=_client(lambda req: httpx.Response(200, json={})))
    result = asyncio.run(tool.execute("c1", query="q"))
    assert result.status == "error"
    assert result.error.code == "config_missing"


def test_web_search_failure_returns_error_not_mock() -> None:
    def handler(req):
        raise httpx.ConnectError("tavily down")

    tool = WebSearchTool(api_key="k", client=_client(handler))
    result = asyncio.run(tool.execute("c1", query="q"))
    assert result.status == "error"
    assert "example.com/result" not in str(result)


def test_web_search_rejects_unregistered_provider() -> None:
    tool = WebSearchTool(api_key="k", provider="unknown", client=_client(lambda req: httpx.Response(200)))
    result = asyncio.run(tool.execute("c1", query="q"))
    assert result.error.code == "unsupported_provider"


# ---- arxiv_search ----

ARXIV_FEED = """<?xml version="1.0"?>
<feed>
  <entry>
    <id>http://arxiv.org/abs/2304.09848v1</id>
    <title>The Title</title>
    <summary>  A   provenance  abstract.  </summary>
  </entry>
</feed>"""


def test_arxiv_search_maps_id_version_and_abstract_scope() -> None:
    tool = ArxivSearchTool(client=_client(lambda req: httpx.Response(200, text=ARXIV_FEED)))
    result = asyncio.run(tool.execute("c1", query="provenance"))
    assert result.status == "ok"
    ev = result.evidence[0]
    assert ev.source_type == "paper"
    assert ev.provenance.arxiv_id == "2304.09848"
    assert ev.provenance.arxiv_version == "v1"
    assert ev.content_scope == "abstract"
    assert ev.citation_id.startswith("A")
    assert ev.raw_text == "A provenance abstract."


def test_arxiv_search_throttles_between_requests() -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, text=ARXIV_FEED)

    tool = ArxivSearchTool(client=_client(handler), sleep=fake_sleep, min_interval_seconds=3.0)
    asyncio.run(tool.execute("c1", query="a"))
    asyncio.run(tool.execute("c2", query="b"))
    assert len(calls) == 2
    assert sleeps and sleeps[0] == pytest.approx(3.0, abs=0.1)


def test_arxiv_search_failure_is_structured_error() -> None:
    def handler(req):
        raise httpx.ConnectError("arxiv down")

    tool = ArxivSearchTool(client=_client(handler))
    result = asyncio.run(tool.execute("c1", query="q"))
    assert result.status == "error"
    assert result.error.retryable is True


# ---- source_fetch ----


def _registry_with_source(url: str = "https://example.org/doc") -> SourceRegistry:
    registry = SourceRegistry()
    registry.register(
        Source(
            id="web:example",
            type="web",
            url=url,
            hash=content_hash("x"),
            version="1",
            metadata={"title": "Doc", "fetched_at": "2026-10-10T00:00:00Z"},
            discovered_via=[Discovery(provider="tavily", query="q", discovered_at="t")],
        )
    )
    return registry


def test_source_fetch_fulltext_only_after_successful_fetch() -> None:
    tool = SourceFetchTool(
        registry=_registry_with_source(),
        client=_client(lambda req: httpx.Response(200, text="全文内容", headers={"content-type": "text/html"})),
    )
    result = asyncio.run(tool.execute("c1", source_id="web:example"))
    assert result.status == "ok"
    ev = result.evidence[0]
    assert ev.content_scope == "fulltext"
    assert ev.raw_text == "全文内容"


def test_source_fetch_refuses_unregistered_source() -> None:
    tool = SourceFetchTool(registry=_registry_with_source(), client=_client(lambda req: httpx.Response(200, text="x")))
    result = asyncio.run(tool.execute("c1", source_id="web:not-registered"))
    assert result.error.code == "source_not_registered"


def test_source_fetch_blocks_redirect_to_private_host() -> None:
    def handler(req):
        return httpx.Response(302, headers={"location": "https://10.0.0.5/steal"})

    tool = SourceFetchTool(registry=_registry_with_source(), client=_client(handler))
    result = asyncio.run(tool.execute("c1", source_id="web:example"))
    assert result.status == "error"
    assert result.error.code == "fetch_blocked"


def test_source_fetch_enforces_size_limit() -> None:
    from tools.fetch_guard import FetchPolicy

    tool = SourceFetchTool(
        registry=_registry_with_source(),
        client=_client(lambda req: httpx.Response(200, text="x" * 100, headers={"content-type": "text/plain"})),
        policy=FetchPolicy(max_bytes=10),
    )
    result = asyncio.run(tool.execute("c1", source_id="web:example"))
    assert result.error.code == "fetch_blocked"


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/a",
        "https://127.0.0.1/a",
        "https://192.168.1.1/a",
        "file:///etc/passwd",
        "https://api.deepseek.com@evil.example.com/a",
    ],
)
def test_fetch_url_guard_blocks_ssrf_targets(url: str) -> None:
    with pytest.raises(FetchBlockedError):
        validate_fetch_url(url)


# ---- evidence_read ----


def test_evidence_read_returns_registered_evidence_only() -> None:
    store = EvidenceStore()
    kb = KBSearchTool(
        base_url="http://kb.internal",
        client=_client(
            lambda req: httpx.Response(
                200,
                json={
                    "chunks": [
                        {
                            "chunk_id": "chunk-1",
                            "score": 0.9,
                            "source": "vector",
                            "chunk_text": "正文",
                            "document_id": "doc-1",
                            "version_id": "ver-1",
                            "doc_title": "T",
                            "doc_type": "law",
                            "page_start": 3,
                        }
                    ]
                },
            )
        ),
        store=store,
        index_identity="idx",
    )
    created = asyncio.run(kb.execute("c1", query="q")).evidence[0]

    tool = EvidenceReadTool(store=store)
    ok = asyncio.run(tool.execute("c2", evidence_id=created.citation_id, page=3))
    assert ok.status == "ok"
    assert ok.evidence[0].raw_text == "正文"

    wrong_page = asyncio.run(tool.execute("c3", evidence_id=created.citation_id, page=9))
    assert wrong_page.error.code == "page_mismatch"

    missing = asyncio.run(tool.execute("c4", evidence_id="Knope"))
    assert missing.error.code == "evidence_not_registered"


# ---- 执行器 ----


def test_executor_rejects_unknown_tool_name() -> None:
    executor = ToolExecutor(tools=[])
    result = asyncio.run(executor.execute("rm -rf /"))
    assert result.error.code == "tool_not_allowed"


def test_executor_isolates_tool_crash() -> None:
    class Boom:
        name = "boom"

        async def execute(self, call_id, **kwargs):
            raise RuntimeError("crash")

    class Fine:
        name = "fine"

        async def execute(self, call_id, **kwargs):
            from tools.base import ToolResult

            return ToolResult(call_id=call_id, status="empty")

    executor = ToolExecutor(tools=[Boom(), Fine()])
    bad = asyncio.run(executor.execute("boom"))
    assert bad.error.code == "tool_crashed"
    good = asyncio.run(executor.execute("fine"))
    assert good.status == "empty"


def test_executor_rejects_unknown_args() -> None:
    tool = WebSearchTool(api_key="k", client=_client(lambda req: httpx.Response(200, json={"results": []})))
    executor = ToolExecutor(tools=[tool])
    result = asyncio.run(executor.execute("web_search", query="q", evil_arg="x"))
    assert result.error.code == "invalid_params"


def test_kb_search_preserves_server_index_identity_and_rejects_mismatch():
    payload = {"chunks": [{"chunk_id": "chunk-1", "score": 0.8, "chunk_text": "Access review every ninety days.",
        "document_id": "doc-1", "version_id": "v1", "doc_title": "Policy", "index_identity": "bge:768:revision"}]}
    for pinned in ("", "bge:768:revision", "other-index"):
        tool = KBSearchTool(base_url="http://kb.internal",index_identity=pinned,
            client=_client(lambda req: httpx.Response(200,json=payload)))
        result = asyncio.run(tool.execute("c-local",query="Access review"))
        if pinned == "other-index":
            assert result.status == "error" and result.error.code == "index_identity_mismatch"
        else:
            assert result.status == "ok"
            assert result.evidence[0].provenance.index_identity == "bge:768:revision"
            assert result.meta.index_identity == "bge:768:revision"


def test_kb_search_missing_or_mixed_identity_fails_without_registering_evidence():
    item = {"chunk_id":"c1","document_id":"d1","version_id":"v1","chunk_text":"policy"}
    for chunks, code in [([item],"invalid_response"),
        ([{**item,"index_identity":"old"},{**item,"chunk_id":"c2","index_identity":"new"}],"index_identity_mismatch")]:
        tool=KBSearchTool(base_url="http://kb.internal",client=_client(lambda req:httpx.Response(200,json={"chunks":chunks})))
        result=asyncio.run(tool.execute("identity-check",query="policy"))
        assert result.status=="error" and result.error.code==code
        assert result.evidence==[]
        assert tool.store.all()==[]
