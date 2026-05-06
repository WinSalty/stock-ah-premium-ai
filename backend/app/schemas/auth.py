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
    remember_login: bool = True


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
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    bio: str | None = None
    permissions: list[str] = Field(default_factory=list)
    can_use_personal_pushplus: bool = False


class UserUpdateRequest(BaseModel):
    """管理员更新用户请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    role: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    bio: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


class ProfileUpdateRequest(BaseModel):
    """个人资料更新请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    display_name: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    bio: str | None = Field(default=None, max_length=500)


class OverviewChartSettings(BaseModel):
    """总览趋势图用户级指标设置。

    创建日期：2026-05-05
    author: sunshengxian
    """

    metric_premium: bool = True
    median_60: bool = True
    p20_60: bool = True
    p80_60: bool = True
    target_threshold: bool = True


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
