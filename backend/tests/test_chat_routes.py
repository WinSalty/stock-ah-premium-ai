from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes_chat import create_session, delete_session, get_session, list_sessions
from app.db.base import Base
from app.schemas.chat import ChatSessionCreate


def test_chat_session_delete_is_logical_and_filtered_from_list() -> None:
    """确认聊天会话逻辑删除后不再出现在列表中。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        session = create_session(ChatSessionCreate(title="待删除会话"), db)
        assert len(list_sessions(db)) == 1

        delete_session(session.id, db)

        assert len(list_sessions(db)) == 0
        assert db.get(type(session), session.id).deleted_at is not None
        with pytest.raises(HTTPException):
            get_session(session.id, db)
