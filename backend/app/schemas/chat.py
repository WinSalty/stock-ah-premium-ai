from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel

ChatModel = Literal["deepseek-v4-flash", "deepseek-v4-pro", "qwen3.6-max-preview"]


class ChatSessionCreate(BaseModel):
    """创建会话请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    title: str = "新的数据问答"


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


class ChatStoredMessageResponse(BaseModel):
    """已保存聊天消息响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    role: str
    content: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChatSessionDetailResponse(ChatSessionResponse):
    """会话详情响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    messages: list[ChatStoredMessageResponse] = Field(default_factory=list)


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


class ChatMessageResponse(BaseModel):
    """聊天消息响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    answer: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
