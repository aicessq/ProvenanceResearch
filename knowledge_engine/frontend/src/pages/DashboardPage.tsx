import { useEffect, useState } from 'react';

import { getApiBaseUrl } from '../api/client';
import { healthApi } from '../api';
import { PageSection } from '../components/PageSection';
import { ResultState } from '../components/ResultState';
import { StatusBadge } from '../components/StatusBadge';
import type { HealthResponse, ReadyResponse } from '../types/api';
import { getErrorMessage } from '../utils/errors';

export function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ready, setReady] = useState<ReadyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    async function loadStatus() {
      try {
        setLoading(true);
        setError(null);
        const [healthResult, readyResult] = await Promise.all([
          healthApi.getLiveness(),
          healthApi.getReadiness(),
        ]);
        if (!mounted) return;
        setHealth(healthResult);
        setReady(readyResult);
      } catch (err) {
        if (!mounted) return;
        setError(getErrorMessage(err));
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    void loadStatus();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="page-stack">
      <PageSection
        title="系统首页 / Dashboard"
        description="查看后端连通状态、基础设施就绪状态，以及当前前端连接的 API 地址。"
        actions={<StatusBadge label={getApiBaseUrl()} tone="neutral" />}
      >
        <ResultState loading={loading} error={error} empty={null}>
          <div className="stats-grid">
            <div className="metric-card">
              <span className="metric-label">项目名称</span>
              <strong>CyberSec RAG Agent</strong>
              <p className="muted">独立前端 MVP，连接现有 FastAPI 后端。</p>
            </div>
            <div className="metric-card">
              <span className="metric-label">后端状态</span>
              <strong>{health?.status ?? '-'}</strong>
              <StatusBadge label={health?.status === 'ok' ? 'Connected' : 'Unknown'} tone={health?.status === 'ok' ? 'success' : 'warning'} />
            </div>
            <div className="metric-card">
              <span className="metric-label">依赖就绪</span>
              <strong>{ready?.status ?? '-'}</strong>
              <StatusBadge label={ready?.status === 'ok' ? 'Ready' : 'Degraded'} tone={ready?.status === 'ok' ? 'success' : 'warning'} />
            </div>
          </div>
        </ResultState>
      </PageSection>

      <PageSection title="基础设施状态" description="来自 /api/v1/health/ready 的 PostgreSQL / Redis / Qdrant 状态。">
        <ResultState loading={loading} error={error} empty={ready ? null : '暂无状态数据'}>
          <div className="stats-grid three">
            {Object.entries(ready?.components ?? {}).map(([name, component]) => (
              <div className="metric-card" key={name}>
                <span className="metric-label">{name}</span>
                <strong>{component.connected ? 'Connected' : 'Disconnected'}</strong>
                <StatusBadge label={`${component.latency_ms ?? '-'} ms`} tone={component.connected ? 'success' : 'danger'} />
              </div>
            ))}
          </div>
        </ResultState>
      </PageSection>
    </div>
  );
}
