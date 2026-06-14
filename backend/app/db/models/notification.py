from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    JSON,
    BigInteger,
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
    # 投资建议附加产物列：建议失败不影响报告本体状态机；
    # 存量行默认 PENDING，由推送/发布链路按需回填（ensure_advice_for_analysis）。
    advice_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    advice_html: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    advice_markdown: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    advice_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    advice_error: Mapped[str | None] = mapped_column(Text)


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


class LimitUpSelectedStock(TimestampMixin, Base):
    """打板信号计划落表（一股一行）。

    业务意图：把多阶段选股 pipeline 与投资建议分层的结论，结构化成"一只票一买入日一行"
        的可 join / 可分组 / 可统计记录，供 QMT 闭环归因与只读导出（外部回测/对账）消费；
        报告/建议本体仍以 HTML/Markdown 留在 limit_up_analysis_cache，本表是其结构化镜像。
    口径：trade_date=T 信号日；target_trade_date=T+1 买入日（a_trade_calendar 映射，禁手工+1天）。
    幂等：(trade_date, ts_code, prompt_version) 唯一；写入用整组 delete-then-insert
        （latest-wins），与报告 READY 同事务原子提交；写失败由收口 try/except 降级不阻断报告。
    口径对齐：id 与 source_analysis_id 用 Integer，与主表 limit_up_analysis_cache.id 一致，
        避免外键类型不匹配。

    创建日期：2026-06-13
    author: claude
    """

    __tablename__ = "limit_up_selected_stock"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "ts_code",
            "prompt_version",
            name="uk_limit_up_selected_once",
        ),
        Index("idx_limit_up_selected_target", "target_trade_date"),
        Index("idx_limit_up_selected_analysis", "source_analysis_id"),
        Index("idx_limit_up_selected_tier", "tier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ① 主键与关联键（QMT 闭环归因 join：ts_code + target_trade_date）
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(64))
    # ② 板块 / 连板维度
    board: Mapped[str | None] = mapped_column(String(16))
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    board_level: Mapped[int | None] = mapped_column(Integer)
    limit_type: Mapped[str | None] = mapped_column(String(16))
    # ③ 龙头强度分及各维度分
    leader_strength_score: Mapped[Decimal | None] = mapped_column(DECIMAL(8, 2))
    strength_dim_json: Mapped[dict | None] = mapped_column(JSON)
    # ④ 角色 / 战法 / 形态 / 动作
    role_tags: Mapped[list | None] = mapped_column(JSON)
    strategy_family: Mapped[str | None] = mapped_column(String(32))
    setup: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(32))
    # ⑤ 情绪周期与可成交性
    sentiment_cycle: Mapped[str | None] = mapped_column(String(16))
    market_state: Mapped[str | None] = mapped_column(String(16))
    tradable_flag: Mapped[str] = mapped_column(
        String(16), nullable=False, default="TRADABLE", server_default="TRADABLE"
    )
    # ⑥ 先验概率（闭环归因先验校准消费）
    continuation_prob: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 4))
    next_day_premium_prob: Mapped[Decimal | None] = mapped_column(DECIMAL(5, 4))
    # ⑦ 晋级 / 失败条件与持有逻辑
    boost_conditions: Mapped[list | None] = mapped_column(JSON)
    fail_conditions: Mapped[list | None] = mapped_column(JSON)
    suggested_hold_thesis: Mapped[str | None] = mapped_column(Text)
    # ⑧ 热字段（可成交性判定与展示快照，直接落库便于 join 不回查）
    seal_ratio_pct: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 4))
    limit_order: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 4))
    close: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 6))
    winner_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 4))
    # 评审 F3：竞价两因子分母，随 watchlist 契约下发执行侧。
    float_mktcap: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 4))   # 流通市值(元)，封流比分母
    first_board_vol: Mapped[int | None] = mapped_column(BigInteger)        # 信号日成交量(手)，量能比分母
    # ⑨ 优先级 / 原始结构 / 入选理由
    priority: Mapped[int | None] = mapped_column(Integer)
    item_json: Mapped[dict | None] = mapped_column(JSON)
    selection_reason: Mapped[str | None] = mapped_column(Text)
    # ⑩ 审计与版本（source_analysis_id 与主表 id 同为 Integer）
    source_analysis_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("limit_up_analysis_cache.id"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    advice_degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )


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
