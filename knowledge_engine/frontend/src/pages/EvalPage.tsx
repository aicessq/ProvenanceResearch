import { FormEvent, useState } from 'react';

import { evalApi } from '../api';
import { JsonBlock } from '../components/JsonBlock';
import { PageSection } from '../components/PageSection';
import { ResultState } from '../components/ResultState';
import type { EvalRunResponse } from '../types/api';
import { getErrorMessage, getErrorPayload } from '../utils/errors';

export function EvalPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorPayload, setErrorPayload] = useState<unknown>(null);
  const [result, setResult] = useState<EvalRunResponse | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);

    try {
      setLoading(true);
      setError(null);
      setErrorPayload(null);
      const response = await evalApi.run({
        dataset_name: String(formData.get('dataset_name') || 'golden-dataset'),
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
      <PageSection title="Eval 页面" description="对接 /api/v1/eval/run，触发评测并展示核心指标。">
        <form className="form-grid" onSubmit={onSubmit}>
          <label>
            <span>Dataset Name</span>
            <input type="text" name="dataset_name" defaultValue="golden-dataset" />
          </label>
          <div className="form-actions full-width">
            <button type="submit" disabled={loading}>{loading ? '运行中...' : '执行 Eval'}</button>
          </div>
        </form>
      </PageSection>

      <PageSection title="评测结果" description="展示 run_id、total_count、Recall@K、MRR、citation_accuracy 等摘要。">
        <ResultState loading={loading} error={error} empty={!result && !errorPayload ? '运行评测后将在这里展示结果。' : null}>
          {result ? <JsonBlock value={result} /> : null}
          {!result && errorPayload ? <JsonBlock value={errorPayload} /> : null}
        </ResultState>
      </PageSection>
    </div>
  );
}
