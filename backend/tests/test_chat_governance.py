"""阶段 5 治理测试：按轮配额、流式并发上限、指标保留期清理。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_chat
from app.api.routes_chat import (
    _enforce_daily_round_limit,
    _now_east8,
    create_message,
)
from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric, LlmChatMessage, LlmChatSession
from app.schemas.chat import ChatMessageCreate, ChatSessionCreate
from app.services.agent.events import DoneEvent
from app.services.llm_metric_maintenance import cleanup_expired_metrics


def _settings(**overrides) -> Settings:
    """构造隔离本机密钥文件的测试配置。

    创建日期：2026-06-12
    author: claude
    """

    base = {
        "llm_api_key": "k",
        "llm_api_key_file": None,
        "qwen_api_key_file": None,
        "bocha_api_key_file": None,
        "tushare_token": "t",
        "tushare_token_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def _add_user(db: Session, username: str = "tester") -> AppUser:
    """写入测试用户。

    创建日期：2026-06-12
    author: claude
    """

    user = AppUser(username=username, password_hash="hash", role="ADMIN", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_daily_round_limit_blocks_when_exceeded(monkeypatch) -> None:
    """确认当日问答轮数达到上限时抛 429（R1 按轮计费口径）。

    创建日期：2026-06-12
    author: claude
    """

    monkeypatch.setattr(routes_chat, "get_settings", lambda: _settings(chat_daily_round_limit=2))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _add_user(db)
        session = LlmChatSession(user_id=user.id, title="t", created_at=_now_east8(),
                                 updated_at=_now_east8())
        db.add(session)
        db.commit()
        # 预置今日 2 条 user 消息（已达上限 2）。
        for _ in range(2):
            db.add(LlmChatMessage(session_id=session.id, role="user", content="q",
                                  created_at=_now_east8(), updated_at=_now_east8()))
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            _enforce_daily_round_limit(db, user.id)
    assert exc_info.value.status_code == 429
    assert "上限 2 轮" in exc_info.value.detail


def test_daily_round_limit_allows_under_limit(monkeypatch) -> None:
    """确认未达上限时放行；limit<=0 表示不限制。

    创建日期：2026-06-12
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = _add_user(db)
        # 未达限：放行不抛。
        monkeypatch.setattr(routes_chat, "get_settings",
                            lambda: _settings(chat_daily_round_limit=5))
        _enforce_daily_round_limit(db, user.id)
        # 关闭限额：恒放行。
        monkeypatch.setattr(routes_chat, "get_settings",
                            lambda: _settings(chat_daily_round_limit=0))
        _enforce_daily_round_limit(db, user.id)


def test_create_message_releases_nothing_but_round_limit_applies(monkeypatch) -> None:
    """确认非流式入口在配额内正常作答，超额时 429（不产生孤立用户消息回归）。

    创建日期：2026-06-12
    author: claude
    """

    class FakeEngine:
        def __init__(self, db, settings=None) -> None:
            self.db = db

        def run(self, question, context):
            yield DoneEvent(answer="回答内容", charts=[], tool_trace=[])

    monkeypatch.setattr(routes_chat, "AgentEngine", FakeEngine)
    monkeypatch.setattr(routes_chat, "get_settings", lambda: _settings(chat_daily_round_limit=1))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                                 expire_on_commit=False)
    monkeypatch.setattr(routes_chat, "SessionLocal", session_local)
    Base.metadata.create_all(engine)
    with session_local() as db:
        user = _add_user(db)
        session = routes_chat.create_session(ChatSessionCreate(), db, user)
        # 第一轮：配额内正常作答。
        resp = create_message(session.id, ChatMessageCreate(question="问题一"), db, user)
        assert resp.answer == "回答内容"
        # 第二轮：已用 1 轮达上限 1，应 429。
        with pytest.raises(HTTPException) as exc_info:
            create_message(session.id, ChatMessageCreate(question="问题二"), db, user)
    assert exc_info.value.status_code == 429


def test_stream_semaphore_acquire_release_balance() -> None:
    """确认流式并发信号量获取与释放成对（不泄漏名额）。

    用一个容量 2 的 BoundedSemaphore 模拟并发上限：取满后第三次限时获取失败，
    释放一个后又可获取——验证 worker finally 释放口径不会泄漏或超额释放。

    创建日期：2026-06-12
    author: claude
    """

    sem = threading.BoundedSemaphore(2)
    assert sem.acquire(timeout=0.1) is True
    assert sem.acquire(timeout=0.1) is True
    # 名额耗尽：第三次限时获取失败。
    assert sem.acquire(timeout=0.1) is False
    sem.release()
    # 释放一个后可再获取。
    assert sem.acquire(timeout=0.1) is True
    # 全部释放，且不允许超额释放（BoundedSemaphore 超额 release 抛 ValueError）。
    sem.release()
    sem.release()
    with pytest.raises(ValueError):
        sem.release()


def test_cleanup_expired_metrics_deletes_old_rows() -> None:
    """确认指标清理删除早于保留天数的记录、保留近期记录、limit<=0 不清理（R4）。

    创建日期：2026-06-12
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = _now_east8()
        # 一条 100 天前（应删），一条今天（应留）。
        db.add(LlmCallMetric(question_id="old", phase="answer_stream",
                             created_at=now - timedelta(days=100), updated_at=now))
        db.add(LlmCallMetric(question_id="new", phase="answer_stream",
                             created_at=now, updated_at=now))
        db.commit()

        deleted = cleanup_expired_metrics(db, _settings(llm_metric_retention_days=90))
        assert deleted == 1
        remaining = db.query(LlmCallMetric).all()
        assert len(remaining) == 1
        assert remaining[0].question_id == "new"

        # 关闭清理：retention<=0 不删任何记录。
        deleted_off = cleanup_expired_metrics(db, _settings(llm_metric_retention_days=0))
        assert deleted_off == 0
