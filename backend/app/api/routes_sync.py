from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps_auth import require_permission
from app.db.models.sync import SyncRun
from app.db.session import get_db
from app.schemas.sync import (
    DatasetInfo,
    EastmoneyUnadjustedSyncBatchCreate,
    EastmoneyUnadjustedSyncBatchResponse,
    SyncBatchCreate,
    SyncRunCreate,
    SyncRunResponse,
)
from app.services.eastmoney_unadjusted_sync_batch_service import (
    EastmoneyUnadjustedSyncBatchService,
)
from app.services.sync_service import SyncService

router = APIRouter(dependencies=[Depends(require_permission("sync"))])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/datasets", response_model=list[DatasetInfo])
def list_datasets(db: DbSession) -> list[dict[str, Any]]:
    """获取支持同步的数据集。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return SyncService(db).list_datasets()


@router.post("/sync/runs", response_model=SyncRunResponse)
def create_sync_run(payload: SyncRunCreate, db: DbSession) -> SyncRun:
    """创建并执行同步任务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    params = payload.model_dump(exclude={"dataset"}, exclude_none=True)
    try:
        return SyncService(db).run_sync(payload.dataset, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync/batches/ah-premium", response_model=list[SyncRunResponse])
def create_ah_premium_sync_batch(payload: SyncBatchCreate, db: DbSession) -> list[SyncRun]:
    """一键同步 AH 溢价分析所需数据。

    创建日期：2026-05-04
    author: sunshengxian
    """

    try:
        return SyncService(db).run_core_plan(
            mode=payload.mode.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync/batches/stock-selection-factors", response_model=SyncRunResponse)
def create_stock_selection_factor_sync_batch(payload: SyncBatchCreate, db: DbSession) -> SyncRun:
    """同步 A 股选股因子核心宽表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    params = payload.model_dump(exclude_none=True)
    try:
        return SyncService(db).run_sync("stock_selection_factors", params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/sync/batches/eastmoney-unadjusted",
    response_model=EastmoneyUnadjustedSyncBatchResponse,
)
def sync_eastmoney_unadjusted_batch(
    payload: EastmoneyUnadjustedSyncBatchCreate,
    db: DbSession,
) -> dict[str, Any]:
    """一键同步关注股票东方财富不复权日线并追跑 AH 比价。

    创建日期：2026-05-06
    author: sunshengxian
    """

    result = EastmoneyUnadjustedSyncBatchService(db).sync_pending_watchlist(
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return {
        "start_date": result.start_date,
        "end_date": result.end_date,
        "pending_pair_count": result.pending_pair_count,
        "quote_rows": result.quote_rows,
        "backfill_pair_count": result.backfill_pair_count,
        "candidate_rows": result.candidate_rows,
        "inserted_rows": result.inserted_rows,
        "skipped_existing_rows": result.skipped_existing_rows,
        "replaced_baidu_rows": result.replaced_baidu_rows,
        "skipped_invalid_rows": result.skipped_invalid_rows,
    }


@router.get("/sync/runs", response_model=list[SyncRunResponse])
def list_sync_runs(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    dataset: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> list[SyncRun]:
    """查询同步任务列表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = select(SyncRun)
    if dataset:
        statement = statement.where(SyncRun.dataset == dataset)
    if status:
        statement = statement.where(SyncRun.status == status)
    if start_date:
        statement = statement.where(SyncRun.started_at >= datetime.combine(start_date, time.min))
    if end_date:
        next_day = end_date + timedelta(days=1)
        statement = statement.where(SyncRun.started_at < datetime.combine(next_day, time.min))
    statement = statement.order_by(desc(SyncRun.id)).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/sync/runs/{run_id}", response_model=SyncRunResponse)
def get_sync_run(run_id: int, db: DbSession) -> SyncRun:
    """查询同步任务详情。

    创建日期：2026-05-04
    author: sunshengxian
    """

    run = db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="同步任务不存在")
    return run
