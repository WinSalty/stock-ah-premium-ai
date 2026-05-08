import { requestJson } from './client';
import type {
  LimitUpActionResponse,
  LimitUpDeliveryItem,
  LimitUpRecipientItem,
  LimitUpRecipientUpdateRequest,
  LimitUpReportDetail,
  LimitUpReportListItem
} from '../types/domain';

export interface LimitUpReportFilters {
  limit?: number;
  keyword?: string;
  status?: string;
  trade_date?: string;
}

export interface LimitUpDeliveryFilters {
  limit?: number;
  keyword?: string;
  status?: string;
  user_id?: number;
}

/**
 * 打板推送管理接口封装。
 * 创建日期：2026-05-08
 * author: sunshengxian
 */
export function fetchLimitUpReports(filters: LimitUpReportFilters = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(filters.limit || 30));
  if (filters.keyword) {
    params.set('keyword', filters.keyword);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }
  if (filters.trade_date) {
    params.set('trade_date', filters.trade_date);
  }
  return requestJson<LimitUpReportListItem[]>(`/api/limit-up-push/reports?${params.toString()}`);
}

export function fetchLimitUpReport(reportId: number) {
  return requestJson<LimitUpReportDetail>(`/api/limit-up-push/reports/${reportId}`);
}

export function generateLatestLimitUpReport() {
  return requestJson<LimitUpActionResponse>('/api/limit-up-push/reports/generate-latest', {
    method: 'POST'
  });
}

export function pushLimitUpReport(reportId: number) {
  return requestJson<LimitUpActionResponse>(`/api/limit-up-push/reports/${reportId}/push`, {
    method: 'POST'
  });
}

export function fetchLimitUpRecipients() {
  return requestJson<LimitUpRecipientItem[]>('/api/limit-up-push/recipients');
}

export function updateLimitUpRecipients(payload: LimitUpRecipientUpdateRequest) {
  return requestJson<LimitUpRecipientItem[]>('/api/limit-up-push/recipients', {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

export function fetchLimitUpDeliveries(filters: LimitUpDeliveryFilters = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(filters.limit || 100));
  if (filters.keyword) {
    params.set('keyword', filters.keyword);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }
  if (filters.user_id) {
    params.set('user_id', String(filters.user_id));
  }
  return requestJson<LimitUpDeliveryItem[]>(`/api/limit-up-push/deliveries?${params.toString()}`);
}
