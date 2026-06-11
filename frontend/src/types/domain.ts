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
  can_use_personal_pushplus: boolean;
}

export interface OverviewChartSettings {
  metric_premium: boolean;
  median_60: boolean;
  p20_60: boolean;
  p80_60: boolean;
  target_threshold: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
  remember_login?: boolean;
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

export interface ImageGenerationQuota {
  daily_limit: number;
  used_count: number;
  remaining_count: number;
  quota_date: string;
}

export interface ImageGenerationItem {
  id: number;
  user_id: number;
  username: string | null;
  display_name: string | null;
  prompt: string;
  model: string;
  size: string;
  status: 'GENERATING' | 'READY' | 'FAILED' | string;
  provider: string;
  generation_mode: 'TEXT_TO_IMAGE' | 'IMAGE_REFERENCE' | string;
  image_url: string | null;
  reference_image_url: string | null;
  mime_type: string | null;
  file_size_bytes: number | null;
  file_sha256: string | null;
  reference_mime_type: string | null;
  reference_file_size_bytes: number | null;
  reference_file_sha256: string | null;
  elapsed_ms: number | null;
  error_message: string | null;
  quota: ImageGenerationQuota | null;
  created_at: string;
  updated_at: string;
}

export interface ImageGenerationListResponse {
  total: number;
  items: ImageGenerationItem[];
}

export interface ImageGenerationAdminQuota {
  user_id: number;
  username: string;
  display_name: string | null;
  role: 'ADMIN' | 'USER' | string;
  is_active: boolean;
  daily_limit: number;
  used_count: number;
  remaining_count: number;
  quota_date: string;
  last_reset_at: string | null;
  updated_at: string | null;
}

export interface ImageGenerationErrorLog {
  id: number;
  generation_id: number;
  user_id: number;
  provider: string;
  model: string;
  phase: string;
  retry_count: number;
  status_code: number | null;
  error_type: string;
  user_message: string;
  detail_message: string;
  created_at: string;
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
  conversation_title: string | null;
  user_id: number | null;
  user_name: string | null;
  session_id: number | null;
  phase: string;
  phase_label: string | null;
  phase_description: string | null;
  provider: string | null;
  model: string | null;
  success: boolean;
  elapsed_ms: number | null;
  first_chunk_ms: number | null;
  output_chars: number;
  chunk_count: number;
  row_count: number;
  request_payload_size: number;
  response_content_size: number;
  request_payload_json: string | null;
  response_content: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface LlmMetricResponse {
  total: number;
  page: number;
  page_size: number;
  total_exact: boolean;
  has_more: boolean;
  summary: LlmMetricSummary | null;
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
  include_summary?: boolean;
  include_total?: boolean;
  include_content?: boolean;
}

export type LlmMetricSummaryParams = Omit<
  LlmMetricParams,
  'page' | 'page_size' | 'include_summary' | 'include_total' | 'include_content'
>;

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

export type DividendReinvestmentSyncMode = 'incremental' | 'full' | 'calculate_only';

export interface DividendReinvestmentSyncBatchCreate {
  mode: DividendReinvestmentSyncMode;
  start_date?: string;
  end_date?: string;
  initial_amount?: number;
  cash_div_field?: 'cash_div_tax' | 'cash_div' | string;
  supplement_dividend_by_stock?: boolean;
  supplement_financial_indicator_by_stock?: boolean;
}

export interface SyncRunFilters {
  dataset?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}

export interface DataRangeHealth {
  row_count: number;
  min_date: string | null;
  max_date: string | null;
}

export interface DividendReinvestmentHealth {
  stock_count: number;
  daily_quote: DataRangeHealth;
  dividend: DataRangeHealth;
  daily_basic: DataRangeHealth;
  latest_success_run_id: number | null;
}

export interface DividendReinvestmentRun {
  id: number;
  run_key: string;
  start_date: string;
  end_date: string;
  initial_amount: string;
  cash_div_field: string;
  status: string;
  stock_count: number;
  summary_count: number;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface DividendReinvestmentSummaryItem {
  run_id: number;
  ts_code: string;
  symbol: string | null;
  name: string;
  industry: string | null;
  list_date: string | null;
  start_trade_date: string | null;
  end_trade_date: string | null;
  initial_amount: string;
  initial_price: string | null;
  initial_shares: string | null;
  final_price: string | null;
  final_shares: string | null;
  final_market_value: string | null;
  total_cash_dividend: string | null;
  total_reinvested_amount: string | null;
  total_reinvested_shares: string | null;
  dividend_event_count: number;
  dividend_year_count: number;
  consecutive_dividend_years: number;
  total_return_amount: string | null;
  total_return_pct: string | null;
  annualized_return_pct: string | null;
  ten_year_avg_annualized_return_pct: string | null;
  latest_dividend_yield_ttm: string | null;
  latest_total_mv: string | null;
  latest_pe: string | null;
  latest_pe_ttm: string | null;
  latest_pb: string | null;
  latest_roe: string | null;
  rank_score: string | null;
  data_quality: string;
  data_issue: string | null;
}

export interface DividendReinvestmentSummaryParams {
  keyword?: string;
  industry?: string;
  data_quality?: string;
  min_annualized_return_pct?: number;
  min_ten_year_avg_annualized_return_pct?: number;
  min_dividend_year_count?: number;
  min_consecutive_dividend_years?: number;
  min_latest_dividend_yield_ttm?: number;
  max_latest_pb?: number;
  max_latest_pe?: number;
  max_latest_pe_ttm?: number;
  min_latest_roe?: number;
  sort_by?:
    | 'annualized_return_pct'
    | 'ten_year_avg_annualized_return_pct'
    | 'total_return_pct'
    | 'total_cash_dividend'
    | 'latest_dividend_yield_ttm'
    | 'latest_pb'
    | 'latest_pe'
    | 'latest_pe_ttm'
    | 'latest_roe';
  sort_order?: 'asc' | 'desc';
  page: number;
  page_size: number;
}

export interface DividendReinvestmentSummaryResponse {
  run_id: number | null;
  total: number;
  page: number;
  page_size: number;
  items: DividendReinvestmentSummaryItem[];
}

export interface DividendReinvestmentYearlyItem {
  run_id: number;
  ts_code: string;
  year: number;
  year_end_trade_date: string | null;
  year_end_price: string | null;
  cash_div_per_share: string | null;
  cash_div_amount: string | null;
  stock_div_per_share: string | null;
  stock_div_shares: string | null;
  reinvest_price_avg: string | null;
  reinvested_shares: string | null;
  holding_shares: string | null;
  market_value: string | null;
  return_amount: string | null;
  return_pct: string | null;
  annualized_return_pct: string | null;
  dividend_event_count: number;
  note: string | null;
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
  a_price_alert_enabled: boolean | null;
  a_price_alert_operator: PriceAlertOperator | string | null;
  a_price_alert_target_price: string | null;
  h_price_alert_enabled: boolean | null;
  h_price_alert_operator: PriceAlertOperator | string | null;
  h_price_alert_target_price: string | null;
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

export interface RealtimeQuoteItem {
  market: string;
  symbol: string;
  last_price: string | null;
  currency: string;
  quote_time: string | null;
  source: string | null;
  quality: string;
}

export interface RealtimePremiumItem {
  a_ts_code: string;
  hk_ts_code: string;
  a_name: string | null;
  hk_name: string | null;
  display_name: string | null;
  a_last_price: string | null;
  hk_last_price: string | null;
  hkd_cny_rate: string | null;
  ah_ratio: string | null;
  ah_premium_pct: string | null;
  ha_ratio: string | null;
  ha_premium_pct: string | null;
  metric_direction: PremiumDirection;
  metric_premium_pct: string | null;
  target_premium_pct: string | null;
  distance_to_target_pct: string | null;
  opportunity_status: OpportunityStatus | string | null;
  quote_quality: string;
  is_realtime: boolean;
  source: string | null;
  calculated_at: string;
  a_quote: RealtimeQuoteItem | null;
  hk_quote: RealtimeQuoteItem | null;
  fx_quote: RealtimeQuoteItem | null;
  watchlist_id: number | null;
  is_watchlist: boolean;
}

export interface RealtimePremiumListResponse {
  total: number;
  items: RealtimePremiumItem[];
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

/**
 * Agent 单步工具执行轨迹摘要。
 * summary 为工具启动时面向用户的一句话（如"查询：自选股机会"），
 * result_summary 为执行结果摘要（如"返回 30 行"），elapsed_ms 为该步耗时毫秒数。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
export interface ToolTraceItem {
  tool: string;
  summary: string;
  result_summary: string;
  ok: boolean;
  elapsed_ms: number;
}

/**
 * 图表规格（Agent render_chart 工具登记的 spec）。
 * 本阶段仅做存储透传不渲染，故定义为宽松类型；阶段 4 接入 ECharts 时再细化字段约束。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
export interface ChartSpec {
  chart_type: string;
  title: string;
  [key: string]: unknown;
}

export interface ChatStoredMessage {
  id: number;
  role: 'user' | 'assistant' | string;
  content: string;
  created_at: string;
  updated_at: string;
  // 以下两个字段为 Agent 引擎新增，仅 assistant 消息携带；
  // 历史旧数据可能缺省，前端需按空数组兜底（向后兼容口径）。
  charts?: ChartSpec[];
  tool_trace?: ToolTraceItem[];
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatStoredMessage[];
}

export interface ChatSessionBatchDeleteRequest {
  session_ids: number[];
}

export interface ChatSessionBatchDeleteResponse {
  deleted_count: number;
}

export interface ChatMessageRequest {
  question: string;
  display_question?: string;
  start_date?: string;
  end_date?: string;
  ts_code?: string;
  only_watchlist?: boolean;
  // Agent 化后服务端统一使用 agent_model，该字段仅作接口兼容保留，前端不再发送。
  llm_model?: ChatModel;
  threshold_recommendation?: ThresholdRecommendationContext;
}

export interface ThresholdRecommendationContext {
  name?: string | null;
  a_ts_code?: string | null;
  hk_ts_code?: string | null;
  direction?: PremiumDirection | null;
  holding_market?: string | null;
  target_premium_pct?: number | null;
  metric_premium_pct?: number | null;
  ah_premium_pct?: number | null;
  ha_premium_pct?: number | null;
  distance_to_target_pct?: number | null;
  premium_median_60?: number | null;
  premium_p20_60?: number | null;
  premium_p80_60?: number | null;
  premium_percentile_60?: number | null;
  connect_channels?: string | null;
}

export interface ChatMessageResponse {
  message_id?: number | null;
  answer: string;
}

export interface ChatTurnExportItem {
  question: string;
  answer: string;
}

export type ChatModel = 'deepseek-v4-flash' | 'deepseek-v4-pro' | 'qwen3.6-flash';

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
export type WatchlistTargetType = 'PAIR' | 'A_ONLY' | 'H_ONLY';

export interface WatchlistStock {
  id: number;
  user_id: number;
  target_type: WatchlistTargetType | string;
  target_key: string;
  a_ts_code: string | null;
  hk_ts_code: string | null;
  display_name: string | null;
  preferred_direction: PremiumDirection;
  target_premium_pct: string | null;
  push_enabled: boolean;
  a_price_alert_enabled: boolean;
  a_price_alert_operator: PriceAlertOperator | string;
  a_price_alert_target_price: string | null;
  h_price_alert_enabled: boolean;
  h_price_alert_operator: PriceAlertOperator | string;
  h_price_alert_target_price: string | null;
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
  single_quote: RealtimeQuoteItem | null;
}

export interface WatchlistCreate {
  target_type?: WatchlistTargetType;
  a_ts_code?: string | null;
  hk_ts_code?: string | null;
  display_name?: string;
  preferred_direction?: PremiumDirection;
  target_premium_pct?: string | number;
  push_enabled?: boolean;
  a_price_alert_enabled?: boolean;
  a_price_alert_operator?: PriceAlertOperator;
  a_price_alert_target_price?: string | number | null;
  h_price_alert_enabled?: boolean;
  h_price_alert_operator?: PriceAlertOperator;
  h_price_alert_target_price?: string | number | null;
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
  a_price_alert_enabled?: boolean | null;
  a_price_alert_operator?: PriceAlertOperator | null;
  a_price_alert_target_price?: string | number | null;
  h_price_alert_enabled?: boolean | null;
  h_price_alert_operator?: PriceAlertOperator | null;
  h_price_alert_target_price?: string | number | null;
  holding_market?: HoldingMarket;
  sort_order?: number;
  note?: string | null;
  is_active?: boolean;
}

export interface WatchlistCandidate {
  target_type: WatchlistTargetType | string;
  a_ts_code: string | null;
  hk_ts_code: string | null;
  name: string;
  display_label: string;
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

export interface PushplusMessageLog {
  id: number;
  user_id: number;
  username: string | null;
  display_name: string | null;
  alert_event_id: number | null;
  recipient_type: string;
  recipient_friend_id: number | null;
  recipient_name: string | null;
  message_title: string;
  message_content: string;
  push_channel: string;
  push_status: string;
  push_message_id: string | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LimitUpRecipientItem {
  user_id: number;
  username: string;
  display_name: string | null;
  enabled: boolean;
  weekend_replay_enabled: boolean;
  can_push: boolean;
  binding_name: string | null;
}

export interface LimitUpRecipientUpdateRequest {
  recipients: Array<{ user_id: number; enabled: boolean; weekend_replay_enabled: boolean }>;
}

export interface LimitUpPushRequest {
  send_all: boolean;
  user_ids: number[];
}

export interface LimitUpReportListItem {
  id: number;
  trade_date: string;
  title: string;
  status: string;
  model: string;
  prompt_version: string;
  data_snapshot_hash: string;
  generated_at: string | null;
  created_at: string;
  updated_at: string;
  error_message: string | null;
}

export interface LimitUpReportDetail extends LimitUpReportListItem {
  content_html: string | null;
  content_markdown: string | null;
  context: Record<string, unknown> | null;
  data_quality: Array<Record<string, unknown>>;
  stage_quality: Array<Record<string, unknown>>;
  selected_chain_stocks: Array<Record<string, unknown>>;
  selected_high_board_stocks: Array<Record<string, unknown>>;
}

export interface LimitUpShareCreateRequest {
  expires_in_hours: number | null;
}

export interface LimitUpShareResponse {
  token: string;
  share_url: string;
  expires_at: string | null;
  permanent: boolean;
}

export interface LimitUpShareItem extends LimitUpShareResponse {
  id: number;
  status: 'ACTIVE' | 'EXPIRED' | 'REVOKED' | string;
  view_count: number;
  revoked_at: string | null;
  last_viewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LimitUpPublicReportDetail {
  title: string;
  trade_date: string;
  content_html: string;
  generated_at: string | null;
  expires_at: string | null;
  permanent: boolean;
}

export interface LimitUpDeliveryItem {
  id: number;
  analysis_id: number;
  trade_date: string | null;
  user_id: number;
  username: string | null;
  display_name: string | null;
  scheduled_kind: string;
  scheduled_at: string;
  status: string;
  pushplus_message_log_id: number | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LimitUpActionResponse {
  ok: boolean;
  message: string;
  report_id: number | null;
  delivery_count: number;
}

export interface NineTurnReportListItem {
  id: number;
  trade_date: string;
  freq: string;
  title: string;
  status: string;
  model: string;
  prompt_version: string;
  data_snapshot_hash: string;
  generated_at: string | null;
  created_at: string;
  updated_at: string;
  error_message: string | null;
}

export interface NineTurnReportDetail extends NineTurnReportListItem {
  content_html: string | null;
  content_markdown: string | null;
  context: Record<string, unknown> | null;
  data_quality: Array<Record<string, unknown>>;
}

export interface NineTurnDeliveryItem {
  id: number;
  analysis_id: number;
  trade_date: string | null;
  user_id: number;
  username: string | null;
  display_name: string | null;
  scheduled_kind: string;
  scheduled_at: string;
  status: string;
  pushplus_message_log_id: number | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NineTurnActionResponse {
  ok: boolean;
  message: string;
  report_id: number | null;
  delivery_count: number;
  xueqiu_record_id: number | null;
}

export interface XueqiuCredentialRequest {
  enabled: boolean;
  cookie_text: string;
  user_agent: string;
  mp_base_url?: string;
  referer_url?: string;
  expires_at?: string | null;
}

export interface XueqiuCredentialSummary {
  configured: boolean;
  enabled: boolean;
  cookie_preview: string | null;
  user_agent: string | null;
  mp_base_url: string | null;
  referer_url: string | null;
  expires_at: string | null;
  last_verified_at: string | null;
  last_error: string | null;
  updated_at: string | null;
}

export interface XueqiuDraftPreview {
  analysis_id: number;
  trade_date: string;
  source_title: string;
  title: string;
  content_html: string;
  content_text: string;
}

export interface XueqiuPublishRequest {
  analysis_id?: number | null;
  publish: boolean;
  force: boolean;
  cover_pic?: string | null;
}

export interface XueqiuChatAnswerPublishRequest {
  message_id: number;
  publish: boolean;
  force: boolean;
  cover_pic?: string | null;
  title?: string | null;
}

export interface XueqiuPublishSettingRequest {
  scheduler_enabled: boolean;
  auto_publish: boolean;
  poll_hours: string;
  poll_minutes: string;
  default_cover_pic?: string | null;
}

export interface XueqiuPublishSettingSummary extends XueqiuPublishSettingRequest {
  effective_scheduler_registered: boolean;
  updated_at: string | null;
}

export interface XueqiuActionResponse {
  ok: boolean;
  message: string;
  record_id: number | null;
  article_url: string | null;
  draft_id: string | null;
  status_id: string | null;
}

export interface XueqiuPublishRecordItem {
  id: number;
  analysis_id: number | null;
  nine_turn_analysis_id: number | null;
  chat_message_id: number | null;
  source_type: string;
  trade_date: string | null;
  publish_mode: string;
  status: string;
  title: string;
  draft_id: string | null;
  status_id: string | null;
  article_url: string | null;
  error_message: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface XueqiuPublishRecordDetail extends XueqiuPublishRecordItem {
  content_html: string;
  cover_pic: string | null;
  request_payload_json: string | null;
  response_json: string | null;
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
