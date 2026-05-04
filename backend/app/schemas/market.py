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
    is_realtime: bool = False
