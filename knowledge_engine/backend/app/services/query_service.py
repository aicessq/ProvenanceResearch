"""查询业务编排服务。

API 层只负责请求/响应转换；安全、改写、检索、证据回取、答案生成与引用校验在服务层完成。
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.services.answer_generator import AnswerGenerator, EvidenceContext
from app.services.citation_checker import CitationChecker, CitationCheckResult
from app.services.crud_service import create_query_log
from app.services.fusion import RetrievalHit
from app.services.intent_classifier import IntentClassifier, IntentResult
from app.services.metadata_filter import MetadataFilter, MetadataFilterBuilder
from app.services.query_rewriter import QueryRewriteResult, QueryRewriter
from app.services.retriever import HybridRetriever, RetrievalResponse
from app.services.safety_guard import SafetyGuard, SafetyGuardResult
from app.services.term_expander import TermExpander


@dataclass(slots=True)
class QueryPreparationResult:
    safety: SafetyGuardResult
    intent: IntentResult
    expanded_terms: list[str]
    rewritten: QueryRewriteResult
    filters: MetadataFilter


@dataclass(slots=True)
class QueryAnswerServiceResult:
    query: str
    preparation: QueryPreparationResult
    answer: str
    citations: list
    confidence: float
    evidence_status: str
    retrieved_chunks: list[RetrievalHit] = field(default_factory=list)
    evidence_contexts: list[EvidenceContext] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    answer_status: str = "grounded"
    model_name: str = ""
    latency_ms: int = 0


class QueryService:
    """查询链路服务层编排。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def prepare(self, *, query: str, explicit_filters: dict) -> QueryPreparationResult:
        """执行 safety / intent / expansion / rewrite / metadata filter。"""
        safety = SafetyGuard().evaluate(query)
        intent = IntentClassifier().classify(query)
        expanded_terms = TermExpander().expand(query)
        rewritten = QueryRewriter().rewrite(query, intent=intent, expanded_terms=expanded_terms)
        filters = MetadataFilterBuilder().build(
            explicit_filters=explicit_filters,
            suggested_doc_types=intent.suggested_doc_types,
        )
        return QueryPreparationResult(
            safety=safety,
            intent=intent,
            expanded_terms=list(expanded_terms),
            rewritten=rewritten,
            filters=filters,
        )

    def answer(
        self,
        *,
        query: str,
        top_k: int,
        explicit_filters: dict,
        debug: bool = False,
        retriever: HybridRetriever | None = None,
    ) -> QueryAnswerServiceResult:
        """执行完整证据约束问答链路并写入 query log。"""
        _ = debug
        started_at = time.perf_counter()
        prepared = self.prepare(query=query, explicit_filters=explicit_filters)
        effective_filters = MetadataFilter.from_input(prepared.filters.to_payload_dict())

        if prepared.safety.action != "allow":
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            answer = prepared.safety.safe_response or "当前请求不适合继续执行问答。"
            create_query_log(
                self.db,
                user_query=query,
                rewritten_query=prepared.rewritten.rewritten_query,
                intent=prepared.intent.intent,
                safety_action=prepared.safety.action,
                risk_type=prepared.safety.risk_type,
                filters=prepared.filters.to_payload_dict(),
                retrieved_chunk_ids=[],
                reranked_chunk_ids=[],
                answer=answer,
                answer_status="blocked",
                latency_ms=latency_ms,
                model_name="safety-guard",
            )
            return QueryAnswerServiceResult(
                query=query,
                preparation=prepared,
                answer=answer,
                citations=[],
                confidence=0.0,
                evidence_status="blocked",
                answer_status="blocked",
                model_name="safety-guard",
                latency_ms=latency_ms,
            )

        active_retriever = retriever or HybridRetriever.from_db(self.db)
        retrieval_kwargs = {
            "query": prepared.rewritten.rewritten_query,
            "top_k": top_k,
            "filters": effective_filters,
            "debug": debug,
        }
        if hasattr(active_retriever, "search"):
            retrieval = active_retriever.search(
                **retrieval_kwargs,
                search_keywords=prepared.rewritten.search_keywords,
                sub_queries=prepared.rewritten.sub_queries,
            )
        else:
            retrieval = active_retriever.retrieve(**retrieval_kwargs)
        evidence_contexts = build_evidence_contexts(self.db, retrieval.final_results)
        generated = AnswerGenerator().generate(query=query, evidence_contexts=evidence_contexts)
        checked = CitationChecker().check(generated=generated, evidence_contexts=evidence_contexts)
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        self._log_answer(
            query=query,
            prepared=prepared,
            retrieval=retrieval,
            checked=checked,
            latency_ms=latency_ms,
            model_name=generated.model_name,
        )
        return QueryAnswerServiceResult(
            query=query,
            preparation=prepared,
            answer=checked.fixed_answer,
            citations=checked.citations,
            confidence=generated.confidence,
            evidence_status=checked.answer_status,
            retrieved_chunks=list(retrieval.final_results),
            evidence_contexts=evidence_contexts,
            unsupported_claims=list(checked.unsupported_claims),
            answer_status=checked.answer_status,
            model_name=generated.model_name,
            latency_ms=latency_ms,
        )

    def _log_answer(
        self,
        *,
        query: str,
        prepared: QueryPreparationResult,
        retrieval: RetrievalResponse,
        checked: CitationCheckResult,
        latency_ms: int,
        model_name: str,
    ) -> None:
        create_query_log(
            self.db,
            user_query=query,
            rewritten_query=prepared.rewritten.rewritten_query,
            intent=prepared.intent.intent,
            safety_action=prepared.safety.action,
            risk_type=prepared.safety.risk_type,
            filters=prepared.filters.to_payload_dict(),
            retrieved_chunk_ids=[str(item.chunk_id) for item in retrieval.debug.fused_results or retrieval.final_results],
            reranked_chunk_ids=[
                str(item.chunk_id)
                for item in getattr(retrieval.debug, "reranked_results", []) or retrieval.final_results
            ],
            answer=checked.fixed_answer,
            answer_status=checked.answer_status,
            latency_ms=latency_ms,
            model_name=model_name,
        )


def build_evidence_contexts(db: Session, results: Iterable[RetrievalHit]) -> list[EvidenceContext]:
    """批量回取 parent chunk 并构造 evidence context。"""
    result_list = list(results)
    parent_ids: list[UUID] = []
    for item in result_list:
        parent_chunk_id = getattr(item, "parent_chunk_id", None)
        if parent_chunk_id:
            parent_ids.append(UUID(str(parent_chunk_id)))
    parent_map = {
        str(chunk.id): chunk
        for chunk in db.execute(select(Chunk).where(Chunk.id.in_(parent_ids))).scalars().all()
    } if parent_ids else {}

    contexts: list[EvidenceContext] = []
    for item in result_list:
        parent_id = str(item.parent_chunk_id) if getattr(item, "parent_chunk_id", None) else None
        parent_chunk = parent_map.get(parent_id) if parent_id else None
        contexts.append(
            EvidenceContext(
                chunk_id=str(item.chunk_id),
                doc_title=item.doc_title,
                doc_type=item.doc_type,
                chunk_text=item.chunk_text,
                page_start=item.page_start,
                page_end=item.page_end,
                chapter=item.chapter,
                section=item.section,
                article_no=item.article_no,
                parent_chunk_id=parent_id,
                parent_text=parent_chunk.text if parent_chunk is not None else item.chunk_text,
                score=item.score,
                source=item.source,
            )
        )
    return contexts
