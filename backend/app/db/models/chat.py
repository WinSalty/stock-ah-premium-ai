from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class LlmChatSession(TimestampMixin, Base):
    """LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "llm_chat_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    messages: Mapped[list[LlmChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="LlmChatMessage.id",
    )


class LlmChatMessage(TimestampMixin, Base):
    """LLM 问答消息。

    创建日期：2026-05-04
    author: sunshengxian
    """

    __tablename__ = "llm_chat_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("llm_chat_session.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sql_text: Mapped[str | None] = mapped_column(Text)
    result_preview_json: Mapped[str | None] = mapped_column(Text)
    session: Mapped[LlmChatSession] = relationship(back_populates="messages")


class LlmCallMetric(TimestampMixin, Base):
    """LLM 调用耗时指标。

    创建日期：2026-05-05
    author: sunshengxian
    """

    __tablename__ = "llm_call_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_chunk_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
