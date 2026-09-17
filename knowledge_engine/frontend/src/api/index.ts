import { apiGet, apiPostForm, apiPostJson } from './client';
import type {
  AnswerRequest,
  AnswerResponse,
  EvalRunRequest,
  EvalRunResponse,
  HealthResponse,
  ReadyResponse,
  RetrieveRequest,
  RetrieveResponse,
  RewriteRequest,
  RewriteResponse,
  UploadFormValues,
  UploadResponse,
} from '../types/api';

export const healthApi = {
  getLiveness: () => apiGet<HealthResponse>('/health'),
  getReadiness: () => apiGet<ReadyResponse>('/api/v1/health/ready'),
};

export const documentsApi = {
  upload: (values: UploadFormValues) => {
    const formData = new FormData();
    formData.append('file', values.file);
    formData.append('title', values.title);
    formData.append('doc_type', values.doc_type);
    if (values.security_domain) formData.append('security_domain', values.security_domain);
    if (values.tags) formData.append('tags', values.tags);
    if (values.publish_date) formData.append('publish_date', values.publish_date);
    if (values.effective_date) formData.append('effective_date', values.effective_date);
    if (values.version_status) formData.append('version_status', values.version_status);
    return apiPostForm<UploadResponse>('/api/v1/documents/upload', formData);
  },
};

export const queryApi = {
  retrieve: (payload: RetrieveRequest) => apiPostJson<RetrieveResponse>('/api/v1/query/retrieve', payload),
  rewrite: (payload: RewriteRequest) => apiPostJson<RewriteResponse>('/api/v1/query/rewrite', payload),
  answer: (payload: AnswerRequest) => apiPostJson<AnswerResponse>('/api/v1/query/answer', payload),
};

export const evalApi = {
  run: (payload: EvalRunRequest) => apiPostJson<EvalRunResponse>('/api/v1/eval/run', payload),
};
