from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps_auth import CurrentUser
from app.db.models.chat import LlmChatMessage, LlmChatSession
from app.db.session import get_db
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionBatchDelete,
    ChatSessionBatchDeleteResponse,
    ChatSessionCreate,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    ChatStoredMessageResponse,
)
from app.services.llm_service import LlmDailyLimitExceeded, LlmService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
logger = logging.getLogger(__name__)
CHAT_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _json_line(payload: dict[str, object]) -> str:
    """生成前端流式读取的一行 JSON。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def _now_east8() -> datetime:
    """生成东八区本地无时区时间，用于聊天会话展示。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return datetime.now(CHAT_TIMEZONE).replace(tzinfo=None)


def _active_session_or_404(db: Session, session_id: int, user_id: int) -> LlmChatSession:
    """读取未删除会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = db.get(LlmChatSession, session_id)
    if session is None or session.deleted_at is not None or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


def _session_title(question: str) -> str:
    """根据首个问题生成会话标题。

    创建日期：2026-05-04
    author: sunshengxian
    """

    title = " ".join(question.strip().split())
    return title[:48] or "新的投资问答"


def _visible_question(payload: ChatMessageCreate) -> str:
    """读取可展示和落库的问题，避免暴露内部提示词。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return (payload.display_question or payload.question).strip()[:256] or payload.question


def _display_user_name(current_user: CurrentUser) -> str:
    """读取指标中展示的用户名称。

    创建日期：2026-05-06
    author: sunshengxian
    """

    return (current_user.display_name or current_user.username).strip()


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


def _recent_history(
    db: Session,
    session_id: int,
    user_id: int,
    limit: int = 10,
) -> list[dict[str, str]]:
    """读取最近对话，供 LLM 生成上下文记忆。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = (
        select(LlmChatMessage)
        .join(LlmChatSession, LlmChatSession.id == LlmChatMessage.session_id)
        .where(LlmChatMessage.session_id == session_id)
        .where(LlmChatSession.user_id == user_id)
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
    session.updated_at = _now_east8()


@router.post("/chat/sessions", response_model=ChatSessionResponse)
def create_session(
    payload: ChatSessionCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> LlmChatSession:
    """创建 LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    now = _now_east8()
    session = LlmChatSession(
        user_id=current_user.id,
        title=payload.title,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/chat/sessions", response_model=list[ChatSessionResponse])
def list_sessions(
    db: DbSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[LlmChatSession]:
    """获取 LLM 问答会话列表。

    创建日期：2026-05-04
    author: sunshengxian
    """

    statement = (
        select(LlmChatSession)
        .where(LlmChatSession.user_id == current_user.id, LlmChatSession.deleted_at.is_(None))
        .order_by(desc(LlmChatSession.updated_at))
        .limit(limit)
    )
    return list(db.scalars(statement).all())


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetailResponse)
def get_session(
    session_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> ChatSessionDetailResponse:
    """获取 LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = _active_session_or_404(db, session_id, current_user.id)
    return ChatSessionDetailResponse(
        id=session.id,
        title=session.title,
        deleted_at=session.deleted_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[_message_response(message) for message in session.messages],
    )


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatStoredMessageResponse])
def list_messages(
    session_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> list[ChatStoredMessageResponse]:
    """获取 LLM 问答消息历史。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = _active_session_or_404(db, session_id, current_user.id)
    return [_message_response(message) for message in session.messages]


@router.delete("/chat/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> Response:
    """逻辑删除 LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = _active_session_or_404(db, session_id, current_user.id)
    now = _now_east8()
    session.deleted_at = now
    session.updated_at = now
    db.commit()
    return Response(status_code=204)


@router.post("/chat/sessions/batch-delete", response_model=ChatSessionBatchDeleteResponse)
def batch_delete_sessions(
    payload: ChatSessionBatchDelete,
    db: DbSession,
    current_user: CurrentUser,
) -> ChatSessionBatchDeleteResponse:
    """批量逻辑删除 LLM 问答会话。

    创建日期：2026-05-05
    author: sunshengxian
    """

    unique_ids = list(dict.fromkeys(payload.session_ids))
    statement = (
        select(LlmChatSession)
        .where(LlmChatSession.user_id == current_user.id)
        .where(LlmChatSession.deleted_at.is_(None))
        .where(LlmChatSession.id.in_(unique_ids))
    )
    sessions = list(db.scalars(statement).all())
    if not sessions:
        return ChatSessionBatchDeleteResponse(deleted_count=0)
    now = _now_east8()
    for session in sessions:
        session.deleted_at = now
        session.updated_at = now
    db.commit()
    return ChatSessionBatchDeleteResponse(deleted_count=len(sessions))


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatMessageResponse)
def create_message(
    session_id: int,
    payload: ChatMessageCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> ChatMessageResponse:
    """提交问题并返回 LLM 回答。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = _active_session_or_404(db, session_id, current_user.id)
    history = _recent_history(db, session_id, current_user.id)
    now = _now_east8()
    visible_question = _visible_question(payload)
    user_message = LlmChatMessage(
        session_id=session_id,
        role="user",
        content=visible_question,
        created_at=now,
        updated_at=now,
    )
    db.add(user_message)
    context = payload.model_dump(
        exclude={"question", "display_question", "llm_model"},
        exclude_none=True,
    )
    context["user_id"] = current_user.id
    context["session_id"] = session_id
    context["_metric_question"] = visible_question
    context["_metric_user_name"] = _display_user_name(current_user)
    context["conversation_history"] = history
    _touch_session(session, visible_question, has_history=bool(history))
    db.commit()
    try:
        answer = LlmService(db).answer(payload.question, context, model=payload.llm_model)
    except LlmDailyLimitExceeded as exc:
        db.rollback()
        logger.error("LLM 非流式问答触发日限流")
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.error("LLM 非流式问答失败", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="智能分析服务暂时不可用，请稍后重试。",
        ) from exc
    assistant_message = LlmChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer.answer,
        sql_text=answer.sql,
        result_preview_json=json.dumps(answer.rows[:20], ensure_ascii=False, default=str),
        created_at=_now_east8(),
        updated_at=_now_east8(),
    )
    db.add(assistant_message)
    _touch_session(session, visible_question, has_history=True)
    db.commit()
    return ChatMessageResponse(answer=answer.answer, rows=answer.rows)


@router.post("/chat/sessions/{session_id}/messages/stream")
def create_message_stream(
    session_id: int,
    payload: ChatMessageCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> StreamingResponse:
    """提交问题并以流式响应返回 LLM 回答。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = _active_session_or_404(db, session_id, current_user.id)
    history = _recent_history(db, session_id, current_user.id)
    now = _now_east8()
    visible_question = _visible_question(payload)
    user_message = LlmChatMessage(
        session_id=session_id,
        role="user",
        content=visible_question,
        created_at=now,
        updated_at=now,
    )
    db.add(user_message)
    _touch_session(session, visible_question, has_history=bool(history))
    db.commit()
    context = payload.model_dump(
        exclude={"question", "display_question", "llm_model"},
        exclude_none=True,
    )
    context["user_id"] = current_user.id
    context["session_id"] = session_id
    context["_metric_question"] = visible_question
    context["_metric_user_name"] = _display_user_name(current_user)
    context["conversation_history"] = history

    def stream() -> Iterator[str]:
        sql = None
        rows: list[dict[str, object]] = []
        answer_parts: list[str] = []
        try:
            sql, rows, chunks = LlmService(db).stream_answer(
                payload.question,
                context,
                model=payload.llm_model,
            )
            yield _json_line({"type": "meta", "rows": rows})
            for chunk in chunks:
                answer_parts.append(chunk)
                yield _json_line({"type": "delta", "content": chunk})
            answer_text = "".join(answer_parts).strip() or "LLM 未返回有效内容。"
            assistant_message = LlmChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                sql_text=sql,
                result_preview_json=json.dumps(rows[:20], ensure_ascii=False, default=str),
                created_at=_now_east8(),
                updated_at=_now_east8(),
            )
            db.add(assistant_message)
            _touch_session(session, visible_question, has_history=True)
            db.commit()
            yield _json_line({"type": "done", "answer": answer_text, "rows": rows})
        except LlmDailyLimitExceeded as exc:
            db.rollback()
            logger.error("LLM 流式问答触发日限流")
            answer_text = str(exc)
            assistant_message = LlmChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                sql_text=sql,
                result_preview_json=json.dumps(rows[:20], ensure_ascii=False, default=str),
                created_at=_now_east8(),
                updated_at=_now_east8(),
            )
            db.add(assistant_message)
            _touch_session(session, visible_question, has_history=True)
            db.commit()
            yield _json_line({"type": "error", "answer": answer_text, "rows": rows})
        except Exception:
            db.rollback()
            logger.error("LLM 流式问答失败", exc_info=True)
            answer_text = "问答失败：智能分析服务暂时不可用，请稍后重试。"
            assistant_message = LlmChatMessage(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                sql_text=sql,
                result_preview_json=json.dumps(rows[:20], ensure_ascii=False, default=str),
                created_at=_now_east8(),
                updated_at=_now_east8(),
            )
            db.add(assistant_message)
            _touch_session(session, visible_question, has_history=True)
            db.commit()
            yield _json_line({"type": "error", "answer": answer_text, "rows": rows})

    return StreamingResponse(stream(), media_type="application/x-ndjson")
