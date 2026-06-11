from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_chat
from app.api.routes_chat import (
    batch_delete_sessions,
    create_message,
    create_message_stream,
    create_session,
    delete_session,
    get_session,
    list_messages,
    list_sessions,
)
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmChatMessage
from app.schemas.chat import ChatMessageCreate, ChatSessionBatchDelete, ChatSessionCreate
from app.services.agent.events import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    ToolResultEvent,
    ToolStartEvent,
)


def add_user(db: Session, username: str = "tester") -> AppUser:
    """写入测试用户。

    创建日期：2026-05-04
    author: sunshengxian
    """

    user = AppUser(username=username, password_hash="hash", role="ADMIN", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _memory_session_factory():
    """构造支持跨线程共享的内存库会话工厂。

    流式 worker 与非流式失败落库都会另开 SessionLocal，
    因此测试必须用 StaticPool 让所有会话命中同一个内存库。

    创建日期：2026-06-12
    author: claude
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_chat_session_delete_is_logical_and_filtered_from_list() -> None:
    """确认聊天会话逻辑删除后不再出现在列表中。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="待删除会话"), db, user)
        assert len(list_sessions(db, user)) == 1

        delete_session(session.id, db, user)

        assert len(list_sessions(db, user)) == 0
        assert db.get(type(session), session.id).deleted_at is not None
        with pytest.raises(HTTPException):
            get_session(session.id, db, user)


def test_chat_session_batch_delete_only_deletes_current_user_sessions() -> None:
    """确认批量删除仅处理当前用户的未删除会话。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db)
        other_user = add_user(db, "other")
        first = create_session(ChatSessionCreate(title="第一条"), db, user)
        second = create_session(ChatSessionCreate(title="第二条"), db, user)
        other = create_session(ChatSessionCreate(title="他人会话"), db, other_user)

        response = batch_delete_sessions(
            ChatSessionBatchDelete(session_ids=[first.id, second.id, other.id, second.id]),
            db,
            user,
        )

        assert response.deleted_count == 2
        assert list_sessions(db, user) == []
        assert db.get(type(first), first.id).deleted_at is not None
        assert db.get(type(second), second.id).deleted_at is not None
        assert db.get(type(other), other.id).deleted_at is None


def _fake_engine_class(events_factory, captured: dict | None = None):
    """构造可注入事件序列的 FakeAgentEngine 类。

    events_factory(question, context) 返回事件列表；captured 捕获入参供断言。

    创建日期：2026-06-12
    author: claude
    """

    class FakeAgentEngine:
        def __init__(self, db: Session, settings=None) -> None:
            self.db = db

        def run(self, question: str, context: dict[str, object]) -> Iterator[AgentEvent]:
            if captured is not None:
                captured["question"] = question
                captured["context"] = context
            yield from events_factory(question, context)

    return FakeAgentEngine


def test_chat_message_stores_display_question_without_internal_prompt(monkeypatch) -> None:
    """确认内部提示词用于引擎调用但不会作为用户消息展示。

    创建日期：2026-05-04
    author: sunshengxian（Agent 化改造：claude，2026-06-12）
    """

    captured: dict = {}

    def events(question, context):
        return [
            DeltaEvent(content="建议将 H/A 目标阈值设为 8.0%。"),
            DoneEvent(answer="建议将 H/A 目标阈值设为 8.0%。"),
        ]

    monkeypatch.setattr(routes_chat, "AgentEngine", _fake_engine_class(events, captured))
    session_local = _memory_session_factory()
    monkeypatch.setattr(routes_chat, "SessionLocal", session_local)
    with session_local() as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="新的数据问答"), db, user)

        create_message(
            session.id,
            ChatMessageCreate(
                question="内部阈值推荐提示词：请读取页面数据并按公式回答。",
                display_question="为招商银行推荐 H/A 目标阈值",
                only_watchlist=True,
                ts_code="600036.SH",
                llm_model="deepseek-v4-flash",
            ),
            db,
            user,
        )

        user_message = db.scalar(
            select(LlmChatMessage).where(
                LlmChatMessage.session_id == session.id,
                LlmChatMessage.role == "user",
            )
        )

    assert user_message is not None
    assert user_message.content == "为招商银行推荐 H/A 目标阈值"
    # 引擎收到完整内部提示词；上下文剔除 display_question/llm_model 等展示字段。
    assert "内部阈值推荐提示词" in captured["question"]
    assert "display_question" not in captured["context"]
    assert "llm_model" not in captured["context"]
    assert captured["context"]["session_id"] == 1


def test_chat_message_returns_429_and_persists_failure_message(monkeypatch) -> None:
    """确认非流式问答触发日限流时返回 429，且失败也落一条 assistant 消息（R7）。

    创建日期：2026-05-05
    author: sunshengxian（Agent 化改造：claude，2026-06-12）
    """

    def events(question, context):
        return [
            ErrorEvent(
                answer="今日智能问答模型调用次数已达到项目日限额 100 次。",
                kind="daily_limit",
            )
        ]

    monkeypatch.setattr(routes_chat, "AgentEngine", _fake_engine_class(events))
    session_local = _memory_session_factory()
    monkeypatch.setattr(routes_chat, "SessionLocal", session_local)
    with session_local() as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="新的数据问答"), db, user)

        with pytest.raises(HTTPException) as exc_info:
            create_message(
                session.id,
                ChatMessageCreate(question="招商银行当前估值怎么看？"),
                db,
                user,
            )
        assistant_message = db.scalar(
            select(LlmChatMessage).where(
                LlmChatMessage.session_id == session.id,
                LlmChatMessage.role == "assistant",
            )
        )

    assert exc_info.value.status_code == 429
    assert "日限额 100 次" in exc_info.value.detail
    # 失败口径统一：限流文案也作为 assistant 消息落库，避免孤立的用户提问。
    assert assistant_message is not None
    assert "日限额 100 次" in assistant_message.content


def test_chat_message_persists_tool_trace_and_charts(monkeypatch) -> None:
    """确认非流式问答把工具轨迹与图表落库，且 rows 不再返回前端。

    创建日期：2026-06-03
    author: codex（Agent 化改造：claude，2026-06-12）
    """

    trace_items = [
        {
            "tool": "query_database",
            "summary": "查询：十年年化",
            "result_summary": "返回 1 行",
            "ok": True,
            "elapsed_ms": 12.5,
        }
    ]

    def events(question, context):
        return [
            ToolStartEvent(tool="query_database", summary="查询：十年年化"),
            ToolResultEvent(tool="query_database", ok=True, summary="返回 1 行", elapsed_ms=12.5),
            DeltaEvent(content="招商银行近十年平均年化约 19.04%。"),
            DoneEvent(
                answer="招商银行近十年平均年化约 19.04%。",
                charts=[],
                tool_trace=trace_items,
            ),
        ]

    monkeypatch.setattr(routes_chat, "AgentEngine", _fake_engine_class(events))
    session_local = _memory_session_factory()
    monkeypatch.setattr(routes_chat, "SessionLocal", session_local)
    with session_local() as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="新的数据问答"), db, user)

        response = create_message(
            session.id,
            ChatMessageCreate(question="招商银行十年平均年化收益率是多少？"),
            db,
            user,
        )
        assistant_message = db.scalar(
            select(LlmChatMessage).where(
                LlmChatMessage.session_id == session.id,
                LlmChatMessage.role == "assistant",
            )
        )
        stored = list_messages(session.id, db, user)

    assert response.rows == []
    assert response.message_id == assistant_message.id
    assert assistant_message is not None
    assert json.loads(assistant_message.tool_trace_json) == trace_items
    assert json.loads(assistant_message.charts_json) == []
    # 历史消息接口透出解析后的轨迹（前端历史回放用）。
    assistant_stored = [item for item in stored if item.role == "assistant"]
    assert assistant_stored[0].tool_trace == trace_items
    assert assistant_stored[0].charts == []


def test_chat_stream_worker_persists_answer_without_response_consumer(monkeypatch) -> None:
    """确认流式问答即使前端断开不消费响应，也会在后台跑完并保存回答与轨迹。

    创建日期：2026-06-02
    author: sunshengxian（Agent 化改造：claude，2026-06-12）
    """

    def events(question, context):
        assert question == "招商银行当前估值怎么看？"
        assert context["session_id"] == 1
        return [
            ToolStartEvent(tool="get_stock_data", summary="获取个股数据：招商银行"),
            ToolResultEvent(
                tool="get_stock_data", ok=True, summary="获取 1 只股票数据", elapsed_ms=30.0
            ),
            DeltaEvent(content="第一段"),
            DeltaEvent(content="第二段"),
            DoneEvent(
                answer="第一段第二段",
                charts=[],
                tool_trace=[
                    {
                        "tool": "get_stock_data",
                        "summary": "获取个股数据：招商银行",
                        "result_summary": "获取 1 只股票数据",
                        "ok": True,
                        "elapsed_ms": 30.0,
                    }
                ],
            ),
        ]

    monkeypatch.setattr(routes_chat, "AgentEngine", _fake_engine_class(events))
    session_local = _memory_session_factory()
    monkeypatch.setattr(routes_chat, "SessionLocal", session_local)

    with session_local() as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="新的数据问答"), db, user)
        response = create_message_stream(
            session.id,
            ChatMessageCreate(question="招商银行当前估值怎么看？"),
            db,
            user,
        )

    assert response.media_type == "application/x-ndjson"
    assistant_message = None
    for _ in range(50):
        with session_local() as db:
            assistant_message = db.scalar(
                select(LlmChatMessage).where(LlmChatMessage.role == "assistant")
            )
            if assistant_message is not None:
                break
        time.sleep(0.02)

    assert assistant_message is not None
    assert assistant_message.content == "第一段第二段"
    # 新引擎不再写 sql_text，轨迹统一进 tool_trace_json。
    assert assistant_message.sql_text is None
    assert "get_stock_data" in assistant_message.tool_trace_json


def test_chat_stream_worker_emits_error_event_with_persisted_message(monkeypatch) -> None:
    """确认流式问答失败时下发 error 事件且失败文案已落库（kind 不进前端协议）。

    创建日期：2026-06-12
    author: claude
    """

    def events(question, context):
        return [ErrorEvent(answer="问答失败：智能分析服务暂时不可用，请稍后重试。", kind="general")]

    monkeypatch.setattr(routes_chat, "AgentEngine", _fake_engine_class(events))
    session_local = _memory_session_factory()
    monkeypatch.setattr(routes_chat, "SessionLocal", session_local)

    with session_local() as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="新的数据问答"), db, user)
        response = create_message_stream(
            session.id,
            ChatMessageCreate(question="招商银行当前估值怎么看？"),
            db,
            user,
        )

    # 消费响应体：终态 error 事件应携带 message_id 且不暴露内部 kind 字段。
    # StreamingResponse 会把同步生成器包装成异步迭代器，这里用 asyncio 消费。
    async def _collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return chunks

    body = "".join(asyncio.run(_collect()))
    lines = [line for line in body.splitlines() if line.strip()]
    events_payload = [json.loads(line) for line in lines]
    assert events_payload[-1]["type"] == "error"
    assert events_payload[-1]["message_id"] is not None
    assert "kind" not in events_payload[-1]

    with session_local() as db:
        assistant_message = db.scalar(
            select(LlmChatMessage).where(LlmChatMessage.role == "assistant")
        )
    assert assistant_message is not None
    assert "问答失败" in assistant_message.content
