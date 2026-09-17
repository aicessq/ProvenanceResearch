"""Phase 8 citation_checker 测试。"""

from __future__ import annotations

from app.services.answer_generator import AnswerCitation, AnswerGenerationResult, EvidenceContext
from app.services.citation_checker import CitationChecker


def test_citation_checker_passes_when_all_citations_match_evidence() -> None:
    checker = CitationChecker()
    evidence_contexts = [
        EvidenceContext(
            chunk_id="chunk-1",
            doc_title="网络安全法样例",
            doc_type="law",
            chunk_text="第一条 为了保障网络安全，制定本法。",
            page_start=1,
            page_end=1,
            chapter="第一章 总则",
            article_no="第一条",
        )
    ]
    generated = AnswerGenerationResult(
        answer="根据《网络安全法样例》第一章总则第一条，可知该法用于保障网络安全。",
        citations=[
            AnswerCitation(
                chunk_id="chunk-1",
                doc_title="网络安全法样例",
                page_start=1,
                page_end=1,
                chapter="第一章 总则",
                article_no="第一条",
                quote="第一条 为了保障网络安全，制定本法。",
            )
        ],
        confidence=0.85,
        evidence_status="grounded",
    )

    result = checker.check(generated=generated, evidence_contexts=evidence_contexts)

    assert result.passed is True
    assert result.unsupported_claims == []
    assert result.fixed_answer == generated.answer
    assert result.answer_status == "grounded"


def test_citation_checker_rejects_nonexistent_or_mismatched_citations() -> None:
    checker = CitationChecker()
    evidence_contexts = [
        EvidenceContext(
            chunk_id="chunk-1",
            doc_title="网络安全法样例",
            doc_type="law",
            chunk_text="第一条 为了保障网络安全，制定本法。",
            page_start=1,
            page_end=1,
            chapter="第一章 总则",
            article_no="第一条",
        )
    ]
    generated = AnswerGenerationResult(
        answer="某结论引用了不存在的证据。",
        citations=[
            AnswerCitation(
                chunk_id="chunk-404",
                doc_title="网络安全法样例",
                page_start=99,
                page_end=99,
                quote="不存在的内容",
            )
        ],
        confidence=0.9,
        evidence_status="grounded",
    )

    result = checker.check(generated=generated, evidence_contexts=evidence_contexts)

    assert result.passed is False
    assert result.citations == []
    assert result.answer_status == "insufficient"
    assert result.unsupported_claims
    assert "未检索到明确依据" in result.fixed_answer
