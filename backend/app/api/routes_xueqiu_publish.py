from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.schemas.xueqiu_publish import (
    XueqiuActionResponse,
    XueqiuCredentialRequest,
    XueqiuCredentialSummary,
    XueqiuDraftPreview,
    XueqiuPublishRecordDetail,
    XueqiuPublishRecordItem,
    XueqiuPublishRequest,
    XueqiuPublishSettingRequest,
    XueqiuPublishSettingSummary,
)
from app.services.auth_service import ROLE_ADMIN
from app.services.xueqiu_publish_service import XueqiuPublishError, XueqiuPublishService

router = APIRouter()
XueqiuPublishUser = Annotated[AppUser, Depends(require_permission("xueqiu_publish"))]


def require_xueqiu_admin(user: AppUser) -> None:
    """校验雪球发布管理权限。

    创建日期：2026-05-10
    author: sunshengxian
    """

    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="没有雪球发布管理权限")


@router.get("/xueqiu-publish/credential", response_model=XueqiuCredentialSummary)
def get_xueqiu_credential(
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuCredentialSummary:
    """查询雪球发布登录态摘要。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    return XueqiuPublishService(db).get_credential_summary()


@router.put("/xueqiu-publish/credential", response_model=XueqiuCredentialSummary)
def save_xueqiu_credential(
    payload: XueqiuCredentialRequest,
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuCredentialSummary:
    """保存雪球发布登录态。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    try:
        return XueqiuPublishService(db).save_credential(payload, current_user)
    except XueqiuPublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/xueqiu-publish/setting", response_model=XueqiuPublishSettingSummary)
def get_xueqiu_publish_setting(
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuPublishSettingSummary:
    """查询雪球发布定时配置。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    return XueqiuPublishService(db).get_publish_setting()


@router.put("/xueqiu-publish/setting", response_model=XueqiuPublishSettingSummary)
def save_xueqiu_publish_setting(
    payload: XueqiuPublishSettingRequest,
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuPublishSettingSummary:
    """保存雪球发布定时配置。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    try:
        return XueqiuPublishService(db).save_publish_setting(payload, current_user)
    except XueqiuPublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/xueqiu-publish/credential/verify", response_model=XueqiuCredentialSummary)
def verify_xueqiu_credential(
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuCredentialSummary:
    """验证雪球发布登录态是否可用。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    try:
        return XueqiuPublishService(db).verify_credential()
    except XueqiuPublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/xueqiu-publish/preview", response_model=XueqiuDraftPreview)
def preview_xueqiu_article(
    db: DbSession,
    current_user: XueqiuPublishUser,
    analysis_id: Annotated[int | None, Query(ge=1)] = None,
) -> XueqiuDraftPreview:
    """预览最新或指定打板报告转换后的雪球长文。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    try:
        return XueqiuPublishService(db).preview_latest_report(analysis_id)
    except XueqiuPublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/xueqiu-publish/publish", response_model=XueqiuActionResponse)
def publish_xueqiu_article(
    payload: XueqiuPublishRequest,
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuActionResponse:
    """保存雪球草稿或正式发布长文。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    try:
        record = XueqiuPublishService(db).save_or_publish_report(
            payload.analysis_id,
            publish=payload.publish,
            force=payload.force,
            cover_pic=payload.cover_pic,
            user=current_user,
        )
    except XueqiuPublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return XueqiuActionResponse(
        ok=True,
        message="雪球长文已发布" if payload.publish else "雪球草稿已保存",
        record_id=record.id,
        article_url=record.article_url,
        draft_id=record.draft_id,
        status_id=record.status_id,
    )


@router.get("/xueqiu-publish/records", response_model=list[XueqiuPublishRecordItem])
def list_xueqiu_records(
    db: DbSession,
    current_user: XueqiuPublishUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    status: Annotated[str | None, Query(max_length=16)] = None,
) -> list[XueqiuPublishRecordItem]:
    """查询雪球发布流水。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    return XueqiuPublishService(db).list_records(limit=limit, status=status)


@router.get("/xueqiu-publish/records/{record_id}", response_model=XueqiuPublishRecordDetail)
def get_xueqiu_record(
    record_id: int,
    db: DbSession,
    current_user: XueqiuPublishUser,
) -> XueqiuPublishRecordDetail:
    """查看雪球发布流水详情。

    创建日期：2026-05-10
    author: sunshengxian
    """

    require_xueqiu_admin(current_user)
    try:
        return XueqiuPublishService(db).get_record(record_id)
    except XueqiuPublishError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
