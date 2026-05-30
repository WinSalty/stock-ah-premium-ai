from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import require_permission
from app.db.session import get_db
from app.schemas.dividend_reinvestment import (
    DividendReinvestmentHealthResponse,
    DividendReinvestmentRunResponse,
    DividendReinvestmentSummaryResponse,
    DividendReinvestmentYearlyItem,
)
from app.services.dividend_reinvestment_service import DividendReinvestmentDataLandingService

router = APIRouter(dependencies=[Depends(require_permission("dividend_reinvestment"))])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/dividend-reinvestment/health", response_model=DividendReinvestmentHealthResponse)
def get_dividend_reinvestment_health(db: DbSession) -> dict:
    """查询分红再投入数据健康概览。

    创建日期：2026-05-30
    author: sunshengxian
    """

    return DividendReinvestmentDataLandingService(db).health_snapshot()


@router.get("/dividend-reinvestment/runs", response_model=list[DividendReinvestmentRunResponse])
def list_dividend_reinvestment_runs(
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> list:
    """查询分红再投入回测批次。

    创建日期：2026-05-30
    author: sunshengxian
    """

    return DividendReinvestmentDataLandingService(db).list_backtest_runs(limit=limit)


@router.get("/dividend-reinvestment/summaries", response_model=DividendReinvestmentSummaryResponse)
def list_dividend_reinvestment_summaries(
    db: DbSession,
    run_id: Annotated[int | None, Query()] = None,
    keyword: Annotated[str | None, Query()] = None,
    industry: Annotated[str | None, Query()] = None,
    data_quality: Annotated[str | None, Query()] = None,
    min_annualized_return_pct: Annotated[Decimal | None, Query()] = None,
    min_dividend_year_count: Annotated[int | None, Query(ge=0)] = None,
    min_consecutive_dividend_years: Annotated[int | None, Query(ge=0)] = None,
    min_latest_dividend_yield_ttm: Annotated[Decimal | None, Query()] = None,
    max_latest_pe_ttm: Annotated[Decimal | None, Query()] = None,
    sort_by: Annotated[
        str,
        Query(
            pattern="^(annualized_return_pct|total_return_pct|total_cash_dividend|latest_dividend_yield_ttm)$"
        ),
    ] = "total_cash_dividend",
    sort_order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> dict:
    """查询分红再投入股票级筛选榜单。

    创建日期：2026-05-30
    author: sunshengxian
    """

    target_run_id, total, items = DividendReinvestmentDataLandingService(db).query_summaries(
        run_id=run_id,
        keyword=keyword,
        industry=industry,
        data_quality=data_quality,
        min_annualized_return_pct=min_annualized_return_pct,
        min_dividend_year_count=min_dividend_year_count,
        min_consecutive_dividend_years=min_consecutive_dividend_years,
        min_latest_dividend_yield_ttm=min_latest_dividend_yield_ttm,
        max_latest_pe_ttm=max_latest_pe_ttm,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return {
        "run_id": target_run_id,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get(
    "/dividend-reinvestment/yearly/{ts_code}",
    response_model=list[DividendReinvestmentYearlyItem],
)
def list_dividend_reinvestment_yearly(
    ts_code: str,
    db: DbSession,
    run_id: Annotated[int | None, Query()] = None,
) -> list:
    """查询单股分红再投入年度明细。

    创建日期：2026-05-30
    author: sunshengxian
    """

    return DividendReinvestmentDataLandingService(db).yearly_rows(
        run_id=run_id,
        ts_code=ts_code.strip().upper(),
    )
