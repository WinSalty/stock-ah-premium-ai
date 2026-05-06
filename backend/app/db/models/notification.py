from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PushplusBinding(TimestampMixin, Base):
    """用户 PushPlus 好友绑定表。

    创建日期：2026-05-05
    author: sunshengxian
    """

    __tablename__ = "pushplus_binding"
    __table_args__ = (
        UniqueConstraint("user_id", name="uk_pushplus_binding_user"),
        Index("idx_pushplus_binding_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    friend_id: Mapped[int] = mapped_column(Integer, nullable=False)
    friend_token: Mapped[str] = mapped_column(String(128), nullable=False)
    friend_nick_name: Mapped[str | None] = mapped_column(String(128))
    friend_remark: Mapped[str | None] = mapped_column(String(128))
    is_follow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AlertEvent(TimestampMixin, Base):
    """提醒事件与推送记录。

    创建日期：2026-05-05
    author: sunshengxian
    """

    __tablename__ = "alert_event"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uk_alert_event_dedupe"),
        Index("idx_alert_event_user_day", "user_id", "trading_day"),
        Index("idx_alert_event_watchlist", "watchlist_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlist_stock.id"))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    metric_direction: Mapped[str | None] = mapped_column(String(8))
    metric_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    target_premium_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8))
    price_alert_market: Mapped[str | None] = mapped_column(String(8))
    price_alert_operator: Mapped[str | None] = mapped_column(String(8))
    price_alert_ts_code: Mapped[str | None] = mapped_column(String(16))
    last_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    target_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    message_title: Mapped[str] = mapped_column(String(128), nullable=False)
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    push_channel: Mapped[str] = mapped_column(String(32), nullable=False, default="PUSHPLUS")
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    push_message_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class PushplusMessageLog(TimestampMixin, Base):
    """PushPlus 推送消息流水。

    创建日期：2026-05-06
    author: sunshengxian
    """

    __tablename__ = "pushplus_message_log"
    __table_args__ = (
        Index("idx_pushplus_message_log_user_created", "user_id", "created_at"),
        Index("idx_pushplus_message_log_status_created", "push_status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    alert_event_id: Mapped[int | None] = mapped_column(ForeignKey("alert_event.id"))
    recipient_type: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_friend_id: Mapped[int | None] = mapped_column(Integer)
    recipient_name: Mapped[str | None] = mapped_column(String(128))
    message_title: Mapped[str] = mapped_column(String(128), nullable=False)
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    push_channel: Mapped[str] = mapped_column(String(32), nullable=False, default="PUSHPLUS")
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    push_message_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
