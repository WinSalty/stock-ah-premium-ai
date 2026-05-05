from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import routes_chat
from app.api.routes_chat import (
    create_message,
    create_session,
    delete_session,
    get_session,
    list_sessions,
)
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmChatMessage
from app.schemas.chat import ChatMessageCreate, ChatSessionCreate
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
            assert model == "qwen3.6-max-preview"
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
                llm_model="qwen3.6-max-preview",
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
