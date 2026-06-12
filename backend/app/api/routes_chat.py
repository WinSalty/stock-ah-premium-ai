from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps_auth import CurrentUser
from app.core.config import get_settings
from app.db.models.chat import LlmChatMessage, LlmChatSession
from app.db.session import SessionLocal, get_db
from app.schemas.chat import (
    DEFAULT_CHAT_SESSION_TITLE,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionBatchDelete,
    ChatSessionBatchDeleteResponse,
    ChatSessionCreate,
    ChatSessionDetailResponse,
    ChatSessionResponse,
    ChatStoredMessageResponse,
)
from app.services.agent.engine import CHAT_FAILURE_MESSAGE, AgentEngine
from app.services.auth_service import ROLE_ADMIN

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
logger = logging.getLogger(__name__)
CHAT_TIMEZONE = ZoneInfo("Asia/Shanghai")
CHAT_STREAM_DONE = object()
# 流式并发名额信号量（旧评审 R5）：进程级共享，按配置上限初始化，
# 每个流式请求获取一个名额、worker 结束释放，防止后台线程无上限耗尽连接池。
_STREAM_SEMAPHORE = threading.BoundedSemaphore(get_settings().chat_stream_max_concurrency)


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
    # 兜底标题统一引用默认会话标题常量（E5）：避免"新的投资问答"等多份魔法字符串漂移。
    return title[:48] or DEFAULT_CHAT_SESSION_TITLE


def _enforce_daily_round_limit(db: Session, user_id: int) -> None:
    """校验用户当日问答轮数是否超过可感知配额（阶段 5 / 旧评审 R1）。

    口径：按"用户消息条数"统计当日（东八区自然日）轮数；这是用户能直接理解的
    配额单位，区别于 llm_daily_call_limit 的内部 LLM 调用硬上限。超限抛 429。

    创建日期：2026-06-12
    author: claude
    """

    limit = get_settings().chat_daily_round_limit
    if limit <= 0:
        return
    now = _now_east8()
    today_start = datetime.combine(now.date(), datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)
    statement = (
        select(func.count(LlmChatMessage.id))
        .join(LlmChatSession, LlmChatSession.id == LlmChatMessage.session_id)
        .where(LlmChatSession.user_id == user_id)
        .where(LlmChatMessage.role == "user")
        .where(LlmChatMessage.created_at >= today_start)
        .where(LlmChatMessage.created_at < tomorrow_start)
    )
    used = int(db.scalar(statement) or 0)
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"今日问答次数已达上限 {limit} 轮，请明天再试。",
        )


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


def _parse_json_list(raw: str | None) -> list[dict[str, object]]:
    """解析落库的 JSON 列表列（tool_trace_json / charts_json）。

    历史数据可能为 NULL 或损坏，统一容错为返回空列表，不影响历史回放接口。

    创建日期：2026-06-12
    author: claude
    """

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _message_response(message: LlmChatMessage) -> ChatStoredMessageResponse:
    """转换聊天消息响应：附带工具轨迹与图表，供前端历史回放渲染。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return ChatStoredMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        # rows 字段为接口兼容保留恒空：底层数据样本只留服务端审计。
        rows=[],
        charts=_parse_json_list(message.charts_json),
        tool_trace=_parse_json_list(message.tool_trace_json),
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

    if not has_history and session.title == DEFAULT_CHAT_SESSION_TITLE:
        session.title = _session_title(question)
    session.updated_at = _now_east8()


def _store_assistant_message(
    session_id: int,
    visible_question: str,
    answer_text: str,
    tool_trace: list[dict[str, object]],
    charts: list[dict[str, object]],
) -> int | None:
    """在独立数据库会话中保存一条 assistant 回答（成功与失败共用口径）。

    创建日期：2026-06-02
    author: sunshengxian（Agent 化改造：轨迹与图表落库，claude，2026-06-12）
    """

    # 流式连接可能被浏览器关闭，后台线程不能复用请求生命周期里的 db；
    # 因此这里重新打开会话，按“每轮回答只写一条 assistant 消息”的口径落库，
    # 即使前端不再消费响应，也能在历史记录中看到完整结果。
    # 新引擎不再写 sql_text（多次查询场景下单列无意义），轨迹统一进 tool_trace_json。
    with SessionLocal() as worker_db:
        session = worker_db.get(LlmChatSession, session_id)
        if session is None:
            logger.error("LLM 流式问答落库失败，会话不存在 session_id=%s", session_id)
            return None
        assistant_message = LlmChatMessage(
            session_id=session_id,
            role="assistant",
            content=answer_text,
            tool_trace_json=json.dumps(tool_trace, ensure_ascii=False, default=str),
            charts_json=json.dumps(charts, ensure_ascii=False, default=str),
            created_at=_now_east8(),
            updated_at=_now_east8(),
        )
        worker_db.add(assistant_message)
        _touch_session(session, visible_question, has_history=True)
        try:
            worker_db.commit()
        except Exception:
            worker_db.rollback()
            logger.error("LLM 流式问答落库失败 session_id=%s", session_id, exc_info=True)
            return None
        return assistant_message.id


def _run_chat_stream_worker(
    session_id: int,
    payload: ChatMessageCreate,
    context: dict[str, object],
    visible_question: str,
    event_queue: queue.Queue[dict[str, object] | object],
) -> None:
    """后台消费 Agent 引擎事件流：转发进度事件、终态先落库再回填 message_id。

    引擎保证以 done 或 error 事件收尾（内部异常已转 error），这里只兜底
    worker 自身的意外异常（如落库失败），保证前端总能等到终态事件。

    创建日期：2026-06-02
    author: sunshengxian（Agent 化改造：claude，2026-06-12）
    """

    terminal_sent = False
    try:
        with SessionLocal() as worker_db:
            engine = AgentEngine(worker_db)
            for event in engine.run(payload.question, context):
                if event.type == "done":
                    answer_text = event.answer.strip() or "LLM 未返回有效内容。"
                    message_id = _store_assistant_message(
                        session_id,
                        visible_question,
                        answer_text,
                        event.tool_trace,
                        event.charts,
                    )
                    body = event.to_payload()
                    body["answer"] = answer_text
                    body["message_id"] = message_id
                    event_queue.put(body)
                    terminal_sent = True
                elif event.type == "error":
                    # 失败同样落一条 assistant 消息（吸收旧评审 R7），轨迹与图表留空。
                    message_id = _store_assistant_message(
                        session_id, visible_question, event.answer, [], []
                    )
                    body = event.to_payload()
                    # kind 是给非流式 HTTP 契约用的内部字段，不进前端协议。
                    body.pop("kind", None)
                    body["message_id"] = message_id
                    event_queue.put(body)
                    terminal_sent = True
                else:
                    event_queue.put(event.to_payload())
    except Exception:
        logger.error("LLM 流式问答 worker 异常", exc_info=True)
        if not terminal_sent:
            message_id = _store_assistant_message(
                session_id, visible_question, CHAT_FAILURE_MESSAGE, [], []
            )
            event_queue.put(
                {"type": "error", "message_id": message_id, "answer": CHAT_FAILURE_MESSAGE}
            )
    finally:
        # 释放流式并发名额（R5）：无论成功/失败/异常，worker 结束必须归还信号量，
        # 否则名额泄漏会逐步耗尽并发额度。
        _STREAM_SEMAPHORE.release()
        # 结束标记只通知仍在线的前端停止读取；后台线程不会因浏览器断开而提前退出。
        event_queue.put(CHAT_STREAM_DONE)


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
    # 按轮配额校验在落库用户消息前做：超限直接 429，不产生孤立提问（R1）。
    _enforce_daily_round_limit(db, current_user.id)
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
    # admin 账户豁免 LLM 内部日限额（2026-06-12）：安全网只约束普通用户。
    context["_llm_limit_exempt"] = current_user.role == ROLE_ADMIN
    context["conversation_history"] = history
    _touch_session(session, visible_question, has_history=bool(history))
    db.commit()
    # 非流式接口兼容口径（设计 3.1）：消费引擎事件流，丢弃中间事件，只取终态。
    engine = AgentEngine(db)
    final_event = None
    for event in engine.run(payload.question, context):
        if event.type in {"done", "error"}:
            final_event = event
    if final_event is None or final_event.type == "error":
        # 失败也落一条 assistant 消息（吸收旧评审 R7），再按既有 HTTP 契约抛错
        # （限流 429 / 其他 502，设计 v3 修订 9：状态码行为保持不变）。
        failure_answer = final_event.answer if final_event is not None else CHAT_FAILURE_MESSAGE
        _store_assistant_message(session_id, visible_question, failure_answer, [], [])
        if final_event is not None and final_event.kind == "daily_limit":
            logger.error("LLM 非流式问答触发日限流")
            raise HTTPException(status_code=429, detail=failure_answer)
        logger.error("LLM 非流式问答失败")
        raise HTTPException(status_code=502, detail="智能分析服务暂时不可用，请稍后重试。")
    answer_text = final_event.answer.strip() or "LLM 未返回有效内容。"
    assistant_message = LlmChatMessage(
        session_id=session_id,
        role="assistant",
        content=answer_text,
        tool_trace_json=json.dumps(final_event.tool_trace, ensure_ascii=False, default=str),
        charts_json=json.dumps(final_event.charts, ensure_ascii=False, default=str),
        created_at=_now_east8(),
        updated_at=_now_east8(),
    )
    db.add(assistant_message)
    _touch_session(session, visible_question, has_history=True)
    db.commit()
    return ChatMessageResponse(
        message_id=assistant_message.id,
        answer=answer_text,
        # rows 字段为接口兼容保留恒空：底层数据样本只留服务端审计。
        rows=[],
    )


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
    # 按轮配额校验在落库用户消息前做：超限直接 429，不产生孤立提问（R1）。
    _enforce_daily_round_limit(db, current_user.id)
    # 流式并发名额（R5）：限时获取信号量，拿不到则返回 503 繁忙提示而非无限制起线程，
    # 避免后台 worker 线程数失控耗尽数据库连接池。
    settings = get_settings()
    if not _STREAM_SEMAPHORE.acquire(timeout=settings.chat_stream_acquire_timeout_seconds):
        raise HTTPException(status_code=503, detail="问答服务繁忙，请稍后重试。")
    # 名额已持有：此后任何提前返回路径都必须释放，否则名额泄漏。
    try:
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
        # admin 账户豁免 LLM 内部日限额（2026-06-12）：安全网只约束普通用户。
        context["_llm_limit_exempt"] = current_user.role == ROLE_ADMIN
        context["conversation_history"] = history

        event_queue: queue.Queue[dict[str, object] | object] = queue.Queue()
        worker = threading.Thread(
            target=_run_chat_stream_worker,
            args=(session_id, payload, context, visible_question, event_queue),
            name=f"chat-stream-session-{session_id}",
            daemon=True,
        )
        # worker 启动成功后由其 finally 释放名额；启动前的异常在 except 里释放。
        worker.start()
    except Exception:
        _STREAM_SEMAPHORE.release()
        raise

    def stream() -> Iterator[str]:
        # StreamingResponse 的生成器会随浏览器断开而关闭；这里只读取后台队列，
        # 真正的 LLM 执行和落库在独立线程里完成，避免用户离开页面导致任务被取消。
        while True:
            event = event_queue.get()
            if event is CHAT_STREAM_DONE:
                break
            if not isinstance(event, dict):
                continue
            yield _json_line(event)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
