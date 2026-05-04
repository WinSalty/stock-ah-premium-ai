from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.auth import AppUser
from app.schemas.auth import ProfileUpdateRequest, UserUpdateRequest
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
