import { requestJson } from './client';
import type {
  PremiumCalculateRequest,
  PremiumCalculateResponse,
  PremiumListResponse,
  PremiumOfficialTrendPoint,
  PremiumPairOption,
  PremiumSummaryResponse,
  PremiumDirection,
  RealtimePremiumListResponse
} from '../types/domain';

export interface PremiumQueryParams {
  trade_date?: string;
  keyword?: string;
  channel?: string;
  min_premium?: number;
  max_premium?: number;
  min_ha_premium?: number;
  max_ha_premium?: number;
  direction?: PremiumDirection;
  only_hk_connect?: boolean;
  only_watchlist?: boolean;
  page?: number;
  page_size?: number;
}

export function fetchPremiumSummary() {
  return requestJson<PremiumSummaryResponse>('/api/ah-premiums/summary');
}

export function fetchPremiumPairs(keyword?: string) {
  const search = new URLSearchParams();
  if (keyword) {
    search.set('keyword', keyword);
  }
  search.set('limit', '300');
  return requestJson<PremiumPairOption[]>(`/api/ah-premiums/pairs?${search.toString()}`);
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

export function fetchRealtimePremiums(params: Pick<PremiumQueryParams, 'only_watchlist' | 'page_size'> = {}) {
  const search = new URLSearchParams();
  if (params.only_watchlist !== undefined) {
    search.set('only_watchlist', String(params.only_watchlist));
  }
  if (params.page_size !== undefined) {
    search.set('page_size', String(params.page_size));
  }
  return requestJson<RealtimePremiumListResponse>(`/api/ah-premiums/realtime?${search.toString()}`);
}

export function fetchPremiumTrend(aTsCode: string, hkTsCode: string, direction: PremiumDirection = 'HA') {
  const search = new URLSearchParams({ direction });
  return requestJson<PremiumListResponse['items']>(
    `/api/ah-premiums/${aTsCode}/${hkTsCode}/trend?${search.toString()}`
  );
}

export function fetchOfficialPremiumTrend(
  aTsCode: string,
  hkTsCode: string,
  direction: PremiumDirection = 'HA'
) {
  const search = new URLSearchParams({ a_ts_code: aTsCode, hk_ts_code: hkTsCode, direction });
  return requestJson<PremiumOfficialTrendPoint[]>(`/api/ah-premiums/official-trend?${search.toString()}`);
}

export function calculatePremium(payload: PremiumCalculateRequest) {
  return requestJson<PremiumCalculateResponse>('/api/ah-premiums/calculate', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}
