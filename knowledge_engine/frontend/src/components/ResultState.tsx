import type { ReactNode } from 'react';

export function ResultState({
  loading,
  error,
  empty,
  children,
}: {
  loading: boolean;
  error?: string | null;
  empty?: string | null;
  children: ReactNode;
}) {
  if (loading) {
    return <div className="state-box loading">加载中...</div>;
  }
  if (error) {
    return <div className="state-box error">{error}</div>;
  }
  if (empty) {
    return <div className="state-box empty">{empty}</div>;
  }
  return <>{children}</>;
}
