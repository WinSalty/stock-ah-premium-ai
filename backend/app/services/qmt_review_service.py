"""QMT 实盘复盘看板只读聚合查询服务。

业务意图：对执行侧回流落库的 qmt_* 四表做只读聚合，产出看板要的「当日汇总 / 成交明细 / 持仓 /
历史净值与绩效」。口径单一来源（前端不二次推算）。

口径与边界（诚实标注）：
- 当日盈亏 daily_pnl 取 qmt_account_daily 已回填值；缺则用 total_asset 与上一交易日 CLOSE 差分（剔出入金）现算。
- 已实现盈亏为近似（总盈亏 − 浮动盈亏）；精确按 FIFO 撮合的交易级盈亏待「数据底座」阶段补。
- 历史净值 NAV 为 total_asset 简单归一（未剔出入金）；精确 TWR 待出入金台账（qmt_cash_flow）落地。
- 风险指标（夏普/回撤/胜率）由 CLOSE 总资产日序列现算，rf=0、年化按 √252（夏普）/ 简单复利（年化收益）。
- 账户范围：当前仅 admin 可见看板，默认返回全部账户；非 admin 多账户隔离待 qmt_account 绑定表落地。

创建日期：2026-06-14
author: claude
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models.market import AStockBasic
from app.db.models.notification import LimitUpSelectedStock
from app.db.models.qmt import QmtAccountDaily, QmtOrder, QmtPositionSnapshot, QmtTrade
from app.schemas.qmt_review import (
    QmtAccountInfo,
    QmtDailySummary,
    QmtHistoryStats,
    QmtNetWorthPoint,
    QmtPositionItem,
    QmtTradeItem,
    QmtTradesPage,
)

_CLOSE = "CLOSE"
_DPL = Decimal("0")


def _dec(v: Any) -> Decimal | None:
    """安全转 Decimal（保 None）。"""
    return None if v is None else (v if isinstance(v, Decimal) else Decimal(str(v)))


def _round(v: float | None, n: int = 6) -> Decimal | None:
    """float → DECIMAL，None 透传。"""
    return None if v is None else Decimal(str(round(v, n)))


class QmtReviewService:
    """QMT 复盘只读聚合服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- 账户 ----------------
    def list_accounts(self) -> list[QmtAccountInfo]:
        """已回流账户清单 + 各自最新交易日（供顶部切换）。"""
        rows = self.db.execute(
            select(
                QmtAccountDaily.account_id,
                func.max(QmtAccountDaily.trade_date),
            ).group_by(QmtAccountDaily.account_id)
        ).all()
        # 兜底：若 account_daily 还没数据，用成交表的账户。
        if not rows:
            rows = self.db.execute(
                select(QmtTrade.account_id, func.max(QmtTrade.trade_date)).group_by(QmtTrade.account_id)
            ).all()
        return [QmtAccountInfo(account_id=a, latest_trade_date=d) for a, d in rows]

    def default_account(self) -> str | None:
        """默认账户：取最新有数据的账户。"""
        accounts = self.list_accounts()
        if not accounts:
            return None
        accounts.sort(key=lambda a: a.latest_trade_date or date.min, reverse=True)
        return accounts[0].account_id

    def latest_trade_date(self, account_id: str) -> date | None:
        """该账户已回流的最新交易日。"""
        return self.db.execute(
            select(func.max(QmtAccountDaily.trade_date)).where(QmtAccountDaily.account_id == account_id)
        ).scalar_one_or_none() or self.db.execute(
            select(func.max(QmtTrade.trade_date)).where(QmtTrade.account_id == account_id)
        ).scalar_one_or_none()

    # ---------------- 当日汇总 ----------------
    def daily_summary(self, account_id: str, trade_date: date) -> QmtDailySummary:
        """当日复盘汇总卡片。"""
        acct = self.db.execute(
            select(QmtAccountDaily).where(
                QmtAccountDaily.account_id == account_id,
                QmtAccountDaily.trade_date == trade_date,
                QmtAccountDaily.snapshot_type == _CLOSE,
            )
        ).scalar_one_or_none()

        # 浮动盈亏：当日 CLOSE 持仓 float_profit 求和。
        float_pnl = self.db.execute(
            select(func.coalesce(func.sum(QmtPositionSnapshot.float_profit), _DPL)).where(
                QmtPositionSnapshot.account_id == account_id,
                QmtPositionSnapshot.trade_date == trade_date,
                QmtPositionSnapshot.snapshot_type == _CLOSE,
            )
        ).scalar_one()

        # 当日总盈亏：优先回填值，缺则用 total_asset 与上一交易日 CLOSE 差分（剔出入金）。
        daily_pnl = acct.daily_pnl if (acct and acct.daily_pnl is not None) else None
        if daily_pnl is None and acct is not None:
            prev = self.db.execute(
                select(QmtAccountDaily.total_asset)
                .where(
                    QmtAccountDaily.account_id == account_id,
                    QmtAccountDaily.snapshot_type == _CLOSE,
                    QmtAccountDaily.trade_date < trade_date,
                )
                .order_by(QmtAccountDaily.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if prev is not None:
                daily_pnl = acct.total_asset - prev - (acct.net_cash_flow or _DPL)

        realized = (daily_pnl - float_pnl) if (daily_pnl is not None and float_pnl is not None) else None

        # 成交统计（按方向）。
        buy_cnt, buy_amt = self._trade_side_stats(account_id, trade_date, "BUY")
        sell_cnt, sell_amt = self._trade_side_stats(account_id, trade_date, "SELL")

        # 下单成功率 / 买不进：基于当日 BUY 委托。
        success_rate, no_fill = self._order_stats(account_id, trade_date)

        return QmtDailySummary(
            trade_date=trade_date,
            has_data=acct is not None or buy_cnt + sell_cnt > 0,
            daily_pnl=_dec(daily_pnl),
            float_pnl=_dec(float_pnl),
            realized_pnl_approx=_dec(realized),
            daily_return=_dec(acct.daily_return) if acct else None,
            total_asset=_dec(acct.total_asset) if acct else None,
            buy_count=buy_cnt,
            sell_count=sell_cnt,
            buy_amount=_dec(buy_amt),
            sell_amount=_dec(sell_amt),
            order_success_rate=_dec(success_rate),
            no_fill_count=no_fill,
        )

    def _trade_side_stats(self, account_id: str, trade_date: date, side: str) -> tuple[int, Decimal]:
        """某方向当日成交笔数与成交额（额缺则用价×量兜底）。"""
        cnt, amt = self.db.execute(
            select(
                func.count(QmtTrade.id),
                func.coalesce(
                    func.sum(
                        func.coalesce(QmtTrade.traded_amount, QmtTrade.traded_price * QmtTrade.traded_volume)
                    ),
                    _DPL,
                ),
            ).where(
                QmtTrade.account_id == account_id,
                QmtTrade.trade_date == trade_date,
                QmtTrade.trade_side == side,
            )
        ).one()
        return int(cnt or 0), amt or _DPL

    def _order_stats(self, account_id: str, trade_date: date) -> tuple[float | None, int]:
        """当日 BUY 委托的下单成功率与买不进只数。

        成功率 = 有成交(traded_volume>0)的委托数 / 全部委托数；买不进 = 终态失败/已撤且零成交的委托数。
        """
        rows = self.db.execute(
            select(QmtOrder.order_status, QmtOrder.traded_volume).where(
                QmtOrder.account_id == account_id,
                QmtOrder.trade_date == trade_date,
                QmtOrder.trade_side == "BUY",
            )
        ).all()
        if not rows:
            return None, 0
        total = len(rows)
        filled = sum(1 for _, tv in rows if (tv or 0) > 0)
        no_fill = sum(
            1 for st, tv in rows if (tv or 0) == 0 and st in ("CANCELLED", "REJECTED", "ERROR")
        )
        return (filled / total) if total else None, no_fill

    # ---------------- 成交明细 ----------------
    def trades(
        self,
        account_id: str,
        trade_date: date | None,
        side: str | None,
        page: int,
        page_size: int,
    ) -> QmtTradesPage:
        """成交明细分页 + 回挂信号。"""
        conds = [QmtTrade.account_id == account_id]
        if trade_date is not None:
            conds.append(QmtTrade.trade_date == trade_date)
        if side in ("BUY", "SELL"):
            conds.append(QmtTrade.trade_side == side)

        total = self.db.execute(select(func.count(QmtTrade.id)).where(*conds)).scalar_one()
        rows = (
            self.db.execute(
                select(QmtTrade)
                .where(*conds)
                .order_by(QmtTrade.traded_time_east8.desc().nullslast(), QmtTrade.id.desc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        # 回挂信号：按 (signal_trade_date, ts_code) 批量查 limit_up_selected_stock；名称查 a_stock_basic。
        sig_map = self._signal_map([(r.signal_trade_date, r.ts_code) for r in rows])
        name_map = self._name_map([r.ts_code for r in rows])

        items = []
        for r in rows:
            sig = sig_map.get((r.signal_trade_date, r.ts_code))
            items.append(
                QmtTradeItem(
                    traded_id=r.traded_id,
                    trade_date=r.trade_date,
                    ts_code=r.ts_code,
                    name=(sig.get("name") if sig else None) or name_map.get(r.ts_code),
                    trade_side=r.trade_side,
                    traded_price=r.traded_price,
                    traded_volume=r.traded_volume,
                    traded_amount=r.traded_amount,
                    traded_time_east8=r.traded_time_east8,
                    signal_trade_date=r.signal_trade_date,
                    strategy_family=sig.get("strategy_family") if sig else None,
                    setup=sig.get("setup") if sig else None,
                    role=sig.get("role") if sig else None,
                    market_state=sig.get("market_state") if sig else None,
                    leader_strength_score=sig.get("leader_strength_score") if sig else None,
                )
            )
        return QmtTradesPage(items=items, total=int(total or 0), page=page, page_size=page_size)

    def _signal_map(self, keys: list[tuple[date | None, str]]) -> dict[tuple[date | None, str], dict[str, Any]]:
        """批量取回挂信号：(signal_trade_date, ts_code) → 信号字段 dict。"""
        valid = {(d, c) for d, c in keys if d is not None and c}
        if not valid:
            return {}
        dates = {d for d, _ in valid}
        codes = {c for _, c in valid}
        rows = self.db.execute(
            select(LimitUpSelectedStock).where(
                LimitUpSelectedStock.trade_date.in_(dates),
                LimitUpSelectedStock.ts_code.in_(codes),
            )
        ).scalars().all()
        out: dict[tuple[date | None, str], dict[str, Any]] = {}
        for s in rows:
            key = (s.trade_date, s.ts_code)
            if key in valid and key not in out:  # 同键多版本取首个
                role = s.role_tags[0] if isinstance(s.role_tags, list) and s.role_tags else None
                out[key] = {
                    "name": s.name,
                    "strategy_family": s.strategy_family,
                    "setup": s.setup,
                    "role": role,
                    "market_state": s.market_state,
                    "leader_strength_score": s.leader_strength_score,
                }
        return out

    def _name_map(self, codes: list[str]) -> dict[str, str]:
        """ts_code → 名称（a_stock_basic 兜底）。"""
        uniq = {c for c in codes if c}
        if not uniq:
            return {}
        rows = self.db.execute(
            select(AStockBasic.ts_code, AStockBasic.name).where(AStockBasic.ts_code.in_(uniq))
        ).all()
        return {c: n for c, n in rows if n}

    # ---------------- 持仓 ----------------
    def positions(self, account_id: str, trade_date: date) -> list[QmtPositionItem]:
        """指定日 CLOSE 持仓（无该日则取 ≤该日 的最近 CLOSE 日）。"""
        eff = self.db.execute(
            select(func.max(QmtPositionSnapshot.trade_date)).where(
                QmtPositionSnapshot.account_id == account_id,
                QmtPositionSnapshot.snapshot_type == _CLOSE,
                QmtPositionSnapshot.trade_date <= trade_date,
            )
        ).scalar_one_or_none()
        if eff is None:
            return []
        rows = self.db.execute(
            select(QmtPositionSnapshot).where(
                QmtPositionSnapshot.account_id == account_id,
                QmtPositionSnapshot.snapshot_type == _CLOSE,
                QmtPositionSnapshot.trade_date == eff,
                QmtPositionSnapshot.volume > 0,
            )
        ).scalars().all()
        name_map = self._name_map([r.ts_code for r in rows])
        return [
            QmtPositionItem(
                ts_code=r.ts_code,
                name=name_map.get(r.ts_code),
                volume=r.volume,
                can_use_volume=r.can_use_volume,
                avg_price=r.avg_price or r.open_price,
                last_price=r.last_price,
                market_value=r.market_value,
                float_profit=r.float_profit,
                profit_rate=r.profit_rate,
            )
            for r in rows
        ]

    # ---------------- 历史净值与绩效 ----------------
    def history(self, account_id: str, start: date | None, end: date | None) -> QmtHistoryStats:
        """CLOSE 总资产序列 → 归一净值 + 回撤 + 绩效指标。"""
        conds = [QmtAccountDaily.account_id == account_id, QmtAccountDaily.snapshot_type == _CLOSE]
        if start is not None:
            conds.append(QmtAccountDaily.trade_date >= start)
        if end is not None:
            conds.append(QmtAccountDaily.trade_date <= end)
        rows = self.db.execute(
            select(QmtAccountDaily.trade_date, QmtAccountDaily.total_asset)
            .where(*conds)
            .order_by(QmtAccountDaily.trade_date.asc())
        ).all()
        if not rows:
            return QmtHistoryStats(points=[], trading_days=0)

        base = float(rows[0][1]) or 1.0
        points: list[QmtNetWorthPoint] = []
        navs: list[float] = []
        rets: list[float] = []
        peak = -math.inf
        prev_ta: float | None = None
        for d, ta in rows:
            ta_f = float(ta)
            nav = ta_f / base if base else 1.0
            peak = max(peak, nav)
            dd = (nav / peak - 1.0) if peak > 0 else 0.0
            dr = (ta_f / prev_ta - 1.0) if (prev_ta and prev_ta != 0) else None
            if dr is not None:
                rets.append(dr)
            navs.append(nav)
            points.append(
                QmtNetWorthPoint(
                    trade_date=d,
                    nav=_round(nav, 6),
                    total_asset=_dec(ta),
                    drawdown=_round(dd, 6),
                    daily_return=_round(dr, 6) if dr is not None else None,
                )
            )
            prev_ta = ta_f

        n = len(points)
        cumulative = navs[-1] - 1.0 if navs else None
        max_dd = min((float(p.drawdown) for p in points), default=0.0)
        win_rate = (sum(1 for r in rets if r > 0) / len(rets)) if rets else None
        sharpe = None
        if len(rets) > 1:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            std = math.sqrt(var)
            sharpe = (mean / std * math.sqrt(252)) if std > 0 else None
        annualized = None
        if cumulative is not None and n > 1:
            annualized = (1.0 + cumulative) ** (252.0 / n) - 1.0

        return QmtHistoryStats(
            start_date=rows[0][0],
            end_date=rows[-1][0],
            points=points,
            cumulative_return=_round(cumulative, 6),
            annualized_return=_round(annualized, 6),
            max_drawdown=_round(max_dd, 6),
            sharpe=_round(sharpe, 4),
            win_rate=_round(win_rate, 4),
            trading_days=n,
        )
