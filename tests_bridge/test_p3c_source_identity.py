"""P3c 来源身份验收（tests_bridge）。

roadmap P3c 验收：KB 带 doc/version/chunk/index、Web 带 URL/fetched_at、
论文带 arXiv ID/版本；所有来源输出同构 Evidence；
Question → Evidence[] → Reader input 可走通；全部 fake/recorded，无凭证、不联网。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evidence.store import EvidenceStore  # noqa: E402
from tools import (  # noqa: E402
    ArxivSearchTool,
    KBSearchTool,
    ToolExecutor,
    WebSearchTool,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


KB_PAYLOAD = {
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
        }
    ]
}

TAVILY_PAYLOAD = {
    "results": [{"title": "RFC", "url": "https://example.org/rfc#s", "content": "OAuth text"}]
}

ARXIV_FEED = """<?xml version="1.0"?>
<feed><entry>
  <id>http://arxiv.org/abs/2304.09848v2</id>
  <title>Provenance</title>
  <summary>Abstract text.</summary>
</entry></feed>"""


def test_question_to_evidence_pipeline_carries_source_identity() -> None:
    """Question → Evidence[]：三类来源的证据都有 source identity 与 citation id。"""
    store = EvidenceStore()
    executor = ToolExecutor(
        tools=[
            KBSearchTool(
                base_url="http://kb.internal",
                client=_client(lambda req: httpx.Response(200, json=KB_PAYLOAD)),
                store=store,
                index_identity="fake:fake-embedding:8:v0",
            ),
            WebSearchTool(api_key="k", client=_client(lambda req: httpx.Response(200, json=TAVILY_PAYLOAD)), store=store),
            ArxivSearchTool(client=_client(lambda req: httpx.Response(200, text=ARXIV_FEED)), store=store),
        ]
    )

    question = "比较两版网络安全法与 OAuth 论文的出处"
    results = [
        asyncio.run(executor.execute("kb_search", query=question, top_k=5)),
        asyncio.run(executor.execute("web_search", query=question, top_k=5)),
        asyncio.run(executor.execute("arxiv_search", query=question, top_k=5)),
    ]
    assert all(r.status == "ok" for r in results)

    evidence = [ev for r in results for ev in r.evidence]
    assert len(evidence) == 3

    by_type = {ev.source_type: ev for ev in evidence}

    kb = by_type["kb_chunk"]
    assert kb.provenance.doc_id == "doc-1"
    assert kb.provenance.doc_version == "ver-1"
    assert kb.provenance.chunk_id == "chunk-1"
    assert kb.provenance.index_identity == "fake:fake-embedding:8:v0"

    web = by_type["web"]
    assert web.provenance.canonical_url == "https://example.org/rfc"
    assert web.provenance.fetched_at

    paper = by_type["paper"]
    assert paper.provenance.arxiv_id == "2304.09848"
    assert paper.provenance.arxiv_version == "v2"

    for ev in evidence:
        assert ev.citation_id, "每条 Evidence 必须有 citation_id"
        assert ev.source_id, "每条 Evidence 必须有 source identity"
        assert ev.untrusted is True
        ev.validate()

    # Reader input：稳定 citation_id 可整体解析
    resolved, missing = store.resolve_citations([ev.citation_id for ev in evidence])
    assert len(resolved) == 3
    assert missing == []


def test_sources_output_homomorphic_evidence() -> None:
    """所有来源输出同构 Evidence（同一类型、同一校验规则）。"""
    store = EvidenceStore()
    kb = KBSearchTool(
        base_url="http://kb.internal",
        client=_client(lambda req: httpx.Response(200, json=KB_PAYLOAD)),
        store=store,
        index_identity="idx",
    )
    web = WebSearchTool(api_key="k", client=_client(lambda req: httpx.Response(200, json=TAVILY_PAYLOAD)), store=store)
    arxiv = ArxivSearchTool(client=_client(lambda req: httpx.Response(200, text=ARXIV_FEED)), store=store)

    all_evidence = []
    for tool, args in (
        (kb, {"query": "q"}),
        (web, {"query": "q"}),
        (arxiv, {"query": "q"}),
    ):
        result = asyncio.run(tool.execute("c", **args))
        all_evidence.extend(result.evidence)

    types = {type(ev) for ev in all_evidence}
    assert len(types) == 1  # 同构：不为新来源建第二套答案结构
    for ev in all_evidence:
        assert ev.schema_version == 2
        assert ev.raw_text is not None
