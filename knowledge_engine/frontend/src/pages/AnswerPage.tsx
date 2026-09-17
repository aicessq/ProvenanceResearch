import { FormEvent, useState } from 'react';

import { queryApi } from '../api';
import { JsonBlock } from '../components/JsonBlock';
import { PageSection } from '../components/PageSection';
import { ResultState } from '../components/ResultState';
import { StatusBadge } from '../components/StatusBadge';
import type { AnswerResponse } from '../types/api';
import { defaultFilters } from '../types/api';
import { getErrorMessage, getErrorPayload } from '../utils/errors';

export function AnswerPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorPayload, setErrorPayload] = useState<unknown>(null);
  const [result, setResult] = useState<AnswerResponse | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);

    try {
      setLoading(true);
      setError(null);
      setErrorPayload(null);
      const response = await queryApi.answer({
        query: String(formData.get('query') || ''),
        top_k: Number(formData.get('top_k') || 5),
        debug: Boolean(formData.get('debug')),
        filters: defaultFilters(),
      });
      setResult(response);
    } catch (err) {
      setError(getErrorMessage(err));
      setErrorPayload(getErrorPayload(err));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const actionTone =
    result?.safety.action === 'allow'
      ? 'success'
      : result?.safety.action === 'redirect'
        ? 'warning'
        : 'danger';

  return (
    <div className="page-stack">
      <PageSection title="问答页面" description="对接 /api/v1/query/answer，展示 answer、citations、confidence、evidence_status。">
        <form className="form-grid" onSubmit={onSubmit}>
          <label className="full-width">
            <span>问题</span>
            <textarea name="query" required rows={4} placeholder="输入一个网络安全相关问题。" />
          </label>
          <label>
            <span>Top K</span>
            <input type="number" name="top_k" min={1} max={10} defaultValue={5} />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" name="debug" />
            <span>返回调试信息</span>
          </label>
          <div className="form-actions full-width">
            <button type="submit" disabled={loading}>{loading ? '生成中...' : '提交问答'}</button>
          </div>
        </form>
      </PageSection>

      <PageSection title="问答结果" description="对 blocked / refuse / redirect 状态做清晰展示，而不是只显示原始文本。">
        <ResultState loading={loading} error={error} empty={!result && !errorPayload ? '提交问题后将在这里展示回答结果。' : null}>
          {result ? (
            <div className="answer-stack">
              <div className="answer-head">
                <StatusBadge label={`safety: ${result.safety.action}`} tone={actionTone} />
                <StatusBadge label={`evidence: ${result.evidence_status}`} tone={result.evidence_status === 'grounded' ? 'success' : result.evidence_status === 'blocked' ? 'danger' : 'warning'} />
                <StatusBadge label={`confidence: ${result.confidence.toFixed(2)}`} tone="neutral" />
              </div>
              <article className="answer-box">{result.answer}</article>
              <div className="result-list">
                {result.citations.map((citation) => (
                  <article className="result-card" key={citation.chunk_id + citation.quote}>
                    <div className="result-card-header">
                      <strong>{citation.doc_title}</strong>
                      <span>{citation.chunk_id}</span>
                    </div>
                    <p className="meta-row">page: {citation.page_start ?? '-'} - {citation.page_end ?? '-'}</p>
                    <p className="chunk-text">{citation.quote || '无引用摘录'}</p>
                  </article>
                ))}
              </div>
              {result.debug ? <JsonBlock value={result.debug} /> : null}
            </div>
          ) : null}
          {!result && errorPayload ? <JsonBlock value={errorPayload} /> : null}
        </ResultState>
      </PageSection>
    </div>
  );
}
