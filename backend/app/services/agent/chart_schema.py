"""Chart DSL 的 pydantic 模型：受控图表规格，同时导出 JSON Schema 作工具参数。

口径（chat-agent-refactor-design-and-plan.md 3.5 节 + 第八节 v3 修订 4）：
- 模型校验失败返回具体错误文本让模型修正（计入轮内 render_chart 配额）；
- kline 的 values 是四元组列表 [open, close, low, high]，其余图型是标量列表，
  按 chart_type 联动校验（v3 修订 4：消除 list[float] 与四元组的类型矛盾）；
- 前端 ChatChart 按本规格映射为 ECharts option，受控字段杜绝任意 HTML/JS 注入。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ChartType = Literal["line", "bar", "pie", "scatter", "kline", "dual_axis"]


class ChartAxis(BaseModel):
    """坐标轴：类目标签与取值（pie 可省略 x 轴）。

    创建日期：2026-06-12
    author: claude
    """

    label: str = Field(default="", max_length=32)
    values: list[str] = Field(default_factory=list, max_length=200)


class ChartYAxis(BaseModel):
    """纵轴：双轴图区分左右轴标签与单位。

    创建日期：2026-06-12
    author: claude
    """

    left_label: str = Field(default="", max_length=32)
    right_label: str = Field(default="", max_length=32)
    unit: str = Field(default="", max_length=16)


class ChartSeries(BaseModel):
    """数据系列。

    values 联动 chart_type：kline 为四元组列表 [[open,close,low,high], ...]，
    其余图型为标量列表 [number|null, ...]；校验在 ChartSpec 层完成。

    创建日期：2026-06-12
    author: claude
    """

    name: str = Field(max_length=32)
    values: list[float | None] | list[list[float]] = Field(max_length=200)
    y_axis: Literal["left", "right"] = "left"


class ChartSpec(BaseModel):
    """受控图表规格（render_chart 工具参数 / 落库 / 前端渲染共用）。

    创建日期：2026-06-12
    author: claude
    """

    chart_type: ChartType
    title: str = Field(max_length=64)
    x_axis: ChartAxis | None = None
    series: list[ChartSeries] = Field(min_length=1, max_length=8)
    y_axis: ChartYAxis | None = None
    note: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_by_chart_type(self) -> ChartSpec:
        """按图型联动校验：长度一致、双轴齐全、kline 四元组、pie 取首系列。

        创建日期：2026-06-12
        author: claude
        """

        is_kline = self.chart_type == "kline"
        for series in self.series:
            scalar = all(not isinstance(v, list) for v in series.values)
            quad = all(isinstance(v, list) for v in series.values)
            if is_kline:
                # kline：每个元素必须是 [open, close, low, high] 四元组。
                if not quad:
                    raise ValueError("kline 图的 series.values 必须是四元组列表")
                for item in series.values:
                    if not isinstance(item, list) or len(item) != 4:
                        raise ValueError("kline 四元组必须为 [open, close, low, high]")
            else:
                if not scalar:
                    raise ValueError(f"{self.chart_type} 图的 series.values 必须是标量列表")

        if self.chart_type == "pie":
            # pie 取 series[0]，扇区名用 x_axis.values，必须与数值等长。
            if self.x_axis is None or not self.x_axis.values:
                raise ValueError("pie 图必须提供 x_axis.values 作为扇区名")
            if len(self.x_axis.values) != len(self.series[0].values):
                raise ValueError("pie 图 x_axis.values 与 series[0].values 长度必须一致")
            return self

        if self.chart_type == "dual_axis":
            # 双轴图必须同时存在左右两组 series，否则退化为普通折线。
            axes = {series.y_axis for series in self.series}
            if axes != {"left", "right"}:
                raise ValueError("dual_axis 图必须同时包含 left 与 right 两组 series")

        # 非 pie 图：每个 series 的长度必须与 x_axis.values 一致（缺 x 轴则跳过）。
        if self.x_axis is not None and self.x_axis.values:
            expected = len(self.x_axis.values)
            for series in self.series:
                if len(series.values) != expected:
                    raise ValueError(
                        f"系列 {series.name} 的数据点数（{len(series.values)}）"
                        f"与 x 轴类目数（{expected}）不一致"
                    )
        return self


def chart_spec_json_schema() -> dict[str, Any]:
    """导出 ChartSpec 的 JSON Schema 作为 render_chart 工具参数定义。

    创建日期：2026-06-12
    author: claude
    """

    return ChartSpec.model_json_schema()
