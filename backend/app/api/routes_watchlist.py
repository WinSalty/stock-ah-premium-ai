from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import CurrentUser
from app.db.models.market import WatchlistStock
from app.db.session import get_db
from app.schemas.watchlist import (
    WatchlistCandidateResponse,
    WatchlistCreate,
    WatchlistOpportunityResponse,
    WatchlistResponse,
    WatchlistUpdate,
)
from app.services.watchlist_service import WatchlistError, WatchlistService
from app.services.watchlist_unadjusted_backfill_trigger_service import (
    WatchlistUnadjustedBackfillTriggerService,
    run_watchlist_unadjusted_backfill_if_needed,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/watchlist", response_model=list[WatchlistOpportunityResponse])
def list_watchlist(
    db: DbSession,
    current_user: CurrentUser,
    active_only: bool = True,
) -> list[WatchlistOpportunityResponse]:
    """查询自选股及当前机会状态。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return WatchlistService(db).list_opportunities(active_only, current_user.id)


@router.get("/watchlist/candidates", response_model=list[WatchlistCandidateResponse])
def list_watchlist_candidates(
    db: DbSession,
    current_user: CurrentUser,
    target_type: str = "PAIR",
    keyword: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[WatchlistCandidateResponse]:
    """查询新增关注弹窗可选标的。

    创建日期：2026-05-19
    author: sunshengxian
    """

    _ = current_user
    return WatchlistService(db).search_candidates(target_type, keyword, limit)


@router.post("/watchlist", response_model=WatchlistResponse)
def create_watchlist_item(
    payload: WatchlistCreate,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> WatchlistStock:
    """新增自选股。

    创建日期：2026-05-04
    author: sunshengxian
    """

    try:
        item = WatchlistService(db).create(payload, current_user.id)
    except WatchlistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _enqueue_unadjusted_backfill_if_needed(db, background_tasks, item)
    return item


@router.patch("/watchlist/{item_id}", response_model=WatchlistResponse)
def update_watchlist_item(
    item_id: int,
    payload: WatchlistUpdate,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> WatchlistStock:
    """更新自选股。

    创建日期：2026-05-04
    author: sunshengxian
    """

    try:
        item = WatchlistService(db).update(item_id, payload, current_user.id)
    except WatchlistError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="自选股不存在")
    _enqueue_unadjusted_backfill_if_needed(db, background_tasks, item)
    return item


@router.delete("/watchlist/{item_id}")
def delete_watchlist_item(
    item_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, bool]:
    """停用自选股。

    创建日期：2026-05-04
    author: sunshengxian
    """

    ok = WatchlistService(db).deactivate(item_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="自选股不存在")
    return {"ok": True}


def _enqueue_unadjusted_backfill_if_needed(
    db: Session,
    background_tasks: BackgroundTasks,
    item: WatchlistStock,
) -> None:
    """关注股票后按需挂起单票腾讯不复权追跑后台任务。

    创建日期：2026-05-07
    author: sunshengxian
    """

    if not item.is_active:
        return
    if item.target_type != "PAIR" or not item.a_ts_code or not item.hk_ts_code:
        return
    # 请求线程只做是否已有追跑记录的轻量判断；真正拉腾讯日线和写 AH 主表放到后台任务中，
    # 避免用户保存自选股时等待多年历史 K 线同步完成。
    if not WatchlistUnadjustedBackfillTriggerService(db).should_trigger(
        item.a_ts_code,
        item.hk_ts_code,
    ):
        return
    background_tasks.add_task(
        run_watchlist_unadjusted_backfill_if_needed,
        item.a_ts_code,
        item.hk_ts_code,
    )
