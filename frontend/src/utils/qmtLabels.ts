/**
 * QMT 实盘复盘看板：后端码值（英文枚举）→ 中文展示标签。
 *
 * 业务意图：信号侧/执行侧落库的是英文枚举（strategy_family/tier/role/action 等，便于跨服务契约稳定），
 * 前端展示一律用中文。映射口径取自后端权威定义（limit_up_leader_scoring_service / EntryAction），
 * 未知码值回退原值（cn() 兜底），保证不丢信息、不报错。
 *
 * 创建日期：2026-06-14
 * author: claude
 */

/** 战法族：DABAN/BANLU/DIXI（信号侧 _STRATEGY_CN）；SELL 为执行侧卖出决策族。 */
export const STRATEGY_CN: Record<string, string> = {
  DABAN: '打板',
  BANLU: '半路',
  DIXI: '低吸',
  SELL: '卖出'
};

/** 入选层级：FIRST_BOARD/CHAIN/HIGH_BOARD（limit_up_watchlist tier）。 */
export const TIER_CN: Record<string, string> = {
  FIRST_BOARD: '首板',
  CHAIN: '连板',
  HIGH_BOARD: '高位板'
};

/** 角色：龙头战法增强层角色枚举（limit_up_leader_scoring_service）。 */
export const ROLE_CN: Record<string, string> = {
  MAIN_LEADER: '总龙头',
  SECTOR_LEADER: '板块龙头',
  MID_ARMY: '中军',
  ASSIST: '助攻',
  STRAGGLER: '跟风'
};

/** 建仓/卖出动作：EntryAction + 执行侧卖出动作。 */
export const ACTION_CN: Record<string, string> = {
  CHASE_LIMIT_UP: '打板跟买',
  CHASE_AUCTION_STRONG: '竞价强开',
  DIP_BUY_MA: '均线低吸',
  LEADER_PULLBACK: '龙回头',
  SKIP: '放弃',
  SELL_CLEAR: '清仓',
  SELL_REDUCE: '减仓',
  HOLD: '续持',
  SELL_SUBMIT: '卖出'
};

/** 可成交性：tradable_flag。 */
export const TRADABLE_CN: Record<string, string> = {
  TRADABLE: '可买',
  WATCH: '观察',
  NON_TRADABLE: '不可买'
};

/** 强度六维子分维度键（strength_dim_json.subscores）。 */
export const DIM_CN: Record<string, string> = {
  seal: '封板',
  money: '资金',
  theme: '题材',
  height: '高度',
  position: '卡位',
  recognition: '辨识度'
};

/** 码值 → 中文；未知码值回退原值（不丢信息）。 */
export function cn(map: Record<string, string>, v: string | null | undefined): string {
  if (v == null || v === '') return '';
  return map[v] ?? v;
}
