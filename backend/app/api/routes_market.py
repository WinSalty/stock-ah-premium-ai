from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.market import AHPremiumDaily
from app.db.session import get_db
from app.schemas.imports import (
    ImportResponse,
    ManualAHPairImportRequest,
    ManualFxRateImportRequest,
)
from app.schemas.market import (
    PremiumCalculateRequest,
    PremiumCalculateResponse,
    PremiumListResponse,
    PremiumQueryResponse,
    PremiumSummaryResponse,
)
from app.services.manual_import_service import ManualImportService
from app.services.premium_calc_service import PremiumCalcService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


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
    result = PremiumCalcService(db).calculate_range(payload.start_date, end_date)
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

    statement = select(AHPremiumDaily)
    count_statement = select(func.count(AHPremiumDaily.id))
    filters = []
    if trade_date:
        filters.append(AHPremiumDaily.trade_date == trade_date)
    if keyword:
        like = f"%{keyword}%"
        filters.append(
            or_(
                AHPremiumDaily.a_ts_code.like(like),
                AHPremiumDaily.hk_ts_code.like(like),
                AHPremiumDaily.a_name.like(like),
                AHPremiumDaily.hk_name.like(like),
            )
        )
    if channel:
        filters.append(AHPremiumDaily.connect_channels.like(f"%{channel}%"))
    if min_premium is not None:
        filters.append(AHPremiumDaily.ah_premium_pct >= min_premium)
    if max_premium is not None:
        filters.append(AHPremiumDaily.ah_premium_pct <= max_premium)
    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)
    total = db.scalar(count_statement) or 0
    statement = (
        statement.order_by(desc(AHPremiumDaily.trade_date), desc(AHPremiumDaily.ah_premium_pct))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [PremiumQueryResponse.model_validate(item) for item in db.scalars(statement).all()]
    return PremiumListResponse(total=total, items=items)


@router.get("/ah-premiums/summary", response_model=PremiumSummaryResponse)
def premium_summary(db: DbSession) -> PremiumSummaryResponse:
    """获取最新交易日 AH 溢价总览。

    创建日期：2026-05-04
    author: sunshengxian
    """

    latest_trade_date = db.scalar(select(func.max(AHPremiumDaily.trade_date)))
    if latest_trade_date is None:
        return PremiumSummaryResponse(latest_trade_date=None, calculated_count=0, issue_count=0)
    calculated_count = db.scalar(
        select(func.count(AHPremiumDaily.id)).where(
            AHPremiumDaily.trade_date == latest_trade_date,
            AHPremiumDaily.calc_status == "OK",
        )
    ) or 0
    issue_count = db.scalar(
        select(func.count(AHPremiumDaily.id)).where(
            AHPremiumDaily.trade_date == latest_trade_date,
            AHPremiumDaily.calc_status != "OK",
        )
    ) or 0
    top = list(
        db.scalars(
            select(AHPremiumDaily)
            .where(
                AHPremiumDaily.trade_date == latest_trade_date,
                AHPremiumDaily.calc_status == "OK",
            )
            .order_by(desc(AHPremiumDaily.ah_premium_pct))
            .limit(10)
        ).all()
    )
    bottom = list(
        db.scalars(
            select(AHPremiumDaily)
            .where(
                AHPremiumDaily.trade_date == latest_trade_date,
                AHPremiumDaily.calc_status == "OK",
            )
            .order_by(asc(AHPremiumDaily.ah_premium_pct))
            .limit(10)
        ).all()
    )
    return PremiumSummaryResponse(
        latest_trade_date=latest_trade_date,
        calculated_count=calculated_count,
        issue_count=issue_count,
        top_premiums=[PremiumQueryResponse.model_validate(item) for item in top],
        bottom_premiums=[PremiumQueryResponse.model_validate(item) for item in bottom],
    )


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

    statement = select(AHPremiumDaily).where(
        AHPremiumDaily.a_ts_code == a_ts_code,
        AHPremiumDaily.hk_ts_code == hk_ts_code,
    )
    if start_date:
        statement = statement.where(AHPremiumDaily.trade_date >= start_date)
    if end_date:
        statement = statement.where(AHPremiumDaily.trade_date <= end_date)
    statement = statement.order_by(AHPremiumDaily.trade_date)
    return [PremiumQueryResponse.model_validate(item) for item in db.scalars(statement).all()]


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
