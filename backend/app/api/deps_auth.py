from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.models.auth import AppUser
from app.db.session import get_db
from app.services.auth_service import ROLE_ADMIN, ROLE_PERMISSIONS, AuthError, AuthService

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AppUser:
    """读取当前登录用户。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = AuthService(db).parse_token(token)
    except (AuthError, ValueError):
        raise HTTPException(status_code=401, detail="登录已失效") from None
    user = db.get(AppUser, int(payload.get("user_id", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="登录已失效")
    return user


CurrentUser = Annotated[AppUser, Depends(get_current_user)]


def require_permission(permission: str) -> Callable[[CurrentUser], AppUser]:
    """构造权限依赖。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def dependency(current_user: CurrentUser) -> AppUser:
        permissions = ROLE_PERMISSIONS.get(current_user.role, [])
        if current_user.role != ROLE_ADMIN and permission not in permissions:
            raise HTTPException(status_code=403, detail="没有访问权限")
        return current_user

    return dependency
