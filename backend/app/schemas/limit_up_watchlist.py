"""打板选股 watchlist 结构化契约（机器可读）。

业务意图：把 limit_up_selected_stock 一股一行的结构化结论，定义为稳定的对外契约——
    既作只读导出接口 (/api/internal/watchlist) 的返回体，也作字段口径的单一来源。
版本：WATCHLIST_SCHEMA_VERSION 与 limit_up_selected_stock.schema_version 对齐，字段结构演进时升版。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# 契约版本：字段结构演进时升版；落表 schema_version 写同一常量，便于按版本筛历史样本。
WATCHLIST_SCHEMA_VERSION = "1.0.0"


class LimitUpWatchlistItem(BaseModel):
    """单只入选股的结构化契约（从 LimitUpSelectedStock ORM 直接序列化）。

    注意：不暴露 item_json（内部审计/回放快照），对外只给结构化列。
    """

    model_config = ConfigDict(from_attributes=True)

    # ① 关联键
    trade_date: date = Field(description="信号日 T")
    target_trade_date: date = Field(description="计划买入日 T+1")
    ts_code: str = Field(description="标准代码 600000.SH 形态")
    name: str | None = None
    # ② 板块 / 连板维度
    board: str | None = Field(default=None, description="MAIN 主板 / GEM 创业板")
    tier: str = Field(description="入选分层：FIRST_BOARD/CHAIN/HIGH_BOARD")
    board_level: int | None = None
    limit_type: str | None = None
    # ③ 龙头强度
    leader_strength_score: Decimal | None = None
    strength_dim_json: dict[str, Any] | None = None
    # ④ 角色 / 战法 / 形态 / 动作
    role_tags: list[str] | None = None
    strategy_family: str | None = None
    setup: str | None = None
    action: str | None = Field(default=None, description="重点观察/谨慎观察/放弃观察")
    # ⑤ 情绪周期与可成交性
    sentiment_cycle: str | None = None
    market_state: str | None = None
    tradable_flag: str = "TRADABLE"
    # ⑥ 先验概率
    continuation_prob: Decimal | None = None
    next_day_premium_prob: Decimal | None = None
    # ⑦ 晋级 / 失败条件与持有逻辑
    boost_conditions: list[Any] | None = None
    fail_conditions: list[Any] | None = None
    suggested_hold_thesis: str | None = None
    # ⑧ 热字段
    seal_ratio_pct: Decimal | None = None
    limit_order: Decimal | None = None
    turnover_rate: Decimal | None = None
    close: Decimal | None = None
    winner_rate: Decimal | None = None
    # ⑨ 优先级 / 入选理由
    priority: int | None = None
    selection_reason: str | None = None
    # ⑩ 版本与审计
    schema_version: str = WATCHLIST_SCHEMA_VERSION
    model: str
    prompt_version: str
    advice_degraded: bool = False


class LimitUpWatchlistResponse(BaseModel):
    """watchlist 只读导出响应体（按买入日查询）。"""

    schema_version: str = WATCHLIST_SCHEMA_VERSION
    trade_date: date | None = Field(default=None, description="查询的信号日 T")
    target_trade_date: date | None = Field(
        default=None, description="买入日 T+1（取自命中行，无数据时为 None）"
    )
    market_state: str | None = Field(default=None, description="当日市场情绪/空仓闸门（全行同值）")
    count: int = 0
    items: list[LimitUpWatchlistItem] = Field(default_factory=list)
