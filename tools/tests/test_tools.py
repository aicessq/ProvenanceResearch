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


def test_arxiv_query_params_prefer_id_then_title_then_all() -> None:
    """查询侧定位（2026-10-12 F2）：编号→id_list（含独立版本标记）、标题→ti 短语、否则 all: 全文。"""
    from tools.arxiv_search import build_search_params

    p = build_search_params("BERT 论文（arXiv 1810.04805）的全称是什么？", 5)
    assert p == {"id_list": "1810.04805", "max_results": 5}
    p2 = build_search_params("arXiv 2304.09848 的 v1 与 v2 差异？", 3)
    assert p2 == {"id_list": "2304.09848v1,2304.09848v2", "max_results": 3}
    assert build_search_params("2304.09848 v1", 1)["id_list"] == "2304.09848v1"
    assert build_search_params("2304.09848v1 and v2", 2)["id_list"] == "2304.09848v1,2304.09848v2"
    assert build_search_params("2304.09848v1 and 1810.04805", 2)["id_list"] == "2304.09848v1,1810.04805"
    p3 = build_search_params("《Attention Is All You Need》提出了什么？", 5)
    assert p3 == {"search_query": 'ti:"Attention Is All You Need"', "max_results": 5}
    p4 = build_search_params("什么是注意力机制", 5)
    assert p4 == {"search_query": "all:什么是注意力机制", "max_results": 5}


def test_arxiv_search_sends_id_list_for_numbered_query() -> None:
    seen: dict = {}

    def handler(req):
        seen.update(req.url.params)
        return httpx.Response(200, text=ARXIV_FEED)

    tool = ArxivSearchTool(client=_client(handler))
    result = asyncio.run(tool.execute("c1", query="BERT 论文（arXiv 1810.04805）的全称"))
    assert result.status == "ok"
    assert seen.get("id_list") == "1810.04805"


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

def test_registered_paper_versions_keep_text_and_page_identity_after_fetch():
    import pymupdf

    def make_pdf(label):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), label + " first page")
            pdf.new_page().insert_text((72, 72), label + " second page")
            return pdf.tobytes()

    entry = ARXIV_FEED.split("<feed>")[1].split("</feed>")[0]
    feed = ARXIV_FEED.replace("</feed>", entry.replace("2304.09848v1", "2304.09848v2") + "</feed>")
    pdfs = {version: make_pdf(version) for version in ("v1", "v2")}
    downloads = []

    def handler(req):
        if req.url.host == "export.arxiv.org":
            return httpx.Response(200, text=feed)
        downloads.append(req.url.path)
        version = req.url.path[-2:]
        return httpx.Response(200, content=pdfs[version], headers={"content-type": "application/pdf"})

    async def scenario():
        registry, store = SourceRegistry(), EvidenceStore()
        async with _client(handler) as client:
            executor = ToolExecutor([
                ArxivSearchTool(client=client, store=store),
                SourceFetchTool(registry=registry, client=client, store=store),
                EvidenceReadTool(store=store),
            ], registry=registry)
            search = await executor.execute("arxiv_search", query="2304.09848 v1 v2")
            assert len(search.evidence) == 2
            for version, abstract in zip(("v1", "v2"), search.evidence):
                fetched = await executor.execute("source_fetch", source_id=abstract.citation_id)
                assert [ev.locator.page for ev in fetched.evidence] == [1, 2]
                cached = await executor.execute("source_fetch", source_id=abstract.source_id)
                assert cached.meta.cached
                read = await executor.execute("evidence_read", source_id=abstract.source_id, page=2)
                assert read.evidence[0].raw_text == version + " second page"
                assert read.evidence[0].provenance.arxiv_version == version
                assert read.evidence[0].content_scope == "fulltext"
            blocked = await executor.execute("source_fetch", source_id="https://arxiv.org/abs/2304.09848v3")
            assert blocked.error.code == "source_not_registered"
            assert downloads == ["/pdf/2304.09848v1", "/pdf/2304.09848v2"]
            assert len({ev.citation_id for ev in store.all()}) == 6

    asyncio.run(scenario())


def test_failed_paper_parse_keeps_only_registered_abstract():
    def handler(req):
        if req.url.host == "export.arxiv.org":
            return httpx.Response(200, text=ARXIV_FEED)
        return httpx.Response(200, content=b"not a pdf", headers={"content-type": "application/pdf"})

    async def scenario():
        registry, store = SourceRegistry(), EvidenceStore()
        async with _client(handler) as client:
            executor = ToolExecutor([
                ArxivSearchTool(client=client, store=store),
                SourceFetchTool(registry=registry, client=client, store=store),
            ], registry=registry)
            search = await executor.execute("arxiv_search", query="2304.09848 v1")
            fetched = await executor.execute("source_fetch", source_id=search.evidence[0].source_id)
            assert fetched.status == "error"
            assert fetched.error.code == "fetch_blocked"
            assert store.all() == search.evidence
            assert store.all()[0].content_scope == "abstract"

    asyncio.run(scenario())


@pytest.mark.parametrize("available", [True, False])
def test_same_address_reuses_fetch_without_collapsing_source_identity(available):
    import pymupdf

    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Paper version two.")
        body = pdf.tobytes()

    async def scenario():
        url = "https://arxiv.org/pdf/2304.09848v2"
        registry = _registry_with_source(url)
        registry.register(Source(
            id="paper:arxiv:2304.09848:v2", type="paper", url=url + "#page=1",
            hash=content_hash(url), version="v2",
            metadata={"arxiv_id": "2304.09848", "arxiv_version": "v2"},
        ))
        calls = []

        async def handler(request):
            calls.append(request.url)
            await asyncio.sleep(0)
            if not available:
                return httpx.Response(503)
            return httpx.Response(200, content=body, headers={"content-type": "application/pdf"})

        async with _client(handler) as client:
            tool = SourceFetchTool(registry=registry, client=client)
            web, paper = await asyncio.gather(
                tool.execute("web", source_id="web:example"),
                tool.execute("paper", source_id="paper:arxiv:2304.09848:v2"),
            )
        assert len(calls) == 1
        assert sum(item.meta.cached for item in (web, paper)) == 1
        if available:
            assert web.evidence[0].source_type == "web"
            assert paper.evidence[0].provenance.arxiv_version == "v2"
            assert paper.evidence[0].locator.page == 1
            assert web.evidence[0].citation_id != paper.evidence[0].citation_id
        else:
            assert web.error.code == paper.error.code == "provider_unavailable"

    asyncio.run(scenario())


def test_source_fetch_resolves_only_exact_task_registered_urls():
    registry = _registry_with_source("https://example.org/registered")
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text="<p>Registered source text</p>",
                              headers={"content-type": "text/html"})

    async def scenario():
        async with _client(handler) as client:
            tool = SourceFetchTool(registry=registry, client=client)
            fetched = await tool.execute("known", source_id="https://example.org/registered")
            blocked = await tool.execute("unknown", source_id="https://example.org/unregistered")
        assert fetched.evidence[0].source_id == "web:example"
        assert fetched.evidence[0].raw_text == "Registered source text"
        assert blocked.error.code == "source_not_registered"
        assert requests == ["https://example.org/registered"]

    asyncio.run(scenario())
