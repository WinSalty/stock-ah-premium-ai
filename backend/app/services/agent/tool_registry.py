"""Agent 工具注册表：JSON Schema 定义、可用性判定、配额强制、分发执行与结果序列化。

口径（chat-agent-refactor-design-and-plan.md 3.2 节）：
- 工具按配置可用性动态裁剪（如博查 key 缺失移除 web_search），系统提示词能力声明
  由 prompts 模块按同一份可用工具清单拼装，保证两处一致；
- 执行异常一律转为错误文本回填给模型（不中断循环），由模型自行修正重试；
- 轮内配额在 execute 入口统一强制（TurnState.consume_quota）。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.services.agent.budget import (
    QUOTA_EXHAUSTED_MESSAGE,
    QUOTA_EXHAUSTED_SUMMARY,
    TurnState,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """工具执行结果。

    payload 是回填给模型的文本（已按预算截断）；summary 是面向用户界面的一句话；
    extra 携带协议性附加物（如 render_chart 的 chart_id/spec，由引擎转为 chart 事件）。

    创建日期：2026-06-12
    author: claude
    """

    ok: bool
    payload: str
    summary: str
    elapsed_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    """单个工具的注册信息。

    - handler(args, turn_state) 返回 ToolResult，内部不必处理配额与兜底异常；
    - summarize(args) 生成 tool_start 事件的一句话摘要，不得暴露 SQL/代码全文；
    - available(settings) 判定当前配置下工具是否可用（日配额降级也走这里）。

    创建日期：2026-06-12
    author: claude
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], TurnState], ToolResult]
    summarize: Callable[[dict[str, Any]], str]
    # 能力声明文本：拼进系统提示词"能力声明段"，与工具目录同步增删。
    capability_note: str = ""

    def to_openai_spec(self) -> dict[str, Any]:
        """转为 OpenAI function calling 的 tools 数组元素。

        创建日期：2026-06-12
        author: claude
        """

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    """LLM 返回的单次工具调用（已从响应 JSON 解析）。

    创建日期：2026-06-12
    author: claude
    """

    call_id: str
    name: str
    arguments_json: str

    def parse_arguments(self) -> dict[str, Any]:
        """解析入参 JSON；模型输出非法 JSON 时抛 ValueError 由执行层转错误文本。

        创建日期：2026-06-12
        author: claude
        """

        if not self.arguments_json or not self.arguments_json.strip():
            return {}
        parsed = json.loads(self.arguments_json)
        if not isinstance(parsed, dict):
            raise ValueError("工具入参必须是 JSON 对象")
        return parsed


class ToolRegistry:
    """工具注册表：持有本轮可用工具集合并负责分发执行。

    实例按"轮"构造（构造时即按配置裁剪可用工具），轮内不变。

    创建日期：2026-06-12
    author: claude
    """

    def __init__(self, tools: list[ToolSpec]) -> None:
        self._tools: dict[str, ToolSpec] = {tool.name: tool for tool in tools}

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        """输出 OpenAI tools 数组；为空时引擎应以纯对话模式调用（不带 tools）。

        创建日期：2026-06-12
        author: claude
        """

        return [tool.to_openai_spec() for tool in self._tools.values()]

    def capability_notes(self) -> list[str]:
        """收集可用工具的能力声明文本，供系统提示词动态拼装。

        创建日期：2026-06-12
        author: claude
        """

        return [tool.capability_note for tool in self._tools.values() if tool.capability_note]

    def summarize(self, call: ToolCall) -> str:
        """生成 tool_start 的用户可读摘要；解析失败时退回工具名。

        创建日期：2026-06-12
        author: claude
        """

        tool = self._tools.get(call.name)
        if tool is None:
            return call.name
        try:
            return tool.summarize(call.parse_arguments())
        except Exception:  # noqa: BLE001
            return call.name

    def execute(self, call: ToolCall, turn_state: TurnState) -> ToolResult:
        """统一执行入口：未知工具/配额耗尽/入参非法/执行异常全部转错误文本结果。

        错误结果 ok=False 且 payload 为面向模型的中文错误说明，
        模型可据此修正参数或调整策略；引擎不会因工具失败中断循环。

        创建日期：2026-06-12
        author: claude
        """

        started_at = perf_counter()
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                ok=False,
                payload=f"工具 {call.name} 不存在或当前不可用，请改用可用工具。",
                summary="工具不可用",
                elapsed_ms=(perf_counter() - started_at) * 1000,
            )
        if not turn_state.consume_quota(call.name):
            return ToolResult(
                ok=False,
                payload=QUOTA_EXHAUSTED_MESSAGE,
                # 摘要面向用户时间线：用"单轮上限"替代内部术语"配额"（试用反馈问题2）。
                summary=QUOTA_EXHAUSTED_SUMMARY,
                elapsed_ms=(perf_counter() - started_at) * 1000,
            )
        try:
            arguments = call.parse_arguments()
        except (json.JSONDecodeError, ValueError) as exc:
            return ToolResult(
                ok=False,
                payload=f"工具入参 JSON 解析失败：{exc}。请修正后重试。",
                summary="入参解析失败",
                elapsed_ms=(perf_counter() - started_at) * 1000,
            )
        try:
            result = tool.handler(arguments, turn_state)
        except Exception as exc:  # noqa: BLE001
            # 工具内部未自行兜底的异常：记日志（含堆栈）后转错误文本回填，循环继续。
            logger.error(
                "Agent 工具执行异常 tool=%s question_id=%s",
                call.name,
                turn_state.question_id,
                exc_info=True,
            )
            return ToolResult(
                ok=False,
                payload=f"工具执行失败：{type(exc).__name__}: {exc}",
                summary="执行失败",
                elapsed_ms=(perf_counter() - started_at) * 1000,
            )
        result.elapsed_ms = (perf_counter() - started_at) * 1000
        return result
