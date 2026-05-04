from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.sync import SyncRun
from app.db.session import get_db
from app.schemas.sync import DatasetInfo, SyncBatchCreate, SyncRunCreate, SyncRunResponse
from app.services.sync_service import SyncService

router = APIRouter()
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


@router.post("/sync/batches/tushare-stock-data", response_model=list[SyncRunResponse])
def create_tushare_stock_data_sync_batch(payload: SyncBatchCreate, db: DbSession) -> list[SyncRun]:
    """同步 Tushare 股票数据目录中 15000 积分及以下接口。

    创建日期：2026-05-04
    author: sunshengxian
    """

    try:
        return SyncService(db).run_tushare_stock_data_plan(
            mode=payload.mode.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
