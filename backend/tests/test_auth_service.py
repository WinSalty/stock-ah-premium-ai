from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.schemas.auth import OverviewChartSettings, ProfileUpdateRequest, UserUpdateRequest
from app.services.auth_service import ROLE_USER, AuthService


def test_user_permissions_are_stored_per_user() -> None:
    """确认菜单权限可按用户独立编辑。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="alice", password_hash="hash", role=ROLE_USER, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        service = AuthService(db)
        updated_user = service.update_user(
            user.id,
            UserUpdateRequest(
                display_name="Alice",
                permissions=["chat", "profile", "unknown"],
            ),
        )

        assert service.user_response(updated_user).display_name == "Alice"
        assert service.user_response(updated_user).permissions == ["chat", "profile"]


def test_profile_update_only_changes_basic_fields() -> None:
    """确认个人信息维护不会改动角色和菜单权限。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="bob", password_hash="hash", role=ROLE_USER, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        service = AuthService(db)
        updated_user = service.update_profile(
            user,
            ProfileUpdateRequest(display_name="Bob", email="bob@example.com", phone="13800138000"),
        )
        response = service.user_response(updated_user)

        assert response.display_name == "Bob"
        assert response.email == "bob@example.com"
        assert response.phone == "13800138000"
        assert response.role == ROLE_USER
        assert response.permissions == ["overview", "premium", "chat", "profile"]


def test_overview_chart_settings_are_stored_per_user() -> None:
    """确认总览趋势图指标配置按用户保存并保留核心溢价线。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="chart-user", password_hash="hash", role=ROLE_USER, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        service = AuthService(db)
        default_settings = service.get_overview_chart_settings(user)
        updated_settings = service.update_overview_chart_settings(
            user,
            OverviewChartSettings(
                metric_premium=False,
                median_60=False,
                p20_60=True,
                p80_60=False,
                target_threshold=False,
            ),
        )
        reloaded_settings = service.get_overview_chart_settings(user)

    assert default_settings.metric_premium is True
    assert updated_settings.metric_premium is True
    assert updated_settings.median_60 is False
    assert updated_settings.p20_60 is True
    assert reloaded_settings == updated_settings


def test_remember_login_token_expires_after_configured_days() -> None:
    """确认记住登录 token 使用一个月有效期。

    创建日期：2026-05-05
    author: sunshengxian
    """

    settings = Settings(
        auth_secret_key="unit-test-secret",
        auth_token_expire_hours=1,
        auth_remember_login_expire_days=30,
    )
    service = AuthService(db=object(), settings=settings)  # type: ignore[arg-type]
    user = AppUser(
        id=1,
        username="remember-user",
        password_hash="hash",
        role=ROLE_USER,
        is_active=True,
    )
    now_ts = int(datetime.now(UTC).timestamp())

    short_token = service.create_token(user)
    remember_token = service.create_token(user, remember_login=True)
    short_payload = service.parse_token(short_token)
    remember_payload = service.parse_token(remember_token)

    assert short_payload["exp"] - now_ts <= 3605
    assert 29 * 24 * 3600 <= remember_payload["exp"] - now_ts <= 30 * 24 * 3600 + 5
