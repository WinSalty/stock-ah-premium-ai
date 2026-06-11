"""通用 LLM HTTP 客户端。

从 llm_service.py 平移的端点选择、双端点 fallback、同步/流式调用、
日限额计数与调用指标落库能力，供问答引擎、雪球发布、推送等多个业务方共用。
本模块只负责"怎么调模型"，不包含任何问答业务逻辑。

创建日期：2026-06-11
author: claude
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.chat import LlmCallMetric

# 日限额异常的单点定义在 agent.budget（设计 2.3：异常类迁入 budget），
# 此处 re-export 维持既有 import 路径（llm_service / routes 过渡期继续可用）。
from app.services.agent.budget import LlmDailyLimitExceeded as LlmDailyLimitExceeded
from app.services.llm_metric_definitions import phase_description, phase_label

logger = logging.getLogger(__name__)

# 非流式与流式调用的整体超时口径：流式回答内容长，给更宽的超时。
LLM_CHAT_TIMEOUT_SECONDS = 90.0
LLM_STREAM_TIMEOUT_SECONDS = 240.0
# 日限额按东八区自然日统计，与业务展示时区保持一致。
LLM_LIMIT_TIMEZONE = ZoneInfo("Asia/Shanghai")
LLM_LIMIT_EXCEEDED_MESSAGE = (
    "今日智能问答模型调用次数已达到项目日限额 100 次，请明天再试或联系管理员调整配置。"
)
# 计入项目日限额的外部模型主调用阶段；first_chunk 等派生指标不重复计数。
# agent_iteration 是 Agent 引擎的迭代调用 phase：必须计入，否则日限额安全网
# 对新引擎失效（设计 v3 修订 2）；旧链路 phase 在旧链路退役后移除。
LLM_EXTERNAL_CALL_PHASES = (
    "agent_iteration",
    "question_router",
    "stock_code_extraction",
    "stock_disambiguation",
    "generate_sql",
    "repair_sql",
    "answer",
    "answer_stream",
    "threshold_answer",
    "threshold_answer_stream",
)
DEFAULT_CHAT_MODEL = "deepseek-v4-flash"
DEEPSEEK_PRO_CHAT_MODEL = "deepseek-v4-pro"
QWEN_CHAT_MODEL = "qwen3.6-flash"
SUPPORTED_CHAT_MODELS = (DEFAULT_CHAT_MODEL, DEEPSEEK_PRO_CHAT_MODEL, QWEN_CHAT_MODEL)
# 这些 HTTP 状态码代表服务端临时不可用，允许透明切换备用端点。
LLM_FALLBACK_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LlmEndpoint:
    """OpenAI-compatible 模型调用端点。

    创建日期：2026-05-04
    author: sunshengxian
    """

    provider: str
    base_url: str
    api_key: str | None
    model: str


@dataclass(frozen=True)
class LlmCallTrace:
    """LLM 单轮调用日志上下文。

    创建日期：2026-05-05
    author: sunshengxian
    """

    question_id: str
    phase: str
    user_id: int | None = None
    session_id: int | None = None
    conversation_title: str | None = None
    user_name: str | None = None
    # Agent 系统提示词版本号（创建日期：2026-06-12，author: claude）：
    # 由 Agent 引擎在构造 trace 时填入，随指标落库到 llm_call_metric.prompt_version，
    # 用于按版本对比提示词迭代效果；旧链路不传，保持 None 向后兼容。
    prompt_version: str | None = None


@dataclass(frozen=True)
class LlmToolCallRequest:
    """LLM 响应中的单次工具调用请求（OpenAI function calling 协议）。

    创建日期：2026-06-12
    author: claude
    """

    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class LlmChatResult:
    """messages 形态调用的结构化响应：正文与工具调用请求二选一或并存。

    创建日期：2026-06-12
    author: claude
    """

    content: str | None
    tool_calls: tuple[LlmToolCallRequest, ...]
    provider: str
    model: str


class LlmClient:
    """OpenAI-compatible LLM 调用客户端。

    设计口径：
    - 指标落库默认沿用调用方传入的 db 会话（与历史行为一致，避免破坏既有事务边界预期）；
    - 传入 metric_session_factory 时改用独立短会话写指标，不再 commit 调用方会话，
      新接入的业务方（雪球发布、Agent 引擎）应显式传入 SessionLocal 以满足事务隔离。

    创建日期：2026-06-11
    author: claude
    """

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        metric_session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self._metric_session_factory = metric_session_factory

    # ------------------------------------------------------------------
    # 模型与端点
    # ------------------------------------------------------------------

    def normalize_chat_model(self, model: str | None) -> str:
        """转换为 OpenAI-compatible API 支持的模型名。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if not model:
            return DEFAULT_CHAT_MODEL
        normalized = model.strip()
        if normalized.startswith("deepseek-v4-pro"):
            return "deepseek-v4-pro"
        if normalized.startswith("deepseek-v4-flash"):
            return "deepseek-v4-flash"
        return normalized

    def model_endpoint(self, model: str | None = None) -> LlmEndpoint:
        """根据模型名选择 DeepSeek 或 Qwen 调用端点。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = self.normalize_chat_model(model or self.settings.llm_model)
        if normalized.startswith("qwen"):
            return LlmEndpoint(
                provider="Qwen",
                base_url=self.settings.qwen_base_url,
                api_key=self.settings.resolve_qwen_api_key(),
                model=normalized,
            )
        return LlmEndpoint(
            provider="DeepSeek",
            base_url=self.settings.llm_base_url,
            api_key=self.settings.resolve_llm_api_key(),
            model=normalized,
        )

    def fallback_endpoint(
        self,
        endpoint: LlmEndpoint,
        exc: httpx.HTTPError,
    ) -> LlmEndpoint | None:
        """在主模型临时不可用时选择备用端点。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if endpoint.provider != "DeepSeek":
            return None
        if not self._is_retryable_llm_error(exc):
            return None
        fallback = self.model_endpoint(QWEN_CHAT_MODEL)
        if not fallback.api_key:
            return None
        return fallback

    def _is_retryable_llm_error(self, exc: httpx.HTTPError) -> bool:
        """判断外部模型错误是否适合透明切到备用模型。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in LLM_FALLBACK_HTTP_STATUS_CODES
        return False

    # ------------------------------------------------------------------
    # 非流式调用
    # ------------------------------------------------------------------

    def chat_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """发起一次非流式调用；主端点临时不可用时自动切换备用端点。

        创建日期：2026-05-04
        author: sunshengxian
        """

        endpoint = self.model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        try:
            return self._chat_completion_with_endpoint(
                endpoint,
                prompt,
                system_prompt,
                temperature,
                trace,
                response_format,
            )
        except httpx.HTTPError as exc:
            fallback_endpoint = self.fallback_endpoint(endpoint, exc)
            if fallback_endpoint is None:
                raise
            logger.error(
                "%s API 临时不可用，自动切换到 %s question_id=%s phase=%s",
                endpoint.provider,
                fallback_endpoint.provider,
                self._trace_values(trace)[0],
                self._trace_values(trace)[1],
                exc_info=True,
            )
            return self._chat_completion_with_endpoint(
                fallback_endpoint,
                prompt,
                system_prompt,
                temperature,
                trace,
                response_format,
            )

    def _chat_completion_with_endpoint(
        self,
        endpoint: LlmEndpoint,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        trace: LlmCallTrace | None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """按指定端点发起非流式调用，供主模型与备用模型复用。

        创建日期：2026-05-08
        author: sunshengxian
        """

        self.enforce_daily_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            # 仅对结构化小任务透传 JSON 约束，普通回答仍保持模型默认输出口径。
            payload["response_format"] = response_format
        request_payload_json = self._metric_request_payload_json(payload)
        started_at = perf_counter()
        with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
        self._raise_for_status(response, endpoint.provider)
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        self.log_completion(endpoint, trace, started_at, content, request_payload_json)
        return content

    # ------------------------------------------------------------------
    # messages 形态调用（Agent 引擎用：支持工具目录与 tool_calls 解析）
    # ------------------------------------------------------------------

    def chat_completion_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
        tool_choice: str = "auto",
    ) -> LlmChatResult:
        """以 messages 数组发起非流式调用，返回含 tool_calls 的结构化结果。

        与 prompt 形态接口共用端点选择、备用端点 fallback、日限额与指标落库；
        Agent 引擎的迭代调用走这里（phase=agent_iteration）。

        创建日期：2026-06-12
        author: claude
        """

        endpoint = self.model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        try:
            return self._chat_completion_messages_with_endpoint(
                endpoint, messages, tools, temperature, trace, tool_choice
            )
        except httpx.HTTPError as exc:
            fallback_endpoint = self.fallback_endpoint(endpoint, exc)
            if fallback_endpoint is None:
                raise
            logger.error(
                "%s API 临时不可用，自动切换到 %s question_id=%s phase=%s",
                endpoint.provider,
                fallback_endpoint.provider,
                self._trace_values(trace)[0],
                self._trace_values(trace)[1],
                exc_info=True,
            )
            return self._chat_completion_messages_with_endpoint(
                fallback_endpoint, messages, tools, temperature, trace, tool_choice
            )

    def _chat_completion_messages_with_endpoint(
        self,
        endpoint: LlmEndpoint,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        trace: LlmCallTrace | None,
        tool_choice: str,
    ) -> LlmChatResult:
        """按指定端点执行 messages 形态调用并解析 tool_calls。

        创建日期：2026-06-12
        author: claude
        """

        self.enforce_daily_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        payload: dict[str, Any] = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        request_payload_json = self._metric_request_payload_json(payload)
        started_at = perf_counter()
        with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
        self._raise_for_status(response, endpoint.provider)
        body = response.json()
        message = body["choices"][0]["message"]
        content = message.get("content")
        tool_calls: list[LlmToolCallRequest] = []
        for index, raw_call in enumerate(message.get("tool_calls") or []):
            function = raw_call.get("function") or {}
            tool_calls.append(
                LlmToolCallRequest(
                    # 个别 OpenAI 兼容端点可能缺 id：用序号兜底，保证回填配对成立。
                    call_id=str(raw_call.get("id") or f"call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments_json=str(function.get("arguments") or "{}"),
                )
            )
        # 指标的响应内容：有正文记正文，纯工具调用记调用清单，便于耗时页排查。
        metric_content = content or json.dumps(
            [{"tool": call.name, "arguments": call.arguments_json} for call in tool_calls],
            ensure_ascii=False,
        )
        self.log_completion(endpoint, trace, started_at, metric_content, request_payload_json)
        return LlmChatResult(
            content=content,
            tool_calls=tuple(tool_calls),
            provider=endpoint.provider,
            model=endpoint.model,
        )

    def chat_completion_stream_messages(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        trace: LlmCallTrace | None = None,
        on_stream_complete: Callable[[str], None] | None = None,
    ) -> Iterator[str]:
        """以 messages 数组发起流式调用（Agent 引擎最终回答用，phase=answer_stream）。

        创建日期：2026-06-12
        author: claude
        """

        endpoint = self.model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        return self._stream_messages_with_fallback(endpoint, messages, trace, on_stream_complete)

    def _stream_messages_with_fallback(
        self,
        endpoint: LlmEndpoint,
        messages: list[dict[str, Any]],
        trace: LlmCallTrace | None,
        on_stream_complete: Callable[[str], None] | None,
    ) -> Iterator[str]:
        """messages 流式调用 + 主端点繁忙时切换备用 Qwen。

        创建日期：2026-06-12
        author: claude
        """

        try:
            yield from self._stream_messages_once(endpoint, messages, trace, on_stream_complete)
        except httpx.HTTPError as exc:
            fallback_endpoint = self.fallback_endpoint(endpoint, exc)
            if fallback_endpoint is None:
                raise
            logger.error(
                "%s 流式 API 临时不可用，自动切换到 %s question_id=%s phase=%s",
                endpoint.provider,
                fallback_endpoint.provider,
                self._trace_values(trace)[0],
                self._trace_values(trace)[1],
                exc_info=True,
            )
            yield from self._stream_messages_once(
                fallback_endpoint, messages, trace, on_stream_complete
            )

    def _stream_messages_once(
        self,
        endpoint: LlmEndpoint,
        messages: list[dict[str, Any]],
        trace: LlmCallTrace | None,
        on_stream_complete: Callable[[str], None] | None,
    ) -> Iterator[str]:
        """按指定端点发起一次 messages 流式调用，不在本层重试。

        创建日期：2026-06-12
        author: claude
        """

        self.enforce_daily_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        request_payload_json = self._metric_request_payload_json(payload)
        started_at = perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        response_parts: list[str] = []
        with httpx.Client(timeout=LLM_STREAM_TIMEOUT_SECONDS) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response, endpoint.provider)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        now = perf_counter()
                        if first_chunk_at is None:
                            first_chunk_at = now
                            self.log_first_chunk(
                                endpoint, trace, started_at, request_payload_json
                            )
                        chunk_count += 1
                        char_count += len(content)
                        response_parts.append(content)
                        yield content
        self.log_stream_done(
            endpoint,
            trace,
            started_at,
            first_chunk_at,
            chunk_count,
            char_count,
            request_payload_json,
            "".join(response_parts),
        )
        if on_stream_complete is not None:
            on_stream_complete(endpoint.model)

    # ------------------------------------------------------------------
    # 流式调用
    # ------------------------------------------------------------------

    def chat_completion_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        trace: LlmCallTrace | None = None,
        on_stream_complete: Callable[[str], None] | None = None,
    ) -> Iterator[str]:
        """发起一次流式调用并逐块产出内容。

        on_stream_complete 在流正常结束后以实际使用的模型名回调，
        供调用方登记"整轮回答总耗时"等需要业务上下文的指标。

        创建日期：2026-05-04
        author: sunshengxian
        """

        endpoint = self.model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        return self._chat_completion_stream_with_fallback(
            endpoint,
            prompt,
            system_prompt,
            trace,
            on_stream_complete,
        )

    def _chat_completion_stream_with_fallback(
        self,
        endpoint: LlmEndpoint,
        prompt: str,
        system_prompt: str | None,
        trace: LlmCallTrace | None,
        on_stream_complete: Callable[[str], None] | None,
    ) -> Iterator[str]:
        """执行流式调用，并在主模型繁忙时切换到备用 Qwen。

        创建日期：2026-05-08
        author: sunshengxian
        """

        try:
            yield from self._chat_completion_stream_once(
                endpoint,
                prompt,
                system_prompt,
                trace,
                on_stream_complete,
            )
        except httpx.HTTPError as exc:
            fallback_endpoint = self.fallback_endpoint(endpoint, exc)
            if fallback_endpoint is None:
                raise
            logger.error(
                "%s 流式 API 临时不可用，自动切换到 %s question_id=%s phase=%s",
                endpoint.provider,
                fallback_endpoint.provider,
                self._trace_values(trace)[0],
                self._trace_values(trace)[1],
                exc_info=True,
            )
            yield from self._chat_completion_stream_once(
                fallback_endpoint,
                prompt,
                system_prompt,
                trace,
                on_stream_complete,
            )

    def _chat_completion_stream_once(
        self,
        endpoint: LlmEndpoint,
        prompt: str,
        system_prompt: str | None,
        trace: LlmCallTrace | None,
        on_stream_complete: Callable[[str], None] | None,
    ) -> Iterator[str]:
        """按指定端点发起一次流式调用，不在本层重试。

        创建日期：2026-05-08
        author: sunshengxian
        """

        self.enforce_daily_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        request_payload_json = self._metric_request_payload_json(payload)
        started_at = perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        response_parts: list[str] = []
        with httpx.Client(timeout=LLM_STREAM_TIMEOUT_SECONDS) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response, endpoint.provider)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        now = perf_counter()
                        if first_chunk_at is None:
                            first_chunk_at = now
                            self.log_first_chunk(
                                endpoint,
                                trace,
                                started_at,
                                request_payload_json,
                            )
                        chunk_count += 1
                        char_count += len(content)
                        response_parts.append(content)
                        yield content
        self.log_stream_done(
            endpoint,
            trace,
            started_at,
            first_chunk_at,
            chunk_count,
            char_count,
            request_payload_json,
            "".join(response_parts),
        )
        if on_stream_complete is not None:
            on_stream_complete(endpoint.model)

    # ------------------------------------------------------------------
    # 日限额
    # ------------------------------------------------------------------

    def enforce_daily_call_limit(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
    ) -> None:
        """检查项目级 LLM 日调用限额。

        创建日期：2026-05-05
        author: sunshengxian
        """

        limit = self.settings.llm_daily_call_limit
        if limit <= 0:
            return
        used_count = self._today_external_llm_call_count()
        if used_count < limit:
            return
        question_id, phase = self._trace_values(trace)
        logger.error(
            "LLM 日调用限额已用尽 question_id=%s phase=%s provider=%s model=%s used=%s limit=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            used_count,
            limit,
        )
        raise LlmDailyLimitExceeded(self.daily_limit_message(limit))

    def _today_external_llm_call_count(self) -> int:
        """统计当天已发生的外部 LLM 主调用次数。

        创建日期：2026-05-05
        author: sunshengxian
        """

        now = datetime.now(LLM_LIMIT_TIMEZONE).replace(tzinfo=None)
        today_start = datetime.combine(now.date(), time.min)
        tomorrow_start = today_start + timedelta(days=1)
        statement = select(func.count(LlmCallMetric.id)).where(
            LlmCallMetric.phase.in_(LLM_EXTERNAL_CALL_PHASES),
            LlmCallMetric.created_at >= today_start,
            LlmCallMetric.created_at < tomorrow_start,
        )
        try:
            raw_count = self.db.scalar(statement)
        except Exception:
            self.db.rollback()
            logger.error("LLM 日调用次数统计失败，临时放行本次模型调用", exc_info=True)
            return 0
        if isinstance(raw_count, int):
            return raw_count
        if isinstance(raw_count, float):
            return int(raw_count)
        return 0

    def daily_limit_message(self, limit: int) -> str:
        """生成可展示的 LLM 日限流提示。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if limit == 100:
            return LLM_LIMIT_EXCEEDED_MESSAGE
        return (
            f"今日智能问答模型调用次数已达到项目日限额 {limit} 次，"
            "请明天再试或联系管理员调整配置。"
        )

    # ------------------------------------------------------------------
    # 指标落库
    # ------------------------------------------------------------------

    def record_metric(
        self,
        *,
        phase: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
        conversation_title: str | None = None,
        user_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        elapsed_ms: float | None = None,
        first_chunk_ms: float | None = None,
        output_chars: int = 0,
        chunk_count: int = 0,
        row_count: int = 0,
        success: bool = True,
        error_message: str | None = None,
        request_payload_json: str | None = None,
        response_content: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        """记录 LLM 调用耗时指标，失败不影响调用主流程。

        prompt_version 为 Agent 系统提示词版本号（2026-06-12 新增，author: claude），
        默认 None 以兼容所有既有调用方；仅 Agent 链路携带，用于提示词迭代效果对比。

        创建日期：2026-05-05
        author: sunshengxian
        """

        metric = LlmCallMetric(
            question_id=question_id,
            conversation_title=conversation_title,
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            phase=phase,
            phase_label=phase_label(phase),
            phase_description=phase_description(phase),
            provider=provider,
            model=model,
            success=1 if success else 0,
            elapsed_ms=elapsed_ms,
            first_chunk_ms=first_chunk_ms,
            output_chars=output_chars,
            chunk_count=chunk_count,
            row_count=row_count,
            request_payload_json=request_payload_json,
            response_content=response_content,
            error_message=error_message[:512] if error_message else None,
            # Agent 提示词版本透传：非 Agent 链路为 None，列保持 NULL。
            prompt_version=prompt_version,
        )
        if self._metric_session_factory is not None:
            # 独立短会话写指标：不污染调用方请求事务，commit 范围只覆盖指标本身。
            try:
                with self._metric_session_factory() as metric_db:
                    metric_db.add(metric)
                    metric_db.commit()
            except Exception:
                logger.error("LLM 调用耗时指标落库失败（独立会话）", exc_info=True)
            return
        try:
            self.db.add(metric)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.error("LLM 调用耗时指标落库失败", exc_info=True)

    def log_completion(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        content: str,
        request_payload_json: str,
    ) -> None:
        """记录非流式调用完成日志与指标。

        创建日期：2026-05-05
        author: sunshengxian
        """

        question_id, phase = self._trace_values(trace)
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 调用完成 question_id=%s phase=%s provider=%s model=%s elapsed_ms=%.1f "
            "output_chars=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            elapsed_ms,
            len(content),
        )
        if trace is not None:
            self.record_metric(
                phase=trace.phase,
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                conversation_title=trace.conversation_title,
                user_name=trace.user_name,
                provider=endpoint.provider,
                model=endpoint.model,
                elapsed_ms=elapsed_ms,
                output_chars=len(content),
                request_payload_json=request_payload_json,
                response_content=content,
                success=True,
                # 透传 Agent 提示词版本（2026-06-12，author: claude），旧链路为 None。
                prompt_version=trace.prompt_version,
            )

    def log_first_chunk(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        request_payload_json: str,
    ) -> None:
        """记录流式调用首包日志与指标。

        创建日期：2026-05-05
        author: sunshengxian
        """

        question_id, phase = self._trace_values(trace)
        first_chunk_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 流式首包 question_id=%s phase=%s provider=%s model=%s first_chunk_ms=%.1f",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            first_chunk_ms,
        )
        if trace is not None:
            self.record_metric(
                phase=f"{trace.phase}_first_chunk",
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                conversation_title=trace.conversation_title,
                user_name=trace.user_name,
                provider=endpoint.provider,
                model=endpoint.model,
                first_chunk_ms=first_chunk_ms,
                request_payload_json=request_payload_json,
                success=True,
                # 透传 Agent 提示词版本（2026-06-12，author: claude），旧链路为 None。
                prompt_version=trace.prompt_version,
            )

    def log_stream_done(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        first_chunk_at: float | None,
        chunk_count: int,
        char_count: int,
        request_payload_json: str,
        response_content: str,
    ) -> None:
        """记录流式调用完成日志与指标。

        创建日期：2026-05-05
        author: sunshengxian
        """

        question_id, phase = self._trace_values(trace)
        elapsed_ms = (perf_counter() - started_at) * 1000
        first_chunk_ms = (first_chunk_at - started_at) * 1000 if first_chunk_at else None
        logger.info(
            "LLM 流式完成 question_id=%s phase=%s provider=%s model=%s elapsed_ms=%.1f "
            "first_chunk_ms=%s chunks=%s output_chars=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            elapsed_ms,
            f"{first_chunk_ms:.1f}" if first_chunk_ms is not None else "-",
            chunk_count,
            char_count,
        )
        if trace is not None:
            self.record_metric(
                phase=trace.phase,
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                conversation_title=trace.conversation_title,
                user_name=trace.user_name,
                provider=endpoint.provider,
                model=endpoint.model,
                elapsed_ms=elapsed_ms,
                first_chunk_ms=first_chunk_ms,
                output_chars=char_count,
                chunk_count=chunk_count,
                request_payload_json=request_payload_json,
                response_content=response_content,
                success=True,
                # 透传 Agent 提示词版本（2026-06-12，author: claude），旧链路为 None。
                prompt_version=trace.prompt_version,
            )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _trace_values(self, trace: LlmCallTrace | None) -> tuple[str, str]:
        """读取日志展示用的追踪键，缺省时用占位符。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if trace is None:
            return "-", "-"
        return trace.question_id, trace.phase

    def _metric_request_payload_json(self, payload: dict[str, Any]) -> str:
        """序列化实际发送给 LLM 的请求参数，不包含鉴权头和 API Key。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return json.dumps(payload, ensure_ascii=False, default=str)

    def _raise_for_status(self, response: httpx.Response, provider: str) -> None:
        """统一抛出带响应体日志的 HTTP 错误，便于排查上游故障。

        创建日期：2026-05-04
        author: sunshengxian
        """

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            try:
                body = response.text
            except httpx.ResponseNotRead:
                body = response.read().decode("utf-8", errors="replace")
            logger.error(
                "%s API 请求失败 status=%s body=%s",
                provider,
                response.status_code,
                body[:2000],
            )
            raise
