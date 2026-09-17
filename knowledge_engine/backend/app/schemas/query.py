"""query 相关 Pydantic schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRetrieveFilters(BaseModel):
    """Phase 6 `/query/retrieve` 显式过滤条件。"""

    doc_type: list[str] = Field(default_factory=list)
    doc_title: list[str] = Field(default_factory=list)
    version_status: list[str] = Field(default_factory=list)
    security_domain: list[str] = Field(default_factory=list)
    chapter: list[str] = Field(default_factory=list)
    section: list[str] = Field(default_factory=list)
    article_no: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    is_active: bool = True
    current_version_only: bool = True


class QueryRetrieveRequest(BaseModel):
    """Phase 6 检索调试接口请求。"""

    query: str
    top_k: int = Field(default=5, ge=1, le=30)
    filters: QueryRetrieveFilters = Field(default_factory=QueryRetrieveFilters)
    debug: bool = Field(default=False)


class QueryRewriteRequest(BaseModel):
    """Phase 7 输入优化调试接口请求。"""

    query: str
    filters: QueryRetrieveFilters = Field(default_factory=QueryRetrieveFilters)


class QueryAnswerRequest(BaseModel):
    """Phase 8 问答接口请求。"""

    query: str
    top_k: int = Field(default=5, ge=1, le=10)
    filters: QueryRetrieveFilters = Field(default_factory=QueryRetrieveFilters)
    debug: bool = Field(default=False)


class QueryChunkResult(BaseModel):
    """单条 chunk 检索结果。"""

    chunk_id: str
    score: float
    source: str
    chunk_text: str
    document_id: str
    version_id: str
    doc_title: str
    doc_type: str
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    parent_chunk_id: str | None = None
    version_status: str | None = None
    is_active: bool = True
    security_domain: list[str] = Field(default_factory=list)
    rrf_score: float | None = None
    source_scores: dict[str, float] = Field(default_factory=dict)


class QueryRetrieveDebug(BaseModel):
    """调试信息。"""

    vector_results: list[QueryChunkResult] = Field(default_factory=list)
    keyword_results: list[QueryChunkResult] = Field(default_factory=list)
    fused_results: list[QueryChunkResult] = Field(default_factory=list)


class QueryRetrieveResponse(BaseModel):
    """Phase 6 检索调试接口响应。"""

    query: str
    top_k: int
    chunks: list[QueryChunkResult] = Field(default_factory=list)
    debug: QueryRetrieveDebug | None = None


class SafetyGuardResponse(BaseModel):
    """Phase 7 safety_guard 输出。"""

    action: str
    risk_type: str
    reason: str
    safe_response: str


class IntentResponse(BaseModel):
    """Phase 7 intent_classifier 输出。"""

    intent: str
    confidence: float
    reason: str
    suggested_doc_types: list[str] = Field(default_factory=list)


class QueryRewritePayload(BaseModel):
    """Phase 7 query_rewriter 输出。"""

    rewritten_query: str
    search_keywords: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)


class QueryRewriteResponse(BaseModel):
    """Phase 7 `/query/rewrite` 调试接口响应。"""

    query: str
    safety: SafetyGuardResponse
    intent: IntentResponse
    expanded_terms: list[str] = Field(default_factory=list)
    rewritten: QueryRewritePayload
    filters: QueryRetrieveFilters


class AnswerCitationResponse(BaseModel):
    """Phase 8 单条答案引用。"""

    chunk_id: str
    doc_title: str
    page_start: int | None = None
    page_end: int | None = None
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    quote: str = ""


class QueryAnswerDebug(BaseModel):
    """Phase 8 问答接口调试信息。"""

    retrieved_chunks: list[QueryChunkResult] = Field(default_factory=list)
    evidence_contexts: list[dict[str, object]] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    answer_status: str | None = None
    model_name: str | None = None


class QueryAnswerResponse(BaseModel):
    """Phase 8 `/query/answer` 接口响应。"""

    query: str
    safety: SafetyGuardResponse
    intent: IntentResponse
    rewritten_query: str
    answer: str
    citations: list[AnswerCitationResponse] = Field(default_factory=list)
    confidence: float = 0.0
    evidence_status: str
    retrieved_chunks: list[QueryChunkResult] = Field(default_factory=list)
    filters: QueryRetrieveFilters
    debug: QueryAnswerDebug | None = None
