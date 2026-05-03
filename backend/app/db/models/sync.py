from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SyncRun(TimestampMixin, Base):
    """数据同步任务运行记录。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class SyncCheckpoint(TimestampMixin, Base):
    """数据同步断点记录。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "sync_checkpoint"

    dataset: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(128), primary_key=True, default="default")
    last_success_date: Mapped[date | None] = mapped_column(Date)
    last_run_id: Mapped[int | None] = mapped_column(Integer)


class DataQualityIssue(TimestampMixin, Base):
    """数据质量问题记录。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "data_quality_issue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_date: Mapped[date | None] = mapped_column(Date)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="WARN")
    ref_key: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
