from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import CurrentUser
from app.db.session import get_db
from app.schemas.imports import (
    CsvImportRequest,
    ImportResponse,
    ManualAHPairImportRequest,
    ManualFxRateImportRequest,
)
from app.schemas.market import (
    PremiumCalculateRequest,
    PremiumCalculateResponse,
    PremiumListResponse,
    PremiumOfficialTrendPoint,
    PremiumPairOption,
    PremiumQueryResponse,
    PremiumSummaryResponse,
)
from app.services.manual_import_service import ManualImportService
from app.services.official_premium_calc_service import OfficialPremiumCalcService
from app.services.premium_query_service import PremiumQueryFilters, PremiumQueryService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/ah-premiums/calculate", response_model=PremiumCalculateResponse)
def calculate_premiums(
    payload: PremiumCalculateRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> PremiumCalculateResponse:
    """计算指定日期或日期区间的 AH 溢价。

    创建日期：2026-05-04
    author: sunshengxian
    """

    end_date = payload.end_date or payload.start_date
    result = OfficialPremiumCalcService(db).calculate_range(payload.start_date, end_date)
    return PremiumCalculateResponse(**result.__dict__)


@router.get("/ah-premiums", response_model=PremiumListResponse)
def list_premiums(
    db: DbSession,
    current_user: CurrentUser,
    trade_date: date | None = None,
    keyword: str | None = None,
    channel: str | None = None,
    min_premium: Decimal | None = None,
    max_premium: Decimal | None = None,
    min_ha_premium: Decimal | None = None,
    max_ha_premium: Decimal | None = None,
    direction: str = Query(default="HA", pattern="^(AH|HA|ah|ha)$"),
    only_hk_connect: bool = True,
    only_watchlist: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
) -> PremiumListResponse:
    """分页查询 AH 溢价结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    filters = PremiumQueryFilters(
        trade_date=trade_date,
        keyword=keyword,
        channel=channel,
        min_premium=min_premium,
        max_premium=max_premium,
        min_ha_premium=min_ha_premium,
        max_ha_premium=max_ha_premium,
        direction=direction,
        only_hk_connect=only_hk_connect,
        only_watchlist=only_watchlist,
    )
    return PremiumQueryService(db).list_premiums(filters, page, page_size, current_user.id)


@router.get("/ah-premiums/summary", response_model=PremiumSummaryResponse)
def premium_summary(db: DbSession, current_user: CurrentUser) -> PremiumSummaryResponse:
    """获取最新交易日 AH 溢价总览。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return PremiumQueryService(db).summary(current_user.id)


@router.get("/ah-premiums/pairs", response_model=list[PremiumPairOption])
def list_premium_pairs(
    db: DbSession,
    current_user: CurrentUser,
    keyword: str | None = None,
    limit: int = Query(default=80, ge=1, le=300),
) -> list[PremiumPairOption]:
    """查询可展示趋势的 AH 配对。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return PremiumQueryService(db).list_pairs(keyword, limit)


@router.get("/ah-premiums/official-trend", response_model=list[PremiumOfficialTrendPoint])
def official_premium_trend(
    a_ts_code: str,
    hk_ts_code: str,
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
    direction: str = Query(default="HA", pattern="^(AH|HA|ah|ha)$"),
) -> list[PremiumOfficialTrendPoint]:
    """查询官方 AH/H/A 溢价趋势。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return PremiumQueryService(db).official_trend_points(
        a_ts_code,
        hk_ts_code,
        start_date,
        end_date,
        direction,
    )


@router.get(
    "/ah-premiums/{a_ts_code}/{hk_ts_code}/trend",
    response_model=list[PremiumQueryResponse],
)
def premium_trend(
    a_ts_code: str,
    hk_ts_code: str,
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = None,
    end_date: date | None = None,
    direction: str = Query(default="HA", pattern="^(AH|HA|ah|ha)$"),
) -> list[PremiumQueryResponse]:
    """查询单个 AH 配对的溢价趋势。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return PremiumQueryService(db).trend(
        a_ts_code,
        hk_ts_code,
        start_date,
        end_date,
        direction,
        current_user.id,
    )


@router.post("/manual-import/ah-pairs", response_model=ImportResponse)
def import_manual_ah_pairs(
    payload: ManualAHPairImportRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ImportResponse:
    """导入人工 AH 配对。

    创建日期：2026-05-04
    author: sunshengxian
    """

    count = ManualImportService(db).import_ah_pairs(payload.rows)
    return ImportResponse(imported_rows=count)


@router.post("/manual-import/fx-rates", response_model=ImportResponse)
def import_manual_fx_rates(
    payload: ManualFxRateImportRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ImportResponse:
    """导入人工汇率。

    创建日期：2026-05-04
    author: sunshengxian
    """

    count = ManualImportService(db).import_fx_rates(payload.rows)
    return ImportResponse(imported_rows=count)


@router.post("/manual-import/ah-pairs/csv", response_model=ImportResponse)
def import_manual_ah_pairs_csv(
    payload: CsvImportRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ImportResponse:
    """导入 CSV 格式人工 AH 配对。

    创建日期：2026-05-04
    author: sunshengxian
    """

    count = ManualImportService(db).import_ah_pairs_csv(payload.content)
    return ImportResponse(imported_rows=count)


@router.post("/manual-import/fx-rates/csv", response_model=ImportResponse)
def import_manual_fx_rates_csv(
    payload: CsvImportRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ImportResponse:
    """导入 CSV 格式人工汇率。

    创建日期：2026-05-04
    author: sunshengxian
    """

    count = ManualImportService(db).import_fx_rates_csv(payload.content)
    return ImportResponse(imported_rows=count)
