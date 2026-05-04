from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AppUser(TimestampMixin, Base):
    """应用用户表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="USER")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_name: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    bio: Mapped[str | None] = mapped_column(Text)
    menu_permissions_json: Mapped[str | None] = mapped_column(Text)


class InvitationCode(TimestampMixin, Base):
    """用户注册邀请码。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "invitation_code"
    __table_args__ = (UniqueConstraint("code", name="uk_invitation_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    used_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[AppUser | None] = relationship(foreign_keys=[created_by_user_id])
    used_by: Mapped[AppUser | None] = relationship(foreign_keys=[used_by_user_id])
