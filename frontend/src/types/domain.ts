export interface DatasetInfo {
  name: string;
  label: string;
  description: string;
}

export interface SyncRun {
  id: number;
  dataset: string;
  params_json: string | null;
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | string;
  started_at: string | null;
  finished_at: string | null;
  row_count: number;
  error_message: string | null;
}

export interface SyncRunCreate {
  dataset: string;
  start_date?: string;
  end_date?: string;
  trade_date?: string;
  ts_code?: string;
  type?: string;
}

export interface PremiumItem {
  trade_date: string;
  a_ts_code: string;
  hk_ts_code: string;
  a_name: string | null;
  hk_name: string | null;
  a_close_cny: string | null;
  h_close_hkd: string | null;
  hkd_cny: string | null;
  h_close_cny: string | null;
  ah_ratio: string | null;
  ah_premium_pct: string | null;
  connect_channels: string | null;
  calc_status: string;
  rate_source: string | null;
  rate_fallback: boolean;
  diff_from_official_pct: string | null;
}

export interface PremiumListResponse {
  total: number;
  items: PremiumItem[];
}

export interface PremiumSummaryResponse {
  latest_trade_date: string | null;
  calculated_count: number;
  issue_count: number;
  top_premiums: PremiumItem[];
  bottom_premiums: PremiumItem[];
}

export interface PremiumCalculateRequest {
  start_date: string;
  end_date?: string;
}

export interface PremiumCalculateResponse {
  start_date: string;
  end_date: string;
  calculated_rows: number;
  skipped_not_connect: number;
  issue_rows: number;
}

export interface ChatSession {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageRequest {
  question: string;
  start_date?: string;
  end_date?: string;
  ts_code?: string;
}

export interface ChatMessageResponse {
  answer: string;
  sql: string | null;
  rows: Record<string, unknown>[];
}

export interface ImportResponse {
  imported_rows: number;
}

export interface QueryColumn {
  key: string;
  label: string;
  width: number | null;
}

export interface QueryDatasetInfo {
  name: string;
  label: string;
  description: string;
  date_field: string | null;
  columns: QueryColumn[];
}

export type QueryCellValue = string | number | boolean | null;

export interface DataQueryResponse {
  dataset: string;
  total: number;
  page: number;
  page_size: number;
  columns: QueryColumn[];
  rows: Record<string, QueryCellValue>[];
}

export interface DataQueryParams {
  dataset: string;
  keyword?: string;
  start_date?: string;
  end_date?: string;
  page: number;
  page_size: number;
}
