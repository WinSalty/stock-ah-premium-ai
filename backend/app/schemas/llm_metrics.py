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


class LlmRoundItem(BaseModel):
    """按问答轮（question_id）聚合的指标行。

    一轮 Agent 问答会产生多条 phase 记录（迭代、工具、流式收尾），
    排查时以轮为单位查看更直观；展开后再按 question_id 拉取阶段明细。

    创建日期：2026-06-12
    author: claude
    """

    question_id: str
    conversation_title: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    session_id: int | None = None
    # 轮内阶段统计：总阶段数 / 外部 LLM 调用数 / 工具执行数 / 是否包含失败阶段。
    phase_count: int
    llm_call_count: int
    tool_call_count: int
    has_failure: bool
    # 耗时口径：sum(elapsed_ms)（注意工具耗时已包含在所属迭代的等待中，求和仅供
    # 相对排查参考，不代表用户真实等待墙钟）。
    total_elapsed_ms: float | None = None
    started_at: datetime
    finished_at: datetime


class LlmRoundResponse(BaseModel):
    """按问答轮聚合的分页响应。

    创建日期：2026-06-12
    author: claude
    """

    total: int
    page: int
    page_size: int
    rows: list[LlmRoundItem] = Field(default_factory=list)
