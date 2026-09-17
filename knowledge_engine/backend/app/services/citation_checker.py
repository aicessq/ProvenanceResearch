"""引用校验服务。

Phase 8 中，answer_generator 的输出不能直接裸返回；
必须经过 citation_checker 对引用存在性和元数据一致性做最低限度校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from app.services.answer_generator import AnswerCitation, AnswerGenerationResult, EvidenceContext, INSUFFICIENT_EVIDENCE_MESSAGE

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "citation_checker.md"


@dataclass(slots=True)
class CitationCheckResult:
    """引用校验输出。"""

    passed: bool
    unsupported_claims: list[str] = field(default_factory=list)
    fixed_answer: str = ""
    citations: list[AnswerCitation] = field(default_factory=list)
    answer_status: str = "grounded"


class CitationChecker:
    """Phase 8 引用与证据一致性校验器。"""

    def check(
        self,
        *,
        generated: AnswerGenerationResult,
        evidence_contexts: list[EvidenceContext],
    ) -> CitationCheckResult:
        """校验答案引用是否真实存在且元数据可追溯。"""
        _ = PROMPT_PATH  # 保留提示词文件路径，当前 Phase 先做规则校验。
        evidence_map = {context.chunk_id: context for context in evidence_contexts}
        valid_citations: list[AnswerCitation] = []
        unsupported_claims: list[str] = []

        for citation in generated.citations:
            context = evidence_map.get(citation.chunk_id)
            if context is None:
                unsupported_claims.append(f"引用 chunk 不存在：{citation.chunk_id}")
                continue
            if citation.doc_title and citation.doc_title != context.doc_title:
                unsupported_claims.append(f"引用标题与证据不一致：{citation.chunk_id}")
                continue
            if citation.page_start is not None and citation.page_start != context.page_start:
                unsupported_claims.append(f"引用页码与证据不一致：{citation.chunk_id}")
                continue
            if citation.page_end is not None and citation.page_end != context.page_end:
                unsupported_claims.append(f"引用页码范围与证据不一致：{citation.chunk_id}")
                continue
            if citation.chapter and citation.chapter != context.chapter:
                unsupported_claims.append(f"引用章节与证据不一致：{citation.chunk_id}")
                continue
            if citation.section and citation.section != context.section:
                unsupported_claims.append(f"引用小节与证据不一致：{citation.chunk_id}")
                continue
            if citation.article_no and citation.article_no != context.article_no:
                unsupported_claims.append(f"引用条款号与证据不一致：{citation.chunk_id}")
                continue
            if citation.quote and not _contains_normalized_quote(citation.quote, context):
                unsupported_claims.append(f"引用原文未出现在证据文本中：{citation.chunk_id}")
                continue
            valid_citations.append(citation)

        if not valid_citations:
            return CitationCheckResult(
                passed=False,
                unsupported_claims=unsupported_claims or ["未找到可验证引用"],
                fixed_answer=INSUFFICIENT_EVIDENCE_MESSAGE,
                citations=[],
                answer_status="insufficient",
            )

        if unsupported_claims:
            fixed_answer = generated.answer + "\n\n说明：部分结论因证据不足或引用不一致，已在最终结果中剔除。"
            return CitationCheckResult(
                passed=False,
                unsupported_claims=unsupported_claims,
                fixed_answer=fixed_answer,
                citations=valid_citations,
                answer_status="partial",
            )
        return CitationCheckResult(
            passed=True,
            unsupported_claims=[],
            fixed_answer=generated.answer,
            citations=valid_citations,
            answer_status=generated.evidence_status,
        )



def _contains_normalized_quote(quote: str, context: EvidenceContext) -> bool:
    """校验引用原文是否可在 child 或 parent 证据文本中找到。"""
    normalized_quote = _normalize_text(quote)
    if not normalized_quote:
        return True
    evidence_text = _normalize_text("\n".join([context.chunk_text, context.parent_text or ""]))
    return normalized_quote in evidence_text


def _normalize_text(value: str) -> str:
    """压缩空白，降低 PDF/Markdown 换行差异导致的误拒。"""
    return re.sub(r"\s+", "", value or "")
