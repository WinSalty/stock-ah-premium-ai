import { requestJson } from './client';
import type {
  PremiumCalculateRequest,
  PremiumCalculateResponse,
  PremiumListResponse,
  PremiumSummaryResponse
} from '../types/domain';

export interface PremiumQueryParams {
  trade_date?: string;
  keyword?: string;
  channel?: string;
  min_premium?: number;
  max_premium?: number;
  page?: number;
  page_size?: number;
}

export function fetchPremiumSummary() {
  return requestJson<PremiumSummaryResponse>('/api/ah-premiums/summary');
}

export function fetchPremiums(params: PremiumQueryParams) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<PremiumListResponse>(`/api/ah-premiums?${search.toString()}`);
}

export function fetchPremiumTrend(aTsCode: string, hkTsCode: string) {
  return requestJson<PremiumListResponse['items']>(`/api/ah-premiums/${aTsCode}/${hkTsCode}/trend`);
}

export function calculatePremium(payload: PremiumCalculateRequest) {
  return requestJson<PremiumCalculateResponse>('/api/ah-premiums/calculate', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}
