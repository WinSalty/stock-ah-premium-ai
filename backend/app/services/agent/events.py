"""Agent 引擎流式事件定义：与前端 NDJSON 协议逐字段对齐。

协议契约（chat-agent-refactor-design-and-plan.md 3.6 节）：
- tool_start / tool_result：工具执行的真实进度，summary 为面向用户的一句话，
  不暴露原始 SQL 与代码全文（审计全文走 llm_call_metric）。
- chart：图表登记即下发，前端先于正文渲染占位。
- delta：最终回答的增量文本。
- done / error：终态事件，message_id 由路由层落库后回填（引擎本身不持久化）。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    """事件基类：type 字段标识事件类型，to_payload 输出 NDJSON 单行字典。

    创建日期：2026-06-12
    author: claude
    """

    type: str = field(init=False, default="")

    def to_payload(self) -> dict[str, Any]:
        """转为可直接 json.dumps 的扁平字典；None 值字段保留以稳定协议形状。

        创建日期：2026-06-12
        author: claude
        """

        payload = dict(self.__dict__)
        payload["type"] = self.type
        return payload


@dataclass
class ToolStartEvent(AgentEvent):
    """工具开始执行事件：summary 由工具入参生成的一句话（如"搜索：美联储 6 月议息"）。

    创建日期：2026-06-12
    author: claude
    """

    tool: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        self.type = "tool_start"


@dataclass
class ToolResultEvent(AgentEvent):
    """工具执行结束事件：ok 标识成败，summary 如"返回 30 行"，elapsed_ms 为耗时。

    创建日期：2026-06-12
    author: claude
    """

    tool: str = ""
    ok: bool = True
    summary: str = ""
    elapsed_ms: float = 0.0

    def __post_init__(self) -> None:
        self.type = "tool_result"


@dataclass
class ChartEvent(AgentEvent):
    """图表登记事件：spec 为校验通过的 ChartSpec 字典，前端即时渲染占位。

    创建日期：2026-06-12
    author: claude
    """

    chart_id: str = ""
    spec: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.type = "chart"


@dataclass
class DeltaEvent(AgentEvent):
    """最终回答增量文本事件。

    创建日期：2026-06-12
    author: claude
    """

    content: str = ""

    def __post_init__(self) -> None:
        self.type = "delta"


@dataclass
class DoneEvent(AgentEvent):
    """正常终态事件：answer 为完整回答，charts 为本轮全部图表 spec，
    tool_trace 为轨迹摘要数组（落库与历史回放共用同一结构）。

    elapsed_ms 为整轮墙钟耗时（提问进入引擎到回答完成，含模型思考与工具执行；
    试用反馈：仅加总工具耗时的"合计"严重低估真实等待）。

    创建日期：2026-06-12
    author: claude
    """

    message_id: int | None = None
    answer: str = ""
    charts: list[dict[str, Any]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float | None = None

    def __post_init__(self) -> None:
        self.type = "done"


@dataclass
class ErrorEvent(AgentEvent):
    """失败终态事件：answer 为已落库的失败文案（限流/不可恢复异常统一走此口径）。

    kind 供路由层区分 HTTP 契约（daily_limit→429，general→502），前端不消费该字段。

    创建日期：2026-06-12
    author: claude
    """

    message_id: int | None = None
    answer: str = ""
    kind: str = "general"

    def __post_init__(self) -> None:
        self.type = "error"
