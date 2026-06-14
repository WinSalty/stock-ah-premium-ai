"""本地演示数据种子：为 QMT 实盘复盘看板灌入一套自洽的假数据（仅本机调试用，勿上生产）。

业务意图：在本地 MySQL 造一个演示账户 8881000123，覆盖看板四张表——
  - qmt_account_daily：约 14 个交易日的收盘总资产曲线（含一段回撤再创新高），驱动历史净值/回撤/夏普/胜率；
  - qmt_trade：最新交易日买入 6 只「信号股」(signal_trade_date=2026-06-12，可 join 真实 limit_up_selected_stock
    展示战法/角色标签) + 2 笔卖出；前一交易日另有少量成交；
  - qmt_order：最新日买入委托 6 成交 + 2 撤单（演示「下单成功率 75% / 买不进 2 只」）；
  - qmt_position_snapshot：最新日收盘持仓 6 只（浮盈浮亏红绿混合）。

幂等：每次运行先清掉该演示账户旧数据再写，便于反复执行。证券名称走库内 a_stock_basic（已有 5525 条）。

创建日期：2026-06-14
author: claude
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.db.models.qmt import (
    QmtAccountDaily,
    QmtDecisionLog,
    QmtOrder,
    QmtPositionSnapshot,
    QmtTrade,
)
from app.db.session import SessionLocal

ACCOUNT = "8881000123"          # 演示资金账号
LATEST = date(2026, 6, 15)      # 最新交易日（= 信号 target_trade_date）
SIGNAL_DAY = date(2026, 6, 12)  # 信号日 T（库内 limit_up_selected_stock 真实存在该日）


def _trading_days_back(end: date, count: int) -> list[date]:
    """从 end 往前取 count 个工作日（跳过周末），升序返回。"""
    days: list[date] = []
    cur = end
    while len(days) < count:
        if cur.weekday() < 5:  # 0=周一..4=周五
            days.append(cur)
        cur -= timedelta(days=1)
    return sorted(days)


# 收盘总资产曲线：起点 100w，逐日盈亏（含 d3~d7 回撤段，末日 +20970），驱动净值/回撤/胜率。
PNL_DELTAS = [8000, 12000, -5000, 15000, -9000, -14000, -6000, 4000, 11000, 9000, -3000, 18000, 20970]

# 最新日买入的 6 只信号股：(代码, 成本价, 数量, 收盘现价) —— 现价相对成本红绿混合。
BUYS = [
    ("001257.SZ", Decimal("18.20"), 3000, Decimal("20.02")),
    ("002830.SZ", Decimal("12.50"), 4000, Decimal("12.10")),
    ("002971.SZ", Decimal("22.30"), 2000, Decimal("24.53")),
    ("600067.SH", Decimal("9.80"), 6000, Decimal("9.50")),
    ("601958.SH", Decimal("14.60"), 3000, Decimal("15.20")),
    ("603065.SH", Decimal("31.00"), 1500, Decimal("34.10")),
]
# 最新日卖出 2 笔（前一交易日买入的隔夜票，今日了结）。
SELLS = [
    ("603738.SH", Decimal("28.50"), 2000),
    ("002927.SZ", Decimal("19.80"), 2500),
]
# 最新日买入委托里「买不进」的 2 只（终态撤单、零成交）。
NO_FILL = [("002976.SZ", 3000), ("603335.SH", 2000)]


def _dt(d: date, hh: int, mm: int) -> tuple[datetime, datetime]:
    """返回 (UTC naive, 东八区 naive)：东八区=展示原值，UTC=东八区-8h。"""
    east8 = datetime(d.year, d.month, d.day, hh, mm, 0)
    return east8 - timedelta(hours=8), east8


def run() -> None:
    db = SessionLocal()
    try:
        # 幂等：先清演示账户旧数据。
        for model in (QmtTrade, QmtOrder, QmtPositionSnapshot, QmtAccountDaily, QmtDecisionLog):
            db.execute(delete(model).where(model.account_id == ACCOUNT))
        db.flush()

        days = _trading_days_back(LATEST, len(PNL_DELTAS) + 1)  # 14 天

        # ---- 账户日快照（净值曲线）----
        total = Decimal("1000000")
        prev: Decimal | None = None
        for i, d in enumerate(days):
            if i == 0:
                daily_pnl = None
                daily_return = None
            else:
                delta = Decimal(str(PNL_DELTAS[i - 1]))
                total = total + delta
                daily_pnl = delta  # net_cash_flow=0，故当日盈亏=资产差分
                daily_return = (delta / prev) if prev else None
            mkt = (Decimal("311270") if d == LATEST else (total * Decimal("0.30")).quantize(Decimal("1.00")))
            cash = total - mkt
            db.add(
                QmtAccountDaily(
                    account_id=ACCOUNT, trade_date=d, snapshot_type="CLOSE",
                    total_asset=total, cash=cash, frozen_cash=Decimal("0"), market_value=mkt,
                    net_cash_flow=Decimal("0"),
                    prev_total_asset=prev, daily_pnl=daily_pnl, daily_return=daily_return,
                    data_source="QUERY",
                )
            )
            prev = total

        # ---- 最新日买入成交 + 委托 + 持仓 ----
        tno = 1
        ono = 9000001
        float_sum = Decimal("0")
        for code, cost, qty, last in BUYS:
            utc, e8 = _dt(LATEST, 9, 31)
            db.add(
                QmtTrade(
                    account_id=ACCOUNT, trade_date=LATEST, ts_code=code, qmt_stock_code=code,
                    traded_id=f"D{LATEST:%Y%m%d}{tno:04d}", order_id=ono, trade_side="BUY",
                    traded_price=cost, traded_volume=qty, traded_amount=cost * qty,
                    traded_time=utc, traded_time_east8=e8, signal_trade_date=SIGNAL_DAY,
                    data_source="CALLBACK",
                )
            )
            db.add(
                QmtOrder(
                    account_id=ACCOUNT, trade_date=LATEST, ts_code=code, qmt_stock_code=code,
                    order_id=ono, trade_side="BUY", order_volume=qty, traded_volume=qty,
                    order_price=cost, traded_price=cost, order_status="TRADED",
                    order_time=utc, order_time_east8=e8, signal_trade_date=SIGNAL_DAY,
                    data_source="CALLBACK",
                )
            )
            fp = (last - cost) * qty
            float_sum += fp
            db.add(
                QmtPositionSnapshot(
                    account_id=ACCOUNT, trade_date=LATEST, snapshot_type="CLOSE",
                    ts_code=code, qmt_stock_code=code, volume=qty, can_use_volume=0,  # T+1 当日买入不可卖
                    open_price=cost, avg_price=cost, last_price=last, market_value=last * qty,
                    float_profit=fp, profit_rate=((last - cost) / cost).quantize(Decimal("0.000001")),
                    data_source="QUERY",
                )
            )
            tno += 1
            ono += 1

        # 卖出 2 笔（信号日同样可 join）。
        for code, price, qty in SELLS:
            utc, e8 = _dt(LATEST, 14, 31)
            db.add(
                QmtTrade(
                    account_id=ACCOUNT, trade_date=LATEST, ts_code=code, qmt_stock_code=code,
                    traded_id=f"D{LATEST:%Y%m%d}{tno:04d}", order_id=ono, trade_side="SELL",
                    traded_price=price, traded_volume=qty, traded_amount=price * qty,
                    traded_time=utc, traded_time_east8=e8, signal_trade_date=SIGNAL_DAY,
                    data_source="CALLBACK",
                )
            )
            tno += 1
            ono += 1

        # 买不进：买入委托零成交、终态撤单。
        for code, qty in NO_FILL:
            utc, e8 = _dt(LATEST, 9, 30)
            db.add(
                QmtOrder(
                    account_id=ACCOUNT, trade_date=LATEST, ts_code=code, qmt_stock_code=code,
                    order_id=ono, trade_side="BUY", order_volume=qty, traded_volume=0,
                    order_price=Decimal("10.00"), order_status="CANCELLED", status_msg="封单不足撤单",
                    order_time=utc, order_time_east8=e8, signal_trade_date=SIGNAL_DAY,
                    data_source="CALLBACK",
                )
            )
            ono += 1

        # ---- 前一交易日(信号日)少量成交，便于切换日期也有数据 ----
        for idx, (code, price, qty, side) in enumerate(
            [("603738.SH", Decimal("26.00"), 2000, "BUY"), ("002927.SZ", Decimal("18.50"), 2500, "BUY")]
        ):
            utc, e8 = _dt(SIGNAL_DAY, 9, 35)
            db.add(
                QmtTrade(
                    account_id=ACCOUNT, trade_date=SIGNAL_DAY, ts_code=code, qmt_stock_code=code,
                    traded_id=f"D{SIGNAL_DAY:%Y%m%d}{idx + 1:04d}", order_id=8000001 + idx,
                    trade_side=side, traded_price=price, traded_volume=qty, traded_amount=price * qty,
                    traded_time=utc, traded_time_east8=e8, signal_trade_date=SIGNAL_DAY,
                    data_source="CALLBACK",
                )
            )

        db.commit()

        # 决策明细：基于已落库的成交/委托 order_id 串联，造一套自洽的「信号达标→下单/未买→卖出」链路。
        n_dec = _seed_decisions(db)

        # 校正最新日「当日盈亏/浮动」一致性：realized≈daily-float（演示口径自洽）。
        print(f"[OK] 演示账户 {ACCOUNT} 已写入：")
        print(f"     决策明细 {n_dec} 条（SIGNAL_QUALIFIED/BUY_SUBMIT/BUY_MISS/SELL_*/SKIP_*）")
        print(f"     交易日 {days[0]} ~ {days[-1]}（{len(days)} 天净值曲线）")
        print(f"     最新日 {LATEST}：买入 {len(BUYS)} 卖出 {len(SELLS)}，浮动盈亏合计 {float_sum}")
        print(f"     委托：{len(BUYS)} 成交 + {len(NO_FILL)} 撤单（成功率 {len(BUYS)}/{len(BUYS)+len(NO_FILL)}）")
    finally:
        db.close()


# 战法族 → 动作映射（与决策枚举口径一致）。
_ACTION_BY_FAMILY = {"DABAN": "CHASE_LIMIT_UP", "BANLU": "LEADER_PULLBACK", "DIXI": "DIP_BUY_MA"}
# 6 只主买的战法族（与信号侧选股同口径，便于闭环对齐）。
_BUY_FAMILY = {
    "001257.SZ": "DABAN", "002830.SZ": "BANLU", "002971.SZ": "DIXI",
    "600067.SH": "BANLU", "601958.SH": "DABAN", "603065.SH": "DABAN",
}


def _order_id_of(db, trade_date: date, ts_code: str, side: str) -> int | None:
    """查已落库成交的 order_id（闭环 fills 串联键），无则返回 None。"""
    return db.execute(
        select(QmtTrade.order_id).where(
            QmtTrade.account_id == ACCOUNT, QmtTrade.trade_date == trade_date,
            QmtTrade.ts_code == ts_code, QmtTrade.trade_side == side,
        ).limit(1)
    ).scalar_one_or_none()


def _cancelled_order_id(db, ts_code: str) -> int | None:
    """查最新日某票「买不进」撤单委托的 order_id（BUY_MISS 关联）。"""
    return db.execute(
        select(QmtOrder.order_id).where(
            QmtOrder.account_id == ACCOUNT, QmtOrder.trade_date == LATEST,
            QmtOrder.ts_code == ts_code, QmtOrder.trade_side == "BUY",
            QmtOrder.order_status == "CANCELLED",
        ).limit(1)
    ).scalar_one_or_none()


def _factors(idx: int) -> dict:
    """构造一份决策当时的因子/阈值快照（数值按序微调，避免雷同）。"""
    return {
        "open_pct": round(2.5 + idx * 0.6, 2),          # 竞价高开幅度%
        "auction_vol_ratio": round(1.4 + idx * 0.15, 2),  # 竞价量能比
        "seal_to_float_ratio": round(0.55 + idx * 0.05, 3),  # 封流比
        "is_limit_up": True,
        "thresholds": {"abandon_pct": -2.0, "overheat_pct": 7.0, "seal_ratio_min": 0.5, "leader_strength_min": 50},
    }


def _seed_decisions(db) -> int:
    """造一套自洽的决策链路（与已落库成交/委托用 order_id 串联）。返回写入条数。"""
    rows: list[QmtDecisionLog] = []
    seq = {LATEST: 0, SIGNAL_DAY: 0}

    def add(trade_date: date, ts_code, dtype, stage, action, family, reason, code, hh, mm, **kw):
        """追加一条决策事件，decision_id 按 (日期, 序号) 生成。"""
        seq[trade_date] += 1
        utc, e8 = _dt(trade_date, hh, mm)
        rows.append(
            QmtDecisionLog(
                account_id=ACCOUNT, trade_date=trade_date,
                decision_id=f"{trade_date:%Y%m%d}-{seq[trade_date]:03d}",
                signal_trade_date=SIGNAL_DAY, ts_code=ts_code, decision_type=dtype,
                decision_stage=stage, action=action, strategy_family=family, order_phase=kw.get("phase"),
                reason=reason, reason_code=code, factors_snapshot=kw.get("factors"),
                limit_price=kw.get("limit_price"), plan_volume=kw.get("plan_volume"),
                order_id=kw.get("order_id"), biz_order_no=kw.get("biz_order_no"),
                decided_time=utc, decided_time_east8=e8,
            )
        )

    # ① 6 只主买：达标 → 提交（关联 BUY 成交 order_id）。
    for i, (code, cost, qty, _last) in enumerate(BUYS):
        fam = _BUY_FAMILY.get(code, "DABAN")
        act = _ACTION_BY_FAMILY.get(fam, "CHASE_LIMIT_UP")
        add(LATEST, code, "SIGNAL_QUALIFIED", "STRATEGY", act, fam,
            "竞价四因子达标：高开放量、封流比达标、重心上移", "qualified", 9, 25,
            phase="AUCTION", factors=_factors(i))
        add(LATEST, code, "BUY_SUBMIT", "ORDER", act, fam,
            f"挂涨停价 {cost} 买入 {qty} 股", "order_submitted", 9, 31,
            phase="OPENING", factors=_factors(i), limit_price=cost, plan_volume=qty,
            order_id=_order_id_of(db, LATEST, code, "BUY"),
            biz_order_no=f"{LATEST:%Y%m%d}_{code}_{fam}_1")

    # ② 2 只买不进：达标 → 未成交（关联撤单 order_id，无成交事实）。
    for i, (code, qty) in enumerate(NO_FILL):
        add(LATEST, code, "SIGNAL_QUALIFIED", "STRATEGY", "CHASE_LIMIT_UP", "DABAN",
            "竞价封板达标，进入排队", "qualified", 9, 25, phase="AUCTION", factors=_factors(i))
        add(LATEST, code, "BUY_MISS", "ORDER", "CHASE_LIMIT_UP", "DABAN",
            "一字封板全天未开，排队未成，尾盘撤单", "miss_unfilled", 9, 31,
            phase="OPENING", plan_volume=qty, order_id=_cancelled_order_id(db, code))

    # ③ 2 只两日闭环：信号日买入 → 最新日卖出。
    for code, price, qty in SELLS:
        add(SIGNAL_DAY, code, "SIGNAL_QUALIFIED", "STRATEGY", "LEADER_PULLBACK", "BANLU",
            "半路打板达标：均线低吸位放量上板", "qualified", 9, 30, phase="AUCTION", factors=_factors(2))
        add(SIGNAL_DAY, code, "BUY_SUBMIT", "ORDER", "LEADER_PULLBACK", "BANLU",
            "半路挂单买入", "order_submitted", 9, 35, phase="OPENING",
            order_id=_order_id_of(db, SIGNAL_DAY, code, "BUY"), biz_order_no=f"{SIGNAL_DAY:%Y%m%d}_{code}_BANLU_1")
        add(LATEST, code, "SELL_SUBMIT", "SELL", "SELL_CLEAR", "SELL",
            f"炸板/跌破成本，清仓止盈 {price}", "sell_clear", 14, 31, phase="INTRADAY",
            plan_volume=qty, order_id=_order_id_of(db, LATEST, code, "SELL"),
            biz_order_no=f"{LATEST:%Y%m%d}_{code}_SELL_1")

    # ④ 续持示例：尾盘决定不卖。
    add(LATEST, "601958.SH", "SELL_HOLD", "SELL", "HOLD", "SELL",
        "尾盘封板稳、重心上移，次日预期溢价，续持", "hold", 14, 55, phase="INTRADAY")

    # ⑤ 评估了没买（为什么没买）。
    add(LATEST, "600229.SH", "SKIP_ORCHESTRATION", "ORCHESTRATION", "SKIP", "BANLU",
        "空仓禁开闸门未放开（情绪退潮、当日不新开仓）", "open_blocked", 9, 30, phase="OPENING")
    add(LATEST, "001696.SZ", "SKIP_STRATEGY", "STRATEGY", "SKIP", "DIXI",
        "竞价弱开低于追买阈值，放弃", "weak_open", 9, 25, phase="AUCTION", factors=_factors(0))

    db.add_all(rows)
    db.commit()
    return len(rows)


if __name__ == "__main__":
    run()
