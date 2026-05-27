from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ImageGenerationQuotaResponse(BaseModel):
    """图片生成次数响应。

    创建日期：2026-05-27
    author: sunshengxian
    """

    daily_limit: int
    used_count: int
    remaining_count: int
    quota_date: date


class ImageGenerationResponse(BaseModel):
    """图片生成记录响应。

    创建日期：2026-05-27
    author: sunshengxian
    """

    id: int
    user_id: int
    username: str | None = None
    display_name: str | None = None
    prompt: str
    model: str
    size: str
    status: str
    provider: str
    generation_mode: str
    image_url: str | None = None
    reference_image_url: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    file_sha256: str | None = None
    reference_mime_type: str | None = None
    reference_file_size_bytes: int | None = None
    reference_file_sha256: str | None = None
    elapsed_ms: float | None = None
    error_message: str | None = None
    quota: ImageGenerationQuotaResponse | None = None
    created_at: datetime
    updated_at: datetime


class ImageGenerationListResponse(BaseModel):
    """图片生成列表响应。

    创建日期：2026-05-27
    author: sunshengxian
    """

    total: int
    items: list[ImageGenerationResponse]


class ImageGenerationQuotaUpdateRequest(BaseModel):
    """管理员维护图片生成次数请求。

    创建日期：2026-05-27
    author: sunshengxian
    """

    daily_limit: int = Field(ge=0, le=100)


class ImageGenerationAdminQuotaResponse(BaseModel):
    """管理员查看用户图片生成次数响应。

    创建日期：2026-05-27
    author: sunshengxian
    """

    user_id: int
    username: str
    display_name: str | None = None
    role: str
    is_active: bool
    daily_limit: int
    used_count: int
    remaining_count: int
    quota_date: date
    last_reset_at: datetime | None = None
    updated_at: datetime | None = None
