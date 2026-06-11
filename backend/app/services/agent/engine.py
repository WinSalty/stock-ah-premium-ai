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
FORCE_FINISH_INSTRUCTION = "工具调用次数已达上限，请基于已有材料直接给出最终回答。"


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
                # 无工具调用：进入最终回答；丢弃本次非流式内容，重新流式生成。
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

    def _stream_final_answer(
        self,
        messages: list[dict[str, Any]],
        turn_state: TurnState,
    ) -> Iterator[AgentEvent]:
        """流式生成最终回答并产出终态 DoneEvent（phase 记 answer_stream）。

        创建日期：2026-06-12
        author: claude
        """

        messages = compress_messages_for_budget(
            messages, self.settings.agent_context_budget_chars
        )
        answer_parts: list[str] = []
        for chunk in self.llm_client.chat_completion_stream_messages(
            messages,
            model=self.settings.agent_model,
            trace=self._trace(turn_state, "answer_stream"),
        ):
            answer_parts.append(chunk)
            yield DeltaEvent(content=chunk)
        yield DoneEvent(
            answer="".join(answer_parts),
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
            provider="AgentTool",
            elapsed_ms=round(result.elapsed_ms, 1),
            output_chars=len(result.payload or ""),
            success=bool(result.ok),
            request_payload_json=call.arguments_json,
            response_content=result.payload,
            prompt_version=PROMPT_VERSION,
        )

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
