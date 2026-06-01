from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.schemas.limit_up_push import LimitUpPushRequest
from app.schemas.nine_turn_push import (
    NineTurnActionResponse,
    NineTurnDeliveryItem,
    NineTurnReportDetail,
    NineTurnReportListItem,
)
from app.services.auth_service import ROLE_ADMIN
from app.services.nine_turn_push_service import (
    NINE_TURN_DELIVERY_KIND_MANUAL,
    NineTurnPushError,
    NineTurnPushService,
)

router = APIRouter()
NineTurnPushUser = Annotated[AppUser, Depends(require_permission("limit_up_push"))]
NINE_TURN_DISABLED_DETAIL = "神奇九转接口权限尚未开通，相关同步、推送和雪球发布入口已暂时注释"


def require_nine_turn_admin(user: AppUser) -> None:
    """校验神奇九转推送管理权限，复用打板推送菜单权限。

    创建日期：2026-06-01
    author: sunshengxian
    """

    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="没有神奇九转推送管理权限")


@router.get("/nine-turn-push/reports", response_model=list[NineTurnReportListItem])
def list_nine_turn_reports(
    db: DbSession,
    current_user: NineTurnPushUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    trade_date: date | None = None,
) -> list[NineTurnReportListItem]:
    """查询神奇九转报告列表。

    创建日期：2026-06-01
    author: sunshengxian
    """

    return NineTurnPushService(db).list_reports(
        limit=limit,
        keyword=keyword,
        status=status,
        trade_date=trade_date,
    )


@router.get("/nine-turn-push/reports/{report_id}", response_model=NineTurnReportDetail)
def get_nine_turn_report(
    report_id: int,
    db: DbSession,
    current_user: NineTurnPushUser,
) -> NineTurnReportDetail:
    """查看完整神奇九转报告。

    创建日期：2026-06-01
    author: sunshengxian
    """

    try:
        return NineTurnPushService(db).get_report(report_id)
    except NineTurnPushError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/nine-turn-push/reports/generate-latest", response_model=NineTurnActionResponse)
def generate_latest_nine_turn_report(
    db: DbSession,
    current_user: NineTurnPushUser,
) -> NineTurnActionResponse:
    """管理员手动检查最新九转数据并生成报告。

    创建日期：2026-06-01
    author: sunshengxian
    """

    require_nine_turn_admin(current_user)
    # 当前账号暂未开通 Tushare stk_nineturn 权限，手动同步会稳定返回权限不足；
    # 因此先在 API 入口阻断真实拉数和 LLM 调用，保留原实现代码便于权限恢复后重新启用。
    raise HTTPException(status_code=400, detail=NINE_TURN_DISABLED_DETAIL)
    try:
        service = NineTurnPushService(db)
        analysis = service.ensure_analysis_for_trade_date(service.latest_a_trade_date())
    except NineTurnPushError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if analysis is None:
        return NineTurnActionResponse(ok=False, message="最新神奇九转数据尚未同步", report_id=None)
    return NineTurnActionResponse(
        ok=True, message="神奇九转报告已生成或已命中缓存", report_id=analysis.id
    )


@router.post("/nine-turn-push/reports/{report_id}/push", response_model=NineTurnActionResponse)
def push_nine_turn_report(
    report_id: int,
    payload: LimitUpPushRequest,
    db: DbSession,
    current_user: NineTurnPushUser,
) -> NineTurnActionResponse:
    """管理员手动推送指定神奇九转报告。

    创建日期：2026-06-01
    author: sunshengxian
    """

    require_nine_turn_admin(current_user)
    # 神奇九转报告来源已暂停生成，手动推送入口同步关闭；
    # 已生成的历史报告仍可查看，待接口权限开通后移除此处阻断即可恢复推送。
    raise HTTPException(status_code=400, detail=NINE_TURN_DISABLED_DETAIL)
    try:
        service = NineTurnPushService(db)
        pushed = service.push_report(
            report_id,
            NINE_TURN_DELIVERY_KIND_MANUAL,
            service._now_naive(),
            target_user_ids=None if payload.send_all else payload.user_ids,
        )
    except NineTurnPushError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return NineTurnActionResponse(
        ok=True, message="神奇九转手动推送已执行", report_id=report_id, delivery_count=pushed
    )


@router.post(
    "/nine-turn-push/reports/{report_id}/publish-xueqiu", response_model=NineTurnActionResponse
)
def publish_nine_turn_report_to_xueqiu(
    report_id: int,
    db: DbSession,
    current_user: NineTurnPushUser,
) -> NineTurnActionResponse:
    """管理员手动将神奇九转报告按雪球配置保存草稿或发布。

    创建日期：2026-06-01
    author: sunshengxian
    """

    require_nine_turn_admin(current_user)
    # 雪球发布依赖九转报告生成结果；当前接口权限未开时不应误触发草稿或正式发布。
    raise HTTPException(status_code=400, detail=NINE_TURN_DISABLED_DETAIL)
    record_id = NineTurnPushService(db).publish_report_to_xueqiu_by_scheduler(report_id)
    if record_id is None:
        return NineTurnActionResponse(ok=False, message="雪球未配置或发布失败", report_id=report_id)
    return NineTurnActionResponse(
        ok=True,
        message="神奇九转报告已提交雪球",
        report_id=report_id,
        xueqiu_record_id=record_id,
    )


@router.get("/nine-turn-push/deliveries", response_model=list[NineTurnDeliveryItem])
def list_nine_turn_deliveries(
    db: DbSession,
    current_user: NineTurnPushUser,
    limit: Annotated[int, Query(ge=1, le=300)] = 100,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    user_id: int | None = None,
) -> list[NineTurnDeliveryItem]:
    """查询神奇九转报告推送流水。

    创建日期：2026-06-01
    author: sunshengxian
    """

    return NineTurnPushService(db).list_deliveries(
        limit=limit,
        keyword=keyword,
        status=status,
        user_id=user_id,
    )
