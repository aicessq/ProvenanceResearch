export type HealthResponse = {
  status: string;
};

export type ComponentStatus = {
  connected: boolean;
  latency_ms: number | null;
};

export type ReadyResponse = {
  status: 'ok' | 'degraded' | string;
  components: Record<string, ComponentStatus>;
};

export type UploadResponse = {
  document_id: string;
  version_id: string;
  task_id: string;
  status: string;
};

export type UploadFormValues = {
  file: File;
  title: string;
  doc_type: string;
  security_domain?: string;
  tags?: string;
  publish_date?: string;
  effective_date?: string;
  version_status?: string;
};

export type QueryRetrieveFilters = {
  doc_type: string[];
  doc_title: string[];
  version_status: string[];
  security_domain: string[];
  chapter: string[];
  section: string[];
  article_no: string[];
  page_start: number | null;
  page_end: number | null;
  is_active: boolean;
  current_version_only: boolean;
};

export type QueryChunkResult = {
  chunk_id: string;
  score: number;
  source: string;
  chunk_text: string;
  document_id: string;
  version_id: string;
  doc_title: string;
  doc_type: string;
  chapter?: string | null;
  section?: string | null;
  article_no?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  parent_chunk_id?: string | null;
  version_status?: string | null;
  is_active: boolean;
  security_domain: string[];
  rrf_score?: number | null;
  source_scores: Record<string, number>;
};

export type RetrieveRequest = {
  query: string;
  top_k: number;
  filters: QueryRetrieveFilters;
  debug: boolean;
};

export type RetrieveResponse = {
  query: string;
  top_k: number;
  chunks: QueryChunkResult[];
  debug?: {
    vector_results: QueryChunkResult[];
    keyword_results: QueryChunkResult[];
    fused_results: QueryChunkResult[];
  } | null;
};

export type SafetyGuardResponse = {
  action: string;
  risk_type: string;
  reason: string;
  safe_response: string;
};

export type IntentResponse = {
  intent: string;
  confidence: number;
  reason: string;
  suggested_doc_types: string[];
};

export type RewriteRequest = {
  query: string;
  filters: QueryRetrieveFilters;
};

export type RewriteResponse = {
  query: string;
  safety: SafetyGuardResponse;
  intent: IntentResponse;
  expanded_terms: string[];
  rewritten: {
    rewritten_query: string;
    search_keywords: string[];
    sub_queries: string[];
  };
  filters: QueryRetrieveFilters;
};

export type AnswerRequest = {
  query: string;
  top_k: number;
  filters: QueryRetrieveFilters;
  debug: boolean;
};

export type AnswerCitationResponse = {
  chunk_id: string;
  doc_title: string;
  page_start?: number | null;
  page_end?: number | null;
  chapter?: string | null;
  section?: string | null;
  article_no?: string | null;
  quote: string;
};

export type AnswerResponse = {
  query: string;
  safety: SafetyGuardResponse;
  intent: IntentResponse;
  rewritten_query: string;
  answer: string;
  citations: AnswerCitationResponse[];
  confidence: number;
  evidence_status: string;
  retrieved_chunks: QueryChunkResult[];
  filters: QueryRetrieveFilters;
  debug?: {
    retrieved_chunks: QueryChunkResult[];
    evidence_contexts: Record<string, unknown>[];
    unsupported_claims: string[];
    answer_status?: string | null;
    model_name?: string | null;
  } | null;
};

export type EvalRunRequest = {
  dataset_name: string;
  dataset_path?: string | null;
};

export type EvalRunResponse = {
  run_id: string;
  dataset_name: string;
  total_count: number;
  recall_at_k: number;
  mrr: number;
  citation_accuracy: number;
  refusal_accuracy: number;
  average_latency_ms: number;
  status: string;
};

export const defaultFilters = (): QueryRetrieveFilters => ({
  doc_type: [],
  doc_title: [],
  version_status: [],
  security_domain: [],
  chapter: [],
  section: [],
  article_no: [],
  page_start: null,
  page_end: null,
  is_active: true,
  current_version_only: true,
});
