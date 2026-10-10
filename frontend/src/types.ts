/** /api/v1 公共契约的前端视图类型（与 app/schemas/agentic.py 对齐）。 */

export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type AnswerStatus = "answered" | "refused";

export interface ClaimView {
  claim: string;
  citations: string[];
  scope: string;
}

export interface EvidenceView {
  citation_id: string;
  source_type: string;
  content_scope: string;
  raw_text: string | null;
  provenance: {
    provider: string;
    title?: string;
    doc_id?: string | null;
    doc_title?: string | null;
    doc_version?: string | null;
    canonical_url?: string | null;
    arxiv_id?: string | null;
    arxiv_version?: string | null;
  };
  locator: {
    page?: number | null;
    chunk?: string | null;
    url?: string | null;
    section?: string | null;
  };
}

export interface AnsweredOutcome {
  status: "answered";
  text: string;
  claims: ClaimView[];
  citations: string[];
  stop_reason: string;
  budget_report: Record<string, number>;
  evidence: EvidenceView[];
  latency_ms?: number | null;
}

export interface RefusedOutcome {
  status: "refused";
  refusal_reason: string;
  stop_reason: string;
  budget_report: Record<string, number>;
  evidence: EvidenceView[];
  latency_ms?: number | null;
}

export type AnswerView = AnsweredOutcome | RefusedOutcome;

export interface TaskView {
  task_id: string;
  status: TaskStatus;
  query: string;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  answer?: AnswerView | null;
  error?: { code: string; message: string } | null;
}

export interface TaskList {
  tasks: TaskView[];
  total: number;
}

export interface SseEvent {
  v: number;
  task_id: string;
  event_id: string;
  sequence: number;
  type:
    | "meta"
    | "plan"
    | "tool_call"
    | "tool_result"
    | "source_status"
    | "evidence"
    | "token_delta"
    | "citation"
    | "done"
    | "error";
  occurred_at: string;
  payload: Record<string, unknown>;
}

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  request_id?: string;
  code: string;
}
