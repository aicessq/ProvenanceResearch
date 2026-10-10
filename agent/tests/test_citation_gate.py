"""Citation Gate v1 契约（四步验证 + 全角归一化）。"""

from __future__ import annotations

import asyncio

from agent.citation_gate import CitationGate, Claim, normalize_text, parse_claims
from evidence.store import EvidenceStore, register_with_computed_id
from evidence.schema import Evidence, Extraction, Locator, Provenance


class YesChecker:
    async def check(self, claim, evidence):
        return True


class NoChecker:
    async def check(self, claim, evidence):
        return False


def _register(store: EvidenceStore, text: str, scope: str = "fulltext") -> str:
    prov = Provenance(
        provider="knowledge_engine",
        content_hash=text,
        doc_id="doc-1",
        doc_version="ver-1",
        chunk_id="chunk-1",
        index_identity="idx",
    )
    ev = Evidence(
        citation_id="",
        source_id="kb:doc-1:ver-1",
        source_type="kb_chunk",
        modality="text",
        content_scope=scope,
        raw_text=text,
        provenance=prov,
        locator=Locator(page=1),
        extraction=Extraction(method="native_text"),
    )
    return register_with_computed_id(store, ev).citation_id


def test_parse_claims_requires_citations() -> None:
    claims = parse_claims('{"claims": [{"claim": "x", "citations": ["K1"]}]}')
    assert claims[0].citations == ("K1",)
    try:
        parse_claims('{"claims": [{"claim": "x", "citations": []}]}')
        raise AssertionError("空引用必须拒绝")
    except ValueError:
        pass


def test_gate_rejects_unregistered_citation() -> None:
    gate = CitationGate(semantic_checker=YesChecker())
    store = EvidenceStore()
    report = asyncio.run(gate.verify([Claim("结论", ("Kmissing",))], store))
    assert not report.passed
    assert "未登记" in report.failed_claims[0].reason


def test_gate_scope_must_cover_claim() -> None:
    gate = CitationGate(semantic_checker=YesChecker())
    store = EvidenceStore()
    cid = _register(store, "摘要内容", scope="abstract")
    # fulltext claim 挂 abstract 证据 → scope 不足
    report = asyncio.run(gate.verify([Claim("结论 2026", (cid,), scope="fulltext")], store))
    assert not report.passed
    # abstract claim 可被 abstract 证据支撑（若无数字/专名问题）
    report2 = asyncio.run(gate.verify([Claim("结论", (cid,), scope="abstract")], store))
    assert report2.passed


def test_gate_numbers_must_exist_with_fullwidth_normalization() -> None:
    gate = CitationGate(semantic_checker=YesChecker())
    store = EvidenceStore()
    cid = _register(store, "施行日期为２０２１年９月１日")  # 全角数字
    # claim 用半角 → 归一化后命中
    report = asyncio.run(gate.verify([Claim("自 2021 年施行", (cid,))], store))
    assert report.passed, report.failed_claims
    # claim 数字不在原文 → 拒
    report2 = asyncio.run(gate.verify([Claim("自 2099 年施行", (cid,))], store))
    assert not report2.passed


def test_gate_proper_nouns_in_quotes_must_exist() -> None:
    gate = CitationGate(semantic_checker=YesChecker())
    store = EvidenceStore()
    cid = _register(store, "本法适用于关键信息基础设施。")
    report = asyncio.run(gate.verify([Claim('保护"关键信息基础设施"', (cid,))], store))
    assert report.passed
    report2 = asyncio.run(gate.verify([Claim('保护"量子计算机"', (cid,))], store))
    assert not report2.passed


def test_gate_semantic_failure_rejects() -> None:
    gate = CitationGate(semantic_checker=NoChecker())
    store = EvidenceStore()
    cid = _register(store, "原文")
    report = asyncio.run(gate.verify([Claim("原文说了", (cid,), scope="snippet")], store))
    assert not report.passed
    assert "语义" in report.failed_claims[0].reason


def test_normalize_text_maps_fullwidth() -> None:
    assert normalize_text("２０２１　Ａ") == "2021 A"
