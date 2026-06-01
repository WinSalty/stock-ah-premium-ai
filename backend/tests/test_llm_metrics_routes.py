from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes_llm_metrics import get_llm_metrics_summary, list_llm_metrics
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric


def add_user(db: Session) -> AppUser:
    """写入有 LLM 耗时菜单权限的管理员。

    创建日期：2026-05-05
    author: sunshengxian
    """

    user = AppUser(
        username="metrics-admin",
        password_hash="hash",
        role="ADMIN",
        is_active=True,
        menu_permissions_json='["llm_metrics"]',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_list_llm_metrics_filters_and_summarizes_rows() -> None:
    """确认 LLM 调用耗时查询支持筛选和汇总。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db)
        metric_time = datetime.combine(date.today(), datetime.min.time())
        db.add_all(
            [
                LlmCallMetric(
                    question_id="trace-001",
                    user_id=user.id,
                    session_id=7,
                    phase="answer_stream",
                    phase_label="流式回答",
                    phase_description="流式回答主体完成记录。",
                    provider="DeepSeek",
                    model="deepseek-v4-flash",
                    success=1,
                    elapsed_ms=1500.25,
                    first_chunk_ms=260.4,
                    output_chars=120,
                    chunk_count=8,
                    row_count=3,
                    request_payload_json='{"model":"deepseek-v4-flash"}',
                    response_content="阶段回答内容",
                    created_at=metric_time,
                    updated_at=metric_time,
                ),
                LlmCallMetric(
                    question_id="trace-002",
                    user_id=user.id,
                    session_id=7,
                    phase="question_router",
                    provider="Qwen",
                    model="qwen3.6-flash",
                    success=1,
                    elapsed_ms=320.0,
                    created_at=metric_time,
                    updated_at=metric_time,
                ),
            ]
        )
        db.commit()

        result = list_llm_metrics(
            db,
            user,
            provider="DeepSeek",
            start_date=date.today(),
            end_date=date.today(),
        )

    assert result.total == 1
    assert result.summary.total == 1
    assert result.summary.success_count == 1
    assert result.summary.avg_elapsed_ms == 1500.2
    assert result.summary.avg_first_chunk_ms == 260.4
    assert result.rows[0].question_id == "trace-001"
    assert result.rows[0].model == "deepseek-v4-flash"
    assert result.rows[0].phase_label == "流式回答"
    assert result.rows[0].request_payload_json == '{"model":"deepseek-v4-flash"}'
    assert result.rows[0].response_content == "阶段回答内容"


def test_list_llm_metrics_can_skip_summary_for_fast_page_load() -> None:
    """确认列表接口可跳过慢统计，便于前端先展示明细。

    创建日期：2026-06-01
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db)
        metric_time = datetime.combine(date.today(), datetime.min.time())
        db.add(
            LlmCallMetric(
                question_id="trace-fast",
                user_id=user.id,
                session_id=9,
                phase="answer",
                provider="DeepSeek",
                model="deepseek-v4-flash",
                success=1,
                elapsed_ms=600.0,
                created_at=metric_time,
                updated_at=metric_time,
            )
        )
        db.commit()

        result = list_llm_metrics(db, user, include_summary=False, include_total=False)
        summary = get_llm_metrics_summary(db, user, provider="DeepSeek")

    assert result.total == 1
    assert result.total_exact is False
    assert result.has_more is False
    assert result.summary is None
    assert result.rows[0].question_id == "trace-fast"
    assert summary.total == 1
    assert summary.success_count == 1
    assert summary.avg_elapsed_ms == 600.0
