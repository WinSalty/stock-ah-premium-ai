from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


class LoginRequest(BaseModel):
    """登录请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(LoginRequest):
    """注册请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    invitation_code: str = Field(min_length=1, max_length=64)


class UserResponse(OrmModel):
    """用户响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    username: str
    role: str
    is_active: bool
    permissions: list[str] = Field(default_factory=list)


class AuthTokenResponse(BaseModel):
    """登录令牌响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    token: str
    user: UserResponse


class InvitationCreateRequest(BaseModel):
    """创建邀请码请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    note: str | None = Field(default=None, max_length=255)


class InvitationResponse(OrmModel):
    """邀请码响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    code: str
    created_by_user_id: int | None
    used_by_user_id: int | None
    used_at: datetime | None
    note: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
