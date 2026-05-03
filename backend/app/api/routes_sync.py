from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.sync import SyncRun
from app.db.session import get_db
from app.schemas.sync import DatasetInfo, SyncRunCreate, SyncRunResponse
from app.services.sync_service import SyncService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/datasets", response_model=list[DatasetInfo])
def list_datasets(db: DbSession) -> list[dict[str, str]]:
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


@router.get("/sync/runs", response_model=list[SyncRunResponse])
def list_sync_runs(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SyncRun]:
    """查询同步任务列表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = select(SyncRun).order_by(desc(SyncRun.id)).limit(limit)
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
