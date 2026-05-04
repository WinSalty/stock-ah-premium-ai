from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.models.chat import LlmChatMessage, LlmChatSession
from app.db.session import get_db
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
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


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session(session_id: int, db: DbSession) -> LlmChatSession:
    """获取 LLM 问答会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    session = db.get(LlmChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


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
    user_message = LlmChatMessage(session_id=session_id, role="user", content=payload.question)
    db.add(user_message)
    context = payload.model_dump(exclude={"question"}, exclude_none=True)
    answer = LlmService(db).answer(payload.question, context)
    assistant_message = LlmChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer.answer,
        sql_text=answer.sql,
        result_preview_json=json.dumps(answer.rows[:20], ensure_ascii=False, default=str),
    )
    db.add(assistant_message)
    db.commit()
    return ChatMessageResponse(answer=answer.answer, sql=answer.sql, rows=answer.rows)


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
    user_message = LlmChatMessage(session_id=session_id, role="user", content=payload.question)
    db.add(user_message)
    db.commit()
    context = payload.model_dump(exclude={"question"}, exclude_none=True)

    def stream() -> Iterator[str]:
        sql = None
        rows: list[dict[str, object]] = []
        answer_parts: list[str] = []
        try:
            sql, rows, chunks = LlmService(db).stream_answer(payload.question, context)
            yield _json_line({"type": "meta", "sql": sql, "rows": rows})
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
            db.commit()
            yield _json_line({"type": "done", "answer": answer_text, "sql": sql, "rows": rows})
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
            db.commit()
            yield _json_line({"type": "error", "answer": answer_text, "sql": sql, "rows": rows})

    return StreamingResponse(stream(), media_type="application/x-ndjson")
