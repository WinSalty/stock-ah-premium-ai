from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser, InvitationCode
from app.schemas.auth import (
    OverviewChartSettings,
    ProfileUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)

ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"

ALL_MENU_PERMISSIONS: dict[str, str] = {
    "overview": "总览",
    "sync": "同步",
    "query": "查询",
    "premium": "AH 机会筛选",
    "dividend_reinvestment": "分红再投筛选",
    "chat": "问答",
    "image_generation": "图片生成",
    "llm_metrics": "LLM 耗时",
    "users": "用户管理",
    "pushplus": "PushPlus",
    "limit_up_push": "打板推送",
    "xueqiu_publish": "雪球发布",
    "chat_xueqiu_publish": "问答发布雪球",
    "qmt_review": "实盘复盘",
    "profile": "个人信息",
}

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    ROLE_ADMIN: [
        "overview",
        "sync",
        "query",
        "premium",
        "dividend_reinvestment",
        "chat",
        "image_generation",
        "llm_metrics",
        "users",
        "pushplus",
        "limit_up_push",
        "xueqiu_publish",
        "chat_xueqiu_publish",
        "qmt_review",
        "profile",
    ],
    ROLE_USER: [
        "overview",
        "premium",
        "dividend_reinvestment",
        "chat",
        "image_generation",
        "profile",
    ],
}

DEFAULT_OVERVIEW_CHART_SETTINGS = OverviewChartSettings()

PASSWORD_HASH_ITERATIONS = 120_000
REMEMBER_LOGIN_TOKEN_EXPIRE_DAYS = 30


class AuthError(ValueError):
    """认证业务错误。

    创建日期：2026-05-04
    author: sunshengxian
    """


class AuthService:
    """应用用户、邀请码和 token 服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def ensure_default_admin(self) -> AppUser:
        """确保预置管理员存在。

        创建日期：2026-05-04
        author: sunshengxian
        """

        username = self.settings.default_admin_username.strip()
        user = self.db.scalar(select(AppUser).where(AppUser.username == username))
        if user is not None:
            return user
        user = AppUser(
            username=username,
            password_hash=self.hash_password(self.settings.default_admin_password),
            role=ROLE_ADMIN,
            is_active=True,
            menu_permissions_json=json.dumps(
                DEFAULT_ROLE_PERMISSIONS[ROLE_ADMIN],
                ensure_ascii=False,
            ),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def login(self, username: str, password: str) -> AppUser:
        """校验用户名密码。

        创建日期：2026-05-04
        author: sunshengxian
        """

        user = self.db.scalar(select(AppUser).where(AppUser.username == username.strip()))
        password_matches = user is not None and self.verify_password(password, user.password_hash)
        if user is None or not user.is_active or not password_matches:
            raise AuthError("用户名或密码错误")
        return user

    def register(self, username: str, password: str, invitation_code: str) -> AppUser:
        """使用邀请码注册普通用户。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized_username = username.strip()
        existing_user = self.db.scalar(
            select(AppUser).where(AppUser.username == normalized_username)
        )
        if existing_user is not None:
            raise AuthError("用户名已存在")
        invitation = self.db.scalar(
            select(InvitationCode).where(
                InvitationCode.code == invitation_code.strip(),
                InvitationCode.is_active.is_(True),
                InvitationCode.used_by_user_id.is_(None),
            )
        )
        if invitation is None:
            raise AuthError("邀请码无效或已使用")
        user = AppUser(
            username=normalized_username,
            password_hash=self.hash_password(password),
            role=ROLE_USER,
            is_active=True,
            menu_permissions_json=json.dumps(
                DEFAULT_ROLE_PERMISSIONS[ROLE_USER],
                ensure_ascii=False,
            ),
        )
        self.db.add(user)
        self.db.flush()
        invitation.used_by_user_id = user.id
        invitation.used_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_invitation(self, created_by: AppUser, note: str | None = None) -> InvitationCode:
        """创建邀请码。

        创建日期：2026-05-04
        author: sunshengxian
        """

        invitation = InvitationCode(
            code=secrets.token_urlsafe(10),
            created_by_user_id=created_by.id,
            note=note.strip() if note else None,
            is_active=True,
        )
        self.db.add(invitation)
        self.db.commit()
        self.db.refresh(invitation)
        return invitation

    def list_invitations(self, limit: int = 50) -> list[InvitationCode]:
        """查询邀请码。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return list(
            self.db.scalars(
                select(InvitationCode).order_by(desc(InvitationCode.id)).limit(limit)
            ).all()
        )

    def list_users(self) -> list[AppUser]:
        """查询应用用户列表。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return list(self.db.scalars(select(AppUser).order_by(AppUser.id)).all())

    def update_user(self, user_id: int, payload: UserUpdateRequest) -> AppUser:
        """管理员更新用户角色、状态、资料和菜单权限。

        创建日期：2026-05-04
        author: sunshengxian
        """

        user = self.db.get(AppUser, user_id)
        if user is None:
            raise AuthError("用户不存在")
        values = payload.model_dump(exclude_unset=True)
        if "role" in values and values["role"] is not None:
            role = values["role"].strip().upper()
            if role not in {ROLE_ADMIN, ROLE_USER}:
                raise AuthError("角色只能是 ADMIN 或 USER")
            user.role = role
        if "is_active" in values and values["is_active"] is not None:
            user.is_active = values["is_active"]
        for field in ("display_name", "email", "phone", "bio"):
            if field in values:
                setattr(user, field, self._normalize_optional_text(values[field]))
        if "permissions" in values and values["permissions"] is not None:
            permissions = self.sanitize_permissions(values["permissions"])
            if not permissions:
                raise AuthError("至少保留一个菜单权限")
            user.menu_permissions_json = json.dumps(permissions, ensure_ascii=False)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_profile(self, user: AppUser, payload: ProfileUpdateRequest) -> AppUser:
        """更新当前用户个人资料。

        创建日期：2026-05-04
        author: sunshengxian
        """

        values = payload.model_dump(exclude_unset=True)
        for field in ("display_name", "email", "phone", "bio"):
            if field in values:
                setattr(user, field, self._normalize_optional_text(values[field]))
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_overview_chart_settings(self, user: AppUser) -> OverviewChartSettings:
        """读取当前用户总览趋势图指标设置。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if user.overview_chart_settings_json:
            try:
                payload = json.loads(user.overview_chart_settings_json)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                return self._sanitize_overview_chart_settings(payload)
        return DEFAULT_OVERVIEW_CHART_SETTINGS

    def update_overview_chart_settings(
        self,
        user: AppUser,
        payload: OverviewChartSettings,
    ) -> OverviewChartSettings:
        """保存当前用户总览趋势图指标设置。

        创建日期：2026-05-05
        author: sunshengxian
        """

        settings = self._sanitize_overview_chart_settings(payload.model_dump())
        user.overview_chart_settings_json = json.dumps(
            settings.model_dump(),
            ensure_ascii=False,
        )
        self.db.commit()
        self.db.refresh(user)
        return settings

    def create_token(self, user: AppUser, remember_login: bool = False) -> str:
        """生成自签登录 token。

        创建日期：2026-05-04
        author: sunshengxian
        """

        remember_days = self.settings.auth_remember_login_expire_days
        if remember_days <= 0:
            remember_days = REMEMBER_LOGIN_TOKEN_EXPIRE_DAYS
        expires_delta = (
            timedelta(days=remember_days)
            if remember_login
            else timedelta(hours=self.settings.auth_token_expire_hours)
        )
        expires_at = datetime.now(UTC) + expires_delta
        payload = {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "exp": int(expires_at.timestamp()),
        }
        body = self._b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = self._signature(body)
        return f"{body}.{signature}"

    def user_response(self, user: AppUser) -> UserResponse:
        """生成带权限的用户响应。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return UserResponse(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            display_name=user.display_name,
            email=user.email,
            phone=user.phone,
            bio=user.bio,
            permissions=self.get_user_permissions(user),
            can_use_personal_pushplus=user.username == self.settings.default_admin_username,
        )

    def get_user_permissions(self, user: AppUser) -> list[str]:
        """读取用户粒度菜单权限，缺省时回退到角色模板。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if user.menu_permissions_json:
            try:
                permissions = json.loads(user.menu_permissions_json)
            except json.JSONDecodeError:
                permissions = []
            if isinstance(permissions, list):
                sanitized = self.sanitize_permissions([str(item) for item in permissions])
                if sanitized:
                    return sanitized
        return list(DEFAULT_ROLE_PERMISSIONS.get(user.role, DEFAULT_ROLE_PERMISSIONS[ROLE_USER]))

    def sanitize_permissions(self, permissions: list[str]) -> list[str]:
        """过滤未知菜单权限并保持前端菜单顺序。

        创建日期：2026-05-04
        author: sunshengxian
        """

        requested = set(permissions)
        return [key for key in ALL_MENU_PERMISSIONS if key in requested]

    def _sanitize_overview_chart_settings(
        self,
        payload: dict[str, object],
    ) -> OverviewChartSettings:
        defaults = DEFAULT_OVERVIEW_CHART_SETTINGS.model_dump()
        values = {
            key: bool(payload.get(key, default_value))
            for key, default_value in defaults.items()
        }
        values["metric_premium"] = True
        return OverviewChartSettings(**values)

    def parse_token(self, token: str) -> dict[str, Any]:
        """校验并解析 token。

        创建日期：2026-05-04
        author: sunshengxian
        """

        try:
            body, signature = token.split(".", maxsplit=1)
        except ValueError as exc:
            raise AuthError("登录已失效") from exc
        if not hmac.compare_digest(signature, self._signature(body)):
            raise AuthError("登录已失效")
        payload = json.loads(self._b64decode(body))
        if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
            raise AuthError("登录已过期")
        return payload

    def hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            PASSWORD_HASH_ITERATIONS,
        ).hex()
        return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            method, iterations, salt, digest = password_hash.split("$", maxsplit=3)
        except ValueError:
            return False
        if method != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _signature(self, body: str) -> str:
        digest = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return self._b64encode(digest)

    def _b64encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")

    def _b64decode(self, value: str) -> bytes:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("utf-8"))
