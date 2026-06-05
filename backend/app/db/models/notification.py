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
from sqlalchemy.dialects.mysql import LONGTEXT
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


class LimitUpAnalysisCache(TimestampMixin, Base):
    """打板 LLM 分析报告缓存表。

    创建日期：2026-05-08
    author: sunshengxian
    """

    __tablename__ = "limit_up_analysis_cache"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "model",
            "prompt_version",
            "data_snapshot_hash",
            name="uk_limit_up_analysis_snapshot",
        ),
        Index("idx_limit_up_analysis_trade_status", "trade_date", "status"),
        Index("idx_limit_up_analysis_generated", "generated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content_html: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    content_markdown: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    context_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    data_quality_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)


class LimitUpAnalysisStageCache(TimestampMixin, Base):
    """打板报告多阶段 LLM 分析缓存表。

    创建日期：2026-06-05
    author: sunshengxian
    """

    __tablename__ = "limit_up_analysis_stage_cache"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "stage_key",
            "model",
            "prompt_version",
            "input_hash",
            name="uk_limit_up_stage_once",
        ),
        Index("idx_limit_up_stage_trade_stage", "trade_date", "stage_key", "status"),
        Index("idx_limit_up_stage_analysis", "analysis_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("limit_up_analysis_cache.id"))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    output_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    content_html: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)


class LimitUpStockSupplementCache(TimestampMixin, Base):
    """打板报告重点股票筹码补数缓存表。

    创建日期：2026-06-05
    author: sunshengxian
    """

    __tablename__ = "limit_up_stock_supplement_cache"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "ts_code",
            "start_date",
            "end_date",
            name="uk_limit_up_stock_supplement_once",
        ),
        Index("idx_limit_up_stock_supplement_trade", "trade_date", "status"),
        Index("idx_limit_up_stock_supplement_code", "ts_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    cyq_perf_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    cyq_chips_summary_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql")
    )
    data_quality_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    error_message: Mapped[str | None] = mapped_column(Text)


class LimitUpPushRecipient(TimestampMixin, Base):
    """打板报告 PushPlus 接收人配置。

    创建日期：2026-05-08
    author: sunshengxian
    """

    __tablename__ = "limit_up_push_recipient"
    __table_args__ = (
        UniqueConstraint("user_id", name="uk_limit_up_push_recipient_user"),
        Index("idx_limit_up_push_recipient_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weekend_replay_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class LimitUpPushDelivery(TimestampMixin, Base):
    """打板报告业务推送计划与结果表。

    创建日期：2026-05-08
    author: sunshengxian
    """

    __tablename__ = "limit_up_push_delivery"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "scheduled_kind",
            "scheduled_at",
            "user_id",
            name="uk_limit_up_push_delivery_once",
        ),
        Index("idx_limit_up_push_delivery_status", "status", "scheduled_at"),
        Index("idx_limit_up_push_delivery_user", "user_id", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("limit_up_analysis_cache.id"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    scheduled_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    pushplus_message_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("pushplus_message_log.id")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class LimitUpReportShare(TimestampMixin, Base):
    """打板报告临时分享链接。

    创建日期：2026-05-09
    author: sunshengxian
    """

    __tablename__ = "limit_up_report_share"
    __table_args__ = (
        UniqueConstraint("share_token", name="uk_limit_up_report_share_token"),
        Index("idx_limit_up_report_share_analysis", "analysis_id", "created_at"),
        Index("idx_limit_up_report_share_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("limit_up_analysis_cache.id"),
        nullable=False,
    )
    share_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NineTurnAnalysisCache(TimestampMixin, Base):
    """神奇九转 LLM 分析报告缓存表。

    创建日期：2026-06-01
    author: sunshengxian
    """

    __tablename__ = "nine_turn_analysis_cache"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "freq",
            "model",
            "prompt_version",
            "data_snapshot_hash",
            name="uk_nine_turn_analysis_snapshot",
        ),
        Index("idx_nine_turn_analysis_trade_status", "trade_date", "status"),
        Index("idx_nine_turn_analysis_generated", "generated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    freq: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content_html: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    content_markdown: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    context_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    data_quality_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    error_message: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)


class NineTurnPushDelivery(TimestampMixin, Base):
    """神奇九转报告业务推送计划与结果表。

    创建日期：2026-06-01
    author: sunshengxian
    """

    __tablename__ = "nine_turn_push_delivery"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "scheduled_kind",
            "scheduled_at",
            "user_id",
            name="uk_nine_turn_push_delivery_once",
        ),
        Index("idx_nine_turn_push_delivery_status", "status", "scheduled_at"),
        Index("idx_nine_turn_push_delivery_user", "user_id", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("nine_turn_analysis_cache.id"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    scheduled_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    pushplus_message_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("pushplus_message_log.id")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class XueqiuPublishCredential(TimestampMixin, Base):
    """雪球创作者平台登录态配置。

    创建日期：2026-05-10
    author: sunshengxian
    """

    __tablename__ = "xueqiu_publish_credential"
    __table_args__ = (Index("idx_xueqiu_publish_credential_enabled", "enabled"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cookie_text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT, "mysql"), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(512), nullable=False)
    mp_base_url: Mapped[str] = mapped_column(
        String(128), nullable=False, default="https://mp.xueqiu.com"
    )
    referer_url: Mapped[str] = mapped_column(
        String(255), nullable=False, default="https://mp.xueqiu.com/write/"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class XueqiuPublishSetting(TimestampMixin, Base):
    """雪球长文自动发布配置。

    创建日期：2026-05-10
    author: sunshengxian
    """

    __tablename__ = "xueqiu_publish_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheduler_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    poll_hours: Mapped[str] = mapped_column(String(32), nullable=False, default="8")
    poll_minutes: Mapped[str] = mapped_column(String(64), nullable=False, default="30")
    default_cover_pic: Mapped[str | None] = mapped_column(String(512))
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class XueqiuPublishRecord(TimestampMixin, Base):
    """雪球长文草稿与发布流水。

    创建日期：2026-05-10
    author: sunshengxian
    """

    __tablename__ = "xueqiu_publish_record"
    __table_args__ = (
        Index(
            "idx_xueqiu_publish_record_mode_latest",
            "analysis_id",
            "publish_mode",
            "created_at",
        ),
        Index("idx_xueqiu_publish_record_status", "status", "created_at"),
        Index("idx_xueqiu_publish_record_analysis", "analysis_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("limit_up_analysis_cache.id"),
        nullable=True,
    )
    nine_turn_analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("nine_turn_analysis_cache.id")
    )
    chat_message_id: Mapped[int | None] = mapped_column(ForeignKey("llm_chat_message.id"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="LIMIT_UP_REPORT")
    publish_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    content_html: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql"),
        nullable=False,
    )
    cover_pic: Mapped[str | None] = mapped_column(String(512))
    draft_id: Mapped[str | None] = mapped_column(String(128))
    status_id: Mapped[str | None] = mapped_column(String(128))
    article_url: Mapped[str | None] = mapped_column(String(512))
    request_payload_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    response_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    error_message: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
