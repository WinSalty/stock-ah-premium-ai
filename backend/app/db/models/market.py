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
    """用户自选 AH 股票表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "watchlist_stock"
    __table_args__ = (
        UniqueConstraint("user_id", "a_ts_code", "hk_ts_code", name="uk_watchlist_user_pair"),
        Index("idx_watchlist_active_order", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    a_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    hk_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    preferred_direction: Mapped[str] = mapped_column(String(8), nullable=False, default="HA")
    target_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price_alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_alert_market: Mapped[str] = mapped_column(String(8), nullable=False, default="UNKNOWN")
    price_alert_operator: Mapped[str] = mapped_column(String(8), nullable=False, default="GTE")
    price_alert_target_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    holding_market: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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
