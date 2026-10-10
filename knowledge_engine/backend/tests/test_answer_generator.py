"""Phase 8 answer_generator 测试。"""

from __future__ import annotations

import json

import pytest

from app.services.answer_generator import AnswerGenerator, EvidenceContext, INSUFFICIENT_EVIDENCE_MESSAGE
from app.services.llm_service import LLMServiceError, LLMResponse, ProviderUnavailableError


class FailingLLMService:
    def complete(self, *, system_prompt: str, user_prompt: str):
        raise LLMServiceError("mock llm unavailable")


class StubLLMService:
    """返回合法 JSON 的 LLM stub，用于覆盖真实生成路径。"""

    def __init__(self, content: str) -> None:
        self._content = content

    def complete(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return LLMResponse(content=self._content, model="stub-model")


def _evidence() -> list[EvidenceContext]:
    return [
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
    ]


def test_answer_generator_returns_conservative_answer_when_no_evidence() -> None:
    generator = AnswerGenerator(llm_service=FailingLLMService())

    result = generator.generate(query="网络安全法第一条讲了什么", evidence_contexts=[])

    assert result.answer == INSUFFICIENT_EVIDENCE_MESSAGE
    assert result.citations == []
    assert result.evidence_status == "insufficient"


def test_answer_generator_raises_provider_unavailable_when_llm_fails() -> None:
    """P2.5-0.2：LLM 失败不得回退本地抽取答案，必须显式抛 ProviderUnavailableError。"""
    generator = AnswerGenerator(llm_service=FailingLLMService())

    with pytest.raises(ProviderUnavailableError):
        generator.generate(query="网络安全法总则讲了什么", evidence_contexts=_evidence())


def test_answer_generator_builds_grounded_answer_from_llm() -> None:
    payload = {
        "answer": "为了保障网络安全而制定本法。",
        "citations": [
            {
                "chunk_id": "chunk-1",
                "doc_title": "网络安全法样例",
                "page_start": 1,
                "page_end": 1,
                "chapter": "第一章 总则",
                "article_no": "第一条",
                "quote": "第一条 为了保障网络安全，制定本法。",
            }
        ],
        "confidence": 0.9,
        "evidence_status": "grounded",
    }
    generator = AnswerGenerator(llm_service=StubLLMService(json.dumps(payload, ensure_ascii=False)))

    result = generator.generate(query="网络安全法总则讲了什么", evidence_contexts=_evidence())

    assert "为了保障网络安全" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == "chunk-1"
    assert result.citations[0].page_start == 1
    assert result.evidence_status == "grounded"
    assert result.model_name == "stub-model"


def test_answer_generator_raises_provider_unavailable_on_malformed_llm_output() -> None:
    """LLM 返回非 JSON 也属于 provider 不可用，不得伪装成功。"""
    generator = AnswerGenerator(llm_service=StubLLMService("not-json"))

    with pytest.raises(ProviderUnavailableError):
        generator.generate(query="任意问题", evidence_contexts=_evidence())
