from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from app.db.models.market import (
    ADailyBasic,
    ADividend,
    AFinancialIndicator,
    AForecast,
    AHolderNumber,
    AMainBusinessComposition,
    AMoneyflow,
    APledgeStat,
    ATop10Holder,
    HKFinancialIndicator,
    LlmMarketDataFetchRun,
)
from app.services.stock_identity_resolver import StockIdentity, StockIdentityResolver
from app.services.tushare_stock_research_fetcher import (
    BUSINESS_PROFILE_PACKAGE,
    CAPITAL_FLOW_PACKAGE,
    DIVIDEND_FORECAST_PACKAGE,
    FINANCIAL_STATEMENT_PACKAGE,
    QUOTE_VALUATION_PACKAGE,
    SHAREHOLDER_GOVERNANCE_PACKAGE,
    TushareStockResearchFetcher,
)

REPORT_KEYWORDS = (
    "分析报告",
    "投资报告",
    "深度报告",
    "投资分析",
    "个股分析",
    "怎么看",
    "估值",
    "买点",
)
FINANCIAL_KEYWORDS = ("财报", "利润", "营收", "现金流", "资产负债", "ROE", "毛利率", "净利率")
DIVIDEND_KEYWORDS = ("分红", "股息", "派息", "业绩预告", "预告")
BUSINESS_PROFILE_KEYWORDS = ("主营", "业务构成", "收入结构", "产品", "地区", "审计", "业绩快报")
GOVERNANCE_KEYWORDS = ("股东", "持股", "质押", "股东户数", "治理", "大股东", "筹码集中")
CAPITAL_FLOW_KEYWORDS = ("资金流", "资金流向", "大单", "特大单", "净流入", "短期资金")
ACCOUNTING_REVIEW_KEYWORDS = (
    "会计政策",
    "会计估计",
    "差错更正",
    "追溯调整",
    "报表更改",
    "财务报表更改",
    "重述",
    "调整财务报表",
    "审计意见",
    "业绩快报",
    "年报",
    "一季报",
    "季报",
)
MAX_MARKET_DATA_STOCKS = 5
AMOUNT_YUAN_FIELDS = frozenset(
    {
        "revenue",
        "total_revenue",
        "operate_income",
        "n_income_attr_p",
        "profit_dedt",
        "n_income",
        "netcash_operate",
        "net_cash_flows_oper_act",
        "n_cashflow_act",
        "n_cashflow_inv_act",
        "n_cash_flows_fnc_act",
        "money_cap",
        "contract_liab",
        "inventories",
        "total_assets",
        "total_liab",
        "total_hldr_eqy_exc_min_int",
        "invest_income",
        "fv_value_chg_gain",
        "assets_impair_loss",
        "credit_impa_loss",
        "bz_sales",
        "bz_profit",
        "bz_cost",
    }
)
AMOUNT_YI_LABELS = {
    "revenue": "营业收入_亿元",
    "total_revenue": "营业总收入_亿元",
    "operate_income": "营业收入_亿元",
    "n_income_attr_p": "归母净利润_亿元",
    "profit_dedt": "扣非净利润_亿元",
    "n_income": "净利润_亿元",
    "netcash_operate": "经营现金流净额_亿元",
    "net_cash_flows_oper_act": "经营现金流净额_亿元",
    "n_cashflow_act": "经营现金流净额_亿元",
    "n_cashflow_inv_act": "投资现金流净额_亿元",
    "n_cash_flows_fnc_act": "筹资现金流净额_亿元",
    "money_cap": "货币资金_亿元",
    "contract_liab": "合同负债_亿元",
    "inventories": "存货_亿元",
    "total_assets": "总资产_亿元",
    "total_liab": "总负债_亿元",
    "total_hldr_eqy_exc_min_int": "归母权益_亿元",
    "invest_income": "投资收益_亿元",
    "fv_value_chg_gain": "公允价值变动收益_亿元",
    "assets_impair_loss": "资产减值损失_亿元",
    "credit_impa_loss": "信用减值损失_亿元",
    "bz_sales": "主营收入_亿元",
    "bz_profit": "主营利润_亿元",
    "bz_cost": "主营成本_亿元",
}


@dataclass(frozen=True)
class MarketDataDemand:
    """LLM 按需补数请求，限定为单只股票和固定数据包。

    创建日期：2026-05-07
    author: sunshengxian
    """

    ts_code: str
    packages: tuple[str, ...]
    market: str = "A"
    intent: str = "stock_research"


@dataclass(frozen=True)
class MarketDataEnsureResult:
    """按需补数和上下文构建结果。

    创建日期：2026-05-07
    author: sunshengxian
    """

    stock: StockIdentity | None
    stocks: tuple[StockIdentity, ...]
    packages: tuple[str, ...]
    context: dict[str, Any]
    fetched_rows: int
    cache_hit: bool
    status: str
    reason: str = ""


class MarketDataOrchestrator:
    """LLM 问答市场数据按需编排服务。

    创建日期：2026-05-07
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        resolver: StockIdentityResolver | None = None,
        fetcher: TushareStockResearchFetcher | None = None,
    ) -> None:
        self.db = db
        self.resolver = resolver or StockIdentityResolver(db)
        self.fetcher = fetcher or TushareStockResearchFetcher(db)

    def ensure_for_question(
        self,
        question: str,
        context: dict[str, Any],
        data_demands: tuple[MarketDataDemand, ...] = (),
        question_id: str | None = None,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> MarketDataEnsureResult:
        """为用户问题准备可供 LLM 分析的本地市场上下文。

        创建日期：2026-05-07
        author: sunshengxian
        """

        demands = self._stock_demands(question, context, data_demands)
        if not demands:
            return MarketDataEnsureResult(
                None,
                (),
                (),
                {},
                0,
                True,
                "SKIPPED",
                "未识别到股票研究需求",
            )
        stock_demands = self._validated_stock_demands(question, demands)
        if not stock_demands:
            return MarketDataEnsureResult(
                None,
                (),
                tuple({package for demand in demands for package in demand.packages}),
                {"resolve_reason": "数据需求中的股票代码未命中本地基础表"},
                0,
                True,
                "SKIPPED",
                "数据需求中的股票代码未命中本地基础表",
            )
        stocks = tuple(stock for stock, _demand, _packages in stock_demands)
        all_packages = self._merged_packages(
            tuple(packages for _stock, _demand, packages in stock_demands)
        )
        run = self._start_run(question_id, user_id, session_id, stocks, all_packages)
        fetched_rows = 0
        stale_count = 0
        try:
            items: list[dict[str, Any]] = []
            for stock, _demand, packages in stock_demands:
                # 多股比较按股票逐只判断缓存新鲜度，避免一只缺数导致其他股票重复抓取。
                stale_packages = [
                    package
                    for package in packages
                    if self._is_package_stale(stock.ts_code, package)
                ]
                stale_count += len(stale_packages)
                stock_fetched_rows = 0
                for package in stale_packages:
                    stock_fetched_rows += self.fetcher.fetch_package(stock.ts_code, package, run.id)
                fetched_rows += stock_fetched_rows
                items.append(
                    {
                        "stock": stock,
                        "packages": packages,
                        "context": self._build_context(stock.ts_code, packages),
                        "fetched_rows": stock_fetched_rows,
                        "cache_hit": not stale_packages,
                    }
                )
            context_payload = self._aggregate_context(items)
            self._finish_run(run, "COMPLETED", fetched_rows, cache_hit=stale_count == 0)
            return MarketDataEnsureResult(
                stocks[0],
                stocks,
                all_packages,
                context_payload,
                fetched_rows,
                cache_hit=stale_count == 0,
                status="COMPLETED",
            )
        except Exception as exc:
            run_id = run.id
            self.db.rollback()
            run = self.db.get(LlmMarketDataFetchRun, run_id) or self._start_run(
                question_id,
                user_id,
                session_id,
                stocks,
                all_packages,
            )
            self._finish_run(
                run,
                "FAILED",
                fetched_rows,
                cache_hit=False,
                error_message=str(exc)[:512],
            )
            self.db.commit()
            return MarketDataEnsureResult(
                stocks[0],
                stocks,
                all_packages,
                {"fetch_error": "市场数据补取失败，已降级为本地已有数据分析"},
                fetched_rows,
                cache_hit=False,
                status="FAILED",
                reason=str(exc)[:200],
            )

    def _stock_demands(
        self,
        question: str,
        context: dict[str, Any],
        data_demands: tuple[MarketDataDemand, ...],
    ) -> tuple[MarketDataDemand, ...]:
        # 路由模型可以提出多股比较需求；后端最多接受 5 只股票，并统一走本地基础表验真。
        routed_demands = self._correct_routed_demands_by_local_name(
            question,
            context,
            tuple(demand for demand in data_demands if demand.ts_code),
        )
        if routed_demands:
            return routed_demands[:MAX_MARKET_DATA_STOCKS]
        if not self._looks_like_stock_research(question, context):
            return ()
        stock_result = self.resolver.resolve(question, context)
        if not stock_result.resolved or stock_result.identity is None:
            return ()
        return (
            MarketDataDemand(
                ts_code=stock_result.identity.ts_code,
                packages=self._packages_for_question(question),
                market=self._market_from_ts_code(stock_result.identity.ts_code),
            ),
        )

    def _correct_routed_demands_by_local_name(
        self,
        question: str,
        context: dict[str, Any],
        routed_demands: tuple[MarketDataDemand, ...],
    ) -> tuple[MarketDataDemand, ...]:
        """用本地名称解析校正路由模型给错的股票代码。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if not routed_demands:
            return routed_demands
        # LLM 前置路由可能把公司名和同业/AH 标的混淆；如果用户文本能被本地基础表
        # 解析成唯一股票，且与路由代码冲突，以本地名称解析为准，避免混入两家公司数据。
        stock_result = self.resolver.resolve(question, context)
        if not stock_result.resolved or stock_result.identity is None:
            return routed_demands
        local_code = stock_result.identity.ts_code
        routed_codes = {demand.ts_code.upper() for demand in routed_demands}
        if local_code in routed_codes:
            return routed_demands
        first_demand = routed_demands[0]
        return (
            MarketDataDemand(
                ts_code=local_code,
                packages=first_demand.packages or self._packages_for_question(question),
                market=self._market_from_ts_code(local_code),
                intent=first_demand.intent,
            ),
        )

    def _validated_stock_demands(
        self,
        question: str,
        demands: tuple[MarketDataDemand, ...],
    ) -> tuple[tuple[StockIdentity, MarketDataDemand, tuple[str, ...]], ...]:
        """校验路由或消歧后的股票代码，并保留每只股票自己的数据包需求。

        创建日期：2026-05-07
        author: sunshengxian
        """

        validated: list[tuple[StockIdentity, MarketDataDemand, tuple[str, ...]]] = []
        seen: set[str] = set()
        for demand in demands:
            # LLM 只能提交 ts_code，真正是否存在、市场是否匹配本地基础表，
            # 由 resolver 再做一次权威校验，防止任意代码触发外部接口。
            stock_result = self.resolver.resolve_code(demand.ts_code)
            if not stock_result.resolved or stock_result.identity is None:
                continue
            if stock_result.identity.ts_code in seen:
                continue
            seen.add(stock_result.identity.ts_code)
            market = self._market_from_ts_code(stock_result.identity.ts_code)
            packages = self._packages_with_question_context(
                demand.packages,
                question,
                market,
            )
            validated.append(
                (stock_result.identity, demand, packages)
            )
        return tuple(validated[:MAX_MARKET_DATA_STOCKS])

    def _looks_like_stock_research(self, question: str, context: dict[str, Any]) -> bool:
        has_stock_code = bool(
            re.search(
                r"\b\d{6}(\.(SH|SZ|BJ))?\b|\b\d{5}\.HK\b",
                question,
                re.IGNORECASE,
            )
        )
        has_context_code = any(
            context.get(key) for key in ("ts_code", "a_ts_code", "stock_code", "symbol")
        )
        has_research_word = any(
            keyword.lower() in question.lower()
            for keyword in REPORT_KEYWORDS + FINANCIAL_KEYWORDS
        )
        return has_stock_code or has_context_code or has_research_word

    def _packages_for_question(self, question: str) -> tuple[str, ...]:
        packages = [QUOTE_VALUATION_PACKAGE]
        if any(
            keyword.lower() in question.lower()
            for keyword in REPORT_KEYWORDS + FINANCIAL_KEYWORDS
        ):
            packages.append(FINANCIAL_STATEMENT_PACKAGE)
        if any(
            keyword.lower() in question.lower()
            for keyword in REPORT_KEYWORDS + BUSINESS_PROFILE_KEYWORDS
        ):
            packages.append(BUSINESS_PROFILE_PACKAGE)
        if any(keyword in question for keyword in REPORT_KEYWORDS + DIVIDEND_KEYWORDS):
            packages.append(DIVIDEND_FORECAST_PACKAGE)
        if any(keyword in question for keyword in REPORT_KEYWORDS + GOVERNANCE_KEYWORDS):
            packages.append(SHAREHOLDER_GOVERNANCE_PACKAGE)
        if any(keyword in question for keyword in CAPITAL_FLOW_KEYWORDS):
            packages.append(CAPITAL_FLOW_PACKAGE)
        return tuple(packages)

    def _normalize_packages(self, packages: tuple[str, ...], market: str = "A") -> tuple[str, ...]:
        # 统一使用市场白名单过滤路由返回包名，避免不同方法里的包顺序或港股限制不一致。
        allowed = self._allowed_packages_for_market(market)
        normalized = tuple(package for package in allowed if package in set(packages))
        if normalized:
            return normalized
        return (FINANCIAL_STATEMENT_PACKAGE,) if market == "HK" else (QUOTE_VALUATION_PACKAGE,)

    def _packages_with_question_context(
        self,
        packages: tuple[str, ...],
        question: str,
        market: str,
    ) -> tuple[str, ...]:
        """根据问题语义扩展路由模型遗漏但研究判断必需的数据包。

        创建日期：2026-05-09
        author: sunshengxian
        """

        normalized_packages = self._normalize_packages(packages, market)
        if market == "HK":
            return normalized_packages
        expanded = list(normalized_packages)
        normalized_question = question.lower()
        # 路由模型经常只返回财务报表包；当用户追问财报调整、重述、审计或年季报异常性质时，
        # 必须同步准备审计/快报和股东治理材料，否则回答只能依赖财务模式做推断，
        # 容易把本轮可准备的结构化材料误报为缺口。
        if FINANCIAL_STATEMENT_PACKAGE in expanded and any(
            keyword.lower() in normalized_question for keyword in ACCOUNTING_REVIEW_KEYWORDS
        ):
            for package in (BUSINESS_PROFILE_PACKAGE, SHAREHOLDER_GOVERNANCE_PACKAGE):
                if package not in expanded:
                    expanded.append(package)
        return tuple(
            package
            for package in self._allowed_packages_for_market(market)
            if package in expanded
        )

    def _allowed_packages_for_market(self, market: str) -> tuple[str, ...]:
        """返回市场可用数据包白名单，供归一化和语义扩展保持同一顺序。

        创建日期：2026-05-09
        author: sunshengxian
        """

        if market == "HK":
            # 港股自动补数目前只开放财务指标和三大报表；行情、股东治理、分红等仍沿用
            # 本地已有 AH/港股通数据或后续单独扩展，避免路由模型误触未沉淀的数据域。
            return (FINANCIAL_STATEMENT_PACKAGE,)
        return (
            QUOTE_VALUATION_PACKAGE,
            FINANCIAL_STATEMENT_PACKAGE,
            BUSINESS_PROFILE_PACKAGE,
            DIVIDEND_FORECAST_PACKAGE,
            SHAREHOLDER_GOVERNANCE_PACKAGE,
            CAPITAL_FLOW_PACKAGE,
        )

    def _merged_packages(self, package_groups: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
        # 批次审计表只记录本轮问答涉及的包合集，逐股实际包仍保留在 market_data_context.items 中。
        allowed = (
            QUOTE_VALUATION_PACKAGE,
            FINANCIAL_STATEMENT_PACKAGE,
            BUSINESS_PROFILE_PACKAGE,
            DIVIDEND_FORECAST_PACKAGE,
            SHAREHOLDER_GOVERNANCE_PACKAGE,
            CAPITAL_FLOW_PACKAGE,
        )
        selected = {package for packages in package_groups for package in packages}
        return tuple(package for package in allowed if package in selected)

    def _is_package_stale(self, ts_code: str, package: str, today: date | None = None) -> bool:
        today = today or date.today()
        if package == QUOTE_VALUATION_PACKAGE:
            latest_date = self.db.scalar(
                select(func.max(ADailyBasic.trade_date)).where(ADailyBasic.ts_code == ts_code)
            )
            return latest_date is None or latest_date < today - timedelta(days=7)
        if package == FINANCIAL_STATEMENT_PACKAGE:
            if self._market_from_ts_code(ts_code) == "HK":
                latest_period = self.db.scalar(
                    select(func.max(HKFinancialIndicator.end_date)).where(
                        HKFinancialIndicator.ts_code == ts_code
                    )
                )
                return latest_period is None or latest_period < today - timedelta(days=220)
            latest_period = self.db.scalar(
                select(func.max(AFinancialIndicator.end_date)).where(
                    AFinancialIndicator.ts_code == ts_code
                )
            )
            return latest_period is None or latest_period < today - timedelta(days=220)
        if package == BUSINESS_PROFILE_PACKAGE:
            latest_business = self.db.scalar(
                select(func.max(AMainBusinessComposition.end_date)).where(
                    AMainBusinessComposition.ts_code == ts_code
                )
            )
            return latest_business is None or latest_business < today - timedelta(days=365)
        if package == DIVIDEND_FORECAST_PACKAGE:
            latest_dividend = self.db.scalar(
                select(func.max(ADividend.ann_date)).where(ADividend.ts_code == ts_code)
            )
            latest_forecast = self.db.scalar(
                select(func.max(AForecast.ann_date)).where(AForecast.ts_code == ts_code)
            )
            latest = max(
                [item for item in (latest_dividend, latest_forecast) if item],
                default=None,
            )
            return latest is None or latest < today - timedelta(days=365)
        if package == SHAREHOLDER_GOVERNANCE_PACKAGE:
            latest_holder = self.db.scalar(
                select(func.max(AHolderNumber.end_date)).where(AHolderNumber.ts_code == ts_code)
            )
            latest_top10 = self.db.scalar(
                select(func.max(ATop10Holder.end_date)).where(ATop10Holder.ts_code == ts_code)
            )
            latest_pledge = self.db.scalar(
                select(func.max(APledgeStat.end_date)).where(APledgeStat.ts_code == ts_code)
            )
            latest = max(
                [item for item in (latest_holder, latest_top10, latest_pledge) if item],
                default=None,
            )
            return latest is None or latest < today - timedelta(days=365)
        if package == CAPITAL_FLOW_PACKAGE:
            latest_moneyflow = self.db.scalar(
                select(func.max(AMoneyflow.trade_date)).where(AMoneyflow.ts_code == ts_code)
            )
            return latest_moneyflow is None or latest_moneyflow < today - timedelta(days=14)
        return False

    def _build_context(self, ts_code: str, packages: tuple[str, ...]) -> dict[str, Any]:
        # 视图输出是给 LLM 的事实材料，控制条数和字段可以避免上下文被低价值历史明细淹没。
        if self._market_from_ts_code(ts_code) == "HK":
            return {
                "ts_code": ts_code,
                "market": "HK",
                "packages": packages,
                "latest": self._query_view(
                    (
                        "select * from v_hk_stock_research_context_latest "
                        "where ts_code = :ts_code limit 1"
                    ),
                    ts_code,
                ),
                "financial_periods": self._query_view(
                    (
                        "select * from v_hk_financial_period_summary "
                        "where ts_code = :ts_code order by end_date desc limit 24"
                    ),
                    ts_code,
                ),
                "statement_items": self._query_view(
                    (
                        "select * from v_hk_financial_statement_item_summary "
                        "where ts_code = :ts_code "
                        "order by end_date desc, statement_type, ind_name limit 80"
                    ),
                    ts_code,
                ),
            }
        return {
            "ts_code": ts_code,
            "packages": packages,
            "latest": self._query_view(
                "select * from v_stock_research_context_latest where ts_code = :ts_code limit 1",
                ts_code,
            ),
            "valuation_trend": self._query_view(
                (
                    "select * from v_stock_quote_valuation_trend "
                    "where ts_code = :ts_code order by trade_date desc limit 12"
                ),
                ts_code,
            ),
            "financial_periods": self._query_view(
                (
                    "select * from v_stock_financial_period_summary "
                    "where ts_code = :ts_code order by end_date desc limit 24"
                ),
                ts_code,
            ),
            "business_profile": self._query_view(
                (
                    "select * from v_stock_business_profile_summary "
                    "where ts_code = :ts_code "
                    "order by end_date desc, business_type, bz_sales desc limit 20"
                ),
                ts_code,
            ),
            "shareholder_governance": self._query_view(
                (
                    "select * from v_stock_shareholder_governance_summary "
                    "where ts_code = :ts_code "
                    "order by sort_date desc, section_type, ranking limit 30"
                ),
                ts_code,
            ),
            "capital_flow_recent": self._query_view(
                (
                    "select * from v_stock_moneyflow_recent "
                    "where ts_code = :ts_code order by trade_date desc limit 20"
                ),
                ts_code,
            ),
        }

    def _aggregate_context(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """聚合单股或多股上下文，保留单股旧字段兼容原提示词消费方式。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if len(items) == 1:
            context_payload = dict(items[0]["context"])
            context_payload["scope"] = "A_STOCK_SINGLE"
            if items[0]["stock"].ts_code.endswith(".HK"):
                context_payload["scope"] = "HK_STOCK_SINGLE"
            context_payload["items"] = items
            context_payload["stocks"] = [items[0]["stock"]]
            return context_payload
        return {
            "scope": self._market_scope(tuple(item["stock"] for item in items)),
            "stocks": [item["stock"] for item in items],
            "items": items,
            "ah_cross_market": self._build_ah_cross_market_context(
                tuple(item["stock"] for item in items)
            ),
            "limit_policy": (
                f"单轮最多补充 {MAX_MARKET_DATA_STOCKS} 只股票，"
                "逐只保留完整报告上下文。"
            ),
        }

    def _query_view(self, sql: str, ts_code: str) -> list[dict[str, Any]]:
        rows = self.db.execute(text(sql), {"ts_code": ts_code}).fetchall()
        return [self._format_context_row(dict(row._mapping)) for row in rows]

    def _format_context_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """为 LLM 上下文补充亿元派生字段，避免模型把元级金额换算错位。

        创建日期：2026-05-09
        author: sunshengxian
        """

        formatted = dict(row)
        for field in AMOUNT_YUAN_FIELDS:
            if field not in row:
                continue
            value = self._yuan_to_yi(row.get(field))
            if value is None:
                continue
            formatted[f"{field}_yi"] = value
            label = AMOUNT_YI_LABELS.get(field)
            if label:
                # 同时给机器友好字段和中文标签字段，确保模型按字段名或标签阅读时口径一致。
                formatted[label] = value
        return formatted

    def _yuan_to_yi(self, value: Any) -> str | None:
        """把元级金额统一换算为亿元字符串；无法解析的空值保持缺失。

        创建日期：2026-05-09
        author: sunshengxian
        """

        if value in (None, ""):
            return None
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return str((amount / Decimal("100000000")).quantize(Decimal("0.01")))

    def _build_ah_cross_market_context(
        self,
        stocks: tuple[StockIdentity, ...],
    ) -> list[dict[str, Any]]:
        """为 A/H 混合问题补充官方价差和港股通通道摘要。

        创建日期：2026-05-08
        author: sunshengxian
        """

        a_codes = [stock.ts_code for stock in stocks if not stock.ts_code.endswith(".HK")]
        hk_codes = [stock.ts_code for stock in stocks if stock.ts_code.endswith(".HK")]
        if not a_codes or not hk_codes:
            return []
        # 只读视图已经按最新官方 AH 比价口径整合港股通标识；这里仅按本轮股票集合过滤，
        # 给 LLM 提供“能否走港股通、AH/H/A 价差是多少”的跨市场事实材料。
        statement = (
            text(
                "select * from v_latest_official_ah_premium "
                "where a_ts_code in :a_codes and hk_ts_code in :hk_codes"
            )
            .bindparams(bindparam("a_codes", expanding=True))
            .bindparams(bindparam("hk_codes", expanding=True))
        )
        rows = self.db.execute(
            statement,
            {"a_codes": tuple(a_codes), "hk_codes": tuple(hk_codes)},
        ).fetchall()
        return [dict(row._mapping) for row in rows]

    def _start_run(
        self,
        question_id: str | None,
        user_id: int | None,
        session_id: int | None,
        stocks: tuple[StockIdentity, ...],
        packages: tuple[str, ...],
    ) -> LlmMarketDataFetchRun:
        # Tushare 积分在本项目中代表接口权限门槛，不是按次扣减制；这里的边界强调接口范围和批量规模。
        stock_codes = [stock.ts_code for stock in stocks]
        market_scope = self._market_scope(stocks)
        run = LlmMarketDataFetchRun(
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
            intent="stock_research",
            market_scope=market_scope,
            symbols_json=json.dumps(stock_codes, ensure_ascii=False),
            data_packages_json=json.dumps(list(packages), ensure_ascii=False),
            period_policy=f"{market_scope}_EXTENDED_15000_PERMISSION",
            start_date=date.today() - timedelta(days=365 * 8),
            end_date=date.today(),
            status="RUNNING",
            cache_hit=False,
            row_count=0,
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.db.add(run)
        self.db.flush()
        return run

    def _finish_run(
        self,
        run: LlmMarketDataFetchRun,
        status: str,
        row_count: int,
        cache_hit: bool,
        error_message: str | None = None,
    ) -> None:
        run.status = status
        run.row_count = row_count
        run.cache_hit = cache_hit
        run.error_message = error_message
        run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.commit()

    def _market_from_ts_code(self, ts_code: str) -> str:
        """按 Tushare 代码后缀判断补数市场，供缓存和白名单分流。

        创建日期：2026-05-08
        author: sunshengxian
        """

        return "HK" if ts_code.upper().endswith(".HK") else "A"

    def _market_scope(self, stocks: tuple[StockIdentity, ...]) -> str:
        """生成补数审计市场范围，明确区分 A 股、港股和混合对比。

        创建日期：2026-05-08
        author: sunshengxian
        """

        markets = {self._market_from_ts_code(stock.ts_code) for stock in stocks}
        if markets == {"HK"}:
            return "HK_STOCK_SINGLE" if len(stocks) == 1 else "HK_STOCK_MULTI"
        if markets == {"A"}:
            return "A_STOCK_SINGLE" if len(stocks) == 1 else "A_STOCK_MULTI"
        return "CROSS_MARKET_MULTI"
