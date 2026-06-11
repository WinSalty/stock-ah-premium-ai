"""get_stock_data 工具：按需拉取个股结构化数据包（本地缓存优先，过期补数）。

口径：
- 股票识别复用 StockIdentityResolver：名称/代码均可；验真失败或歧义时把候选
  清单回填给模型确认（替代旧链路的专用消歧 LLM 调用）；
- 数据新鲜度与 Tushare 补数完全复用 MarketDataOrchestrator，工具层不重复实现；
- 数据包内容缓存进 turn_state.stock_packages 供 run_python 沙箱注入（阶段 3）。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.budget import TurnState, truncate_text
from app.services.agent.tool_registry import ToolResult, ToolSpec
from app.services.market_data_orchestrator import (
    MAX_MARKET_DATA_STOCKS,
    MarketDataDemand,
    MarketDataOrchestrator,
)
from app.services.stock_identity_resolver import StockIdentityResolver

logger = logging.getLogger(__name__)

# 工具入参的数据包白名单：对外名称与内部包名的映射。
# 设计文档对外名称用 capital_flow，内部实现为 capital_flow_light，这里做归一。
PACKAGE_ALIASES: dict[str, str] = {
    "quote_valuation": "quote_valuation",
    "financial_statement": "financial_statement",
    "dividend_forecast": "dividend_forecast",
    "business_profile": "business_profile",
    "shareholder_governance": "shareholder_governance",
    "capital_flow": "capital_flow_light",
    "capital_flow_light": "capital_flow_light",
}
# 回填给模型的数据包材料字符预算：个股上下文很宽，超出部分截断。
STOCK_CONTEXT_MAX_CHARS = 9000


def build_get_stock_data_tool(db: Session, turn_state: TurnState) -> ToolSpec:
    """构造 get_stock_data 工具：闭包持有 db，识别与补数都在 handler 内完成。

    创建日期：2026-06-12
    author: claude
    """

    resolver = StockIdentityResolver(db)
    orchestrator = MarketDataOrchestrator(db)

    def handler(args: dict[str, Any], state: TurnState) -> ToolResult:
        """识别股票→组装补数需求→编排器取数→回填结构化上下文。

        创建日期：2026-06-12
        author: claude
        """

        stocks = [str(item).strip() for item in (args.get("stocks") or []) if str(item).strip()]
        raw_packages = [str(item) for item in (args.get("packages") or [])]
        if not stocks:
            return ToolResult(ok=False, payload="缺少 stocks 参数。", summary="缺少股票")
        if len(stocks) > MAX_MARKET_DATA_STOCKS:
            return ToolResult(
                ok=False,
                payload=f"单次最多查询 {MAX_MARKET_DATA_STOCKS} 只股票，请拆分调用。",
                summary="股票数量超限",
            )
        packages: list[str] = []
        for name in raw_packages:
            normalized = PACKAGE_ALIASES.get(name)
            if normalized is None:
                return ToolResult(
                    ok=False,
                    payload=(
                        f"数据包 {name} 不存在。可用：" + "、".join(sorted(set(PACKAGE_ALIASES)))
                    ),
                    summary="数据包不存在",
                )
            if normalized not in packages:
                packages.append(normalized)
        if not packages:
            return ToolResult(ok=False, payload="缺少 packages 参数。", summary="缺少数据包")

        demands: list[MarketDataDemand] = []
        unresolved: list[str] = []
        for stock in stocks:
            resolved = resolver.resolve(stock)
            if resolved.identity is None or resolved.ambiguous_candidates:
                # 歧义/未命中：把候选回填给模型确认后重试，不在工具内替模型做决定。
                candidates = "；".join(
                    f"{item.name}（{item.ts_code}）" for item in resolved.ambiguous_candidates
                )
                unresolved.append(
                    f"{stock}：{resolved.reason or '未找到匹配股票'}"
                    + (f"，候选：{candidates}" if candidates else "")
                )
                continue
            identity = resolved.identity
            # market 字段在基础表中可空：缺省按 A 股处理（HK 识别依赖来源表标记）。
            market = "HK" if (identity.market or "").upper().startswith("HK") else "A"
            demands.append(
                MarketDataDemand(
                    ts_code=identity.ts_code,
                    packages=tuple(packages),
                    market=market,
                )
            )
        if unresolved:
            return ToolResult(
                ok=False,
                payload="以下股票无法确认：" + "\n".join(unresolved) + "\n请用准确代码重试。",
                summary="股票识别待确认",
            )

        result = orchestrator.ensure_for_question(
            question="agent get_stock_data: " + "、".join(stocks),
            context={},
            data_demands=tuple(demands),
            question_id=state.question_id,
            user_id=state.user_id,
            session_id=state.session_id,
        )
        if result.status == "FAILED" and not result.context:
            return ToolResult(
                ok=False,
                payload=f"个股数据获取失败：{result.reason or '数据源暂不可用'}",
                summary="取数失败",
            )
        # 完整上下文缓存供沙箱使用；回填模型的材料按预算截断。
        for demand in demands:
            state.stock_packages.append((demand.ts_code, ",".join(packages), result.context))
        context_json = json.dumps(result.context, ensure_ascii=False, default=str)
        cache_note = "命中本地缓存" if result.cache_hit else f"补数 {result.fetched_rows} 行"
        payload = (
            f"（{cache_note}；数据包：{'、'.join(packages)}）\n"
            + truncate_text(context_json, STOCK_CONTEXT_MAX_CHARS)
        )
        return ToolResult(
            ok=True,
            payload=payload,
            summary=f"获取 {len(demands)} 只股票数据（{cache_note}）",
        )

    return ToolSpec(
        name="get_stock_data",
        description=(
            "按需拉取个股结构化数据包：自动判断本地缓存新鲜度，过期时从数据源补数。"
            "适用于个股研究、财务质量分析、多股对比。A 股支持全部数据包；"
            "港股只支持 financial_statement。数据包说明："
            "quote_valuation=行情与估值趋势，financial_statement=三大报表与财务指标，"
            "dividend_forecast=分红与业绩预告，business_profile=主营构成与审计意见，"
            "shareholder_governance=股东户数/十大股东/质押，capital_flow=近期资金流。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "stocks": {
                    "type": "array",
                    "maxItems": MAX_MARKET_DATA_STOCKS,
                    "items": {"type": "string"},
                    "description": "股票名称或 ts_code（如 600036.SH / 03968.HK），A 股与港股均可",
                },
                "packages": {
                    "type": "array",
                    "items": {
                        "enum": [
                            "quote_valuation",
                            "financial_statement",
                            "dividend_forecast",
                            "business_profile",
                            "shareholder_governance",
                            "capital_flow",
                        ]
                    },
                    "description": "需要的数据包列表，按问题需要选择，不要全选",
                },
            },
            "required": ["stocks", "packages"],
        },
        handler=handler,
        summarize=lambda args: "获取个股数据：" + "、".join(
            str(item) for item in (args.get("stocks") or [])[:MAX_MARKET_DATA_STOCKS]
        ),
        capability_note=(
            "get_stock_data：按需获取个股行情估值、财务报表、分红预告、主营构成、"
            "股东治理与资金流数据包（本地缓存优先，过期自动补数）。"
        ),
    )
