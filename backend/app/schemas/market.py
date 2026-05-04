from __future__ import annotations

from datetime import date
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
    """溢价结果列表响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    trade_date: date
    a_ts_code: str
    hk_ts_code: str
    a_name: str | None
    hk_name: str | None
    a_close_cny: Decimal | None
    h_close_hkd: Decimal | None
    hkd_cny: Decimal | None
    h_close_cny: Decimal | None
    ah_ratio: Decimal | None
    ah_premium_pct: Decimal | None
    ha_ratio: Decimal | None
    ha_premium_pct: Decimal | None
    connect_channels: str | None
    calc_status: str
    rate_source: str | None
    rate_fallback: bool
    official_ah_ratio: Decimal | None
    official_ah_premium_pct: Decimal | None
    official_ha_ratio: Decimal | None
    official_ha_premium_pct: Decimal | None
    diff_from_official_pct: Decimal | None
    diff_from_official_ha_pct: Decimal | None


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
