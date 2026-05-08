from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.schemas.limit_up_push import (
    LimitUpActionResponse,
    LimitUpDeliveryItem,
    LimitUpPushRequest,
    LimitUpRecipientItem,
    LimitUpRecipientUpdateRequest,
    LimitUpReportDetail,
    LimitUpReportListItem,
)
from app.services.auth_service import ROLE_ADMIN
from app.services.limit_up_push_service import DELIVERY_KIND_MANUAL, LimitUpPushError, LimitUpPushService

router = APIRouter()
LimitUpPushUser = Annotated[AppUser, Depends(require_permission("limit_up_push"))]


def require_limit_up_admin(user: AppUser) -> None:
    """校验打板推送管理权限。

    创建日期：2026-05-08
    author: sunshengxian
    """

    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="没有打板推送管理权限")


@router.get("/limit-up-push/reports", response_model=list[LimitUpReportListItem])
def list_limit_up_reports(
    db: DbSession,
    current_user: LimitUpPushUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    trade_date: date | None = None,
) -> list[LimitUpReportListItem]:
    """查询打板报告列表。

    创建日期：2026-05-08
    author: sunshengxian
    """

    return LimitUpPushService(db).list_reports(
        limit=limit,
        keyword=keyword,
        status=status,
        trade_date=trade_date,
    )


@router.get("/limit-up-push/reports/{report_id}", response_model=LimitUpReportDetail)
def get_limit_up_report(
    report_id: int,
    db: DbSession,
    current_user: LimitUpPushUser,
) -> LimitUpReportDetail:
    """查看完整打板报告。

    创建日期：2026-05-08
    author: sunshengxian
    """

    try:
        return LimitUpPushService(db).get_report(report_id)
    except LimitUpPushError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/limit-up-push/reports/generate-latest", response_model=LimitUpActionResponse)
def generate_latest_limit_up_report(
    db: DbSession,
    current_user: LimitUpPushUser,
) -> LimitUpActionResponse:
    """管理员手动检查最新 KPL 数据并生成报告。

    创建日期：2026-05-08
    author: sunshengxian
    """

    require_limit_up_admin(current_user)
    try:
        service = LimitUpPushService(db)
        analysis = service.ensure_analysis_for_trade_date(service.latest_a_trade_date())
    except LimitUpPushError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if analysis is None:
        return LimitUpActionResponse(ok=False, message="最新交易日 KPL 数据尚未同步", report_id=None)
    return LimitUpActionResponse(ok=True, message="报告已生成或已命中缓存", report_id=analysis.id)


@router.post("/limit-up-push/reports/{report_id}/push", response_model=LimitUpActionResponse)
def push_limit_up_report(
    report_id: int,
    payload: LimitUpPushRequest,
    db: DbSession,
    current_user: LimitUpPushUser,
) -> LimitUpActionResponse:
    """管理员手动推送指定打板报告。

    创建日期：2026-05-08
    author: sunshengxian
    """

    require_limit_up_admin(current_user)
    try:
        service = LimitUpPushService(db)
        pushed = service.push_report(
            report_id,
            DELIVERY_KIND_MANUAL,
            service._now_naive(),
            target_user_ids=None if payload.send_all else payload.user_ids,
        )
    except LimitUpPushError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LimitUpActionResponse(ok=True, message="手动推送已执行", report_id=report_id, delivery_count=pushed)


@router.get("/limit-up-push/recipients", response_model=list[LimitUpRecipientItem])
def list_limit_up_recipients(
    db: DbSession,
    current_user: LimitUpPushUser,
) -> list[LimitUpRecipientItem]:
    """管理员查询打板报告接收人配置。

    创建日期：2026-05-08
    author: sunshengxian
    """

    require_limit_up_admin(current_user)
    return LimitUpPushService(db).list_recipients()


@router.put("/limit-up-push/recipients", response_model=list[LimitUpRecipientItem])
def update_limit_up_recipients(
    payload: LimitUpRecipientUpdateRequest,
    db: DbSession,
    current_user: LimitUpPushUser,
) -> list[LimitUpRecipientItem]:
    """管理员保存打板报告接收人配置。

    创建日期：2026-05-08
    author: sunshengxian
    """

    require_limit_up_admin(current_user)
    try:
        return LimitUpPushService(db).update_recipients(payload, current_user)
    except LimitUpPushError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/limit-up-push/deliveries", response_model=list[LimitUpDeliveryItem])
def list_limit_up_deliveries(
    db: DbSession,
    current_user: LimitUpPushUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[LimitUpDeliveryItem]:
    """查询打板报告业务推送流水。

    创建日期：2026-05-08
    author: sunshengxian
    """

    visible_user_id = user_id if current_user.role == ROLE_ADMIN else current_user.id
    return LimitUpPushService(db).list_deliveries(
        limit=limit,
        keyword=keyword,
        status=status,
        user_id=visible_user_id,
    )
