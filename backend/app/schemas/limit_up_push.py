from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class LimitUpRecipientItem(BaseModel):
    """打板推送接收人配置响应。

    创建日期：2026-05-08
    author: sunshengxian
    """

    user_id: int
    username: str
    display_name: str | None = None
    enabled: bool
    can_push: bool
    binding_name: str | None = None


class LimitUpRecipientUpdateItem(BaseModel):
    """打板推送接收人配置更新项。

    创建日期：2026-05-08
    author: sunshengxian
    """

    user_id: int = Field(ge=1)
    enabled: bool = True


class LimitUpRecipientUpdateRequest(BaseModel):
    """打板推送接收人批量更新请求。

    创建日期：2026-05-08
    author: sunshengxian
    """

    recipients: list[LimitUpRecipientUpdateItem] = Field(default_factory=list)


class LimitUpPushRequest(BaseModel):
    """打板报告手动推送请求。

    创建日期：2026-05-08
    author: sunshengxian
    """

    send_all: bool = True
    user_ids: list[int] = Field(default_factory=list)


class LimitUpReportListItem(BaseModel):
    """打板分析报告列表项。

    创建日期：2026-05-08
    author: sunshengxian
    """

    id: int
    trade_date: date
    title: str
    status: str
    model: str
    prompt_version: str
    data_snapshot_hash: str
    generated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class LimitUpReportDetail(LimitUpReportListItem):
    """打板分析报告详情。

    创建日期：2026-05-08
    author: sunshengxian
    """

    content_html: str | None = None
    content_markdown: str | None = None
    context: dict[str, Any] | None = None
    data_quality: list[dict[str, Any]] = Field(default_factory=list)


class LimitUpDeliveryItem(BaseModel):
    """打板报告业务推送流水响应。

    创建日期：2026-05-08
    author: sunshengxian
    """

    id: int
    analysis_id: int
    trade_date: date | None = None
    user_id: int
    username: str | None = None
    display_name: str | None = None
    scheduled_kind: str
    scheduled_at: datetime
    status: str
    pushplus_message_log_id: int | None = None
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LimitUpActionResponse(BaseModel):
    """打板推送操作响应。

    创建日期：2026-05-08
    author: sunshengxian
    """

    ok: bool
    message: str
    report_id: int | None = None
    delivery_count: int = 0
