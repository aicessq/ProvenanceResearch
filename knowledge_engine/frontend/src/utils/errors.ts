import type { ApiError } from '../api/client';

export function getErrorMessage(error: unknown) {
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as { message?: string }).message || '请求失败');
  }
  return '请求失败';
}

export function getErrorPayload(error: unknown) {
  if (error && typeof error === 'object' && 'payload' in error) {
    return (error as ApiError).payload;
  }
  return undefined;
}
