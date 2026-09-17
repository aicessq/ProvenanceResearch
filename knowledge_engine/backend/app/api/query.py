"""查询接口。

Phase 6：提供 `/query/retrieve` 检索调试接口。
Phase 7：补齐 `/query/rewrite` 输入优化调试接口。
Phase 8：补齐 `/query/answer` 证据约束问答接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas.query import (
    AnswerCitationResponse,
    IntentResponse,
    QueryAnswerDebug,
    QueryAnswerRequest,
    QueryAnswerResponse,
    QueryChunkResult,
    QueryRetrieveDebug,
    QueryRetrieveRequest,
    QueryRetrieveResponse,
    QueryRewritePayload,
    QueryRewriteRequest,
    QueryRewriteResponse,
    SafetyGuardResponse,
)
from app.services.answer_generator import AnswerCitation, EvidenceContext
from app.services.query_service import QueryService
from app.services.retriever import HybridRetriever

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/retrieve", response_model=QueryRetrieveResponse)
def retrieve_chunks(
    request: QueryRetrieveRequest,
    db: Session = Depends(get_db),
) -> QueryRetrieveResponse:
    """执行 Phase 6 检索调试接口。"""
    try:
        service = QueryService(db)
        prepared = service.prepare(query=request.query, explicit_filters=request.filters.model_dump())
        retriever = HybridRetriever.from_db(db)
        retrieval_kwargs = {
            "query": prepared.rewritten.rewritten_query,
            "top_k": request.top_k,
            "filters": prepared.filters,
            "debug": request.debug,
        }
        if hasattr(retriever, "search"):
            result = retriever.search(
                **retrieval_kwargs,
                search_keywords=prepared.rewritten.search_keywords,
                sub_queries=prepared.rewritten.sub_queries,
            )
        else:
            result = retriever.retrieve(**retrieval_kwargs)
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转换为结构化错误响应
        raise _internal_error("检索失败，请稍后重试", str(exc)) from exc

    return QueryRetrieveResponse(
        query=request.query,
        top_k=result.top_k,
        chunks=[_to_chunk_result(item) for item in result.final_results],
        debug=(
            QueryRetrieveDebug(
                vector_results=[_to_chunk_result(item) for item in result.debug.vector_results],
                keyword_results=[_to_chunk_result(item) for item in result.debug.keyword_results],
                fused_results=[_to_chunk_result(item) for item in result.debug.fused_results],
            )
            if request.debug
            else None
        ),
    )


@router.post("/rewrite", response_model=QueryRewriteResponse)
def rewrite_query(request: QueryRewriteRequest, db: Session = Depends(get_db)) -> QueryRewriteResponse:
    """执行 Phase 7 输入优化调试接口。"""
    try:
        prepared = QueryService(db).prepare(
            query=request.query,
            explicit_filters=request.filters.model_dump(),
        )
        safety = prepared.safety
        intent = prepared.intent
        expanded_terms = prepared.expanded_terms
        rewritten = prepared.rewritten
        built_filters = prepared.filters
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _internal_error("输入优化失败，请稍后重试", str(exc)) from exc

    return QueryRewriteResponse(
        query=request.query,
        safety=_to_safety_response(safety),
        intent=_to_intent_response(intent),
        expanded_terms=list(expanded_terms),
        rewritten=QueryRewritePayload(
            rewritten_query=rewritten.rewritten_query,
            search_keywords=list(rewritten.search_keywords),
            sub_queries=list(rewritten.sub_queries),
        ),
        filters=_to_filter_response(request.filters, built_filters),
    )


@router.post("/answer", response_model=QueryAnswerResponse)
def answer_query(
    request: QueryAnswerRequest,
    db: Session = Depends(get_db),
) -> QueryAnswerResponse:
    """执行 Phase 8 证据约束问答接口。"""
    try:
        result = QueryService(db).answer(
            query=request.query,
            top_k=request.top_k,
            explicit_filters=request.filters.model_dump(),
            debug=request.debug,
            retriever=HybridRetriever.from_db(db),
        )
        prepared = result.preparation
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _internal_error("问答失败，请稍后重试", str(exc)) from exc

    return QueryAnswerResponse(
        query=request.query,
        safety=_to_safety_response(prepared.safety),
        intent=_to_intent_response(prepared.intent),
        rewritten_query=prepared.rewritten.rewritten_query,
        answer=result.answer,
        citations=[_to_answer_citation_response(item) for item in result.citations],
        confidence=result.confidence,
        evidence_status=result.evidence_status,
        retrieved_chunks=[_to_chunk_result(item) for item in result.retrieved_chunks],
        filters=_to_filter_response(request.filters, prepared.filters),
        debug=(
            QueryAnswerDebug(
                retrieved_chunks=[_to_chunk_result(item) for item in result.retrieved_chunks],
                evidence_contexts=[_serialize_evidence_context(item) for item in result.evidence_contexts],
                unsupported_claims=list(result.unsupported_claims),
                answer_status=result.answer_status,
                model_name=result.model_name,
            )
            if request.debug
            else None
        ),
    )


def _serialize_evidence_context(context: EvidenceContext) -> dict[str, object]:
    """把 EvidenceContext 输出给调试字段。"""
    return {
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
        "score": context.score,
        "source": context.source,
    }


def _to_answer_citation_response(citation: AnswerCitation) -> AnswerCitationResponse:
    """把答案引用映射为 API schema。"""
    return AnswerCitationResponse(
        chunk_id=citation.chunk_id,
        doc_title=citation.doc_title,
        page_start=citation.page_start,
        page_end=citation.page_end,
        chapter=citation.chapter,
        section=citation.section,
        article_no=citation.article_no,
        quote=citation.quote,
    )


def _to_safety_response(safety) -> SafetyGuardResponse:
    return SafetyGuardResponse(
        action=safety.action,
        risk_type=safety.risk_type,
        reason=safety.reason,
        safe_response=safety.safe_response,
    )


def _to_intent_response(intent) -> IntentResponse:
    return IntentResponse(
        intent=intent.intent,
        confidence=intent.confidence,
        reason=intent.reason,
        suggested_doc_types=list(intent.suggested_doc_types),
    )


def _to_filter_response(original_filters, built_filters) -> object:
    return original_filters.model_copy(
        update={
            "doc_type": built_filters.doc_type,
            "doc_title": built_filters.doc_title,
            "version_status": built_filters.version_status,
            "security_domain": built_filters.security_domain,
            "chapter": built_filters.chapter,
            "section": built_filters.section,
            "article_no": built_filters.article_no,
            "page_start": built_filters.page_start,
            "page_end": built_filters.page_end,
            "is_active": built_filters.is_active,
            "current_version_only": built_filters.current_version_only,
        }
    )


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "invalid_request",
                "message": message,
                "details": {},
            }
        },
    )


def _internal_error(message: str, reason: str) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={
            "error": {
                "code": "internal_error",
                "message": message,
                "details": {"reason": reason},
            }
        },
    )


def _to_chunk_result(item) -> QueryChunkResult:
    """把服务层结果映射为 API schema。"""
    return QueryChunkResult(
        chunk_id=item.chunk_id,
        score=item.score,
        source=item.source,
        chunk_text=item.chunk_text,
        document_id=item.document_id,
        version_id=item.version_id,
        doc_title=item.doc_title,
        doc_type=item.doc_type,
        chapter=item.chapter,
        section=item.section,
        article_no=item.article_no,
        page_start=item.page_start,
        page_end=item.page_end,
        parent_chunk_id=item.parent_chunk_id,
        version_status=item.version_status,
        is_active=item.is_active,
        security_domain=list(item.security_domain),
        rrf_score=getattr(item, "rrf_score", None),
        source_scores=dict(getattr(item, "source_scores", {})),
    )
