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

from sqlalchemy import delete

from app.db.models.qmt import QmtAccountDaily, QmtOrder, QmtPositionSnapshot, QmtTrade
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
        for model in (QmtTrade, QmtOrder, QmtPositionSnapshot, QmtAccountDaily):
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

        # 校正最新日「当日盈亏/浮动」一致性：realized≈daily-float（演示口径自洽）。
        print(f"[OK] 演示账户 {ACCOUNT} 已写入：")
        print(f"     交易日 {days[0]} ~ {days[-1]}（{len(days)} 天净值曲线）")
        print(f"     最新日 {LATEST}：买入 {len(BUYS)} 卖出 {len(SELLS)}，浮动盈亏合计 {float_sum}")
        print(f"     委托：{len(BUYS)} 成交 + {len(NO_FILL)} 撤单（成功率 {len(BUYS)}/{len(BUYS)+len(NO_FILL)}）")
    finally:
        db.close()


if __name__ == "__main__":
    run()
