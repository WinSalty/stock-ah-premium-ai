from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import DECIMAL, Boolean, Date, Index, Integer, String, Text, UniqueConstraint
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


class AHPremiumDaily(TimestampMixin, Base):
    """自算港股通 AH 溢价结果表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "ah_premium_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "a_ts_code", "hk_ts_code", name="uk_ah_premium_daily"),
        Index("idx_ah_premium_rank", "trade_date", "ah_premium_pct"),
        Index("idx_ah_premium_hk", "hk_ts_code", "trade_date"),
        Index("idx_ah_premium_a", "a_ts_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    a_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    hk_ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    a_name: Mapped[str | None] = mapped_column(String(128))
    hk_name: Mapped[str | None] = mapped_column(String(128))
    a_close_cny: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    h_close_hkd: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    hkd_cny: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    h_close_cny: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    ah_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ah_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ha_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    ha_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    is_hk_connect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    connect_channels: Mapped[str | None] = mapped_column(String(64))
    rate_date: Mapped[date | None] = mapped_column(Date)
    rate_source: Mapped[str | None] = mapped_column(String(64))
    rate_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calc_status: Mapped[str] = mapped_column(String(32), nullable=False, default="OK")
    official_ah_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    official_ah_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    official_ha_ratio: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    official_ha_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    diff_from_official_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    diff_from_official_ha_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    error_message: Mapped[str | None] = mapped_column(Text)
