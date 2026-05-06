from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


class PremiumCalculateRequest(BaseModel):
    """溢价计算请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    start_date: date
    end_date: date | None = None


class PremiumCalculateResponse(BaseModel):
    """溢价计算响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    start_date: date
    end_date: date
    calculated_rows: int
    skipped_not_connect: int
    issue_rows: int


class PremiumQueryResponse(OrmModel):
    """官方 AH 比价与溢价列表响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    trade_date: date
    a_ts_code: str
    hk_ts_code: str
    a_name: str | None
    hk_name: str | None
    a_close: Decimal | None
    a_pct_chg: Decimal | None
    hk_close: Decimal | None
    hk_pct_chg: Decimal | None
    ah_ratio: Decimal | None
    ah_premium_pct: Decimal | None
    ha_ratio: Decimal | None
    ha_premium_pct: Decimal | None
    is_hk_connect: bool = False
    connect_channels: str | None = None
    metric_direction: str = "HA"
    metric_premium_pct: Decimal | None = None
    premium_avg_20: Decimal | None = None
    premium_avg_60: Decimal | None = None
    premium_avg_120: Decimal | None = None
    premium_median_60: Decimal | None = None
    premium_p20_60: Decimal | None = None
    premium_p80_60: Decimal | None = None
    premium_percentile_60: Decimal | None = None
    premium_deviation_from_60d_avg: Decimal | None = None
    watchlist_id: int | None = None
    is_watchlist: bool = False
    watchlist_display_name: str | None = None
    preferred_direction: str | None = None
    target_premium_pct: Decimal | None = None
    push_enabled: bool | None = None
    a_price_alert_enabled: bool | None = None
    a_price_alert_operator: str | None = None
    a_price_alert_target_price: Decimal | None = None
    h_price_alert_enabled: bool | None = None
    h_price_alert_operator: str | None = None
    h_price_alert_target_price: Decimal | None = None
    holding_market: str | None = None
    distance_to_target_pct: Decimal | None = None
    opportunity_status: str | None = None
    is_realtime: bool
    data_source: str
    source_updated_at: datetime | None


class PremiumListResponse(BaseModel):
    """分页溢价结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    total: int
    items: list[PremiumQueryResponse]


class PremiumSummaryResponse(BaseModel):
    """溢价总览响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    latest_trade_date: date | None
    calculated_count: int
    issue_count: int
    hk_connect_count: int = 0
    watchlist_count: int = 0
    top_premiums: list[PremiumQueryResponse] = Field(default_factory=list)
    bottom_premiums: list[PremiumQueryResponse] = Field(default_factory=list)


class PremiumPairOption(BaseModel):
    """AH 配对选择项。

    创建日期：2026-05-04
    author: sunshengxian
    """

    a_ts_code: str
    hk_ts_code: str
    a_name: str | None
    hk_name: str | None
    latest_trade_date: date | None


class PremiumOfficialTrendPoint(BaseModel):
    """官方 AH/H/A 溢价趋势点。

    创建日期：2026-05-04
    author: sunshengxian
    """

    trade_date: date
    a_ts_code: str
    hk_ts_code: str
    a_name: str | None
    hk_name: str | None
    ah_ratio: Decimal | None
    ah_premium_pct: Decimal | None
    ha_ratio: Decimal | None
    ha_premium_pct: Decimal | None
    metric_direction: str = "HA"
    metric_premium_pct: Decimal | None = None
    premium_avg_20: Decimal | None = None
    premium_avg_60: Decimal | None = None
    premium_avg_120: Decimal | None = None
    premium_median_60: Decimal | None = None
    premium_p20_60: Decimal | None = None
    premium_p80_60: Decimal | None = None
    premium_percentile_60: Decimal | None = None
    is_realtime: bool = False


class RealtimeQuoteItem(BaseModel):
    """实时行情标准化报价。

    创建日期：2026-05-05
    author: sunshengxian
    """

    market: str
    symbol: str
    last_price: Decimal | None
    currency: str
    quote_time: datetime | None
    source: str | None
    quality: str


class RealtimePremiumResponse(BaseModel):
    """实时 AH/H/A 溢价响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    a_ts_code: str
    hk_ts_code: str
    a_name: str | None = None
    hk_name: str | None = None
    display_name: str | None = None
    a_last_price: Decimal | None
    hk_last_price: Decimal | None
    hkd_cny_rate: Decimal | None
    ah_ratio: Decimal | None
    ah_premium_pct: Decimal | None
    ha_ratio: Decimal | None
    ha_premium_pct: Decimal | None
    metric_direction: str = "HA"
    metric_premium_pct: Decimal | None = None
    target_premium_pct: Decimal | None = None
    distance_to_target_pct: Decimal | None = None
    opportunity_status: str | None = None
    quote_quality: str
    is_realtime: bool
    source: str | None = None
    calculated_at: datetime
    a_quote: RealtimeQuoteItem | None = None
    hk_quote: RealtimeQuoteItem | None = None
    fx_quote: RealtimeQuoteItem | None = None
    watchlist_id: int | None = None
    is_watchlist: bool = False


class RealtimePremiumListResponse(BaseModel):
    """实时 AH/H/A 溢价列表响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    total: int
    items: list[RealtimePremiumResponse]
