from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.schemas.llm_metrics import (
    LlmCallMetricItem,
    LlmCallMetricResponse,
    LlmCallMetricSummary,
)

router = APIRouter()
MetricsUser = Annotated[AppUser, Depends(require_permission("llm_metrics"))]


@router.get("/llm-metrics", response_model=LlmCallMetricResponse)
def list_llm_metrics(
    db: DbSession,
    metrics_user: MetricsUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=200)] = 30,
    question_id: Annotated[str | None, Query(max_length=32)] = None,
    provider: Annotated[str | None, Query(max_length=32)] = None,
    model: Annotated[str | None, Query(max_length=64)] = None,
    phase: Annotated[str | None, Query(max_length=64)] = None,
    session_id: Annotated[int | None, Query(ge=1)] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> LlmCallMetricResponse:
    """查询 LLM 调用耗时指标。

    创建日期：2026-05-05
    author: sunshengxian
    """

    filters = _metric_filters(
        question_id=question_id,
        provider=provider,
        model=model,
        phase=phase,
        session_id=session_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )
    total = db.scalar(select(func.count()).select_from(LlmCallMetric).where(*filters)) or 0
    summary = _summary(db, filters)
    statement = (
        select(LlmCallMetric)
        .where(*filters)
        .order_by(desc(LlmCallMetric.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(db.scalars(statement).all())
    return LlmCallMetricResponse(
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
        rows=[_metric_item(row) for row in rows],
    )


def _metric_filters(
    *,
    question_id: str | None,
    provider: str | None,
    model: str | None,
    phase: str | None,
    session_id: int | None,
    user_id: int | None,
    start_date: date | None,
    end_date: date | None,
) -> list[object]:
    filters: list[object] = []
    if question_id:
        filters.append(LlmCallMetric.question_id == question_id.strip())
    if provider:
        filters.append(LlmCallMetric.provider == provider.strip())
    if model:
        filters.append(LlmCallMetric.model == model.strip())
    if phase:
        filters.append(LlmCallMetric.phase == phase.strip())
    if session_id:
        filters.append(LlmCallMetric.session_id == session_id)
    if user_id:
        filters.append(LlmCallMetric.user_id == user_id)
    if start_date:
        filters.append(LlmCallMetric.created_at >= datetime.combine(start_date, time.min))
    if end_date:
        filters.append(LlmCallMetric.created_at <= datetime.combine(end_date, time.max))
    return filters


def _summary(db: DbSession, filters: list[object]) -> LlmCallMetricSummary:
    statement = select(
        func.count(LlmCallMetric.id),
        func.coalesce(func.sum(LlmCallMetric.success), 0),
        func.avg(LlmCallMetric.elapsed_ms),
        func.max(LlmCallMetric.elapsed_ms),
        func.avg(LlmCallMetric.first_chunk_ms),
    ).where(*filters)
    total, success_count, avg_elapsed, max_elapsed, avg_first_chunk = db.execute(statement).one()
    return LlmCallMetricSummary(
        total=int(total or 0),
        success_count=int(success_count or 0),
        avg_elapsed_ms=_round_metric(avg_elapsed),
        max_elapsed_ms=_round_metric(max_elapsed),
        avg_first_chunk_ms=_round_metric(avg_first_chunk),
    )


def _metric_item(metric: LlmCallMetric) -> LlmCallMetricItem:
    return LlmCallMetricItem(
        id=metric.id,
        question_id=metric.question_id,
        user_id=metric.user_id,
        session_id=metric.session_id,
        phase=metric.phase,
        phase_label=metric.phase_label,
        phase_description=metric.phase_description,
        provider=metric.provider,
        model=metric.model,
        success=bool(metric.success),
        elapsed_ms=_round_metric(metric.elapsed_ms),
        first_chunk_ms=_round_metric(metric.first_chunk_ms),
        output_chars=metric.output_chars,
        chunk_count=metric.chunk_count,
        row_count=metric.row_count,
        request_payload_json=metric.request_payload_json,
        response_content=metric.response_content,
        error_message=metric.error_message,
        created_at=metric.created_at,
        updated_at=metric.updated_at,
    )


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 1)
