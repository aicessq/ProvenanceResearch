import { FormEvent, useState } from 'react';

import { documentsApi } from '../api';
import { JsonBlock } from '../components/JsonBlock';
import { PageSection } from '../components/PageSection';
import { ResultState } from '../components/ResultState';
import type { UploadResponse } from '../types/api';
import { getErrorMessage, getErrorPayload } from '../utils/errors';

export function UploadPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<UploadResponse | null>(null);
  const [errorPayload, setErrorPayload] = useState<unknown>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const file = formData.get('file');
    if (!(file instanceof File) || !file.name) {
      setError('请选择上传文件');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setErrorPayload(null);
      setPayload(null);
      const response = await documentsApi.upload({
        file,
        title: String(formData.get('title') || ''),
        doc_type: String(formData.get('doc_type') || ''),
        security_domain: String(formData.get('security_domain') || ''),
        tags: String(formData.get('tags') || ''),
        publish_date: String(formData.get('publish_date') || ''),
        effective_date: String(formData.get('effective_date') || ''),
        version_status: String(formData.get('version_status') || 'active'),
      });
      setPayload(response);
    } catch (err) {
      setError(getErrorMessage(err));
      setErrorPayload(getErrorPayload(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-stack">
      <PageSection title="文档上传" description="对接 /api/v1/documents/upload，提交新文档及基础元数据。">
        <form className="form-grid" onSubmit={onSubmit}>
          <label>
            <span>文件</span>
            <input type="file" name="file" required />
          </label>
          <label>
            <span>标题</span>
            <input type="text" name="title" required placeholder="例如：等保2.0安全通信网络要求" />
          </label>
          <label>
            <span>文档类型</span>
            <input type="text" name="doc_type" required placeholder="law / standard / textbook ..." />
          </label>
          <label>
            <span>安全域</span>
            <input type="text" name="security_domain" placeholder="逗号分隔，例如: network,compliance" />
          </label>
          <label>
            <span>标签</span>
            <input type="text" name="tags" placeholder="逗号分隔，例如: 等保,基础要求" />
          </label>
          <label>
            <span>发布日期</span>
            <input type="date" name="publish_date" />
          </label>
          <label>
            <span>生效日期</span>
            <input type="date" name="effective_date" />
          </label>
          <label>
            <span>版本状态</span>
            <input type="text" name="version_status" defaultValue="active" />
          </label>
          <div className="form-actions full-width">
            <button type="submit" disabled={loading}>
              {loading ? '上传中...' : '提交上传'}
            </button>
          </div>
        </form>
      </PageSection>

      <PageSection title="上传结果" description="成功时展示 document_id / version_id / task_id，失败时展示结构化错误。">
        <ResultState loading={loading} error={error} empty={!payload && !errorPayload ? '提交后将在这里展示返回结果。' : null}>
          {payload ? <JsonBlock value={payload} /> : null}
          {!payload && errorPayload ? <JsonBlock value={errorPayload} /> : null}
        </ResultState>
      </PageSection>
    </div>
  );
}
