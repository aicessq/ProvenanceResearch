/** /api/v1 客户端：任务生命周期 + SSE v1（EventSource 自动携带 Last-Event-ID 续传）。 */

import { ref } from "vue";
import type { Problem, SseEvent, TaskList, TaskView } from "./types";

/** 服务端要求认证时置位（App 弹登录层）；token 只驻内存。 */
export const authRequired = ref(false);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  const resp = await fetch(path, { headers, ...init });
  if (!resp.ok) {
    let problem: Problem | null = null;
    try {
      problem = (await resp.json()) as Problem;
    } catch {
      /* 非 problem+json */
    }
    if (resp.status === 401) authRequired.value = true;
    throw new ApiError(problem?.detail ?? `请求失败: ${resp.status}`, problem);
  }
  return (await resp.json()) as T;
}

export class ApiError extends Error {
  problem: Problem | null;
  constructor(message: string, problem: Problem | null) {
    super(message);
    this.problem = problem;
  }
}

export const api = {
  listTasks: () => request<TaskList>("/api/v1/tasks"),
  getTask: (taskId: string) => request<TaskView>(`/api/v1/tasks/${encodeURIComponent(taskId)}`),
  createTask: (query: string) =>
    request<TaskView>("/api/v1/tasks", { method: "POST", body: JSON.stringify({ query }) }),
  cancelTask: (taskId: string) =>
    request<{ task_id: string; status: string }>(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST",
    }),
  deleteTask: (taskId: string) =>
    request<{ task_id: string; deleted: boolean }>(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
      method: "DELETE",
    }),
};

export interface StreamHandlers {
  onEvent: (event: SseEvent) => void;
  onError: (message: string) => void;
  onOpen?: () => void;
}

/** 打开任务 SSE 流。返回 close()；done/error(fatal) 终态自动收流。 */
export function openTaskStream(taskId: string, handlers: StreamHandlers): () => void {
  const source = new EventSource(`/api/v1/tasks/${encodeURIComponent(taskId)}/events`);
  const types = [
    "meta",
    "plan",
    "tool_call",
    "tool_result",
    "source_status",
    "evidence",
    "token_delta",
    "citation",
    "done",
    "error",
  ] as const;

  const finish = () => source.close();
  let closed = false;
  const close = () => {
    closed = true;
    source.close();
  };

  source.onopen = () => handlers.onOpen?.();
  source.onerror = () => {
    // EventSource 断线会自动带 Last-Event-ID 重连；只有显式关闭后才报错
    if (!closed) handlers.onError("连接中断，正在用 Last-Event-ID 重连续传…");
  };

  for (const type of types) {
    source.addEventListener(type, (raw) => {
      const message = raw as MessageEvent;
      try {
        const event = JSON.parse(message.data) as SseEvent;
        handlers.onEvent(event);
        const payload = event.payload as { fatal?: boolean };
        if (event.type === "done" || (event.type === "error" && payload.fatal === true)) {
          finish();
        }
      } catch {
        handlers.onError("事件解析失败");
      }
    });
  }

  return close;
}

/** ---- 云服务配置（凭证只写不读；GET 仅回 configured/missing） ---- */

export interface CapabilityView {
  configured: boolean;
  source: "env" | "override";
  provider: string;
  model: string;
  model_version: string;
  base_url: string;
  api_key: "configured" | "missing";
  index_migration_pending: boolean;
}

export interface OutboundCapabilityView {
  fingerprint: string;
  approved: boolean;
  reason: string;
  provider: string;
  endpoint: string;
  model: string;
}

export interface ConfigView {
  capabilities: Record<string, CapabilityView>;
  sources: Record<string, { configured: boolean; source: string }>;
  vault_enabled: boolean;
  outbound: {
    upload_allowed: boolean;
    region: string;
    approvals: Record<string, string>;
    capabilities: Record<string, OutboundCapabilityView>;
  };
}

export interface CapabilityPayload {
  provider?: string;
  model?: string;
  model_version?: string;
  base_url?: string;
  api_key?: string;
}

export const configApi = {
  get: () => request<ConfigView>("/api/v1/config"),
  update: (capability: string, payload: CapabilityPayload) =>
    request<CapabilityView>(`/api/v1/config/${encodeURIComponent(capability)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  remove: (capability: string) =>
    request<CapabilityView>(`/api/v1/config/${encodeURIComponent(capability)}`, { method: "DELETE" }),
  test: (capability: string, payload: { probe?: boolean; confirm_fingerprint?: string } = {}) =>
    request<{ capability: string; validation: string; config?: CapabilityView }>(
      `/api/v1/config/${encodeURIComponent(capability)}/test`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  approveOutbound: (capability: string) =>
    request<OutboundCapabilityView>(`/api/v1/config/outbound/${encodeURIComponent(capability)}`, {
      method: "PUT",
    }),
  rotateKey: (newKey: string) =>
    request<{ rotated: number; note: string }>("/api/v1/config/rotate-key", {
      method: "POST",
      body: JSON.stringify({ new_key: newKey }),
    }),
};

/** ---- 认证（AUTH_ENABLED=true 时必需；token 只驻内存，不落 localStorage） ---- */

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export const authApi = {
  login: async (username: string, password: string) => {
    const result = await request<{ access_token: string; token_type: string; expires_in: number }>(
      "/api/v1/auth/token",
      { method: "POST", body: JSON.stringify({ username, password }) },
    );
    authToken = result.access_token;
    return result;
  },
  logout: () => {
    authToken = null;
  },
};
