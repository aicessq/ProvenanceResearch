import { FormEvent, useState } from 'react';

import { queryApi } from '../api';
import { JsonBlock } from '../components/JsonBlock';
import { PageSection } from '../components/PageSection';
import { ResultState } from '../components/ResultState';
import type { RewriteResponse } from '../types/api';
import { defaultFilters } from '../types/api';
import { getErrorMessage, getErrorPayload } from '../utils/errors';

export function RewritePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorPayload, setErrorPayload] = useState<unknown>(null);
  const [result, setResult] = useState<RewriteResponse | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);

    try {
      setLoading(true);
      setError(null);
      setErrorPayload(null);
      const response = await queryApi.rewrite({
        query: String(formData.get('query') || ''),
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
      <PageSection title="Rewrite 调试" description="对接 /api/v1/query/rewrite，查看 safety / intent / expanded terms / rewritten query。">
        <form className="form-grid" onSubmit={onSubmit}>
          <label className="full-width">
            <span>Query</span>
            <textarea name="query" required rows={4} placeholder="输入待分析的问题。" />
          </label>
          <div className="form-actions full-width">
            <button type="submit" disabled={loading}>{loading ? '分析中...' : '执行 Rewrite 调试'}</button>
          </div>
        </form>
      </PageSection>

      <PageSection title="Rewrite 结果" description="结构化展示 query 理解过程，便于联调和调试。">
        <ResultState loading={loading} error={error} empty={!result && !errorPayload ? '提交 query 后将在这里展示结果。' : null}>
          {result ? <JsonBlock value={result} /> : null}
          {!result && errorPayload ? <JsonBlock value={errorPayload} /> : null}
        </ResultState>
      </PageSection>
    </div>
  );
}
