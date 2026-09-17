"""答案生成服务。

Phase 8 负责把“已检索到的证据”整理成可读答案，
但必须严格遵守“只基于证据回答、证据不足时明确说明不足”的边界。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.services.llm_service import LLMService, LLMServiceError

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "answer_generator.md"
INSUFFICIENT_EVIDENCE_MESSAGE = "当前知识库未检索到明确依据，暂无法给出确定答案。"


@dataclass(slots=True)
class AnswerCitation:
    """答案中的单条引用。"""

    chunk_id: str
    doc_title: str
    page_start: int | None
    page_end: int | None
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    quote: str = ""


@dataclass(slots=True)
class EvidenceContext:
    """面向答案生成的证据上下文。"""

    chunk_id: str
    doc_title: str
    doc_type: str
    chunk_text: str
    page_start: int | None
    page_end: int | None
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    parent_chunk_id: str | None = None
    parent_text: str | None = None
    score: float | None = None
    source: str | None = None


@dataclass(slots=True)
class AnswerGenerationResult:
    """答案生成输出。"""

    answer: str
    citations: list[AnswerCitation] = field(default_factory=list)
    confidence: float = 0.0
    evidence_status: str = "insufficient"
    model_name: str = "deterministic-evidence-summarizer"


class AnswerGenerator:
    """Phase 8 证据约束答案生成器。"""

    def __init__(self, *, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService.from_settings()

    def generate(self, *, query: str, evidence_contexts: list[EvidenceContext]) -> AnswerGenerationResult:
        """基于证据上下文生成结构化答案。"""
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query 不能为空")

        if not evidence_contexts:
            return AnswerGenerationResult(
                answer=INSUFFICIENT_EVIDENCE_MESSAGE,
                citations=[],
                confidence=0.1,
                evidence_status="insufficient",
            )

        try:
            return self._generate_with_llm(query=normalized_query, evidence_contexts=evidence_contexts)
        except LLMServiceError:
            return self._generate_deterministic(query=normalized_query, evidence_contexts=evidence_contexts)

    def _generate_with_llm(self, *, query: str, evidence_contexts: list[EvidenceContext]) -> AnswerGenerationResult:
        """优先尝试真实 LLM 生成；失败时由上层回退。"""
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        user_prompt = self._build_llm_user_prompt(query=query, evidence_contexts=evidence_contexts)
        response = self.llm_service.complete(system_prompt=system_prompt, user_prompt=user_prompt)

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise LLMServiceError("answer_generator 的 LLM 输出不是合法 JSON") from exc

        citations = [self._citation_from_payload(item) for item in payload.get("citations", [])]
        return AnswerGenerationResult(
            answer=str(payload.get("answer") or INSUFFICIENT_EVIDENCE_MESSAGE),
            citations=citations,
            confidence=float(payload.get("confidence", 0.5)),
            evidence_status=str(payload.get("evidence_status") or "partial"),
            model_name=response.model,
        )

    def _generate_deterministic(self, *, query: str, evidence_contexts: list[EvidenceContext]) -> AnswerGenerationResult:
        """在未配置真实 LLM 时，使用可解释的本地保守生成。"""
        top_contexts = evidence_contexts[:3]
        answer_parts = [f"基于当前检索到的资料，关于“{query}”可参考以下证据："]
        citations: list[AnswerCitation] = []

        for index, context in enumerate(top_contexts, start=1):
            snippet = _trim_text(context.chunk_text, limit=120)
            location = _format_location(context)
            answer_parts.append(f"{index}. 《{context.doc_title}》{location}提到：{snippet}")
            citations.append(
                AnswerCitation(
                    chunk_id=context.chunk_id,
                    doc_title=context.doc_title,
                    page_start=context.page_start,
                    page_end=context.page_end,
                    chapter=context.chapter,
                    section=context.section,
                    article_no=context.article_no,
                    quote=snippet,
                )
            )

        if not citations:
            return AnswerGenerationResult(
                answer=INSUFFICIENT_EVIDENCE_MESSAGE,
                citations=[],
                confidence=0.1,
                evidence_status="insufficient",
            )

        answer_parts.append("如果你需要，我可以继续基于这些证据整理成更精炼的法规解读、标准要求归纳或修复建议。")
        evidence_status = "grounded" if len(citations) >= 2 else "partial"
        confidence = 0.82 if evidence_status == "grounded" else 0.62
        return AnswerGenerationResult(
            answer="\n".join(answer_parts),
            citations=citations,
            confidence=confidence,
            evidence_status=evidence_status,
        )

    def _build_llm_user_prompt(self, *, query: str, evidence_contexts: list[EvidenceContext]) -> str:
        """构造给 LLM 的证据输入。"""
        serialized_contexts = []
        for context in evidence_contexts:
            serialized_contexts.append(
                {
                    "chunk_id": context.chunk_id,
                    "doc_title": context.doc_title,
                    "doc_type": context.doc_type,
                    "page_start": context.page_start,
                    "page_end": context.page_end,
                    "chapter": context.chapter,
                    "section": context.section,
                    "article_no": context.article_no,
                    "parent_chunk_id": context.parent_chunk_id,
                    "parent_text": context.parent_text,
                    "chunk_text": context.chunk_text,
                }
            )
        return json.dumps({"query": query, "evidence_contexts": serialized_contexts}, ensure_ascii=False, indent=2)

    def _citation_from_payload(self, payload: dict) -> AnswerCitation:
        """把 LLM JSON 转成引用结构。"""
        return AnswerCitation(
            chunk_id=str(payload.get("chunk_id") or ""),
            doc_title=str(payload.get("doc_title") or ""),
            page_start=_to_int_or_none(payload.get("page_start")),
            page_end=_to_int_or_none(payload.get("page_end")),
            chapter=_to_str_or_none(payload.get("chapter")),
            section=_to_str_or_none(payload.get("section")),
            article_no=_to_str_or_none(payload.get("article_no")),
            quote=str(payload.get("quote") or ""),
        )


def _format_location(context: EvidenceContext) -> str:
    """格式化引用位置。"""
    parts: list[str] = []
    if context.chapter:
        parts.append(context.chapter)
    if context.section:
        parts.append(context.section)
    if context.article_no:
        parts.append(context.article_no)
    if context.page_start is not None:
        if context.page_end is not None and context.page_end != context.page_start:
            parts.append(f"第{context.page_start}-{context.page_end}页")
        else:
            parts.append(f"第{context.page_start}页")
    return f"（{' / '.join(parts)}）" if parts else ""


def _trim_text(value: str, *, limit: int) -> str:
    """截断过长文本，便于回答展示。"""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _to_int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _to_str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
