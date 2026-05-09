import { requestJson } from './client';
import type {
  XueqiuActionResponse,
  XueqiuCredentialRequest,
  XueqiuCredentialSummary,
  XueqiuDraftPreview,
  XueqiuPublishRecordDetail,
  XueqiuPublishRecordItem,
  XueqiuPublishRequest
} from '../types/domain';

export interface XueqiuRecordFilters {
  limit?: number;
  status?: string;
}

/**
 * 雪球发布管理接口封装。
 * 创建日期：2026-05-10
 * author: sunshengxian
 */
export function fetchXueqiuCredential() {
  return requestJson<XueqiuCredentialSummary>('/api/xueqiu-publish/credential');
}

export function saveXueqiuCredential(payload: XueqiuCredentialRequest) {
  return requestJson<XueqiuCredentialSummary>('/api/xueqiu-publish/credential', {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

export function verifyXueqiuCredential() {
  return requestJson<XueqiuCredentialSummary>('/api/xueqiu-publish/credential/verify', {
    method: 'POST'
  });
}

export function fetchXueqiuPreview(analysisId?: number | null) {
  const params = new URLSearchParams();
  if (analysisId) {
    params.set('analysis_id', String(analysisId));
  }
  const query = params.toString();
  return requestJson<XueqiuDraftPreview>(`/api/xueqiu-publish/preview${query ? `?${query}` : ''}`);
}

export function publishXueqiuArticle(payload: XueqiuPublishRequest) {
  return requestJson<XueqiuActionResponse>('/api/xueqiu-publish/publish', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function fetchXueqiuRecords(filters: XueqiuRecordFilters = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(filters.limit || 100));
  if (filters.status) {
    params.set('status', filters.status);
  }
  return requestJson<XueqiuPublishRecordItem[]>(`/api/xueqiu-publish/records?${params.toString()}`);
}

export function fetchXueqiuRecord(recordId: number) {
  return requestJson<XueqiuPublishRecordDetail>(`/api/xueqiu-publish/records/${recordId}`);
}
