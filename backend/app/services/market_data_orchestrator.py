from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models.market import (
    ADailyBasic,
    ADividend,
    AFinancialIndicator,
    AForecast,
    LlmMarketDataFetchRun,
)
from app.services.stock_identity_resolver import StockIdentity, StockIdentityResolver
from app.services.tushare_stock_research_fetcher import (
    DIVIDEND_FORECAST_PACKAGE,
    FINANCIAL_STATEMENT_PACKAGE,
    QUOTE_VALUATION_PACKAGE,
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


@dataclass(frozen=True)
class MarketDataDemand:
    """LLM 按需补数请求，限定为单只股票和固定数据包。

    创建日期：2026-05-07
    author: sunshengxian
    """

    ts_code: str
    packages: tuple[str, ...]
    intent: str = "stock_research"


@dataclass(frozen=True)
class MarketDataEnsureResult:
    """按需补数和上下文构建结果。

    创建日期：2026-05-07
    author: sunshengxian
    """

    stock: StockIdentity | None
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

        demand = self._single_stock_demand(question, context, data_demands)
        if demand is None:
            return MarketDataEnsureResult(None, (), {}, 0, True, "SKIPPED", "未识别到单只 A 股需求")
        stock_result = self.resolver.resolve(question, context)
        if not stock_result.resolved or stock_result.identity is None:
            return MarketDataEnsureResult(
                None,
                demand.packages,
                {"resolve_reason": stock_result.reason},
                0,
                True,
                "SKIPPED",
                stock_result.reason,
            )
        if demand.ts_code and demand.ts_code != stock_result.identity.ts_code:
            return MarketDataEnsureResult(
                stock_result.identity,
                demand.packages,
                {"resolve_reason": "路由代码与本地解析代码不一致，已停止自动补数"},
                0,
                True,
                "SKIPPED",
                "路由代码与本地解析代码不一致",
            )
        packages = self._normalize_packages(demand.packages)
        run = self._start_run(question_id, user_id, session_id, stock_result.identity, packages)
        fetched_rows = 0
        try:
            stale_packages = [
                package
                for package in packages
                if self._is_package_stale(stock_result.identity.ts_code, package)
            ]
            for package in stale_packages:
                fetched_rows += self.fetcher.fetch_package(
                    stock_result.identity.ts_code,
                    package,
                    run.id,
                )
            context_payload = self._build_context(stock_result.identity.ts_code, packages)
            self._finish_run(run, "COMPLETED", fetched_rows, cache_hit=not stale_packages)
            return MarketDataEnsureResult(
                stock_result.identity,
                packages,
                context_payload,
                fetched_rows,
                cache_hit=not stale_packages,
                status="COMPLETED",
            )
        except Exception as exc:
            run_id = run.id
            self.db.rollback()
            run = self.db.get(LlmMarketDataFetchRun, run_id) or self._start_run(
                question_id,
                user_id,
                session_id,
                stock_result.identity,
                packages,
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
                stock_result.identity,
                packages,
                {"fetch_error": "市场数据补取失败，已降级为本地已有数据分析"},
                fetched_rows,
                cache_hit=False,
                status="FAILED",
                reason=str(exc)[:200],
            )

    def _single_stock_demand(
        self,
        question: str,
        context: dict[str, Any],
        data_demands: tuple[MarketDataDemand, ...],
    ) -> MarketDataDemand | None:
        # 路由模型可以提出需求，但这里只接受单股需求；
        # 本地关键词兜底让模型不可用时仍能补足报告上下文。
        if len(data_demands) == 1 and data_demands[0].ts_code:
            return data_demands[0]
        if len(data_demands) > 1:
            return None
        if not self._looks_like_stock_research(question, context):
            return None
        stock_result = self.resolver.resolve(question, context)
        if not stock_result.resolved or stock_result.identity is None:
            return None
        return MarketDataDemand(
            ts_code=stock_result.identity.ts_code,
            packages=self._packages_for_question(question),
        )

    def _looks_like_stock_research(self, question: str, context: dict[str, Any]) -> bool:
        has_stock_code = bool(re.search(r"\b\d{6}(\.(SH|SZ|BJ))?\b", question, re.IGNORECASE))
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
        if any(keyword in question for keyword in REPORT_KEYWORDS + DIVIDEND_KEYWORDS):
            packages.append(DIVIDEND_FORECAST_PACKAGE)
        return tuple(packages)

    def _normalize_packages(self, packages: tuple[str, ...]) -> tuple[str, ...]:
        allowed = (QUOTE_VALUATION_PACKAGE, FINANCIAL_STATEMENT_PACKAGE, DIVIDEND_FORECAST_PACKAGE)
        normalized = tuple(package for package in allowed if package in set(packages))
        return normalized or (QUOTE_VALUATION_PACKAGE,)

    def _is_package_stale(self, ts_code: str, package: str, today: date | None = None) -> bool:
        today = today or date.today()
        if package == QUOTE_VALUATION_PACKAGE:
            latest_date = self.db.scalar(
                select(func.max(ADailyBasic.trade_date)).where(ADailyBasic.ts_code == ts_code)
            )
            return latest_date is None or latest_date < today - timedelta(days=7)
        if package == FINANCIAL_STATEMENT_PACKAGE:
            latest_period = self.db.scalar(
                select(func.max(AFinancialIndicator.end_date)).where(
                    AFinancialIndicator.ts_code == ts_code
                )
            )
            return latest_period is None or latest_period < today - timedelta(days=220)
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
        return False

    def _build_context(self, ts_code: str, packages: tuple[str, ...]) -> dict[str, Any]:
        # 视图输出是给 LLM 的事实材料，控制条数和字段可以避免上下文被低价值历史明细淹没。
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
                    "where ts_code = :ts_code order by end_date desc limit 8"
                ),
                ts_code,
            ),
        }

    def _query_view(self, sql: str, ts_code: str) -> list[dict[str, Any]]:
        rows = self.db.execute(text(sql), {"ts_code": ts_code}).fetchall()
        return [dict(row._mapping) for row in rows]

    def _start_run(
        self,
        question_id: str | None,
        user_id: int | None,
        session_id: int | None,
        stock: StockIdentity,
        packages: tuple[str, ...],
    ) -> LlmMarketDataFetchRun:
        run = LlmMarketDataFetchRun(
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
            intent="stock_research",
            market_scope="A_STOCK_SINGLE",
            symbols_json=json.dumps([stock.ts_code], ensure_ascii=False),
            data_packages_json=json.dumps(list(packages), ensure_ascii=False),
            period_policy="SINGLE_STOCK_RECENT_LIMITED_15000_POINTS",
            start_date=date.today() - timedelta(days=365 * 5),
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
