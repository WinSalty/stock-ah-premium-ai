"""recommend_threshold 工具：自选股溢价阈值的本地确定性公式。

公式自 llm_service._calculate_threshold_recommendation 逐行平移（数值口径不变，
有数值回归测试保护）。设计 v3 修订 3：工具零参数，输入取自前端透传并由引擎
写入 turn_state 的阈值上下文，避免模型抄写大对象时产生数字幻觉。

创建日期：2026-06-12
author: claude（公式平移自 sunshengxian 的旧实现）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.services.agent.budget import TurnState
from app.services.agent.tool_registry import ToolResult, ToolSpec


@dataclass(frozen=True)
class ThresholdRecommendationResult:
    """自选股阈值推荐的本地确定性计算结果。

    创建日期：2026-05-07
    author: sunshengxian
    """

    threshold_pct: Decimal
    direction: str
    direction_label: str
    reason_code: str
    formula_note: str


def decimal_or_none(value: Any) -> Decimal | None:
    """把前端字符串或数字安全转为 Decimal，无法解析时视作缺失字段。

    创建日期：2026-05-07
    author: sunshengxian
    """

    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_threshold_number(value: Decimal) -> str:
    """格式化百分比数值，保留两位精度但去掉无意义尾零。

    创建日期：2026-05-07
    author: sunshengxian
    """

    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(quantized.normalize(), "f")


def missing_history_buffer(payload: dict[str, Any]) -> Decimal:
    """根据通道和当前值给历史缺失场景设置保守缓冲，避免阈值贴得过近。

    创建日期：2026-05-07
    author: sunshengxian
    """

    current = decimal_or_none(payload.get("metric_premium_pct")) or Decimal("0")
    channels = str(payload.get("connect_channels") or "").strip()
    buffer_pct = Decimal("3")
    if abs(current) >= Decimal("30"):
        buffer_pct = Decimal("5")
    elif not channels:
        buffer_pct = Decimal("4")
    if current < 0:
        return -buffer_pct
    return buffer_pct


def calculate_threshold_recommendation(
    payload: dict[str, Any],
) -> ThresholdRecommendationResult:
    """按本地确定性公式计算阈值，保证固定页面输入下的建议值稳定。

    创建日期：2026-05-07
    author: sunshengxian
    """

    direction = str(payload.get("direction") or "HA").upper()
    if direction not in {"AH", "HA"}:
        direction = "HA"
    direction_label = "A/H" if direction == "AH" else "H/A"
    current = decimal_or_none(payload.get("metric_premium_pct"))
    median = decimal_or_none(payload.get("premium_median_60"))
    p80 = decimal_or_none(payload.get("premium_p80_60"))
    percentile = decimal_or_none(payload.get("premium_percentile_60"))
    if current is not None and median is not None and p80 is not None:
        base = median + Decimal("0.65") * (p80 - median)
        if percentile is not None and percentile > Decimal("80"):
            threshold = max(base, current)
            reason_code = "current_above_p80"
            note = "当前分位高于 80%，取基础锚点与当前溢价的较高值作为确认触发线"
        else:
            threshold = base
            reason_code = "base_formula"
            note = (
                "60 日分位齐全，取 median + 0.65 * (p80 - median) "
                "作为靠近 80% 分位但不追高的锚点"
            )
    elif current is not None and median is not None:
        threshold = median + Decimal("0.5") * abs(current - median)
        reason_code = "median_current_only"
        note = "缺少 80% 分位时，取 median + 0.5 * abs(current - median) 作为折中锚点"
    elif current is not None:
        buffer_pct = missing_history_buffer(payload)
        threshold = current + buffer_pct
        reason_code = "missing_history"
        note = (
            f"历史分位缺失，按当前溢价加 "
            f"{format_threshold_number(buffer_pct)} 个百分点缓冲"
        )
    else:
        threshold = Decimal("0")
        reason_code = "missing_current"
        note = "当前溢价缺失，先给 0% 观察阈值并要求补齐页面行情后复核"
    return ThresholdRecommendationResult(
        threshold_pct=threshold.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        direction=direction,
        direction_label=direction_label,
        reason_code=reason_code,
        formula_note=note,
    )


def build_recommend_threshold_tool(turn_state: TurnState) -> ToolSpec:
    """构造 recommend_threshold 工具：零参数，输入读 turn_state 阈值上下文。

    创建日期：2026-06-12
    author: claude
    """

    stock_name = str((turn_state.threshold_context or {}).get("name") or "当前自选股")

    def handler(args: dict[str, Any], state: TurnState) -> ToolResult:
        """执行确定性公式并返回结构化结果（含输入回显便于模型解释）。

        创建日期：2026-06-12
        author: claude
        """

        payload = state.threshold_context
        if not payload:
            return ToolResult(
                ok=False,
                payload="当前轮次没有页面透传的阈值推荐上下文，无法计算阈值。",
                summary="缺少阈值上下文",
            )
        result = calculate_threshold_recommendation(payload)
        body = {
            "stock_name": payload.get("name"),
            "direction": result.direction,
            "direction_label": result.direction_label,
            "recommended_threshold_pct": format_threshold_number(result.threshold_pct),
            "reason_code": result.reason_code,
            "formula_note": result.formula_note,
            "inputs": {
                "metric_premium_pct": payload.get("metric_premium_pct"),
                "premium_median_60": payload.get("premium_median_60"),
                "premium_p80_60": payload.get("premium_p80_60"),
                "premium_percentile_60": payload.get("premium_percentile_60"),
                "connect_channels": payload.get("connect_channels"),
                "target_premium_pct": payload.get("target_premium_pct"),
            },
        }
        return ToolResult(
            ok=True,
            payload=json.dumps(body, ensure_ascii=False),
            summary=(
                f"建议 {result.direction_label} 阈值 "
                f"{format_threshold_number(result.threshold_pct)}%"
            ),
        )

    return ToolSpec(
        name="recommend_threshold",
        description=(
            f"基于页面已携带的自选股（{stock_name}）价差与 60 日分位上下文，"
            "用确定性公式计算建议的溢价目标阈值。无需任何参数。"
            "用户在自选股页面询问阈值设置时必须调用本工具，"
            "并基于返回的公式结果解释推荐理由与执行条件，不得自行估算阈值。"
        ),
        parameters={"type": "object", "properties": {}},
        handler=handler,
        summarize=lambda args: f"计算{stock_name}的建议阈值",
        capability_note="recommend_threshold：基于页面自选股上下文用确定性公式推荐溢价阈值。",
    )
