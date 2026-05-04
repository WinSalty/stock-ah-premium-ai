from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel
from app.schemas.market import PremiumQueryResponse


class WatchlistCreate(BaseModel):
    """新增自选股请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    a_ts_code: str = Field(min_length=1, max_length=16)
    hk_ts_code: str = Field(min_length=1, max_length=16)
    display_name: str | None = Field(default=None, max_length=128)
    preferred_direction: str = "HA"
    target_premium_pct: Decimal | None = None
    holding_market: str = "UNKNOWN"
    sort_order: int = 1000
    note: str | None = None
    is_active: bool = True


class WatchlistUpdate(BaseModel):
    """更新自选股请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    display_name: str | None = Field(default=None, max_length=128)
    preferred_direction: str | None = None
    target_premium_pct: Decimal | None = None
    holding_market: str | None = None
    sort_order: int | None = None
    note: str | None = None
    is_active: bool | None = None


class WatchlistResponse(OrmModel):
    """自选股响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    a_ts_code: str
    hk_ts_code: str
    display_name: str | None
    preferred_direction: str
    target_premium_pct: Decimal | None
    holding_market: str
    sort_order: int
    note: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WatchlistOpportunityResponse(BaseModel):
    """自选股机会响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    watchlist: WatchlistResponse
    premium: PremiumQueryResponse | None = None
