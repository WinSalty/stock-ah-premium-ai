from __future__ import annotations

import time

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
    list_sessions,
)
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmChatMessage
from app.schemas.chat import ChatMessageCreate, ChatSessionBatchDelete, ChatSessionCreate
from app.services.llm_service import ChatAnswer, LlmDailyLimitExceeded


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


def test_chat_message_stores_display_question_without_internal_prompt(monkeypatch) -> None:
    """确认内部提示词用于 LLM 调用但不会作为用户消息展示。

    创建日期：2026-05-04
    author: sunshengxian
    """

    class FakeLlmService:
        def __init__(self, db: Session) -> None:
            self.db = db

        def answer(
            self,
            question: str,
            context: dict[str, object],
            model: str | None = None,
        ) -> ChatAnswer:
            assert "内部阈值推荐提示词" in question
            assert "display_question" not in context
            assert "llm_model" not in context
            assert context["session_id"] == 1
            assert model == "deepseek-v4-flash"
            return ChatAnswer(answer="建议将 H/A 目标阈值设为 8.0%。", sql=None, rows=[])

    monkeypatch.setattr(routes_chat, "LlmService", FakeLlmService)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
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


def test_chat_message_returns_429_when_daily_llm_limit_exceeded(monkeypatch) -> None:
    """确认非流式问答触发项目日限流时返回 429。

    创建日期：2026-05-05
    author: sunshengxian
    """

    class FakeLlmService:
        def __init__(self, db: Session) -> None:
            self.db = db

        def answer(
            self,
            question: str,
            context: dict[str, object],
            model: str | None = None,
        ) -> ChatAnswer:
            raise LlmDailyLimitExceeded("今日智能问答模型调用次数已达到项目日限额 100 次。")

    monkeypatch.setattr(routes_chat, "LlmService", FakeLlmService)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user(db)
        session = create_session(ChatSessionCreate(title="新的数据问答"), db, user)

        with pytest.raises(HTTPException) as exc_info:
            create_message(
                session.id,
                ChatMessageCreate(question="招商银行当前估值怎么看？"),
                db,
                user,
            )

    assert exc_info.value.status_code == 429
    assert "日限额 100 次" in exc_info.value.detail


def test_chat_stream_worker_persists_answer_without_response_consumer(monkeypatch) -> None:
    """确认流式问答即使前端断开不消费响应，也会在后台跑完并保存回答。

    创建日期：2026-06-02
    author: sunshengxian
    """

    class FakeLlmService:
        def __init__(self, db: Session) -> None:
            self.db = db

        def stream_answer(
            self,
            question: str,
            context: dict[str, object],
            model: str | None = None,
        ) -> tuple[str, list[dict[str, object]], object]:
            assert question == "招商银行当前估值怎么看？"
            assert context["session_id"] == 1
            assert model is None
            return "select 1", [{"name": "招商银行"}], iter(["第一段", "第二段"])

    monkeypatch.setattr(routes_chat, "LlmService", FakeLlmService)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(routes_chat, "SessionLocal", testing_session_local)
    Base.metadata.create_all(engine)

    with testing_session_local() as db:
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
        with testing_session_local() as db:
            assistant_message = db.scalar(
                select(LlmChatMessage).where(LlmChatMessage.role == "assistant")
            )
            if assistant_message is not None:
                break
        time.sleep(0.02)

    assert assistant_message is not None
    assert assistant_message.content == "第一段第二段"
    assert assistant_message.sql_text == "select 1"
