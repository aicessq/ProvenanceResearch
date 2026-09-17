import { FormEvent, useState } from 'react';

import { queryApi } from '../api';
import { JsonBlock } from '../components/JsonBlock';
import { PageSection } from '../components/PageSection';
import { ResultState } from '../components/ResultState';
import type { RetrieveResponse } from '../types/api';
import { defaultFilters } from '../types/api';
import { getErrorMessage, getErrorPayload } from '../utils/errors';

export function RetrievePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorPayload, setErrorPayload] = useState<unknown>(null);
  const [result, setResult] = useState<RetrieveResponse | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);

    try {
      setLoading(true);
      setError(null);
      setErrorPayload(null);
      const response = await queryApi.retrieve({
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

  return (
    <div className="page-stack">
      <PageSection title="检索调试" description="对接 /api/v1/query/retrieve，查看 chunk 级检索结果。">
        <form className="form-grid" onSubmit={onSubmit}>
          <label className="full-width">
            <span>Query</span>
            <textarea name="query" required rows={4} placeholder="输入一个待检索的问题或关键句。" />
          </label>
          <label>
            <span>Top K</span>
            <input type="number" name="top_k" min={1} max={30} defaultValue={5} />
          </label>
          <label className="checkbox-row">
            <input type="checkbox" name="debug" />
            <span>返回调试信息</span>
          </label>
          <div className="form-actions full-width">
            <button type="submit" disabled={loading}>{loading ? '检索中...' : '执行检索'}</button>
          </div>
        </form>
      </PageSection>

      <PageSection title="检索结果" description="每条结果展示 chunk_id、标题、类型、分数、页码和 chunk_text。">
        <ResultState loading={loading} error={error} empty={!result && !errorPayload ? '执行检索后将在这里展示结果。' : null}>
          {result ? (
            <div className="result-list">
              {result.chunks.map((chunk) => (
                <article className="result-card" key={chunk.chunk_id}>
                  <div className="result-card-header">
                    <strong>{chunk.doc_title}</strong>
                    <span>{chunk.doc_type}</span>
                  </div>
                  <p className="meta-row">chunk_id: {chunk.chunk_id}</p>
                  <p className="meta-row">score: {chunk.score.toFixed(4)} | page: {chunk.page_start ?? '-'} - {chunk.page_end ?? '-'}</p>
                  <p className="chunk-text">{chunk.chunk_text}</p>
                </article>
              ))}
              {result.debug ? <JsonBlock value={result.debug} /> : null}
            </div>
          ) : null}
          {!result && errorPayload ? <JsonBlock value={errorPayload} /> : null}
        </ResultState>
      </PageSection>
    </div>
  );
}
