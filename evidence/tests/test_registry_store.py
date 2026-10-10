"""Source Registry 与 EvidenceStore 契约（去重、发现 provenance、引用冲突）。"""

from __future__ import annotations

import pytest

from evidence.registry import (
    Discovery,
    ProviderRegistry,
    ProviderStatus,
    Source,
    SourceConflictError,
    SourceRegistry,
    content_hash,
    extract_arxiv_identity,
    normalize_web_url,
)
from evidence.store import (
    CitationConflictError,
    EvidenceStore,
    register_with_computed_id,
)
from evidence.schema import Evidence, Extraction, Locator, Provenance


def _web_source(url: str, *, sid: str = "web:1", text: str = "t") -> Source:
    return Source(
        id=sid,
        type="web",
        url=url,
        hash=content_hash(text),
        version="1",
        metadata={"title": "T"},
        discovered_via=[Discovery(provider="tavily", query="q", discovered_at="2026-10-10T00:00:00Z")],
    )


def test_normalize_web_url_strips_fragment_and_case() -> None:
    assert normalize_web_url("HTTPS://Example.ORG/Path/#frag") == "https://example.org/Path"
    assert normalize_web_url("https://example.org") == "https://example.org"


def test_extract_arxiv_identity_with_and_without_version() -> None:
    assert extract_arxiv_identity("http://arxiv.org/abs/2304.09848v1") == ("2304.09848", "v1")
    assert extract_arxiv_identity("https://arxiv.org/pdf/2304.09848v2.pdf") == ("2304.09848", "v2")
    assert extract_arxiv_identity("https://example.org/x") is None


def test_same_paper_via_two_channels_merges_but_keeps_discovery() -> None:
    """Tavily 与 arXiv 同时命中同一论文：合并为同一 Source，保留两条发现 provenance。"""
    registry = SourceRegistry()
    from_tavily = Source(
        id="web:arxiv-abs",
        type="paper",
        url="http://arxiv.org/abs/2304.09848v1",
        hash="h",
        version="v1",
        metadata={"arxiv_id": "2304.09848", "arxiv_version": "v1"},
        discovered_via=[Discovery(provider="tavily", query="q1", discovered_at="t1")],
    )
    from_arxiv = Source(
        id="paper:arxiv:2304.09848:v1",
        type="paper",
        url="http://arxiv.org/abs/2304.09848v1",
        hash="h",
        version="v1",
        metadata={"arxiv_id": "2304.09848", "arxiv_version": "v1"},
        discovered_via=[Discovery(provider="arxiv", query="q2", discovered_at="t2")],
    )
    merged = registry.register(from_tavily)
    same = registry.register(from_arxiv)
    assert same is merged
    assert len(merged.discovered_via) == 2
    assert {d.provider for d in merged.discovered_via} == {"tavily", "arxiv"}
    assert len(registry.all()) == 1


def test_different_paper_versions_never_merge() -> None:
    registry = SourceRegistry()
    v1 = Source(
        id="paper:arxiv:2304.09848:v1",
        type="paper",
        url="http://arxiv.org/abs/2304.09848v1",
        hash="h1",
        version="v1",
        metadata={"arxiv_id": "2304.09848", "arxiv_version": "v1"},
    )
    v2 = Source(
        id="paper:arxiv:2304.09848:v2",
        type="paper",
        url="http://arxiv.org/abs/2304.09848v2",
        hash="h2",
        version="v2",
        metadata={"arxiv_id": "2304.09848", "arxiv_version": "v2"},
    )
    registry.register(v1)
    registry.register(v2)
    assert len(registry.all()) == 2


def test_same_id_with_different_content_raises_conflict() -> None:
    registry = SourceRegistry()
    registry.register(_web_source("https://example.org/a", text="t1"))
    with pytest.raises(SourceConflictError):
        registry.register(_web_source("https://example.org/a", sid="web:1", text="t2"))


def test_provider_registry_gates_capability_and_health() -> None:
    providers = ProviderRegistry()
    providers.register(ProviderStatus(name="tavily", capabilities=("web_search",), requires_api_key=True))
    assert providers.require_enabled("tavily", "web_search").name == "tavily"
    with pytest.raises(RuntimeError):
        providers.require_enabled("tavily", "kb_search")
    with pytest.raises(KeyError):
        providers.require_enabled("nope", "web_search")
    providers.register(ProviderStatus(name="arxiv", capabilities=("paper_search",), requires_api_key=False, healthy=False))
    with pytest.raises(RuntimeError):
        providers.require_enabled("arxiv", "paper_search")


def _evidence(text: str = "内容", *, cid: str = "") -> Evidence:
    prov = Provenance(
        provider="knowledge_engine",
        content_hash=content_hash(text),
        doc_id="doc-1",
        doc_version="ver-1",
        chunk_id="chunk-1",
        index_identity="idx",
    )
    return Evidence(
        citation_id=cid,
        source_id="kb:doc-1:ver-1",
        source_type="kb_chunk",
        modality="text",
        content_scope="fulltext",
        raw_text=text,
        provenance=prov,
        locator=Locator(page=1, chunk="chunk-1"),
        extraction=Extraction(method="native_text"),
    )


def test_store_register_computes_and_verifies_citation_id() -> None:
    store = EvidenceStore()
    registered = register_with_computed_id(store, _evidence())
    assert registered.citation_id.startswith("K")
    assert store.require(registered.citation_id).raw_text == "内容"


def test_store_rejects_forged_citation_id() -> None:
    store = EvidenceStore()
    with pytest.raises(CitationConflictError):
        store.register(_evidence(cid="KFORGED"))


def test_store_rejects_same_citation_different_content() -> None:
    store = EvidenceStore()
    first = register_with_computed_id(store, _evidence("内容A"))
    forged = Evidence(
        citation_id=first.citation_id,
        source_id="kb:doc-1:ver-1",
        source_type="kb_chunk",
        modality="text",
        content_scope="fulltext",
        raw_text="内容B",
        provenance=Provenance(
            provider="knowledge_engine",
            content_hash=content_hash("内容B"),
            doc_id="doc-1",
            doc_version="ver-1",
            chunk_id="chunk-1",
            index_identity="idx",
        ),
        locator=Locator(page=1, chunk="chunk-1"),
        extraction=Extraction(method="native_text"),
    )
    with pytest.raises(CitationConflictError):
        store.register(forged)


def test_store_resolve_citations_reports_missing() -> None:
    store = EvidenceStore()
    registered = register_with_computed_id(store, _evidence())
    resolved, missing = store.resolve_citations([registered.citation_id, "Kmissing"])
    assert len(resolved) == 1
    assert missing == ["Kmissing"]
