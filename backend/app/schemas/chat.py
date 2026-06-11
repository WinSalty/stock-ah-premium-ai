from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import OrmModel

ChatModel = Literal["deepseek-v4-flash", "deepseek-v4-pro", "qwen3.6-flash"]

# 默认会话标题单点定义（吸收旧评审 E5）：会话创建默认值与"首问改标题"判定
# 此前在 schema 默认值、路由 _touch_session、前端三处硬编码同一字符串，
# 改一处即破坏改名逻辑。后端统一引用本常量，避免魔法字符串漂移。
DEFAULT_CHAT_SESSION_TITLE = "新的数据问答"


class ChatSessionCreate(BaseModel):
    """创建会话请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    title: str = DEFAULT_CHAT_SESSION_TITLE


class ChatSessionResponse(OrmModel):
    """会话响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    title: str
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionBatchDelete(BaseModel):
    """批量删除会话请求。

    创建日期：2026-05-05
    author: sunshengxian
    """

    session_ids: list[int] = Field(min_length=1, max_length=100)


class ChatSessionBatchDeleteResponse(BaseModel):
    """批量删除会话响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    deleted_count: int


def _parse_json_list(raw: Any) -> list[dict[str, Any]]:
    """把 DB 落库的 JSON 文本解析为字典列表，任何异常一律回退空列表。

    业务口径：tool_trace_json / charts_json 由 Agent 引擎写入；历史消息、旧链路消息
    或写入异常时列值为 NULL / 非法 JSON，历史消息接口不应因此报错，统一按"无轨迹/无图表"返回。

    创建日期：2026-06-12
    author: claude
    """

    if not raw or not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        # 非法 JSON 视为无数据，不向前端暴露解析错误。
        return []
    if not isinstance(parsed, list):
        return []
    # 只保留字典元素：防御个别脏数据（如列表里混入字符串）导致响应模型校验失败。
    return [item for item in parsed if isinstance(item, dict)]


class ChatStoredMessageResponse(OrmModel):
    """已保存聊天消息响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    role: str
    content: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    # Agent 引擎扩展字段（创建日期：2026-06-12，author: claude）：
    # charts 为本条回答登记的图表 ChartSpec 列表，tool_trace 为工具执行轨迹；
    # 均从 ORM 的 charts_json / tool_trace_json 文本列解析而来，缺失或解析失败回退空列表。
    charts: list[dict[str, Any]] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _load_json_columns(cls, data: Any) -> Any:
        """构造前从 ORM 对象 / 入参字典解析 *_json 文本列。

        兼容两条构造路径：
        - model_validate(ORM 对象)：探测 charts_json / tool_trace_json 属性并解析为列表，
          其余字段（含 rows，保持历史接口"不回传查询样本"的口径）仍走 from_attributes 默认取值；
        - 关键字构造 / dict 校验（既有调用方）：显式传入的 charts / tool_trace 原样保留，
          未传时若携带 *_json 文本则解析，否则落到字段默认空列表，不影响 rows 既有行为。

        创建日期：2026-06-12
        author: claude
        """

        if isinstance(data, dict):
            # dict 路径：调用方显式给出的解析结果优先，仅在缺失时尝试解析 *_json 文本。
            if "charts" not in data and "charts_json" in data:
                data = {**data, "charts": _parse_json_list(data.get("charts_json"))}
            if "tool_trace" not in data and "tool_trace_json" in data:
                data = {**data, "tool_trace": _parse_json_list(data.get("tool_trace_json"))}
            return data
        if hasattr(data, "charts_json") or hasattr(data, "tool_trace_json"):
            # ORM 路径：把整对象拍平成 dict，确保 charts / tool_trace 来自 *_json 列解析；
            # rows 故意不从 result_preview_json 还原（历史接口约定查询样本不回传前端）。
            return {
                "id": getattr(data, "id", None),
                "role": getattr(data, "role", None),
                "content": getattr(data, "content", None),
                "charts": _parse_json_list(getattr(data, "charts_json", None)),
                "tool_trace": _parse_json_list(getattr(data, "tool_trace_json", None)),
                "created_at": getattr(data, "created_at", None),
                "updated_at": getattr(data, "updated_at", None),
            }
        return data


class ChatSessionDetailResponse(ChatSessionResponse):
    """会话详情响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    messages: list[ChatStoredMessageResponse] = Field(default_factory=list)


class ThresholdRecommendationContext(BaseModel):
    """自选股 AI 阈值推荐的结构化页面上下文。

    创建日期：2026-05-07
    author: sunshengxian
    """

    name: str | None = None
    a_ts_code: str | None = None
    hk_ts_code: str | None = None
    direction: Literal["AH", "HA"] | None = None
    holding_market: str | None = None
    target_premium_pct: float | None = None
    metric_premium_pct: float | None = None
    ah_premium_pct: float | None = None
    ha_premium_pct: float | None = None
    distance_to_target_pct: float | None = None
    premium_median_60: float | None = None
    premium_p20_60: float | None = None
    premium_p80_60: float | None = None
    premium_percentile_60: float | None = None
    connect_channels: str | None = None


class ChatMessageCreate(BaseModel):
    """创建聊天消息请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    question: str
    display_question: str | None = Field(default=None, max_length=256)
    start_date: date | None = None
    end_date: date | None = None
    ts_code: str | None = None
    only_watchlist: bool = False
    llm_model: ChatModel = "deepseek-v4-flash"
    threshold_recommendation: ThresholdRecommendationContext | None = None


class ChatMessageResponse(BaseModel):
    """聊天消息响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    message_id: int | None = None
    answer: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
