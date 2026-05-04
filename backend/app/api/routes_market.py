from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.market import OfficialAHComparison
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

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _official_to_response(item: OfficialAHComparison) -> PremiumQueryResponse:
    return PremiumQueryResponse(
        trade_date=item.trade_date,
        a_ts_code=item.a_ts_code,
        hk_ts_code=item.hk_ts_code,
        a_name=item.a_name,
        hk_name=item.hk_name,
        a_close=item.a_close,
        a_pct_chg=item.a_pct_chg,
        hk_close=item.hk_close,
        hk_pct_chg=item.hk_pct_chg,
        ah_ratio=item.ah_comparison,
        ah_premium_pct=item.ah_premium,
        ha_ratio=item.ha_comparison,
        ha_premium_pct=item.ha_premium,
        is_realtime=item.is_realtime,
        data_source=item.data_source,
        source_updated_at=item.source_updated_at,
    )


@router.post("/ah-premiums/calculate", response_model=PremiumCalculateResponse)
def calculate_premiums(
    payload: PremiumCalculateRequest,
    db: DbSession,
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
    trade_date: date | None = None,
    keyword: str | None = None,
    channel: str | None = None,
    min_premium: float | None = None,
    max_premium: float | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
) -> PremiumListResponse:
    """分页查询 AH 溢价结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = select(OfficialAHComparison)
    count_statement = select(func.count(OfficialAHComparison.id))
    filters = []
    if trade_date:
        filters.append(OfficialAHComparison.trade_date == trade_date)
    else:
        latest_trade_date = db.scalar(select(func.max(OfficialAHComparison.trade_date)))
        if latest_trade_date is not None:
            filters.append(OfficialAHComparison.trade_date == latest_trade_date)
    if keyword:
        like = f"%{keyword}%"
        filters.append(
            or_(
                OfficialAHComparison.a_ts_code.like(like),
                OfficialAHComparison.hk_ts_code.like(like),
                OfficialAHComparison.a_name.like(like),
                OfficialAHComparison.hk_name.like(like),
            )
        )
    if min_premium is not None:
        filters.append(OfficialAHComparison.ah_premium >= min_premium)
    if max_premium is not None:
        filters.append(OfficialAHComparison.ah_premium <= max_premium)
    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)
    total = db.scalar(count_statement) or 0
    statement = (
        statement.order_by(
            desc(OfficialAHComparison.trade_date),
            desc(OfficialAHComparison.ah_premium),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_official_to_response(item) for item in db.scalars(statement).all()]
    return PremiumListResponse(total=total, items=items)


@router.get("/ah-premiums/summary", response_model=PremiumSummaryResponse)
def premium_summary(db: DbSession) -> PremiumSummaryResponse:
    """获取最新交易日 AH 溢价总览。

    创建日期：2026-05-04
    author: sunshengxian
    """

    latest_trade_date = db.scalar(select(func.max(OfficialAHComparison.trade_date)))
    if latest_trade_date is None:
        return PremiumSummaryResponse(latest_trade_date=None, calculated_count=0, issue_count=0)
    calculated_count = db.scalar(
        select(func.count(OfficialAHComparison.id)).where(
            OfficialAHComparison.trade_date == latest_trade_date,
        )
    ) or 0
    issue_count = db.scalar(
        select(func.count(OfficialAHComparison.id)).where(
            OfficialAHComparison.trade_date == latest_trade_date,
            OfficialAHComparison.is_realtime.is_(True),
        )
    ) or 0
    top = list(
        db.scalars(
            select(OfficialAHComparison)
            .where(
                OfficialAHComparison.trade_date == latest_trade_date,
            )
            .order_by(desc(OfficialAHComparison.ah_premium))
            .limit(10)
        ).all()
    )
    bottom = list(
        db.scalars(
            select(OfficialAHComparison)
            .where(
                OfficialAHComparison.trade_date == latest_trade_date,
            )
            .order_by(asc(OfficialAHComparison.ah_premium))
            .limit(10)
        ).all()
    )
    return PremiumSummaryResponse(
        latest_trade_date=latest_trade_date,
        calculated_count=calculated_count,
        issue_count=issue_count,
        top_premiums=[_official_to_response(item) for item in top],
        bottom_premiums=[_official_to_response(item) for item in bottom],
    )


@router.get("/ah-premiums/pairs", response_model=list[PremiumPairOption])
def list_premium_pairs(
    db: DbSession,
    keyword: str | None = None,
    limit: int = Query(default=80, ge=1, le=300),
) -> list[PremiumPairOption]:
    """查询可展示趋势的 AH 配对。

    创建日期：2026-05-04
    author: sunshengxian
    """

    latest_date = func.max(OfficialAHComparison.trade_date).label("latest_trade_date")
    statement = select(
        OfficialAHComparison.a_ts_code,
        OfficialAHComparison.hk_ts_code,
        OfficialAHComparison.a_name,
        OfficialAHComparison.hk_name,
        latest_date,
    )
    if keyword:
        like = f"%{keyword}%"
        statement = statement.where(
            or_(
                OfficialAHComparison.a_ts_code.like(like),
                OfficialAHComparison.hk_ts_code.like(like),
                OfficialAHComparison.a_name.like(like),
                OfficialAHComparison.hk_name.like(like),
            )
        )
    statement = (
        statement.group_by(
            OfficialAHComparison.a_ts_code,
            OfficialAHComparison.hk_ts_code,
            OfficialAHComparison.a_name,
            OfficialAHComparison.hk_name,
        )
        .order_by(desc(latest_date), OfficialAHComparison.a_ts_code)
        .limit(limit)
    )
    return [
        PremiumPairOption(
            a_ts_code=row.a_ts_code,
            hk_ts_code=row.hk_ts_code,
            a_name=row.a_name,
            hk_name=row.hk_name,
            latest_trade_date=row.latest_trade_date,
        )
        for row in db.execute(statement).all()
    ]


@router.get("/ah-premiums/official-trend", response_model=list[PremiumOfficialTrendPoint])
def official_premium_trend(
    a_ts_code: str,
    hk_ts_code: str,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[PremiumOfficialTrendPoint]:
    """查询官方 AH/H/A 溢价趋势。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = select(OfficialAHComparison).where(
        OfficialAHComparison.a_ts_code == a_ts_code,
        OfficialAHComparison.hk_ts_code == hk_ts_code,
    )
    if start_date:
        statement = statement.where(OfficialAHComparison.trade_date >= start_date)
    if end_date:
        statement = statement.where(OfficialAHComparison.trade_date <= end_date)
    statement = statement.order_by(OfficialAHComparison.trade_date)
    return [
        PremiumOfficialTrendPoint(
            trade_date=item.trade_date,
            a_ts_code=item.a_ts_code,
            hk_ts_code=item.hk_ts_code,
            a_name=item.a_name,
            hk_name=item.hk_name,
            ah_ratio=item.ah_comparison,
            ah_premium_pct=item.ah_premium,
            ha_ratio=item.ha_comparison,
            ha_premium_pct=item.ha_premium,
            is_realtime=item.is_realtime,
        )
        for item in db.scalars(statement).all()
    ]


@router.get(
    "/ah-premiums/{a_ts_code}/{hk_ts_code}/trend",
    response_model=list[PremiumQueryResponse],
)
def premium_trend(
    a_ts_code: str,
    hk_ts_code: str,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[PremiumQueryResponse]:
    """查询单个 AH 配对的溢价趋势。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = select(OfficialAHComparison).where(
        OfficialAHComparison.a_ts_code == a_ts_code,
        OfficialAHComparison.hk_ts_code == hk_ts_code,
    )
    if start_date:
        statement = statement.where(OfficialAHComparison.trade_date >= start_date)
    if end_date:
        statement = statement.where(OfficialAHComparison.trade_date <= end_date)
    statement = statement.order_by(OfficialAHComparison.trade_date)
    return [_official_to_response(item) for item in db.scalars(statement).all()]


@router.post("/manual-import/ah-pairs", response_model=ImportResponse)
def import_manual_ah_pairs(
    payload: ManualAHPairImportRequest,
    db: DbSession,
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
) -> ImportResponse:
    """导入 CSV 格式人工汇率。

    创建日期：2026-05-04
    author: sunshengxian
    """

    count = ManualImportService(db).import_fx_rates_csv(payload.content)
    return ImportResponse(imported_rows=count)
