export type ApiErrorPayload = {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
};

export class ApiError extends Error {
  status: number;
  payload?: ApiErrorPayload;

  constructor(status: number, message: string, payload?: ApiErrorPayload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

function buildUrl(path: string) {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const payloadObject = typeof payload === 'object' ? (payload as ApiErrorPayload) : undefined;
    const message = payloadObject?.error?.message || response.statusText || 'Request failed';
    throw new ApiError(response.status, message, payloadObject);
  }

  return payload as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'GET',
  });
  return parseResponse<T>(response);
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  return parseResponse<T>(response);
}

export async function apiPostForm<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    body: formData,
  });
  return parseResponse<T>(response);
}

export function getApiBaseUrl() {
  return API_BASE_URL;
}
