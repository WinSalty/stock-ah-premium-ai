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

export interface UserInfo {
  id: number;
  username: string;
  role: 'ADMIN' | 'USER' | string;
  is_active: boolean;
  display_name: string | null;
  email: string | null;
  phone: string | null;
  bio: string | null;
  permissions: string[];
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest extends LoginRequest {
  invitation_code: string;
}

export interface AuthTokenResponse {
  token: string;
  user: UserInfo;
}

export interface InvitationCreateRequest {
  note?: string;
}

export interface InvitationResponse {
  id: number;
  code: string;
  created_by_user_id: number | null;
  used_by_user_id: number | null;
  used_at: string | null;
  note: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserUpdateRequest {
  role?: 'ADMIN' | 'USER' | string;
  is_active?: boolean;
  display_name?: string | null;
  email?: string | null;
  phone?: string | null;
  bio?: string | null;
  permissions?: string[];
}

export interface ProfileUpdateRequest {
  display_name?: string | null;
  email?: string | null;
  phone?: string | null;
  bio?: string | null;
}

export interface LlmMetricSummary {
  total: number;
  success_count: number;
  avg_elapsed_ms: number | null;
  max_elapsed_ms: number | null;
  avg_first_chunk_ms: number | null;
}

export interface LlmMetricItem {
  id: number;
  question_id: string;
  user_id: number | null;
  session_id: number | null;
  phase: string;
  provider: string | null;
  model: string | null;
  success: boolean;
  elapsed_ms: number | null;
  first_chunk_ms: number | null;
  output_chars: number;
  chunk_count: number;
  row_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface LlmMetricResponse {
  total: number;
  page: number;
  page_size: number;
  summary: LlmMetricSummary;
  rows: LlmMetricItem[];
}

export interface LlmMetricParams {
  page: number;
  page_size: number;
  question_id?: string;
  provider?: string;
  model?: string;
  phase?: string;
  session_id?: number;
  user_id?: number;
  start_date?: string;
  end_date?: string;
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
  is_hk_connect: boolean;
  connect_channels: string | null;
  metric_direction: PremiumDirection;
  metric_premium_pct: string | null;
  premium_avg_20: string | null;
  premium_avg_60: string | null;
  premium_avg_120: string | null;
  premium_median_60: string | null;
  premium_p20_60: string | null;
  premium_p80_60: string | null;
  premium_percentile_60: string | null;
  premium_deviation_from_60d_avg: string | null;
  watchlist_id: number | null;
  is_watchlist: boolean;
  watchlist_display_name: string | null;
  preferred_direction: PremiumDirection | null;
  target_premium_pct: string | null;
  push_enabled: boolean | null;
  price_alert_enabled: boolean | null;
  price_alert_market: PriceAlertMarket | string | null;
  price_alert_operator: PriceAlertOperator | string | null;
  price_alert_target_price: string | null;
  holding_market: HoldingMarket | string | null;
  distance_to_target_pct: string | null;
  opportunity_status: OpportunityStatus | string | null;
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
  hk_connect_count: number;
  watchlist_count: number;
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
  metric_direction: PremiumDirection;
  metric_premium_pct: string | null;
  premium_avg_20: string | null;
  premium_avg_60: string | null;
  premium_avg_120: string | null;
  premium_median_60: string | null;
  premium_p20_60: string | null;
  premium_p80_60: string | null;
  premium_percentile_60: string | null;
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
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatStoredMessage {
  id: number;
  role: 'user' | 'assistant' | string;
  content: string;
  rows: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatStoredMessage[];
}

export interface ChatMessageRequest {
  question: string;
  display_question?: string;
  start_date?: string;
  end_date?: string;
  ts_code?: string;
  only_watchlist?: boolean;
  llm_model?: ChatModel;
}

export interface ChatMessageResponse {
  answer: string;
  rows: Record<string, unknown>[];
}

export type ChatModel = 'deepseek-v4-flash' | 'deepseek-v4-pro' | 'qwen3.6-max-preview';

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

export type PremiumDirection = 'AH' | 'HA';
export type HoldingMarket = 'A' | 'H' | 'UNKNOWN';
export type OpportunityStatus = 'REACHED' | 'NEAR' | 'WATCH' | 'DATA_ISSUE' | 'NOT_CONNECT';

export interface WatchlistStock {
  id: number;
  user_id: number;
  a_ts_code: string;
  hk_ts_code: string;
  display_name: string | null;
  preferred_direction: PremiumDirection;
  target_premium_pct: string | null;
  push_enabled: boolean;
  price_alert_enabled: boolean;
  price_alert_market: PriceAlertMarket | string;
  price_alert_operator: PriceAlertOperator | string;
  price_alert_target_price: string | null;
  holding_market: HoldingMarket | string;
  sort_order: number;
  note: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WatchlistOpportunity {
  watchlist: WatchlistStock;
  premium: PremiumItem | null;
}

export interface WatchlistCreate {
  a_ts_code: string;
  hk_ts_code: string;
  display_name?: string;
  preferred_direction?: PremiumDirection;
  target_premium_pct?: string | number;
  push_enabled?: boolean;
  price_alert_enabled?: boolean;
  price_alert_market?: PriceAlertMarket;
  price_alert_operator?: PriceAlertOperator;
  price_alert_target_price?: string | number | null;
  holding_market?: HoldingMarket;
  sort_order?: number;
  note?: string;
  is_active?: boolean;
}

export interface WatchlistUpdate {
  display_name?: string | null;
  preferred_direction?: PremiumDirection;
  target_premium_pct?: string | number | null;
  push_enabled?: boolean | null;
  price_alert_enabled?: boolean | null;
  price_alert_market?: PriceAlertMarket | null;
  price_alert_operator?: PriceAlertOperator | null;
  price_alert_target_price?: string | number | null;
  holding_market?: HoldingMarket;
  sort_order?: number;
  note?: string | null;
  is_active?: boolean;
}

export type PriceAlertMarket = 'A' | 'H' | 'UNKNOWN';
export type PriceAlertOperator = 'GTE' | 'LTE';

export interface PushplusBinding {
  is_bound: boolean;
  status: string;
  id?: number;
  user_id?: number;
  username?: string;
  is_active?: boolean;
  friend_id: number | null;
  friend_nick_name: string | null;
  friend_remark: string | null;
  is_follow: boolean | null;
  bound_at: string | null;
}

export interface PushplusQrCodeRequest {
  expire_seconds: number;
  scan_count: number;
}

export interface PushplusQrCodeResponse {
  qr_code_img_url: string;
}

export interface PushplusFriend {
  id: number;
  friend_id: number;
  nick_name: string | null;
  remark: string | null;
  is_follow: boolean;
  create_time: string | null;
}

export interface PushplusBindRequest {
  friend_id: number;
}

export interface AdminPushplusBindRequest extends PushplusBindRequest {
  user_id: number;
}

export interface TestPushRequest {
  title?: string;
  content?: string;
}

export interface TestPushResponse {
  ok: boolean;
  message_id: string | null;
}

export interface AlertEvent {
  id: number;
  user_id: number;
  watchlist_id: number | null;
  event_type: string;
  trading_day: string;
  metric_direction: PremiumDirection | string | null;
  metric_premium_pct: string | null;
  target_premium_pct: string | null;
  price_alert_market: PriceAlertMarket | string | null;
  price_alert_operator: PriceAlertOperator | string | null;
  price_alert_ts_code: string | null;
  last_price: string | null;
  target_price: string | null;
  message_title: string;
  push_status: string;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}
