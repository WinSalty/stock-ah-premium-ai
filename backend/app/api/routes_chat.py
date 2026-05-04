from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.chat import LlmChatMessage, LlmChatSession
from app.db.session import get_db
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    ChatStoredMessageResponse,
)
from app.services.llm_service import LlmService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
logger = logging.getLogger(__name__)


def _json_line(payload: dict[str, object]) -> str:
    """生成前端流式读取的一行 JSON。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def _session_title(question: str) -> str:
    """根据首个问题生成会话标题。

    创建日期：2026-05-04
    author: sunshengxian
    """

    title = " ".join(question.strip().split())
    return title[:48] or "新的投资问答"


def _parse_rows(message: LlmChatMessage) -> list[dict[str, object]]:
    """解析消息中保存的数据预览。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if not message.result_preview_json:
        return []
    try:
        rows = json.loads(message.result_preview_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _message_response(message: LlmChatMessage) -> ChatStoredMessageResponse:
    """转换聊天消息响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return ChatStoredMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        rows=_parse_rows(message),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _recent_history(db: Session, session_id: int, limit: int = 10) -> list[dict[str, str]]:
    """读取最近对话，供 LLM 生成上下文记忆。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = (
        select(LlmChatMessage)
        .where(LlmChatMessage.session_id == session_id)
        .order_by(desc(LlmChatMessage.id))
        .limit(limit)
    )
    messages = list(reversed(db.scalars(statement).all()))
    return [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in {"user", "assistant"}
    ]


def _touch_session(session: LlmChatSession, question: str, has_history: bool) -> None:
    """更新会话标题和更新时间。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if not has_history and session.title == "新的数据问答":
        session.title = _session_title(question)
    session.updated_at = datetime.now()


@router.post("/chat/sessions", response_model=ChatSessionResponse)
def create_session(payload: ChatSessionCreate, db: DbSession) -> LlmChatSession:
    """创建 LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = LlmChatSession(title=payload.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/chat/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[LlmChatSession]:
    """获取 LLM 问答会话列表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = select(LlmChatSession).order_by(desc(LlmChatSession.updated_at)).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetailResponse)
def get_session(session_id: int, db: DbSession) -> ChatSessionDetailResponse:
    """获取 LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = db.get(LlmChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ChatSessionDetailResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[_message_response(message) for message in session.messages],
    )


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatStoredMessageResponse])
def list_messages(session_id: int, db: DbSession) -> list[ChatStoredMessageResponse]:
    """获取 LLM 问答消息历史。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = db.get(LlmChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return [_message_response(message) for message in session.messages]


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatMessageResponse)
def create_message(
    session_id: int,
    payload: ChatMessageCreate,
    db: DbSession,
) -> ChatMessageResponse:
    """提交问题并返回 LLM 回答。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = db.get(LlmChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    history = _recent_history(db, session_id)
    user_message = LlmChatMessage(session_id=session_id, role="user", content=payload.question)
    db.add(user_message)
    context = payload.model_dump(exclude={"question"}, exclude_none=True)
    context["conversation_history"] = history
    _touch_session(session, payload.question, has_history=bool(history))
    db.commit()
    answer = LlmService(db).answer(payload.question, context)
    assistant_message = LlmChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer.answer,
        sql_text=answer.sql,
        result_preview_json=json.dumps(answer.rows[:20], ensure_ascii=False, default=str),
    )
    db.add(assistant_message)
    _touch_session(session, payload.question, has_history=True)
    db.commit()
    return ChatMessageResponse(answer=answer.answer, rows=answer.rows)


@router.post("/chat/sessions/{session_id}/messages/stream")
def create_message_stream(
    session_id: int,
    payload: ChatMessageCreate,
    db: DbSession,
) -> StreamingResponse:
    """提交问题并以流式响应返回 LLM 回答。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = db.get(LlmChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    history = _recent_history(db, session_id)
    user_message = LlmChatMessage(session_id=session_id, role="user", content=payload.question)
    db.add(user_message)
    _touch_session(session, payload.question, has_history=bool(history))
    db.commit()
    context = payload.model_dump(exclude={"question"}, exclude_none=True)
    context["conversation_history"] = history

    def stream() -> Iterator[str]:
        sql = None
        rows: list[dict[str, object]] = []
        answer_parts: list[str] = []
        try:
            sql, rows, chunks = LlmService(db).stream_answer(payload.question, context)
            yield _json_line({"type": "meta", "rows": rows})
            for chunk in chunks:
                answer_parts.append(chunk)
                yield _json_line({"type": "delta", "content": chunk})
            answer_text = "".join(answer_parts).strip() or "DeepSeek 未返回有效内容。"
            assistant_message = LlmChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                sql_text=sql,
                result_preview_json=json.dumps(rows[:20], ensure_ascii=False, default=str),
            )
            db.add(assistant_message)
            _touch_session(session, payload.question, has_history=True)
            db.commit()
            yield _json_line({"type": "done", "answer": answer_text, "rows": rows})
        except Exception:
            db.rollback()
            logger.error("LLM 流式问答失败", exc_info=True)
            answer_text = "问答失败：LLM 生成的查询无法执行或服务暂时不可用，请换一种问法再试。"
            assistant_message = LlmChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                sql_text=sql,
                result_preview_json=json.dumps(rows[:20], ensure_ascii=False, default=str),
            )
            db.add(assistant_message)
            _touch_session(session, payload.question, has_history=True)
            db.commit()
            yield _json_line({"type": "error", "answer": answer_text, "rows": rows})

    return StreamingResponse(stream(), media_type="application/x-ndjson")
