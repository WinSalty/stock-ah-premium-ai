from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps_auth import CurrentUser, require_permission
from app.db.models.auth import AppUser
from app.db.models.notification import AlertEvent
from app.db.session import get_db
from app.schemas.notification import (
    AdminPushplusBindingResponse,
    AdminPushplusBindRequest,
    AlertEventResponse,
    PushplusBindingResponse,
    PushplusBindRequest,
    PushplusCallbackRequest,
    PushplusFriendResponse,
    PushplusMessageLogResponse,
    PushplusQrCodeRequest,
    PushplusQrCodeResponse,
    TestPushRequest,
    TestPushResponse,
)
from app.services.notification_service import NotificationError, NotificationService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
AdminUser = Annotated[AppUser, Depends(require_permission("users"))]
logger = logging.getLogger(__name__)
PUSHPLUS_CALLBACK_SUCCESS = {"code": 200, "msg": "success"}
PUSHPLUS_CALLBACK_INVALID_PAYLOAD = {"code": 600, "msg": "invalid callback payload"}


@router.get("/notifications/pushplus/binding", response_model=PushplusBindingResponse)
def get_pushplus_binding(
    db: DbSession,
    current_user: CurrentUser,
) -> PushplusBindingResponse:
    """读取当前用户 PushPlus 好友绑定状态。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return NotificationService(db).get_pushplus_binding(current_user.id)


@router.post("/notifications/pushplus/qrcode", response_model=PushplusQrCodeResponse)
def create_pushplus_qrcode(
    payload: PushplusQrCodeRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> PushplusQrCodeResponse:
    """创建 PushPlus 好友二维码。

    创建日期：2026-05-05
    author: sunshengxian
    """

    try:
        url = NotificationService(db).create_pushplus_qr_code(
            current_user,
            payload.expire_seconds,
            payload.scan_count,
        )
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PushplusQrCodeResponse(qr_code_img_url=url)


@router.get("/notifications/pushplus/friends", response_model=list[PushplusFriendResponse])
def list_pushplus_friends(
    db: DbSession,
    admin_user: AdminUser,
) -> list[PushplusFriendResponse]:
    """管理员查询 PushPlus 好友列表。

    创建日期：2026-05-05
    author: sunshengxian
    """

    try:
        return NotificationService(db).list_pushplus_friends()
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/notifications/pushplus/bind", response_model=PushplusBindingResponse)
def bind_pushplus_friend(
    payload: PushplusBindRequest,
    db: DbSession,
    admin_user: AdminUser,
) -> PushplusBindingResponse:
    """管理员手动绑定自己的 PushPlus 好友。

    创建日期：2026-05-05
    author: sunshengxian
    """

    try:
        return NotificationService(db).bind_pushplus_friend(admin_user, payload.friend_id)
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/notifications/admin/pushplus/bindings",
    response_model=PushplusBindingResponse,
)
def admin_bind_pushplus_friend(
    payload: AdminPushplusBindRequest,
    db: DbSession,
    admin_user: AdminUser,
) -> PushplusBindingResponse:
    """管理员手动绑定系统用户与 PushPlus 好友。

    创建日期：2026-05-05
    author: sunshengxian
    """

    try:
        return NotificationService(db).bind_pushplus_friend_for_user(
            payload.user_id,
            payload.friend_id,
        )
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/notifications/pushplus/callback")
def pushplus_callback_probe() -> dict[str, int | str]:
    """兼容 PushPlus 保存回调地址时的可达性校验请求。

    创建日期：2026-05-06
    author: sunshengxian
    """

    return PUSHPLUS_CALLBACK_SUCCESS


@router.post("/notifications/pushplus/callback")
async def pushplus_callback(
    request: Request,
    db: DbSession,
) -> dict[str, int | str]:
    """接收 PushPlus 新增好友回调并按绑定票据自动完成系统用户绑定。

    创建日期：2026-05-05
    author: sunshengxian
    """

    try:
        payload_data = await request.json()
    except ValueError:
        return PUSHPLUS_CALLBACK_SUCCESS
    if not isinstance(payload_data, dict):
        return PUSHPLUS_CALLBACK_SUCCESS
    event = str(payload_data.get("event") or "").strip()
    if event != "add_friend":
        return PUSHPLUS_CALLBACK_SUCCESS
    try:
        payload = PushplusCallbackRequest.model_validate(payload_data)
    except ValidationError as exc:
        logger.error("PushPlus 回调请求体无效 errors=%s", exc.errors())
        return PUSHPLUS_CALLBACK_INVALID_PAYLOAD
    try:
        NotificationService(db).bind_pushplus_callback(
            payload.qrCode,
            payload.friendInfo.friendId,
            payload.friendInfo.token,
            payload.friendInfo.nickName,
            payload.friendInfo.isFollow == 1,
        )
    except NotificationError as exc:
        logger.error(
            "PushPlus 新增好友回调绑定失败 friend_id=%s error=%s",
            payload.friendInfo.friendId,
            str(exc),
        )
        return PUSHPLUS_CALLBACK_SUCCESS
    return PUSHPLUS_CALLBACK_SUCCESS


@router.get(
    "/notifications/admin/pushplus/bindings",
    response_model=list[AdminPushplusBindingResponse],
)
def list_pushplus_bindings(
    db: DbSession,
    admin_user: AdminUser,
) -> list[AdminPushplusBindingResponse]:
    """管理员查询 PushPlus 用户绑定列表。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return NotificationService(db).list_pushplus_bindings()


@router.get(
    "/notifications/admin/pushplus/messages",
    response_model=list[PushplusMessageLogResponse],
)
def list_pushplus_message_logs(
    db: DbSession,
    admin_user: AdminUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PushplusMessageLogResponse]:
    """管理员查询 PushPlus 推送流水。

    创建日期：2026-05-06
    author: sunshengxian
    """

    return NotificationService(db).list_pushplus_message_logs(limit)


@router.delete("/notifications/pushplus/binding")
def unbind_pushplus_friend(
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, bool]:
    """解除当前用户 PushPlus 好友绑定。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return {"ok": NotificationService(db).unbind_pushplus_friend(current_user.id)}


@router.post("/notifications/test-push", response_model=TestPushResponse)
def send_test_push(
    payload: TestPushRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> TestPushResponse:
    """发送测试好友消息。

    创建日期：2026-05-05
    author: sunshengxian
    """

    try:
        message_id = NotificationService(db).send_test_push(
            current_user.id,
            payload.title,
            payload.content,
        )
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestPushResponse(ok=True, message_id=message_id)


@router.post("/notifications/scan-alerts", response_model=list[AlertEventResponse])
def scan_current_user_alerts(
    db: DbSession,
    current_user: CurrentUser,
    trading_day: date | None = None,
) -> list[AlertEvent]:
    """手动扫描当前用户提醒。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return NotificationService(db).scan_alerts_for_day(trading_day, current_user.id)


@router.get("/notifications/events", response_model=list[AlertEventResponse])
def list_alert_events(
    db: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AlertEvent]:
    """查询当前用户提醒事件。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return NotificationService(db).list_alert_events(current_user.id, limit)
