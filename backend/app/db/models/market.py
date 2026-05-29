from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AStockBasic(TimestampMixin, Base):
    """A 股基础信息表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "a_stock_basic"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    area: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))
    fullname: Mapped[str | None] = mapped_column(String(255))
    market: Mapped[str | None] = mapped_column(String(64))
    exchange: Mapped[str | None] = mapped_column(String(16))
    curr_type: Mapped[str | None] = mapped_column(String(16))
    list_status: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    is_hs: Mapped[str | None] = mapped_column(String(8))


class HKStockBasic(TimestampMixin, Base):
    """港股基础信息表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "hk_stock_basic"

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    fullname: Mapped[str | None] = mapped_column(String(255))
    enname: Mapped[str | None] = mapped_column(String(255))
    cn_spell: Mapped[str | None] = mapped_column(String(64))
    market: Mapped[str | None] = mapped_column(String(64))
    list_status: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    trade_unit: Mapped[Decimal | None] = mapped_column(DECIMAL(18, 4))
    isin: Mapped[str | None] = mapped_column(String(32))
    curr_type: Mapped[str | None] = mapped_column(String(16))


class ATradeCalendar(TimestampMixin, Base):
    """A 股交易日历表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "a_trade_calendar"
    __table_args__ = (UniqueConstraint("exchange", "cal_date", name="uk_a_trade_calendar"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="SSE")
    cal_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pretrade_date: Mapped[date | None] = mapped_column(Date)


class HKTradeCalendar(TimestampMixin, Base):
    """港股交易日历表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "hk_trade_calendar"

    cal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pretrade_date: Mapped[date | None] = mapped_column(Date)


class ADailyQuote(TimestampMixin, Base):
    """A 股日线行情表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "a_daily_quote"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uk_a_daily_quote"),
        Index("idx_a_daily_trade_date", "trade_date"),
        Index("idx_a_daily_ts_code", "ts_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    high: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    low: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    pre_close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    change_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    pct_chg: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))


class HKDailyQuote(TimestampMixin, Base):
    """港股日线行情表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "hk_daily_quote"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uk_hk_daily_quote"),
        Index("idx_hk_daily_trade_date", "trade_date"),
        Index("idx_hk_daily_ts_code", "ts_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    high: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    low: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    pre_close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    change_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    pct_chg: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))


class HsgtConstituent(TimestampMixin, Base):
    """沪深港通名单表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "hsgt_constituent"
    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "connect_type", name="uk_hsgt_constituent"),
        Index("idx_hsgt_date_type", "trade_date", "connect_type"),
        Index("idx_hsgt_ts_code", "ts_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    connect_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    type_name: Mapped[str | None] = mapped_column(String(128))


class FxRateDaily(TimestampMixin, Base):
    """外汇汇率日线表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "fx_rate_daily"
    __table_args__ = (
        UniqueConstraint("rate_pair", "rate_date", "source", name="uk_fx_rate_daily"),
        Index("idx_fx_pair_date", "rate_pair", "rate_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_pair: Mapped[str] = mapped_column(String(32), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    base_ccy: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_ccy: Mapped[str] = mapped_column(String(8), nullable=False)
    mid_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    bid_close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ask_close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="TUSHARE_FXCM")
    raw_ts_code: Mapped[str | None] = mapped_column(String(32))
    is_cross_rate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RealtimeQuoteSnapshot(TimestampMixin, Base):
    """实时行情快照表。

    创建日期：2026-05-05
    author: sunshengxian
    """

    __tablename__ = "realtime_quote_snapshot"
    __table_args__ = (
        Index("idx_realtime_quote_symbol_time", "market", "symbol", "quote_time"),
        Index("idx_realtime_quote_source_time", "source", "quote_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    last_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_time: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False, default="UNAVAILABLE")
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AHStockPair(TimestampMixin, Base):
    """AH 股票配对表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "ah_stock_pair"
    __table_args__ = (
        UniqueConstraint("a_ts_code", "hk_ts_code", name="uk_ah_stock_pair"),
        Index("idx_ah_pair_hk", "hk_ts_code"),
        Index("idx_ah_pair_a", "a_ts_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    a_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    hk_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    a_name: Mapped[str | None] = mapped_column(String(128))
    hk_name: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="TUSHARE_STK_AH")
    effective_start_date: Mapped[date | None] = mapped_column(Date)
    effective_end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WatchlistStock(TimestampMixin, Base):
    """用户自选关注标的表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "watchlist_stock"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_key", name="uk_watchlist_user_target"),
        Index("idx_watchlist_active_order", "is_active", "sort_order"),
        Index("idx_watchlist_a_code", "a_ts_code"),
        Index("idx_watchlist_hk_code", "hk_ts_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False, default="PAIR")
    target_key: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    a_ts_code: Mapped[str | None] = mapped_column(String(16))
    hk_ts_code: Mapped[str | None] = mapped_column(String(16))
    display_name: Mapped[str | None] = mapped_column(String(128))
    preferred_direction: Mapped[str] = mapped_column(String(8), nullable=False, default="HA")
    target_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    a_price_alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    a_price_alert_operator: Mapped[str] = mapped_column(String(8), nullable=False, default="GTE")
    a_price_alert_target_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    h_price_alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    h_price_alert_operator: Mapped[str] = mapped_column(String(8), nullable=False, default="GTE")
    h_price_alert_target_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    holding_market: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


@event.listens_for(WatchlistStock, "before_insert")
@event.listens_for(WatchlistStock, "before_update")
def _fill_watchlist_target_key(_mapper, _connection, target: WatchlistStock) -> None:
    """写入自选股前补齐统一关注身份键。

    创建日期：2026-05-19
    author: sunshengxian
    """

    # 测试、迁移脚本或历史代码可能直接构造 WatchlistStock；这里兜底生成 target_key，
    # 保证新唯一键不会因为默认空字符串导致多条配对关注互相冲突。
    if not target.target_type:
        if target.a_ts_code and target.hk_ts_code:
            target.target_type = "PAIR"
        elif target.a_ts_code:
            target.target_type = "A_ONLY"
        else:
            target.target_type = "H_ONLY"
    if target.target_type == "PAIR" and target.a_ts_code and target.hk_ts_code:
        target.target_key = f"{target.a_ts_code}|{target.hk_ts_code}"
    elif target.target_type == "A_ONLY" and target.a_ts_code:
        target.target_key = target.a_ts_code
        target.hk_ts_code = None
    elif target.target_type == "H_ONLY" and target.hk_ts_code:
        target.target_key = target.hk_ts_code
        target.a_ts_code = None


class StockSelectionFactorSnapshot(TimestampMixin, Base):
    """A 股选股因子快照宽表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "stock_selection_factor_snapshot"
    __table_args__ = (
        UniqueConstraint("factor_date", "ts_code", name="uk_stock_selection_factor"),
        Index("idx_selection_factor_date_score", "factor_date", "selection_score"),
        Index("idx_selection_factor_tags", "selection_tags"),
        Index("idx_selection_factor_industry", "industry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factor_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128))
    area: Mapped[str | None] = mapped_column(String(64))
    market: Mapped[str | None] = mapped_column(String(64))
    selection_tags: Mapped[str] = mapped_column(String(128), nullable=False)
    selection_score: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    selection_reason: Mapped[str | None] = mapped_column(Text)
    is_hs300: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sse50: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_csi300_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_csi_dividend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sse_dividend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sz_dividend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    pct_chg: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    turnover_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    pe_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    pb: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ps_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dividend_yield_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    total_mv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    circ_mv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    roe: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    grossprofit_margin: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    netprofit_margin: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    debt_to_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    revenue_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    latest_report_period: Mapped[date | None] = mapped_column(Date)
    return_20d: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    return_60d: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    return_120d: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    latest_dividend_year: Mapped[str | None] = mapped_column(String(16))
    latest_cash_div_tax: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    latest_dividend_proc: Mapped[str | None] = mapped_column(String(64))
    forecast_type: Mapped[str | None] = mapped_column(String(64))
    forecast_summary: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="TUSHARE")
    source_trade_date: Mapped[date | None] = mapped_column(Date)


class DividendReinvestmentBacktestRun(TimestampMixin, Base):
    """分红再投入回测批次表。

    创建日期：2026-05-29
    author: sunshengxian
    """

    __tablename__ = "dividend_reinvestment_backtest_run"
    __table_args__ = (
        Index("idx_div_reinvest_run_status_started", "status", "started_at"),
        Index("idx_div_reinvest_run_key", "run_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_key: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_amount: Mapped[Decimal] = mapped_column(DECIMAL(24, 6), nullable=False)
    cash_div_field: Mapped[str] = mapped_column(String(32), nullable=False, default="cash_div_tax")
    reinvest_price_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="EX_DATE_OR_NEXT_CLOSE",
    )
    share_rounding_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="FRACTIONAL_SHARES",
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING")
    stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class DividendReinvestmentBacktestSummary(TimestampMixin, Base):
    """分红再投入回测摘要表。

    创建日期：2026-05-29
    author: sunshengxian
    """

    __tablename__ = "dividend_reinvestment_backtest_summary"
    __table_args__ = (
        UniqueConstraint("run_id", "ts_code", name="uk_div_reinvest_summary_run_code"),
        Index("idx_div_reinvest_summary_return", "run_id", "annualized_return_pct"),
        Index("idx_div_reinvest_summary_industry", "run_id", "industry"),
        Index("idx_div_reinvest_summary_quality", "run_id", "data_quality"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128))
    list_date: Mapped[date | None] = mapped_column(Date)
    start_trade_date: Mapped[date | None] = mapped_column(Date)
    end_trade_date: Mapped[date | None] = mapped_column(Date)
    initial_amount: Mapped[Decimal] = mapped_column(DECIMAL(24, 6), nullable=False)
    initial_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    initial_shares: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 8))
    final_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    final_shares: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 8))
    final_market_value: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_cash_dividend: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_reinvested_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_reinvested_shares: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 8))
    dividend_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dividend_year_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_dividend_years: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_return_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_return_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    annualized_return_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    latest_dividend_yield_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    latest_total_mv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    latest_pe_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    latest_pb: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    rank_score: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    data_quality: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    data_issue: Mapped[str | None] = mapped_column(Text)


class DividendReinvestmentBacktestYearly(TimestampMixin, Base):
    """分红再投入年度明细表。

    创建日期：2026-05-29
    author: sunshengxian
    """

    __tablename__ = "dividend_reinvestment_backtest_yearly"
    __table_args__ = (
        UniqueConstraint("run_id", "ts_code", "year", name="uk_div_reinvest_yearly"),
        Index("idx_div_reinvest_yearly_code", "ts_code", "year"),
        Index("idx_div_reinvest_yearly_run_year", "run_id", "year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    year_end_trade_date: Mapped[date | None] = mapped_column(Date)
    year_end_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    cash_div_per_share: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    cash_div_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    stock_div_per_share: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    stock_div_shares: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 8))
    reinvest_price_avg: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    reinvested_shares: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 8))
    holding_shares: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 8))
    market_value: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    return_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    return_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    annualized_return_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dividend_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)


class OfficialAHComparison(TimestampMixin, Base):
    """Tushare 官方 AH 比价快照表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "official_ah_comparison"
    __table_args__ = (
        UniqueConstraint("trade_date", "a_ts_code", "hk_ts_code", name="uk_official_ah"),
        Index("idx_official_ah_trade_date", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    a_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    hk_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    a_name: Mapped[str | None] = mapped_column(String(128))
    hk_name: Mapped[str | None] = mapped_column(String(128))
    a_close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    a_pct_chg: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    hk_close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    hk_pct_chg: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 6))
    ah_comparison: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ah_premium: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ha_comparison: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ha_premium: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    is_realtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="TUSHARE_OFFICIAL")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class HistoricalPremiumBackfillRecord(TimestampMixin, Base):
    """Baidu 历史 AH 比价补数执行记录表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    __tablename__ = "historical_premium_backfill_record"
    __table_args__ = (
        UniqueConstraint(
            "a_ts_code",
            "hk_ts_code",
            "data_source",
            name="uk_hist_premium_backfill_pair",
        ),
        Index("idx_hist_premium_backfill_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    a_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    hk_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_existing_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_trade_date: Mapped[date | None] = mapped_column(Date)
    last_trade_date: Mapped[date | None] = mapped_column(Date)
    last_error: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class TencentUnadjustedDailyQuote(TimestampMixin, Base):
    """腾讯不复权历史日线表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    __tablename__ = "tencent_unadjusted_daily_quote"
    __table_args__ = (
        UniqueConstraint(
            "market",
            "ts_code",
            "trade_date",
            "adjust_type",
            name="uk_tencent_unadj_quote",
        ),
        Index("idx_tencent_unadj_quote_date", "trade_date"),
        Index("idx_tencent_unadj_quote_code_date", "ts_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    tencent_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    close: Mapped[Decimal] = mapped_column(DECIMAL(20, 6), nullable=False)
    high: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    low: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    volume: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 4))
    amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 4))
    amplitude: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    pct_chg: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    change_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    turnover_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    adjust_type: Mapped[str] = mapped_column(String(16), nullable=False, default="NONE")
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="TENCENT_KLINE")
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class WaterstockFxRateDaily(TimestampMixin, Base):
    """water-stock 历史汇率日线表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    __tablename__ = "waterstock_fx_rate_daily"
    __table_args__ = (
        UniqueConstraint("currency_pair", "rate_date", "data_source", name="uk_waterstock_fx_rate"),
        Index("idx_waterstock_fx_rate_date", "rate_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency_pair: Mapped[str] = mapped_column(String(16), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    close: Mapped[Decimal] = mapped_column(DECIMAL(20, 8), nullable=False)
    high: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    low: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    data_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="WATER_STOCK_BAIDU_FX",
    )
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class HistoricalAhUnadjustedBackfillRun(TimestampMixin, Base):
    """不复权历史 AH 比价补数执行记录表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    __tablename__ = "historical_ah_unadjusted_backfill_run"
    __table_args__ = (
        UniqueConstraint("a_ts_code", "hk_ts_code", "data_source", name="uk_unadj_backfill_pair"),
        Index("idx_unadj_backfill_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    a_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    hk_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_existing_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_trade_date: Mapped[date | None] = mapped_column(Date)
    last_trade_date: Mapped[date | None] = mapped_column(Date)
    last_error: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ADailyBasic(TimestampMixin, Base):
    """A 股每日估值指标表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_daily_basic"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uk_a_daily_basic"),
        Index("idx_a_daily_basic_date", "trade_date"),
        Index("idx_a_daily_basic_code_date", "ts_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    turnover_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    volume_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    pe: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    pe_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    pb: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ps_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dv_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dv_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    total_share: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    float_share: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    free_share: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_mv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    circ_mv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AIncomeStatement(TimestampMixin, Base):
    """A 股利润表核心字段表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_income_statement"
    __table_args__ = (
        UniqueConstraint(
            "ts_code",
            "end_date",
            "report_type",
            "update_flag",
            name="uk_a_income_statement",
        ),
        Index("idx_a_income_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date | None] = mapped_column(Date)
    f_ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    comp_type: Mapped[str | None] = mapped_column(String(16))
    end_type: Mapped[str | None] = mapped_column(String(16))
    basic_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    diluted_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    total_revenue: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    revenue: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_cogs: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    oper_cost: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    biz_tax_surchg: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    admin_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    fin_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    rd_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    assets_impair_loss: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    credit_impa_loss: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    oth_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    asset_disp_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    operate_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    non_oper_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    non_oper_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    income_tax: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_income_attr_p: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    minority_gain: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    invest_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    fv_value_chg_gain: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    ebit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    ebitda: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    update_flag: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class ABalanceSheet(TimestampMixin, Base):
    """A 股资产负债表核心字段表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_balance_sheet"
    __table_args__ = (
        UniqueConstraint(
            "ts_code",
            "end_date",
            "report_type",
            "update_flag",
            name="uk_a_balance_sheet",
        ),
        Index("idx_a_balance_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date | None] = mapped_column(Date)
    f_ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    comp_type: Mapped[str | None] = mapped_column(String(16))
    total_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_liab: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_hldr_eqy_inc_min_int: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_hldr_eqy_exc_min_int: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    money_cap: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    trad_asset: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    lt_eqt_invest: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    invest_real_estate: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    notes_receiv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    accounts_receiv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    oth_receiv: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    inventories: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    fix_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    cip: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    intan_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    goodwill: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_cur_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_nca: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    st_borr: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    notes_payable: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    acct_payable: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    contract_liab: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    lt_borr: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    bond_payable: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_cur_liab: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_ncl: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    cap_rese: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    surplus_rese: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    undistr_porfit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    update_flag: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class ACashflowStatement(TimestampMixin, Base):
    """A 股现金流量表核心字段表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_cashflow_statement"
    __table_args__ = (
        UniqueConstraint(
            "ts_code",
            "end_date",
            "report_type",
            "update_flag",
            name="uk_a_cashflow_statement",
        ),
        Index("idx_a_cashflow_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date | None] = mapped_column(Date)
    f_ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    comp_type: Mapped[str | None] = mapped_column(String(16))
    net_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    finan_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_fr_sale_sg: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_paid_goods_s: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_paid_to_for_empl: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_paid_for_taxes: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_cashflow_act: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_recp_return_invest: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_recp_disp_fiolta: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_pay_acq_const_fiolta: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_cashflow_inv_act: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_recp_borrow: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_prepay_amt_borr: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_pay_dist_dpcp_int_exp: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_cash_flows_fnc_act: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_incr_cash_cash_equ: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    c_cash_equ_end_period: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    update_flag: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AFinancialIndicator(TimestampMixin, Base):
    """A 股财务指标核心字段表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_financial_indicator"
    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", name="uk_a_financial_indicator"),
        Index("idx_a_fin_indicator_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dt_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roe: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roe_waa: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roe_dt: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roa: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    grossprofit_margin: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    netprofit_margin: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    sales_gpr: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    profit_to_gr: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    debt_to_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    current_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    quick_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    assets_to_eqt: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    or_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    q_sales_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    netprofit_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    q_netprofit_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ocf_to_revenue: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ocfps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roe_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    bps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    profit_dedt: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    update_flag: Mapped[str | None] = mapped_column(String(8))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class HKFinancialIndicator(TimestampMixin, Base):
    """港股财务指标摘要表。

    创建日期：2026-05-08
    author: sunshengxian
    """

    __tablename__ = "hk_financial_indicator"
    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "report_type", name="uk_hk_financial_indicator"),
        Index("idx_hk_fin_indicator_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    std_report_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(16))
    org_type: Mapped[str | None] = mapped_column(String(64))
    per_netcash_operate: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    per_oi: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    bps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    basic_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    diluted_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    operate_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    operate_income_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    gross_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    gross_profit_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    holder_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    holder_profit_yoy: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    gross_profit_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    eps_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    operate_income_qoq: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    net_profit_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roe_avg: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    gross_profit_qoq: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roa: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    holder_profit_qoq: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roe_yearly: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    roic_yearly: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    total_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_liabilities: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    tax_ebt: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ocf_sales: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    total_parent_equity: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    debt_asset_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    operate_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    pretax_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    netcash_operate: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    netcash_invest: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    netcash_finance: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    end_cash: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    divi_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dividend_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    current_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    currentdebt_debt: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    total_market_cap: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    hksk_market_cap: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    pe_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    pb_ttm: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dps_hkd: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    dps_hkd_ly: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    equity_multiplier: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    equity_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class HKFinancialStatementItem(TimestampMixin, Base):
    """港股三大财务报表项目明细表。

    创建日期：2026-05-08
    author: sunshengxian
    """

    __tablename__ = "hk_financial_statement_item"
    __table_args__ = (
        UniqueConstraint(
            "ts_code",
            "end_date",
            "statement_type",
            "ind_name",
            name="uk_hk_fin_statement_item",
        ),
        Index("idx_hk_fin_statement_code_period", "ts_code", "end_date"),
        Index("idx_hk_fin_statement_type", "statement_type", "ind_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    statement_type: Mapped[str] = mapped_column(String(16), nullable=False)
    ind_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ind_value: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class ADividend(TimestampMixin, Base):
    """A 股分红送股表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_dividend"
    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "ann_date", "div_proc", name="uk_a_dividend"),
        Index("idx_a_dividend_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    div_proc: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    stk_div: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    cash_div: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    cash_div_tax: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    record_date: Mapped[date | None] = mapped_column(Date)
    ex_date: Mapped[date | None] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AForecast(TimestampMixin, Base):
    """A 股业绩预告表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_forecast"
    __table_args__ = (
        UniqueConstraint("ts_code", "ann_date", "end_date", "type", name="uk_a_forecast"),
        Index("idx_a_forecast_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    p_change_min: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    p_change_max: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    net_profit_min: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    net_profit_max: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    last_parent_net: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    first_ann_date: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AMainBusinessComposition(TimestampMixin, Base):
    """A 股主营业务构成表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_main_business_composition"
    __table_args__ = (
        UniqueConstraint(
            "ts_code",
            "end_date",
            "business_type",
            "bz_item",
            name="uk_a_main_business_composition",
        ),
        Index("idx_a_main_business_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    business_type: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    bz_item: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    bz_sales: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    bz_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    bz_cost: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    curr_type: Mapped[str | None] = mapped_column(String(16))
    update_flag: Mapped[str | None] = mapped_column(String(8))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AFinancialAudit(TimestampMixin, Base):
    """A 股财务审计意见表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_financial_audit"
    __table_args__ = (
        UniqueConstraint("ts_code", "ann_date", "end_date", name="uk_a_financial_audit"),
        Index("idx_a_financial_audit_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    audit_result: Mapped[str | None] = mapped_column(String(128))
    audit_fees: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    audit_agency: Mapped[str | None] = mapped_column(String(255))
    audit_sign: Mapped[str | None] = mapped_column(String(255))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AExpress(TimestampMixin, Base):
    """A 股业绩快报表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_express"
    __table_args__ = (
        UniqueConstraint("ts_code", "ann_date", "end_date", name="uk_a_express"),
        Index("idx_a_express_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    revenue: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    operate_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    n_income: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_hldr_eqy_exc_min_int: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    diluted_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    diluted_roe: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_net_profit: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    bps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_sales: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_op: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_tp: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_dedu_np: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_eps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_roe: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    growth_assets: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    yoy_equity: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    growth_bps: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    perf_summary: Mapped[str | None] = mapped_column(Text)
    is_audit: Mapped[int | None] = mapped_column(Integer)
    remark: Mapped[str | None] = mapped_column(Text)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class ATop10Holder(TimestampMixin, Base):
    """A 股前十大股东和前十大流通股东表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_top10_holder"
    __table_args__ = (
        UniqueConstraint(
            "ts_code",
            "end_date",
            "holder_scope",
            "holder_name",
            name="uk_a_top10_holder",
        ),
        Index("idx_a_top10_holder_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    holder_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hold_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    hold_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    hold_float_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    hold_change: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    holder_type: Mapped[str | None] = mapped_column(String(128))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AHolderNumber(TimestampMixin, Base):
    """A 股股东户数表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_holder_number"
    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", "ann_date", name="uk_a_holder_number"),
        Index("idx_a_holder_number_code_period", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    holder_num: Mapped[int | None] = mapped_column(Integer)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class APledgeStat(TimestampMixin, Base):
    """A 股股权质押统计表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_pledge_stat"
    __table_args__ = (
        UniqueConstraint("ts_code", "end_date", name="uk_a_pledge_stat"),
        Index("idx_a_pledge_stat_code_date", "ts_code", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    pledge_count: Mapped[int | None] = mapped_column(Integer)
    unrest_pledge: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    rest_pledge: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    total_share: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    pledge_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class AMoneyflow(TimestampMixin, Base):
    """A 股个股资金流向表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "a_moneyflow"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uk_a_moneyflow"),
        Index("idx_a_moneyflow_code_date", "ts_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    buy_sm_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_sm_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_sm_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_sm_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_md_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_md_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_md_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_md_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_lg_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_lg_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_lg_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_lg_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_elg_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    buy_elg_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_elg_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    sell_elg_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    net_mf_vol: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    net_mf_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(24, 6))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)


class LlmMarketDataFetchRun(TimestampMixin, Base):
    """LLM 按需市场数据抓取批次表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "llm_market_data_fetch_run"
    __table_args__ = (
        Index("idx_llm_market_fetch_question", "question_id"),
        Index("idx_llm_market_fetch_status", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(Integer)
    session_id: Mapped[int | None] = mapped_column(Integer)
    intent: Mapped[str] = mapped_column(String(64), nullable=False, default="stock_research")
    market_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="A_STOCK_SINGLE")
    symbols_json: Mapped[str | None] = mapped_column(Text)
    data_packages_json: Mapped[str | None] = mapped_column(Text)
    period_policy: Mapped[str] = mapped_column(String(64), nullable=False, default="RECENT_LIMITED")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class LlmMarketDataFetchItem(TimestampMixin, Base):
    """LLM 按需市场数据抓取明细表。

    创建日期：2026-05-07
    author: sunshengxian
    """

    __tablename__ = "llm_market_data_fetch_item"
    __table_args__ = (
        Index("idx_llm_market_fetch_item_run", "run_id"),
        Index("idx_llm_market_fetch_item_api", "api_name", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer)
    package_name: Mapped[str] = mapped_column(String(64), nullable=False)
    api_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[str | None] = mapped_column(Text)
    fields_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(String(512))
