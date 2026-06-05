from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.auth import AppUser


class AiImageGeneration(TimestampMixin, Base):
    """AI 图片生成记录。

    创建日期：2026-05-27
    author: sunshengxian
    """

    __tablename__ = "ai_image_generation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="86gamestore")
    generation_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="TEXT_TO_IMAGE",
    )
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reference_file_relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reference_mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    external_url_expires_unknown: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    request_payload_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql"),
        nullable=True,
    )
    response_summary_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql"),
        nullable=True,
    )
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[AppUser] = relationship()


class AiImageUserQuota(TimestampMixin, Base):
    """AI 图片生成用户每日次数配置。

    创建日期：2026-05-27
    author: sunshengxian
    """

    __tablename__ = "ai_image_user_quota"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    quota_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    user: Mapped[AppUser] = relationship(foreign_keys=[user_id])
    updated_by: Mapped[AppUser | None] = relationship(foreign_keys=[updated_by_user_id])


class AiImageGenerationErrorLog(TimestampMixin, Base):
    """AI 图片生成错误日志，供管理员排查后台任务和供应商失败细节。

    创建日期：2026-06-05
    author: sunshengxian
    """

    __tablename__ = "ai_image_generation_error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_image_generation.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="86gamestore")
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str] = mapped_column(String(128), nullable=False)
    user_message: Mapped[str] = mapped_column(String(512), nullable=False)
    detail_message: Mapped[str] = mapped_column(Text, nullable=False)

    generation: Mapped[AiImageGeneration] = relationship()
    user: Mapped[AppUser] = relationship()
