"""图表 Chart DSL 与 render_chart 工具单元测试。

覆盖口径：
- ChartSpec/ChartSeries/ChartAxis/ChartYAxis 的按 chart_type 联动校验矩阵
  （line/bar/pie/scatter/kline/dual_axis 各自的合法与非法路径）；
- 字段长度边界（title/series.name/x_axis.values/note）的拒绝；
- chart_spec_json_schema() 的结构；
- build_render_chart_tool().handler 的登记、占位符、extra、turn_state.charts 累积；
- 经 ToolRegistry 的合法执行与轮内 render_chart 配额（上限 4，第 5 次耗尽）。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.services.agent.budget import PER_TURN_TOOL_LIMITS, TurnState
from app.services.agent.chart_schema import ChartSpec, chart_spec_json_schema
from app.services.agent.tool_registry import ToolCall, ToolRegistry
from app.services.agent.tools.chart import build_render_chart_tool


# ---------------------------------------------------------------------------
# 校验矩阵：6 种图型 × 合法/非法
# ---------------------------------------------------------------------------
def test_line_valid_and_length_mismatch_rejected() -> None:
    """line 合法（x 轴与 series 等长）通过；长度不一致抛错且含"不一致"。

    创建日期：2026-06-12
    author: claude
    """

    spec = ChartSpec.model_validate(
        {
            "chart_type": "line",
            "title": "AH 溢价走势",
            "x_axis": {"label": "日期", "values": ["d1", "d2", "d3"]},
            "series": [{"name": "溢价率", "values": [1.0, 2.0, 3.0]}],
        }
    )
    assert spec.chart_type == "line"
    assert len(spec.series[0].values) == 3

    with pytest.raises(ValidationError) as exc_info:
        ChartSpec.model_validate(
            {
                "chart_type": "line",
                "title": "长度不一致",
                "x_axis": {"label": "日期", "values": ["d1", "d2", "d3"]},
                "series": [{"name": "溢价率", "values": [1.0, 2.0]}],
            }
        )
    assert "不一致" in str(exc_info.value)


def test_bar_valid_and_series_count_bounds() -> None:
    """bar 合法通过；series 超过 8 个被拒；series 为空被拒。

    创建日期：2026-06-12
    author: claude
    """

    x_values = ["c1", "c2"]
    spec = ChartSpec.model_validate(
        {
            "chart_type": "bar",
            "title": "成交量对比",
            "x_axis": {"values": x_values},
            "series": [{"name": "A", "values": [1.0, 2.0]}],
        }
    )
    assert spec.chart_type == "bar"

    # 9 个 series 超过 max_length=8，被拒。
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                "chart_type": "bar",
                "title": "系列过多",
                "x_axis": {"values": x_values},
                "series": [{"name": f"s{i}", "values": [1.0, 2.0]} for i in range(9)],
            }
        )

    # 空 series 触发 min_length=1，被拒。
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                "chart_type": "bar",
                "title": "无系列",
                "x_axis": {"values": x_values},
                "series": [],
            }
        )


def test_pie_valid_and_invalid_paths() -> None:
    """pie 合法（扇区名与首系列等长）通过；缺 x_axis.values 被拒；长度不等被拒。

    创建日期：2026-06-12
    author: claude
    """

    spec = ChartSpec.model_validate(
        {
            "chart_type": "pie",
            "title": "行业占比",
            "x_axis": {"values": ["银行", "券商", "保险"]},
            "series": [{"name": "占比", "values": [40.0, 35.0, 25.0]}],
        }
    )
    assert spec.chart_type == "pie"

    # 缺 x_axis.values：无法作扇区名，被拒。
    with pytest.raises(ValidationError) as exc_missing:
        ChartSpec.model_validate(
            {
                "chart_type": "pie",
                "title": "缺扇区名",
                "series": [{"name": "占比", "values": [40.0, 60.0]}],
            }
        )
    assert "x_axis.values" in str(exc_missing.value)

    # 扇区名数量与数值数量不等，被拒。
    with pytest.raises(ValidationError) as exc_info:
        ChartSpec.model_validate(
            {
                "chart_type": "pie",
                "title": "长度不等",
                "x_axis": {"values": ["银行", "券商"]},
                "series": [{"name": "占比", "values": [40.0, 35.0, 25.0]}],
            }
        )
    assert "长度必须一致" in str(exc_info.value)


def test_scatter_valid() -> None:
    """scatter 合法通过。

    创建日期：2026-06-12
    author: claude
    """

    spec = ChartSpec.model_validate(
        {
            "chart_type": "scatter",
            "title": "PE-PB 散点",
            "x_axis": {"label": "PE", "values": ["10", "20", "30"]},
            "series": [{"name": "样本", "values": [1.1, 2.2, 3.3]}],
        }
    )
    assert spec.chart_type == "scatter"


def test_kline_valid_and_invalid_paths() -> None:
    """kline 合法（四元组列表，与 x 轴等长）通过；标量列表被拒；四元组长度≠4 被拒。

    创建日期：2026-06-12
    author: claude
    """

    spec = ChartSpec.model_validate(
        {
            "chart_type": "kline",
            "title": "K 线",
            "x_axis": {"values": ["d1", "d2"]},
            "series": [
                {
                    "name": "OHLC",
                    "values": [[10.0, 11.0, 9.5, 11.5], [11.0, 10.5, 10.0, 11.2]],
                }
            ],
        }
    )
    assert spec.chart_type == "kline"

    # values 是标量列表（非四元组），被拒。
    with pytest.raises(ValidationError) as exc_scalar:
        ChartSpec.model_validate(
            {
                "chart_type": "kline",
                "title": "标量错误",
                "x_axis": {"values": ["d1", "d2"]},
                "series": [{"name": "OHLC", "values": [10.0, 11.0]}],
            }
        )
    assert "四元组" in str(exc_scalar.value)

    # 四元组长度不等于 4，被拒。
    with pytest.raises(ValidationError) as exc_quad:
        ChartSpec.model_validate(
            {
                "chart_type": "kline",
                "title": "三元组错误",
                "x_axis": {"values": ["d1"]},
                "series": [{"name": "OHLC", "values": [[10.0, 11.0, 9.5]]}],
            }
        )
    assert "四元组" in str(exc_quad.value)


def test_dual_axis_valid_and_left_only_rejected() -> None:
    """dual_axis 合法（左右轴各一系列）通过；只有 left 被拒且含"left 与 right"。

    创建日期：2026-06-12
    author: claude
    """

    spec = ChartSpec.model_validate(
        {
            "chart_type": "dual_axis",
            "title": "价格与溢价",
            "x_axis": {"values": ["d1", "d2"]},
            "series": [
                {"name": "价格", "values": [10.0, 12.0], "y_axis": "left"},
                {"name": "溢价率", "values": [1.0, 2.0], "y_axis": "right"},
            ],
        }
    )
    assert spec.chart_type == "dual_axis"

    with pytest.raises(ValidationError) as exc_info:
        ChartSpec.model_validate(
            {
                "chart_type": "dual_axis",
                "title": "仅左轴",
                "x_axis": {"values": ["d1", "d2"]},
                "series": [
                    {"name": "价格", "values": [10.0, 12.0], "y_axis": "left"},
                ],
            }
        )
    assert "left 与 right" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 字段长度边界
# ---------------------------------------------------------------------------
def test_field_length_bounds_rejected() -> None:
    """title 超 64、series.name 超 32、x_axis.values 超 200、note 超 128 均被拒。

    创建日期：2026-06-12
    author: claude
    """

    base = {
        "chart_type": "line",
        "title": "正常标题",
        "x_axis": {"values": ["d1", "d2"]},
        "series": [{"name": "s", "values": [1.0, 2.0]}],
    }

    # title 超 64 字。
    with pytest.raises(ValidationError):
        ChartSpec.model_validate({**base, "title": "标" * 65})

    # series.name 超 32 字。
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {**base, "series": [{"name": "名" * 33, "values": [1.0, 2.0]}]}
        )

    # x_axis.values 超 200 个。
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(
            {
                **base,
                "x_axis": {"values": [str(i) for i in range(201)]},
                "series": [{"name": "s", "values": [float(i) for i in range(201)]}],
            }
        )

    # note 超 128 字。
    with pytest.raises(ValidationError):
        ChartSpec.model_validate({**base, "note": "备" * 129})


def test_chart_spec_json_schema_structure() -> None:
    """chart_spec_json_schema() 返回 dict 且 properties 含 chart_type/title/series。

    创建日期：2026-06-12
    author: claude
    """

    schema = chart_spec_json_schema()
    assert isinstance(schema, dict)
    properties = schema.get("properties", {})
    assert "chart_type" in properties
    assert "title" in properties
    assert "series" in properties


# ---------------------------------------------------------------------------
# render_chart 工具 handler
# ---------------------------------------------------------------------------
def _valid_line_args() -> dict:
    """构造一份合法的 line 图入参，供 handler 用例复用。

    创建日期：2026-06-12
    author: claude
    """

    return {
        "chart_type": "line",
        "title": "溢价率走势",
        "x_axis": {"label": "日期", "values": ["d1", "d2"]},
        "series": [{"name": "溢价率", "values": [1.0, 2.0]}],
    }


def test_render_chart_handler_registers_and_returns_placeholder() -> None:
    """合法 spec → ok=True、payload 含 chart_id/placeholder、extra 含 spec、charts 追加。

    创建日期：2026-06-12
    author: claude
    """

    turn_state = TurnState()
    tool = build_render_chart_tool(turn_state)
    result = tool.handler(_valid_line_args(), turn_state)

    assert result.ok is True
    payload = json.loads(result.payload)
    assert payload["chart_id"] == "c1"
    assert payload["placeholder"] == "{{chart:c1}}"
    assert "溢价率走势" in result.summary
    assert result.extra["chart_id"] == "c1"
    assert result.extra["spec"]["chart_type"] == "line"
    assert len(turn_state.charts) == 1
    assert turn_state.charts[0]["chart_id"] == "c1"


def test_render_chart_handler_increments_chart_id() -> None:
    """连续登记两张 → chart_id 依次 c1、c2，charts 长度为 2。

    创建日期：2026-06-12
    author: claude
    """

    turn_state = TurnState()
    tool = build_render_chart_tool(turn_state)

    first = tool.handler(_valid_line_args(), turn_state)
    second = tool.handler(_valid_line_args(), turn_state)

    assert json.loads(first.payload)["chart_id"] == "c1"
    assert json.loads(second.payload)["chart_id"] == "c2"
    assert len(turn_state.charts) == 2


def test_render_chart_handler_invalid_spec_not_registered() -> None:
    """非法 spec（line 长度不一致）→ ok=False、payload 含"校验失败"、charts 不增长。

    创建日期：2026-06-12
    author: claude
    """

    turn_state = TurnState()
    tool = build_render_chart_tool(turn_state)
    bad_args = {
        "chart_type": "line",
        "title": "长度不一致",
        "x_axis": {"values": ["d1", "d2", "d3"]},
        "series": [{"name": "s", "values": [1.0, 2.0]}],
    }
    result = tool.handler(bad_args, turn_state)

    assert result.ok is False
    assert "校验失败" in result.payload
    assert len(turn_state.charts) == 0


def test_render_chart_to_openai_spec_parameters() -> None:
    """ToolSpec.to_openai_spec() 的 function.parameters 来自 ChartSpec JSON schema。

    创建日期：2026-06-12
    author: claude
    """

    turn_state = TurnState()
    tool = build_render_chart_tool(turn_state)
    openai_spec = tool.to_openai_spec()

    assert openai_spec["type"] == "function"
    parameters = openai_spec["function"]["parameters"]
    assert "chart_type" in parameters["properties"]


# ---------------------------------------------------------------------------
# 经 ToolRegistry 执行与轮内配额
# ---------------------------------------------------------------------------
def test_render_chart_registry_quota_exhausted_on_fifth_call() -> None:
    """经 ToolRegistry 合法调用 ok=True；render_chart 上限 4，第 5 次返回配额耗尽。

    创建日期：2026-06-12
    author: claude
    """

    # 前置断言：配置上限确为 4，避免上限调整后用例静默失效。
    assert PER_TURN_TOOL_LIMITS["render_chart"] == 4

    turn_state = TurnState()
    registry = ToolRegistry([build_render_chart_tool(turn_state)])
    call = ToolCall(
        call_id="c1",
        name="render_chart",
        arguments_json=json.dumps(_valid_line_args(), ensure_ascii=False),
    )

    # 前 4 次在配额内，均成功。
    for index in range(4):
        result = registry.execute(call, turn_state)
        assert result.ok is True, f"第 {index + 1} 次应成功"

    # 第 5 次配额耗尽：ok=False 且 payload 含"配额"。
    fifth = registry.execute(call, turn_state)
    assert fifth.ok is False
    assert "配额" in fifth.payload
    # 配额耗尽不应再登记新图表，charts 应停在 4。
    assert len(turn_state.charts) == 4
