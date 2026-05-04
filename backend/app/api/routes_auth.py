from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps_auth import CurrentUser, DbSession, require_permission
from app.db.models.auth import AppUser
from app.schemas.auth import (
    AuthTokenResponse,
    InvitationCreateRequest,
    InvitationResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.auth_service import AuthError, AuthService

router = APIRouter()
AdminUser = Annotated[AppUser, Depends(require_permission("users"))]


@router.post("/auth/login", response_model=AuthTokenResponse)
def login(payload: LoginRequest, db: DbSession) -> AuthTokenResponse:
    """用户名密码登录。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = AuthService(db)
    service.ensure_default_admin()
    try:
        user = service.login(payload.username, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthTokenResponse(token=service.create_token(user), user=service.user_response(user))


@router.post("/auth/register", response_model=AuthTokenResponse)
def register(payload: RegisterRequest, db: DbSession) -> AuthTokenResponse:
    """邀请码注册普通用户。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = AuthService(db)
    try:
        user = service.register(payload.username, payload.password, payload.invitation_code)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthTokenResponse(token=service.create_token(user), user=service.user_response(user))


@router.get("/auth/me", response_model=UserResponse)
def current_user(user: CurrentUser, db: DbSession) -> UserResponse:
    """读取当前用户。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return AuthService(db).user_response(user)


@router.post("/invitations", response_model=InvitationResponse)
def create_invitation(
    payload: InvitationCreateRequest,
    db: DbSession,
    admin_user: AdminUser,
) -> InvitationResponse:
    """管理员生成邀请码。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return AuthService(db).create_invitation(admin_user, payload.note)


@router.get("/invitations", response_model=list[InvitationResponse])
def list_invitations(
    db: DbSession,
    admin_user: AdminUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[InvitationResponse]:
    """管理员查看邀请码。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return AuthService(db).list_invitations(limit)
