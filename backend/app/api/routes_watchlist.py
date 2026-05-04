from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps_auth import CurrentUser
from app.db.models.market import WatchlistStock
from app.db.session import get_db
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistOpportunityResponse,
    WatchlistResponse,
    WatchlistUpdate,
)
from app.services.watchlist_service import WatchlistService

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


@router.post("/watchlist", response_model=WatchlistResponse)
def create_watchlist_item(
    payload: WatchlistCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> WatchlistStock:
    """新增自选股。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return WatchlistService(db).create(payload, current_user.id)


@router.patch("/watchlist/{item_id}", response_model=WatchlistResponse)
def update_watchlist_item(
    item_id: int,
    payload: WatchlistUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> WatchlistStock:
    """更新自选股。

    创建日期：2026-05-04
    author: sunshengxian
    """

    item = WatchlistService(db).update(item_id, payload, current_user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="自选股不存在")
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
