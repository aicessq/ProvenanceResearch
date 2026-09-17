"""Phase 8 answer_generator 测试。"""

from __future__ import annotations

from app.services.answer_generator import AnswerGenerator, EvidenceContext, INSUFFICIENT_EVIDENCE_MESSAGE
from app.services.llm_service import LLMServiceError


class FailingLLMService:
    def complete(self, *, system_prompt: str, user_prompt: str):
        raise LLMServiceError("mock llm unavailable")


def test_answer_generator_returns_conservative_answer_when_no_evidence() -> None:
    generator = AnswerGenerator(llm_service=FailingLLMService())

    result = generator.generate(query="网络安全法第一条讲了什么", evidence_contexts=[])

    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert result.citations == []
    assert result.evidence_status == "insufficient"


def test_answer_generator_builds_grounded_answer_from_evidence() -> None:
    generator = AnswerGenerator(llm_service=FailingLLMService())
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
            parent_chunk_id="parent-1",
            parent_text="第一章 总则 第一条 为了保障网络安全，制定本法。",
            score=0.92,
            source="vector",
        ),
        EvidenceContext(
            chunk_id="chunk-2",
            doc_title="网络安全法样例",
            doc_type="law",
            chunk_text="第二条 本法适用于中华人民共和国境内网络安全工作。",
            page_start=2,
            page_end=2,
            chapter="第一章 总则",
            article_no="第二条",
            parent_chunk_id="parent-1",
            parent_text="第一章 总则 第二条 本法适用于中华人民共和国境内网络安全工作。",
            score=0.88,
            source="keyword",
        ),
    ]

    result = generator.generate(query="网络安全法总则讲了什么", evidence_contexts=evidence_contexts)

    assert "基于当前检索到的资料" in result.answer
    assert len(result.citations) == 2
    assert result.citations[0].chunk_id == "chunk-1"
    assert result.citations[0].page_start == 1
    assert result.evidence_status == "grounded"
    assert result.confidence > 0.8
