from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LlmCallMetricItem(BaseModel):
    """LLM 调用耗时指标项。

    创建日期：2026-05-05
    author: sunshengxian
    """

    id: int
    question_id: str
    conversation_title: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    session_id: int | None = None
    phase: str
    phase_label: str | None = None
    phase_description: str | None = None
    provider: str | None = None
    model: str | None = None
    success: bool
    elapsed_ms: float | None = None
    first_chunk_ms: float | None = None
    output_chars: int
    chunk_count: int
    row_count: int
    request_payload_size: int = 0
    response_content_size: int = 0
    request_payload_json: str | None = None
    response_content: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class LlmCallMetricSummary(BaseModel):
    """LLM 调用耗时指标摘要。

    创建日期：2026-05-05
    author: sunshengxian
    """

    total: int
    success_count: int
    avg_elapsed_ms: float | None = None
    max_elapsed_ms: float | None = None
    avg_first_chunk_ms: float | None = None


class LlmCallMetricResponse(BaseModel):
    """LLM 调用耗时指标分页响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    total: int
    page: int
    page_size: int
    total_exact: bool = True
    has_more: bool = False
    summary: LlmCallMetricSummary | None = None
    rows: list[LlmCallMetricItem] = Field(default_factory=list)
