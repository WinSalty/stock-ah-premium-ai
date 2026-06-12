"""Agent 主循环引擎：消息组装、迭代控制、流式事件产出与失败口径收敛。

执行口径（chat-agent-refactor-design-and-plan.md 3.1 节）：
- 中间迭代用非流式调用便于完整解析 tool_calls；判定无 tool_calls 后以同样
  messages 重新发起一次流式生成（接受一次重复调用成本，换取打字机体验）；
- 迭代耗尽时注入强制收尾指令做最后一次流式作答；
- 任何不可恢复异常（含日限额）统一转 error 事件，由路由层落库失败消息；
- 指标一律经 LlmCallTrace 走 llm_client 落库，且引擎构造 LlmClient 时显式传
  metric_session_factory（独立短会话，R3 终态）。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.services.agent.budget import (
    TOOL_MESSAGE_MAX_CHARS,
    LlmDailyLimitExceeded,
    ToolTraceItem,
    TurnState,
    compress_messages_for_budget,
    truncate_text,
)
from app.services.agent.events import (
    AgentEvent,
    ChartEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    ToolResultEvent,
    ToolStartEvent,
)
from app.services.agent.prompts import PROMPT_VERSION, build_system_prompt
from app.services.agent.tool_registry import ToolCall, ToolRegistry
from app.services.agent.tools import build_tools
from app.services.llm_client import LlmCallTrace, LlmChatResult, LlmClient

logger = logging.getLogger(__name__)

# 失败兜底文案：与旧链路对用户口径保持一致，避免前端文案回归。
CHAT_FAILURE_MESSAGE = "问答失败：智能分析服务暂时不可用，请稍后重试。"
# 会话历史窗口：沿用旧链路"最近 10 条、单条 1200 字"的清洗口径。
HISTORY_MAX_MESSAGES = 10
HISTORY_MESSAGE_MAX_CHARS = 1200
# 迭代耗尽时的强制收尾指令（设计 3.1 主循环伪代码）。
FORCE_FINISH_INSTRUCTION = (
    "工具调用次数已达上限，请基于已有材料用自然语言直接给出最终回答，"
    "禁止输出任何工具调用标记、XML 或内部协议语法。"
)
# 迭代内容为空/疑似协议泄漏时的补救收尾指令。
FINAL_ANSWER_NUDGE = (
    "请用自然语言直接输出最终回答；禁止再调用任何工具，"
    "禁止输出工具调用标记、XML 或内部协议语法。"
)
# 流式收尾仍泄漏工具语法时的兜底文案（生产缺陷 219bddf9 的最后防线）。
MARKUP_FALLBACK_MESSAGE = "本轮回答生成出现异常内容已被拦截，请重试或换一种问法。"
# 回答只剩无效图表占位符时的纠错指令（生产缺陷 977cf4a3：模型引用历史轮次占位符，
# 前端按安全口径渲染为空，用户看到空回答）。回填后模型可重新调 render_chart 出图。
INVALID_CHART_NUDGE = (
    "你引用的图表占位符在本轮无效：图表必须在本轮调用 render_chart 重新登记后，"
    "使用新返回的占位符。请重新组织回答；需要展示图表就先调用 render_chart，"
    "否则用文字和表格直接回答。"
)
# 图表占位符匹配（与前端 CHART_PLACEHOLDER_PATTERN 口径一致）。
_CHART_PLACEHOLDER_PATTERN = re.compile(r"\{\{chart:([a-zA-Z0-9_-]+)\}\}")
# 流式头部缓冲长度：攒够这些字符先做协议泄漏检测，再开始向前端下发。
STREAM_GUARD_BUFFER_CHARS = 64
# 复用迭代内容下发时的分片长度：保持前端打字机渐进渲染体验。
PREPARED_ANSWER_CHUNK_CHARS = 48
# 工具调用语法泄漏特征：模型把 function calling 协议当正文输出时的标记
# （DeepSeek 的 DSML 标记、OpenAI 风格 tool_calls 文本等）。
_TOOL_MARKUP_PATTERNS = (
    "｜DSML｜",
    "<|DSML|",
    "tool_calls>",
    "tool▁call",
    "<|tool",
    "invoke name=",
)


class AgentEngine:
    """问答 Agent 引擎：以事件流形式产出一轮回答的全部执行过程。

    创建日期：2026-06-12
    author: claude
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        # 指标写独立短会话：不污染请求事务（吸收旧评审 R3）。
        self.llm_client = LlmClient(
            db,
            self.settings,
            metric_session_factory=SessionLocal,
        )

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def run(self, question: str, context: dict[str, Any] | None = None) -> Iterator[AgentEvent]:
        """执行一轮问答：产出 tool_start/tool_result/chart/delta 与终态事件。

        终态保证：要么以 DoneEvent 结束，要么以 ErrorEvent 结束（统一失败口径，
        覆盖流式与非流式入口，吸收旧评审 R7）。

        创建日期：2026-06-12
        author: claude
        """

        try:
            yield from self._run(question, context or {})
        except LlmDailyLimitExceeded as exc:
            # 日限额是用户可感知的预期失败：用异常文本作为回答文案落库。
            yield ErrorEvent(answer=str(exc), kind="daily_limit")
        except Exception:  # noqa: BLE001
            logger.error("Agent 引擎执行失败 question=%s", question[:80], exc_info=True)
            yield ErrorEvent(answer=CHAT_FAILURE_MESSAGE, kind="general")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _run(self, question: str, context: dict[str, Any]) -> Iterator[AgentEvent]:
        """主循环实现：见模块头部口径说明。

        创建日期：2026-06-12
        author: claude
        """

        metric_question = str(context.get("_metric_question") or question).strip()
        turn_state = TurnState(
            question_id=uuid.uuid4().hex,
            user_id=self._optional_int(context.get("user_id")),
            session_id=self._optional_int(context.get("session_id")),
            # 指标展示口径与旧链路一致：会话标题取问题前 48 字、用户名截 64 字。
            conversation_title=metric_question[:48] or None,
            user_name=(str(context.get("_metric_user_name") or "").strip()[:64] or None),
            threshold_context=self._threshold_context(context),
        )
        tools = build_tools(self.db, self.settings, turn_state)
        registry = ToolRegistry(tools)
        messages = self._build_messages(question, context, registry, turn_state)

        for _iteration in range(max(1, self.settings.agent_max_iterations)):
            messages = compress_messages_for_budget(
                messages, self.settings.agent_context_budget_chars
            )
            result = self.llm_client.chat_completion_messages(
                messages,
                tools=registry.specs() or None,
                model=self.settings.agent_model,
                trace=self._trace(turn_state, "agent_iteration"),
            )
            if not result.tool_calls:
                # 无工具调用：直接复用本次迭代生成的内容作为最终回答（生产缺陷
                # 219bddf9 修复）。此前的"丢弃内容重发流式"会让模型二次生成时改判
                # 去调工具，而流式请求不带 tools，工具调用语法就被当正文吐出；
                # 复用内容同时省掉一次外部 LLM 调用。
                content = (result.content or "").strip()
                if content and not self._looks_like_tool_markup(content):
                    # 净化无效图表占位符（缺陷 977cf4a3：模型引用历史轮次占位符）。
                    sanitized = self._strip_invalid_chart_placeholders(content, turn_state)
                    if sanitized.strip():
                        yield from self._emit_prepared_answer(sanitized, turn_state)
                        return
                    # 净化后为空说明回答全靠无效占位符：回填纠错指令继续迭代，
                    # 给模型重新调用 render_chart 出图（或改用文字回答）的机会。
                    logger.warning(
                        "Agent 回答仅含无效图表占位符，回填纠错重试 question_id=%s",
                        turn_state.question_id,
                    )
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "system", "content": INVALID_CHART_NUDGE})
                    continue
                # 内容为空或疑似协议泄漏：注入禁止工具指令后改走流式补救。
                logger.warning(
                    "Agent 迭代内容异常（空或疑似工具语法泄漏），走流式补救 question_id=%s",
                    turn_state.question_id,
                )
                messages.append({"role": "system", "content": FINAL_ANSWER_NUDGE})
                yield from self._stream_final_answer(messages, turn_state)
                return
            messages.append(self._assistant_tool_call_message(result))
            for raw_call in result.tool_calls:
                call = ToolCall(
                    call_id=raw_call.call_id,
                    name=raw_call.name,
                    arguments_json=raw_call.arguments_json,
                )
                start_summary = registry.summarize(call)
                yield ToolStartEvent(tool=call.name, summary=start_summary)
                tool_result = registry.execute(call, turn_state)
                yield ToolResultEvent(
                    tool=call.name,
                    ok=tool_result.ok,
                    summary=tool_result.summary,
                    elapsed_ms=round(tool_result.elapsed_ms, 1),
                )
                turn_state.tool_trace.append(
                    ToolTraceItem(
                        tool=call.name,
                        summary=start_summary,
                        result_summary=tool_result.summary,
                        ok=tool_result.ok,
                        elapsed_ms=round(tool_result.elapsed_ms, 1),
                    )
                )
                self._record_tool_metric(turn_state, call, tool_result)
                if call.name == "render_chart" and tool_result.ok:
                    chart_id = str(tool_result.extra.get("chart_id") or "")
                    spec = tool_result.extra.get("spec") or {}
                    yield ChartEvent(chart_id=chart_id, spec=spec)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "name": call.name,
                        "content": truncate_text(tool_result.payload, TOOL_MESSAGE_MAX_CHARS),
                    }
                )
        # 迭代耗尽：注入收尾指令后做最后一次流式作答。
        messages.append({"role": "system", "content": FORCE_FINISH_INSTRUCTION})
        yield from self._stream_final_answer(messages, turn_state)

    def _emit_prepared_answer(
        self,
        answer: str,
        turn_state: TurnState,
    ) -> Iterator[AgentEvent]:
        """把迭代阶段已生成的回答按分片下发为 delta 事件并产出 DoneEvent。

        内容已在 agent_iteration 阶段计量，本路径不再发起外部调用；
        分片下发保持前端渐进渲染体验。

        创建日期：2026-06-12
        author: claude
        """

        for start in range(0, len(answer), PREPARED_ANSWER_CHUNK_CHARS):
            yield DeltaEvent(content=answer[start : start + PREPARED_ANSWER_CHUNK_CHARS])
        yield DoneEvent(
            answer=answer,
            charts=list(turn_state.charts),
            tool_trace=[item.to_payload() for item in turn_state.tool_trace],
        )

    def _stream_final_answer(
        self,
        messages: list[dict[str, Any]],
        turn_state: TurnState,
    ) -> Iterator[AgentEvent]:
        """流式生成最终回答并产出终态 DoneEvent（phase 记 answer_stream）。

        仅两条路径走到这里：迭代耗尽强制收尾、迭代内容异常的补救生成。
        头部先攒 STREAM_GUARD_BUFFER_CHARS 字符做协议泄漏检测：流式请求不带
        tools，模型若试图调工具会把工具调用语法当正文输出；命中特征则吞掉
        整段输出，改下发兜底文案，避免把内部协议渲染到页面（缺陷 219bddf9）。

        创建日期：2026-06-12
        author: claude
        """

        messages = compress_messages_for_budget(
            messages, self.settings.agent_context_budget_chars
        )
        answer_parts: list[str] = []
        head_buffer: list[str] = []
        head_chars = 0
        head_flushed = False
        markup_detected = False
        for chunk in self.llm_client.chat_completion_stream_messages(
            messages,
            model=self.settings.agent_model,
            trace=self._trace(turn_state, "answer_stream"),
        ):
            if markup_detected:
                # 已确认泄漏：吞掉剩余流（不中断上游迭代器，保证指标正常收尾）。
                continue
            if head_flushed:
                answer_parts.append(chunk)
                yield DeltaEvent(content=chunk)
                continue
            head_buffer.append(chunk)
            head_chars += len(chunk)
            head_text = "".join(head_buffer)
            if self._looks_like_tool_markup(head_text):
                markup_detected = True
                continue
            if head_chars >= STREAM_GUARD_BUFFER_CHARS:
                # 头部检测通过：补发缓冲并转入透传模式。
                answer_parts.append(head_text)
                head_flushed = True
                yield DeltaEvent(content=head_text)
        if markup_detected:
            logger.warning(
                "Agent 流式收尾检测到工具语法泄漏，已拦截 question_id=%s",
                turn_state.question_id,
            )
            answer_parts = [MARKUP_FALLBACK_MESSAGE]
            yield DeltaEvent(content=MARKUP_FALLBACK_MESSAGE)
        elif not head_flushed and head_buffer:
            # 整段回答不足缓冲长度：流结束时一次性补发。
            head_text = "".join(head_buffer)
            answer_parts.append(head_text)
            yield DeltaEvent(content=head_text)
        # 终态再净化一次无效占位符：流式路径无法在 delta 阶段拦截，
        # 但落库与 done.answer（前端以其覆盖展示）保持干净。
        final_answer = self._strip_invalid_chart_placeholders(
            "".join(answer_parts), turn_state
        )
        if not final_answer.strip():
            final_answer = MARKUP_FALLBACK_MESSAGE
        yield DoneEvent(
            answer=final_answer,
            charts=list(turn_state.charts),
            tool_trace=[item.to_payload() for item in turn_state.tool_trace],
        )

    # ------------------------------------------------------------------
    # 消息组装
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        question: str,
        context: dict[str, Any],
        registry: ToolRegistry,
        turn_state: TurnState,
    ) -> list[dict[str, Any]]:
        """组装初始 messages：系统提示词 + 历史窗口 + 携带页面上下文的用户消息。

        创建日期：2026-06-12
        author: claude
        """

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(registry, self.settings),
            }
        ]
        messages.extend(self._history_window(context))
        messages.append({"role": "user", "content": self._user_message(question, context)})
        return messages

    def _history_window(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """清洗会话历史：只保留 user/assistant 角色文本，限条数与单条长度。

        历史 assistant 消息只带最终回答文本，不回带工具轨迹原文（设计 3.1）。

        创建日期：2026-06-12
        author: claude
        """

        raw_history = context.get("conversation_history") or []
        cleaned: list[dict[str, Any]] = []
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            cleaned.append(
                {"role": role, "content": truncate_text(content, HISTORY_MESSAGE_MAX_CHARS)}
            )
        return cleaned[-HISTORY_MAX_MESSAGES:]

    def _user_message(self, question: str, context: dict[str, Any]) -> str:
        """用户消息：原始问题 + 页面透传的结构化上下文说明。

        阈值推荐上下文不在此展开数值明细——由 recommend_threshold 零参数工具
        从 turn_state 读取（设计 v3 修订 3），这里只告知模型上下文已就绪。

        创建日期：2026-06-12
        author: claude
        """

        sections = [question.strip()]
        hints: list[str] = []
        if context.get("threshold_recommendation"):
            name = str((context.get("threshold_recommendation") or {}).get("name") or "")
            hints.append(
                f"页面已携带自选股（{name}）的阈值推荐上下文，"
                "如需推荐阈值请调用 recommend_threshold 工具。"
            )
        for key, label in (
            ("ts_code", "指定股票代码"),
            ("start_date", "起始日期"),
            ("end_date", "结束日期"),
        ):
            if context.get(key):
                hints.append(f"{label}：{context[key]}")
        if context.get("only_watchlist"):
            hints.append("用户要求只看自选股范围。")
        if hints:
            sections.append("（页面上下文：" + "；".join(hints) + "）")
        return "\n".join(sections)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _assistant_tool_call_message(self, result: LlmChatResult) -> dict[str, Any]:
        """把 LLM 的 tool_calls 响应原样回填为 assistant 消息（OpenAI 协议要求）。

        创建日期：2026-06-12
        author: claude
        """

        return {
            "role": "assistant",
            "content": result.content or "",
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments_json},
                }
                for call in result.tool_calls
            ],
        }

    def _trace(self, turn_state: TurnState, phase: str) -> LlmCallTrace:
        """构造指标追踪上下文：同一轮所有调用共享 question_id。

        创建日期：2026-06-12
        author: claude
        """

        return LlmCallTrace(
            question_id=turn_state.question_id,
            phase=phase,
            user_id=turn_state.user_id,
            session_id=turn_state.session_id,
            conversation_title=turn_state.conversation_title,
            user_name=turn_state.user_name,
            # 提示词版本随指标落库，支撑按版本对比迭代效果（旧评审 4.1）。
            prompt_version=PROMPT_VERSION,
        )

    def _record_tool_metric(self, turn_state: TurnState, call: ToolCall, result: Any) -> None:
        """每次工具执行写一条 llm_call_metric（phase=tool_*）。

        作用：①审计留痕（入参与结果全文，含后续 run_python 的代码与输出）；
        ②作为搜索/沙箱日配额的计数基准。工具调用不计入 LLM 外部调用日限额
        （LLM_EXTERNAL_CALL_PHASES 不含 tool_* phase）。落库失败不影响主流程。

        创建日期：2026-06-12
        author: claude
        """

        self.llm_client.record_metric(
            phase=f"tool_{call.name}",
            question_id=turn_state.question_id,
            user_id=turn_state.user_id,
            session_id=turn_state.session_id,
            conversation_title=turn_state.conversation_title,
            user_name=turn_state.user_name,
            # 工具可通过 extra 标注真实外部供应商（如博查），便于按 provider 看成本。
            provider=str(result.extra.get("metric_provider") or "AgentTool"),
            elapsed_ms=round(result.elapsed_ms, 1),
            output_chars=len(result.payload or ""),
            success=bool(result.ok),
            request_payload_json=call.arguments_json,
            response_content=result.payload,
            prompt_version=PROMPT_VERSION,
        )

    def _strip_invalid_chart_placeholders(self, answer: str, turn_state: TurnState) -> str:
        """剥离回答中未在本轮登记的图表占位符（输出净化，设计 3.10）。

        模型可能引用历史轮次的 {{chart:cN}}（图表登记按轮隔离，跨轮无效），
        前端会把未知占位符渲染为空——若不剥离，回答可能"看起来为空"
        （生产缺陷 977cf4a3）。本轮已登记的占位符原样保留。

        创建日期：2026-06-12
        author: claude
        """

        registered = {str(chart.get("chart_id")) for chart in turn_state.charts}

        def replace(match: re.Match[str]) -> str:
            return match.group(0) if match.group(1) in registered else ""

        return _CHART_PLACEHOLDER_PATTERN.sub(replace, answer)

    def _looks_like_tool_markup(self, text: str) -> bool:
        """判断文本是否疑似泄漏的工具调用协议语法。

        特征串覆盖 DeepSeek DSML 标记与 OpenAI 风格 tool_calls 文本；
        只做包含判断，宁可误杀走补救/兜底，也不把内部协议渲染给用户。

        创建日期：2026-06-12
        author: claude
        """

        return any(pattern in text for pattern in _TOOL_MARKUP_PATTERNS)

    def _threshold_context(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """提取前端透传的阈值推荐上下文（dict 之外的形态一律忽略）。

        创建日期：2026-06-12
        author: claude
        """

        payload = context.get("threshold_recommendation")
        return payload if isinstance(payload, dict) else None

    def _optional_int(self, value: Any) -> int | None:
        """宽松转 int：context 中的 user_id/session_id 可能是字符串。

        创建日期：2026-06-12
        author: claude
        """

        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
