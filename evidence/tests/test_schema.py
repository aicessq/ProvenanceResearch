"""Evidence Schema v2 契约（P3c 验收：所有 Evidence 都有 source identity 与 citation id）。"""

from __future__ import annotations

import pytest

from evidence.schema import (
    Evidence,
    EvidenceValidationError,
    Extraction,
    Locator,
    Provenance,
    make_citation_id,
)


def _kb_evidence(**overrides) -> Evidence:
    base = dict(
        citation_id="",
        source_id="kb:doc-1:ver-1",
        source_type="kb_chunk",
        modality="text",
        content_scope="fulltext",
        raw_text="第一条 为了保障网络安全，制定本法。",
        provenance=Provenance(
            provider="knowledge_engine",
            title="网络安全法",
            content_hash="h1",
            doc_id="doc-1",
            doc_title="网络安全法",
            doc_version="ver-1",
            chunk_id="chunk-1",
            index_identity="fake:fake-embedding:8:v0",
        ),
        locator=Locator(page=1, chunk="chunk-1", section="第一章"),
        extraction=Extraction(method="native_text", provider="knowledge_engine"),
    )
    base.update(overrides)
    return Evidence(**base)


def test_kb_evidence_has_source_identity_and_citation_id() -> None:
    ev = _kb_evidence()
    ev = Evidence(**{**ev.__dict__, "citation_id": ev.make_citation_id()})
    ev.validate()
    assert ev.citation_id.startswith("K")
    assert ev.provenance.doc_id == "doc-1"
    assert ev.provenance.doc_version == "ver-1"
    assert ev.provenance.chunk_id == "chunk-1"
    assert ev.provenance.index_identity


def test_kb_evidence_rejects_missing_identity_fields() -> None:
    ev = _kb_evidence(provenance=Provenance(provider="knowledge_engine", content_hash="h1"))
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_web_evidence_requires_url_and_fetched_at() -> None:
    ev = Evidence(
        citation_id="W1",
        source_id="web:https://example.org/a",
        source_type="web",
        modality="text",
        content_scope="snippet",
        raw_text="snippet",
        provenance=Provenance(provider="tavily", content_hash="h"),
        locator=Locator(url="https://example.org/a"),
        extraction=Extraction(method="provider_text"),
    )
    with pytest.raises(EvidenceValidationError):
        ev.validate()

    ok = Evidence(
        citation_id="W1",
        source_id="web:https://example.org/a",
        source_type="web",
        modality="text",
        content_scope="snippet",
        raw_text="snippet",
        provenance=Provenance(provider="tavily", content_hash="h", canonical_url="https://example.org/a", fetched_at="2026-10-10T00:00:00Z"),
        locator=Locator(url="https://example.org/a"),
        extraction=Extraction(method="provider_text"),
    )
    ok.validate()


def test_paper_evidence_requires_arxiv_id_and_version() -> None:
    ev = Evidence(
        citation_id="A1",
        source_id="paper:arxiv:2304.09848:v1",
        source_type="paper",
        modality="text",
        content_scope="abstract",
        raw_text="abstract text",
        provenance=Provenance(provider="arxiv", content_hash="h"),
        locator=Locator(url="http://arxiv.org/abs/2304.09848v1"),
        extraction=Extraction(method="provider_text"),
    )
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_citation_id_prefix_must_match_source_type() -> None:
    ev = _kb_evidence(citation_id="W999")
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_fulltext_scope_rejects_empty_text() -> None:
    """摘要不得冒充全文：fulltext 范围必须有正文。"""
    ev = _kb_evidence(raw_text="   ", content_scope="fulltext")
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_text_modality_requires_raw_text() -> None:
    ev = _kb_evidence(raw_text=None, content_scope="snippet")
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_page_must_start_from_one() -> None:
    ev = _kb_evidence(locator=Locator(page=0, chunk="chunk-1"))
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_bbox_shape_validated_even_when_reserved() -> None:
    """bbox 是 P3b 占位字段，但形状已校验（0-1 四坐标）。"""
    ev = _kb_evidence(locator=Locator(page=1, bbox=(0.1, 0.2, 1.5, 0.4)))
    with pytest.raises(EvidenceValidationError):
        ev.validate()


def test_citation_id_stable_and_content_sensitive() -> None:
    ev = _kb_evidence()
    id_a = make_citation_id("kb_chunk", ev.provenance, ev.locator)
    id_b = make_citation_id("kb_chunk", ev.provenance, ev.locator)
    assert id_a == id_b
    other = Provenance(
        provider="knowledge_engine",
        content_hash="DIFFERENT",
        doc_id="doc-1",
        doc_title="网络安全法",
        doc_version="ver-1",
        chunk_id="chunk-1",
        index_identity="fake:fake-embedding:8:v0",
    )
    assert make_citation_id("kb_chunk", other, ev.locator) != id_a


def test_untrusted_default_true() -> None:
    ev = _kb_evidence()
    assert ev.untrusted is True
    assert ev.schema_version == 2
