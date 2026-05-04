export interface DatasetInfo {
  name: string;
  label: string;
  description: string;
  supports_date_range: boolean;
  supports_incremental: boolean;
  supports_full_sync: boolean;
  default_full_start_date: string | null;
  sync_strategy: string;
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
  mode?: 'manual' | 'incremental' | 'full';
  start_date?: string;
  end_date?: string;
  trade_date?: string;
  ts_code?: string;
  type?: string;
}

export interface SyncBatchCreate {
  mode: 'incremental' | 'full';
  start_date?: string;
  end_date?: string;
}

export interface SyncRunFilters {
  dataset?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}

export interface PremiumItem {
  trade_date: string;
  a_ts_code: string;
  hk_ts_code: string;
  a_name: string | null;
  hk_name: string | null;
  a_close: string | null;
  a_pct_chg: string | null;
  hk_close: string | null;
  hk_pct_chg: string | null;
  ah_ratio: string | null;
  ah_premium_pct: string | null;
  ha_ratio: string | null;
  ha_premium_pct: string | null;
  is_realtime: boolean;
  data_source: string;
  source_updated_at: string | null;
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

export interface PremiumPairOption {
  a_ts_code: string;
  hk_ts_code: string;
  a_name: string | null;
  hk_name: string | null;
  latest_trade_date: string | null;
}

export interface PremiumOfficialTrendPoint {
  trade_date: string;
  a_ts_code: string;
  hk_ts_code: string;
  a_name: string | null;
  hk_name: string | null;
  ah_ratio: string | null;
  ah_premium_pct: string | null;
  ha_ratio: string | null;
  ha_premium_pct: string | null;
  is_realtime?: boolean;
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
