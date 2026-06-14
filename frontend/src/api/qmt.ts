import { requestJson } from './client';

/**
 * QMT 实盘复盘看板只读接口客户端。
 *
 * 业务意图：对接后端 /api/review/*（仅 admin 有 qmt_review 权限），为「实盘复盘」菜单取数。
 * 金额/比率字段后端以 Decimal 序列化，可能是 number 或字符串，故类型统一声明为 NumLike，
 * 展示前用 utils 的 toNum 归一，避免前端二次推算口径。
 *
 * 创建日期：2026-06-14
 * author: claude
 */

/** Decimal 字段在 JSON 中可能是数字或字符串，统一用此别名，展示层 toNum 归一。 */
export type NumLike = number | string | null;

export interface QmtAccountInfo {
  account_id: string;
  latest_trade_date: string | null;
}

export interface QmtDailySummary {
  trade_date: string;
  has_data: boolean;
  daily_pnl: NumLike;
  float_pnl: NumLike;
  realized_pnl_approx: NumLike;
  daily_return: NumLike;
  total_asset: NumLike;
  buy_count: number;
  sell_count: number;
  buy_amount: NumLike;
  sell_amount: NumLike;
  order_success_rate: NumLike;
  no_fill_count: number;
}

export interface QmtTradeItem {
  traded_id: string;
  trade_date: string;
  ts_code: string;
  name: string | null;
  trade_side: 'BUY' | 'SELL' | string;
  traded_price: NumLike;
  traded_volume: number;
  traded_amount: NumLike;
  traded_time_east8: string | null;
  signal_trade_date: string | null;
  strategy_family: string | null;
  setup: string | null;
  role: string | null;
  market_state: string | null;
  leader_strength_score: NumLike;
}

export interface QmtTradesPage {
  items: QmtTradeItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface QmtPositionItem {
  ts_code: string;
  name: string | null;
  volume: number;
  can_use_volume: number;
  avg_price: NumLike;
  last_price: NumLike;
  market_value: NumLike;
  float_profit: NumLike;
  profit_rate: NumLike;
}

export interface QmtNetWorthPoint {
  trade_date: string;
  nav: NumLike;
  total_asset: NumLike;
  drawdown: NumLike;
  daily_return: NumLike;
}

export interface QmtHistoryStats {
  start_date: string | null;
  end_date: string | null;
  points: QmtNetWorthPoint[];
  cumulative_return: NumLike;
  annualized_return: NumLike;
  max_drawdown: NumLike;
  sharpe: NumLike;
  win_rate: NumLike;
  trading_days: number;
  nav_method: string;
}

export interface QmtSelectionItem {
  trade_date: string;
  target_trade_date: string | null;
  ts_code: string;
  name: string | null;
  tier: string | null;
  board: string | null;
  board_level: number | null;
  limit_type: string | null;
  leader_strength_score: NumLike;
  strength_dim_json: Record<string, unknown> | null;
  role_tags: string[] | null;
  strategy_family: string | null;
  setup: string | null;
  action: string | null;
  sentiment_cycle: string | null;
  market_state: string | null;
  tradable_flag: string | null;
  continuation_prob: NumLike;
  next_day_premium_prob: NumLike;
  boost_conditions: unknown[] | null;
  fail_conditions: unknown[] | null;
  suggested_hold_thesis: string | null;
  selection_reason: string | null;
  seal_ratio_pct: NumLike;
  turnover_rate: NumLike;
  winner_rate: NumLike;
  priority: number | null;
}

export interface QmtSelectionResp {
  trade_date: string | null;
  prompt_version: string | null;
  count: number;
  items: QmtSelectionItem[];
}

/** 拼接查询串，跳过空值，避免后端把空字符串当成有效筛选。 */
function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

/** 已回流账户清单（供顶部账户切换）。 */
export function fetchQmtAccounts() {
  return requestJson<QmtAccountInfo[]>('/api/review/accounts');
}

/** 当日复盘汇总卡片。缺省 account/date 取最新。 */
export function fetchQmtDailySummary(params: { account_id?: string; trade_date?: string }) {
  return requestJson<QmtDailySummary>(`/api/review/daily${buildQuery(params)}`);
}

/** 成交明细分页（含回挂信号侧策略/角色）。 */
export function fetchQmtTrades(params: {
  account_id?: string;
  trade_date?: string;
  side?: string;
  page?: number;
  page_size?: number;
}) {
  return requestJson<QmtTradesPage>(`/api/review/trades${buildQuery(params)}`);
}

/** 指定日收盘持仓（无该日取 ≤该日 最近 CLOSE 日）。 */
export function fetchQmtPositions(params: { account_id?: string; trade_date?: string }) {
  return requestJson<QmtPositionItem[]>(`/api/review/positions${buildQuery(params)}`);
}

/** 历史净值曲线 + 绩效指标。 */
export function fetchQmtHistory(params: { account_id?: string; start?: string; end?: string }) {
  return requestJson<QmtHistoryStats>(`/api/review/history${buildQuery(params)}`);
}

/** 信号选股决策明细（什么信号达标/为什么入选）。缺省取最新信号日。 */
export function fetchQmtSelection(params: { date?: string }) {
  return requestJson<QmtSelectionResp>(`/api/review/selection${buildQuery(params)}`);
}
