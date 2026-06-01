from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class NineTurnReportListItem(BaseModel):
    """神奇九转分析报告列表项。

    创建日期：2026-06-01
    author: sunshengxian
    """

    id: int
    trade_date: date
    freq: str
    title: str
    status: str
    model: str
    prompt_version: str
    data_snapshot_hash: str
    generated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class NineTurnReportDetail(NineTurnReportListItem):
    """神奇九转分析报告详情。

    创建日期：2026-06-01
    author: sunshengxian
    """

    content_html: str | None = None
    content_markdown: str | None = None
    context: dict[str, Any] | None = None
    data_quality: list[dict[str, Any]]


class NineTurnDeliveryItem(BaseModel):
    """神奇九转报告业务推送流水响应。

    创建日期：2026-06-01
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


class NineTurnActionResponse(BaseModel):
    """神奇九转推送操作响应。

    创建日期：2026-06-01
    author: sunshengxian
    """

    ok: bool
    message: str
    report_id: int | None = None
    delivery_count: int = 0
    xueqiu_record_id: int | None = None
