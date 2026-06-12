from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import load_only

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.schemas.llm_metrics import (
    LlmCallMetricItem,
    LlmCallMetricResponse,
    LlmCallMetricSummary,
    LlmRoundItem,
    LlmRoundResponse,
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
    include_summary: bool = True,
    include_total: bool = True,
    include_content: bool = True,
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
    # 列表首屏只需要分页数据时允许跳过精确 count 和聚合统计，避免慢统计拖住明细呈现。
    total = (
        db.scalar(select(func.count()).select_from(LlmCallMetric).where(*filters))
        if include_total
        else None
    )
    summary = _summary(db, filters) if include_summary else None
    limit_size = page_size if include_total else page_size + 1
    # 列表默认兼容旧接口可返回完整内容；前端首屏传 include_content=false 时，
    # 用 deferred LONGTEXT + 长度派生列保留“可查看”状态，避免一次拉取大上下文。
    metric_columns = [
        LlmCallMetric.id,
        LlmCallMetric.question_id,
        LlmCallMetric.conversation_title,
        LlmCallMetric.user_id,
        LlmCallMetric.user_name,
        LlmCallMetric.session_id,
        LlmCallMetric.phase,
        LlmCallMetric.phase_label,
        LlmCallMetric.phase_description,
        LlmCallMetric.provider,
        LlmCallMetric.model,
        LlmCallMetric.success,
        LlmCallMetric.elapsed_ms,
        LlmCallMetric.first_chunk_ms,
        LlmCallMetric.output_chars,
        LlmCallMetric.chunk_count,
        LlmCallMetric.row_count,
        LlmCallMetric.error_message,
        LlmCallMetric.created_at,
        LlmCallMetric.updated_at,
    ]
    if include_content:
        metric_columns.extend([LlmCallMetric.request_payload_json, LlmCallMetric.response_content])
    statement = (
        select(
            LlmCallMetric,
            AppUser.display_name,
            AppUser.username,
            func.char_length(LlmCallMetric.request_payload_json),
            func.char_length(LlmCallMetric.response_content),
        )
        .options(load_only(*metric_columns))
        .outerjoin(AppUser, AppUser.id == LlmCallMetric.user_id)
        .where(*filters)
        .order_by(desc(LlmCallMetric.id))
        .offset((page - 1) * page_size)
        .limit(limit_size)
    )
    rows = list(db.execute(statement).all())
    has_more = not include_total and len(rows) > page_size
    page_rows = rows[:page_size]
    display_total = int(total or _minimum_visible_total(page, page_size, len(page_rows), has_more))
    return LlmCallMetricResponse(
        total=display_total,
        page=page,
        page_size=page_size,
        total_exact=include_total,
        has_more=has_more,
        summary=summary,
        rows=[
            _metric_item(
                metric,
                _fallback_user_name(display_name, username),
                request_payload_size=payload_size,
                response_content_size=response_size,
                include_content=include_content,
            )
            for metric, display_name, username, payload_size, response_size in page_rows
        ],
    )


@router.get("/llm-metrics/rounds", response_model=LlmRoundResponse)
def list_llm_metric_rounds(
    db: DbSession,
    metrics_user: MetricsUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 20,
    question_id: Annotated[str | None, Query(max_length=32)] = None,
    session_id: Annotated[int | None, Query(ge=1)] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> LlmRoundResponse:
    """按问答轮（question_id）聚合查询指标：一轮一行，便于排查单次对话全貌。

    Agent 化后一轮问答产生多条 phase 记录（迭代/工具/流式收尾），明细视图
    排查不便（试用反馈问题4）；本接口按 question_id 聚合分页，明细由前端
    点击展开后用既有 /llm-metrics?question_id=xxx 懒加载。

    创建日期：2026-06-12
    author: claude
    """

    filters = _metric_filters(
        question_id=question_id,
        provider=None,
        model=None,
        phase=None,
        session_id=session_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )
    total = int(
        db.scalar(
            select(func.count(func.distinct(LlmCallMetric.question_id))).where(*filters)
        )
        or 0
    )
    # 聚合口径：external LLM 调用按 provider 维度（DeepSeek/Qwen 等真实模型），
    # 工具执行按 phase 前缀 tool_ 计数；首包派生记录（*_first_chunk）不计入两者。
    is_tool_phase = LlmCallMetric.phase.like("tool\\_%", escape="\\")
    is_first_chunk = LlmCallMetric.phase.like("%\\_first\\_chunk", escape="\\")
    statement = (
        select(
            LlmCallMetric.question_id,
            func.max(LlmCallMetric.conversation_title),
            func.max(LlmCallMetric.user_id),
            func.max(LlmCallMetric.user_name),
            func.max(LlmCallMetric.session_id),
            func.count(LlmCallMetric.id),
            func.coalesce(
                func.sum(
                    case((is_tool_phase | is_first_chunk, 0), else_=1)
                ),
                0,
            ),
            func.coalesce(func.sum(case((is_tool_phase, 1), else_=0)), 0),
            func.min(LlmCallMetric.success),
            func.sum(LlmCallMetric.elapsed_ms),
            func.min(LlmCallMetric.created_at),
            func.max(LlmCallMetric.created_at),
            func.max(LlmCallMetric.id),
        )
        .where(*filters)
        .group_by(LlmCallMetric.question_id)
        .order_by(desc(func.max(LlmCallMetric.id)))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = []
    for row in db.execute(statement).all():
        (
            qid,
            title,
            row_user_id,
            user_name,
            row_session_id,
            phase_count,
            llm_count,
            tool_count,
            min_success,
            sum_elapsed,
            started_at,
            finished_at,
            _max_id,
        ) = row
        rows.append(
            LlmRoundItem(
                question_id=qid,
                conversation_title=title,
                user_id=row_user_id,
                user_name=user_name,
                session_id=row_session_id,
                phase_count=int(phase_count or 0),
                llm_call_count=int(llm_count or 0),
                tool_call_count=int(tool_count or 0),
                has_failure=int(min_success or 0) == 0,
                total_elapsed_ms=_round_metric(sum_elapsed),
                started_at=started_at,
                finished_at=finished_at,
            )
        )
    return LlmRoundResponse(total=total, page=page, page_size=page_size, rows=rows)


@router.get("/llm-metrics/summary", response_model=LlmCallMetricSummary)
def get_llm_metrics_summary(
    db: DbSession,
    metrics_user: MetricsUser,
    question_id: Annotated[str | None, Query(max_length=32)] = None,
    provider: Annotated[str | None, Query(max_length=32)] = None,
    model: Annotated[str | None, Query(max_length=64)] = None,
    phase: Annotated[str | None, Query(max_length=64)] = None,
    session_id: Annotated[int | None, Query(ge=1)] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> LlmCallMetricSummary:
    """懒加载 LLM 调用耗时统计摘要。

    创建日期：2026-06-01
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
    return _summary(db, filters)


@router.get("/llm-metrics/{metric_id}", response_model=LlmCallMetricItem)
def get_llm_metric_detail(
    db: DbSession,
    metrics_user: MetricsUser,
    metric_id: Annotated[int, Path(ge=1)],
) -> LlmCallMetricItem:
    """按指标 ID 懒加载请求参数和模型响应全文。

    创建日期：2026-06-02
    author: sunshengxian
    """

    # 详情接口只在管理员点击“查看”时读取 LONGTEXT，避免列表首屏携带大 payload。
    statement = (
        select(LlmCallMetric, AppUser.display_name, AppUser.username)
        .outerjoin(AppUser, AppUser.id == LlmCallMetric.user_id)
        .where(LlmCallMetric.id == metric_id)
    )
    row = db.execute(statement).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="指标记录不存在")
    metric, display_name, username = row
    return _metric_item(
        metric,
        _fallback_user_name(display_name, username),
        include_content=True,
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
        # 追踪 ID 精确匹配单轮问答，避免模糊查询误把重复问题或相邻会话混入排查范围。
        filters.append(LlmCallMetric.question_id == question_id.strip())
    if provider:
        # 来源、模型、阶段均按落库枚举精确过滤，保证统计口径和表格明细口径一致。
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
        # 日期筛选按页面选择的自然日闭区间展开，重跑统计时不遗漏当天最后一条指标。
        filters.append(LlmCallMetric.created_at >= datetime.combine(start_date, time.min))
    if end_date:
        filters.append(LlmCallMetric.created_at <= datetime.combine(end_date, time.max))
    return filters


def _summary(db: DbSession, filters: list[object]) -> LlmCallMetricSummary:
    """按当前筛选条件聚合顶部统计卡片。

    创建日期：2026-05-05
    author: sunshengxian
    """

    # 摘要统计仍保持数据库单次聚合，前端已拆成懒加载接口；慢统计不会再阻塞列表首屏。
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


def _minimum_visible_total(page: int, page_size: int, row_count: int, has_more: bool) -> int:
    """计算跳过精确 count 时分页可用的最小总数。

    创建日期：2026-06-01
    author: sunshengxian
    """

    # 前端首屏只需要知道当前页行数以及是否存在下一页；若多取一行发现还有数据，
    # 总数先给到“下一页至少存在”的下界，待摘要懒加载完成后再替换成精确统计。
    current_page_end = (page - 1) * page_size + row_count
    return current_page_end + (1 if has_more else 0)


def _metric_item(
    metric: LlmCallMetric,
    fallback_user_name: str | None = None,
    *,
    request_payload_size: int | None = None,
    response_content_size: int | None = None,
    include_content: bool = True,
) -> LlmCallMetricItem:
    request_payload_json = metric.request_payload_json if include_content else None
    response_content = metric.response_content if include_content else None
    payload_size = request_payload_size
    if payload_size is None and request_payload_json:
        payload_size = len(request_payload_json)
    response_size = response_content_size
    if response_size is None and response_content:
        response_size = len(response_content)
    return LlmCallMetricItem(
        id=metric.id,
        question_id=metric.question_id,
        conversation_title=metric.conversation_title,
        user_id=metric.user_id,
        user_name=metric.user_name or fallback_user_name,
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
        request_payload_size=int(payload_size or 0),
        response_content_size=int(response_size or 0),
        request_payload_json=request_payload_json,
        response_content=response_content,
        error_message=metric.error_message,
        created_at=metric.created_at,
        updated_at=metric.updated_at,
    )


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 1)


def _fallback_user_name(display_name: str | None, username: str | None) -> str | None:
    display_name = (display_name or "").strip()
    username = (username or "").strip()
    return display_name or username or None
