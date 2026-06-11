"""render_chart 工具：校验 Chart DSL 并登记图表，返回占位符供回答正文引用。

口径（chat-agent-refactor-design-and-plan.md 3.5 节）：
- 校验通过 → 生成轮内自增 chart_id（c1/c2/...）→ spec 暂存 turn_state →
  引擎据此即时下发 chart 事件 → 给模型返回 {"chart_id","placeholder":"{{chart:c1}}"}
  → 模型把占位符独立成行嵌入回答正文；
- 校验失败返回具体错误文本，模型修正后重试（计入轮内 4 张上限）；
- 未被正文引用的图表由前端追加在回答末尾兜底渲染。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.services.agent.budget import TurnState
from app.services.agent.chart_schema import ChartSpec, chart_spec_json_schema
from app.services.agent.tool_registry import ToolResult, ToolSpec


def _format_validation_error(exc: ValidationError) -> str:
    """把 pydantic 校验错误压成模型可读的一行错误说明。

    创建日期：2026-06-12
    author: claude
    """

    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg')}")
    return "图表规格校验失败：" + "；".join(parts)


def build_render_chart_tool(turn_state: TurnState) -> ToolSpec:
    """构造 render_chart 工具。

    创建日期：2026-06-12
    author: claude
    """

    def handler(args: dict, state: TurnState) -> ToolResult:
        """校验图表规格并登记，返回占位符。

        创建日期：2026-06-12
        author: claude
        """

        try:
            spec = ChartSpec.model_validate(args)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                payload=_format_validation_error(exc),
                summary="图表规格不合法",
            )
        chart_id = state.next_chart_id()
        spec_dict = spec.model_dump()
        spec_dict["chart_id"] = chart_id
        # 登记进 turn_state：done 事件携带全部 spec，落库与前端回放共用。
        state.charts.append(spec_dict)
        placeholder = f"{{{{chart:{chart_id}}}}}"
        return ToolResult(
            ok=True,
            payload=json.dumps(
                {
                    "chart_id": chart_id,
                    "placeholder": placeholder,
                    "hint": "把该占位符独立成行嵌入回答正文需要展示图表的位置。",
                },
                ensure_ascii=False,
            ),
            summary=f"登记图表：{spec.title}",
            # 引擎据 extra 下发 chart 事件（前端先于正文渲染占位）。
            extra={"chart_id": chart_id, "spec": spec_dict},
        )

    # 工具参数直接用 ChartSpec 的 JSON Schema（pydantic 同步生成）。
    parameters = chart_spec_json_schema()
    return ToolSpec(
        name="render_chart",
        description=(
            "登记一张图表用于回答展示。支持 line/bar/pie/scatter/kline/dual_axis。"
            "校验通过后返回占位符 {{chart:cN}}，你必须把该占位符独立成行嵌入回答正文"
            "需要展示图表的位置。仅在图表确实比文字表格更有助于理解时出图，"
            "单个数值不要出图。"
        ),
        parameters=parameters,
        handler=handler,
        summarize=lambda args: f"绘制图表：{str(args.get('title') or '')[:40]}",
        capability_note=(
            "render_chart：把数据登记为受控图表（折线/柱/饼/散点/K线/双轴），"
            "在回答中以占位符嵌入展示。"
        ),
    )
