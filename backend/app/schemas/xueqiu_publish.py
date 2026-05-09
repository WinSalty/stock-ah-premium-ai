from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class XueqiuCredentialRequest(BaseModel):
    """雪球发布登录态保存请求。

    创建日期：2026-05-10
    author: sunshengxian
    """

    enabled: bool = True
    cookie_text: str = Field(min_length=20)
    user_agent: str = Field(default="", max_length=512)
    mp_base_url: str = Field(default="https://mp.xueqiu.com", max_length=128)
    referer_url: str = Field(default="https://mp.xueqiu.com/write/", max_length=255)
    expires_at: datetime | None = None


class XueqiuCredentialSummary(BaseModel):
    """雪球发布登录态摘要响应。

    创建日期：2026-05-10
    author: sunshengxian
    """

    configured: bool
    enabled: bool = False
    cookie_preview: str | None = None
    user_agent: str | None = None
    mp_base_url: str | None = None
    referer_url: str | None = None
    expires_at: datetime | None = None
    last_verified_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime | None = None


class XueqiuActionResponse(BaseModel):
    """雪球发布操作响应。

    创建日期：2026-05-10
    author: sunshengxian
    """

    ok: bool
    message: str
    record_id: int | None = None
    article_url: str | None = None
    draft_id: str | None = None
    status_id: str | None = None


class XueqiuDraftPreview(BaseModel):
    """雪球长文草稿预览。

    创建日期：2026-05-10
    author: sunshengxian
    """

    analysis_id: int
    trade_date: date
    source_title: str
    title: str
    content_html: str
    content_text: str


class XueqiuPublishRequest(BaseModel):
    """雪球长文发布请求。

    创建日期：2026-05-10
    author: sunshengxian
    """

    analysis_id: int | None = Field(default=None, ge=1)
    publish: bool = False
    force: bool = False
    cover_pic: str | None = Field(default=None, max_length=512)


class XueqiuPublishRecordItem(BaseModel):
    """雪球发布流水列表项。

    创建日期：2026-05-10
    author: sunshengxian
    """

    id: int
    analysis_id: int
    trade_date: date | None = None
    publish_mode: str
    status: str
    title: str
    draft_id: str | None = None
    status_id: str | None = None
    article_url: str | None = None
    error_message: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class XueqiuPublishRecordDetail(XueqiuPublishRecordItem):
    """雪球发布流水详情。

    创建日期：2026-05-10
    author: sunshengxian
    """

    content_html: str
    cover_pic: str | None = None
    request_payload_json: str | None = None
    response_json: str | None = None
