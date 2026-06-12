from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes_llm_metrics import (
    get_llm_metric_detail,
    get_llm_metrics_summary,
    list_llm_metrics,
)
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
                request_payload_json='{"messages":["用于验证列表不直接返回大字段"]}',
                response_content="详情接口再返回完整响应",
                created_at=metric_time,
                updated_at=metric_time,
            )
        )
        db.commit()

        result = list_llm_metrics(
            db,
            user,
            include_summary=False,
            include_total=False,
            include_content=False,
        )
        summary = get_llm_metrics_summary(db, user, provider="DeepSeek")
        detail = get_llm_metric_detail(db, user, result.rows[0].id)

    assert result.total == 1
    assert result.total_exact is False
    assert result.has_more is False
    assert result.summary is None
    assert result.rows[0].question_id == "trace-fast"
    assert result.rows[0].request_payload_size > 0
    assert result.rows[0].response_content_size > 0
    assert result.rows[0].request_payload_json is None
    assert result.rows[0].response_content is None
    assert summary.total == 1
    assert summary.success_count == 1
    assert summary.avg_elapsed_ms == 600.0
    assert detail.question_id == "trace-fast"
    assert detail.request_payload_json == '{"messages":["用于验证列表不直接返回大字段"]}'
    assert detail.response_content == "详情接口再返回完整响应"


def test_list_llm_metric_rounds_groups_by_question() -> None:
    """确认按问答轮聚合：一轮一行、阶段/工具计数与失败标记正确（试用反馈问题4）。

    创建日期：2026-06-12
    author: claude
    """

    from app.api.routes_llm_metrics import list_llm_metric_rounds

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db)
        t0 = datetime.combine(date.today(), datetime.min.time())

        def metric(qid: str, phase: str, success: int, elapsed: float, seq: int) -> LlmCallMetric:
            return LlmCallMetric(
                question_id=qid,
                conversation_title=f"问题-{qid}",
                user_id=user.id,
                user_name="管理员",
                session_id=9,
                phase=phase,
                success=success,
                elapsed_ms=elapsed,
                created_at=t0.replace(minute=seq),
                updated_at=t0.replace(minute=seq),
            )

        # 一轮 Agent 问答：2 次迭代 + 1 次工具（失败）+ 首包派生 + 流式收尾。
        db.add_all(
            [
                metric("round-a", "agent_iteration", 1, 1000.0, 1),
                metric("round-a", "tool_query_database", 0, 12.0, 2),
                metric("round-a", "agent_iteration", 1, 2000.0, 3),
                metric("round-a", "answer_stream_first_chunk", 1, 0.0, 4),
                metric("round-a", "answer_stream", 1, 3000.0, 5),
                # 另一轮纯回答。
                metric("round-b", "agent_iteration", 1, 800.0, 6),
            ]
        )
        db.commit()

        result = list_llm_metric_rounds(db, user)

        assert result.total == 2
        assert [row.question_id for row in result.rows] == ["round-b", "round-a"]
        round_a = result.rows[1]
        # 阶段总数 5；外部 LLM 调用 3（迭代×2 + 流式收尾，首包派生与工具不计）；工具 1。
        assert round_a.phase_count == 5
        assert round_a.llm_call_count == 3
        assert round_a.tool_call_count == 1
        # 轮内含失败工具步骤 → 失败标记。
        assert round_a.has_failure is True
        assert round_a.total_elapsed_ms == 6012.0
        assert round_a.conversation_title == "问题-round-a"
        round_b = result.rows[0]
        assert round_b.phase_count == 1
        assert round_b.has_failure is False

        # question_id 过滤精确命中单轮。
        filtered = list_llm_metric_rounds(db, user, question_id="round-a")
        assert filtered.total == 1
        assert filtered.rows[0].question_id == "round-a"
