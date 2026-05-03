from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


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
    created_at: datetime
    updated_at: datetime


class ChatMessageCreate(BaseModel):
    """创建聊天消息请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    question: str
    start_date: date | None = None
    end_date: date | None = None
    ts_code: str | None = None


class ChatMessageResponse(BaseModel):
    """聊天消息响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    answer: str
    sql: str | None
    rows: list[dict[str, Any]] = Field(default_factory=list)
