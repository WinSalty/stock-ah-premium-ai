from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.market import (
    ADailyBasic,
    ADailyQuote,
    ADividend,
    AFinancialIndicator,
    AStockBasic,
    ATradeCalendar,
    DividendReinvestmentBacktestRun,
    DividendReinvestmentBacktestSummary,
    DividendReinvestmentBacktestYearly,
)
from app.db.models.sync import SyncCheckpoint
from app.services.date_utils import format_tushare_date, parse_tushare_date
from app.services.decimal_utils import quantize_decimal, to_decimal
from app.services.repository import UpsertRepository
from app.services.tushare_client import TushareClient

DIVIDEND_REINVESTMENT_DATASET = "dividend_reinvestment_data_landing"
DEFAULT_BACKTEST_START_DATE = date(2016, 1, 1)
DEFAULT_INITIAL_AMOUNT = Decimal("100000")
MAX_REINVEST_PRICE_LOOKAHEAD_DAYS = 10
RESULT_UPSERT_CHUNK_SIZE = 500
TEN_YEAR_AVG_WINDOW = 10

SUMMARY_EXPORT_COLUMNS = [
    ("ts_code", "代码"),
    ("name", "名称"),
    ("industry", "行业"),
    ("annualized_return_pct", "年化收益率"),
    ("ten_year_avg_annualized_return_pct", "近十年平均年化收益率"),
    ("latest_pe", "最新PE"),
    ("latest_pe_ttm", "最新PE_TTM"),
    ("latest_roe", "最新ROE"),
    ("total_return_pct", "累计收益率"),
    ("final_market_value", "期末市值"),
    ("total_cash_dividend", "累计分红"),
    ("dividend_year_count", "分红年数"),
    ("consecutive_dividend_years", "连续分红年数"),
    ("latest_dividend_yield_ttm", "最新股息率TTM"),
    ("latest_pb", "最新PB"),
    ("rank_score", "综合排序分"),
    ("data_quality", "数据质量"),
    ("data_issue", "数据问题"),
]
YEARLY_EXPORT_COLUMNS = [
    ("ts_code", "代码"),
    ("name", "名称"),
    ("industry", "行业"),
    ("year", "年份"),
    ("year_end_trade_date", "年度交易日"),
    ("year_end_price", "年末股价"),
    ("cash_div_per_share", "每股现金分红"),
    ("cash_div_amount", "现金分红金额"),
    ("stock_div_per_share", "每股送转"),
    ("stock_div_shares", "送转股数"),
    ("reinvest_price_avg", "再投均价"),
    ("reinvested_shares", "再投股数"),
    ("holding_shares", "持仓股数"),
    ("market_value", "市值"),
    ("return_amount", "累计收益金额"),
    ("return_pct", "累计收益率"),
    ("annualized_return_pct", "年度年化收益率"),
    ("dividend_event_count", "分红事件数"),
    ("note", "备注"),
]


@dataclass(frozen=True)
class DividendReinvestmentSyncParams:
    """分红再投入数据落地参数。

    创建日期：2026-05-29
    author: sunshengxian
    """

    mode: str
    start_date: date
    end_date: date
    initial_amount: Decimal
    cash_div_field: str
    supplement_dividend_by_stock: bool = False
    supplement_financial_indicator_by_stock: bool = False


@dataclass(frozen=True)
class DividendReinvestmentSyncResult:
    """分红再投入数据落地结果。

    创建日期：2026-05-29
    author: sunshengxian
    """

    stock_rows: int
    calendar_rows: int
    daily_rows: int
    dividend_rows: int
    stock_dividend_rows: int
    daily_basic_rows: int
    financial_indicator_rows: int
    summary_rows: int
    yearly_rows: int

    @property
    def total_rows(self) -> int:
        return (
            self.stock_rows
            + self.calendar_rows
            + self.daily_rows
            + self.dividend_rows
            + self.stock_dividend_rows
            + self.daily_basic_rows
            + self.financial_indicator_rows
            + self.summary_rows
            + self.yearly_rows
        )


class DividendReinvestmentDataLandingService:
    """分红再投入所需数据落地与本地回测服务。

    创建日期：2026-05-29
    author: sunshengxian
    """

    stock_basic_fields = [
        "ts_code",
        "symbol",
        "name",
        "area",
        "industry",
        "fullname",
        "market",
        "exchange",
        "curr_type",
        "list_status",
        "list_date",
        "delist_date",
        "is_hs",
    ]
    trade_calendar_fields = ["exchange", "cal_date", "is_open", "pretrade_date"]
    daily_fields = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ]
    dividend_fields = [
        "ts_code",
        "end_date",
        "ann_date",
        "div_proc",
        "stk_div",
        "cash_div",
        "cash_div_tax",
        "record_date",
        "ex_date",
        "pay_date",
    ]
    daily_basic_fields = [
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    ]
    financial_indicator_fields = [
        "ts_code",
        "ann_date",
        "end_date",
        "eps",
        "dt_eps",
        "roe",
        "roe_waa",
        "roe_dt",
        "roa",
        "grossprofit_margin",
        "netprofit_margin",
        "sales_gpr",
        "profit_to_gr",
        "debt_to_assets",
        "current_ratio",
        "quick_ratio",
        "assets_to_eqt",
        "or_yoy",
        "q_sales_yoy",
        "netprofit_yoy",
        "q_netprofit_yoy",
        "ocf_to_revenue",
        "ocfps",
        "roe_yoy",
        "bps",
        "profit_dedt",
        "update_flag",
    ]

    def __init__(
        self,
        db: Session,
        client: TushareClient | None = None,
        repository: UpsertRepository | None = None,
    ) -> None:
        self.db = db
        self.client = client or TushareClient(get_settings())
        self.repository = repository or UpsertRepository(db)

    def sync(self, params: dict[str, Any]) -> DividendReinvestmentSyncResult:
        """按固定阶段顺序落地数据并计算回测结果。

        创建日期：2026-05-29
        author: sunshengxian
        """

        normalized = self._normalize_params(params)
        if normalized.mode == "calculate_only":
            # 仅本地回测模式用于在原始数据已落库后重算榜单和年度明细；
            # 这里显式跳过所有 Tushare 阶段，即使请求里误带补数开关也不会产生外部取数。
            summary_rows, yearly_rows = self.calculate_backtest(normalized)
            return DividendReinvestmentSyncResult(
                stock_rows=0,
                calendar_rows=0,
                daily_rows=0,
                dividend_rows=0,
                stock_dividend_rows=0,
                daily_basic_rows=0,
                financial_indicator_rows=0,
                summary_rows=summary_rows,
                yearly_rows=yearly_rows,
            )
        # 阶段顺序固定为“基础资料、交易日历、日线、分红、最新指标、回测计算”，
        # 这样失败时可通过各阶段 checkpoint 定位缺口，计算阶段也不会再访问外部接口。
        stock_rows = self._sync_stock_basic()
        calendar_rows = self._sync_trade_calendar(normalized.start_date, normalized.end_date)
        daily_rows = self._sync_daily_quotes(normalized)
        dividend_rows = self._sync_dividends(normalized)
        stock_dividend_rows = (
            self._sync_candidate_dividends_by_stock(normalized)
            if normalized.supplement_dividend_by_stock
            else 0
        )
        daily_basic_rows = self._sync_latest_daily_basic(normalized.end_date)
        financial_indicator_rows = (
            self._sync_candidate_financial_indicators_by_stock(normalized)
            if normalized.supplement_financial_indicator_by_stock
            else 0
        )
        summary_rows, yearly_rows = self.calculate_backtest(normalized)
        return DividendReinvestmentSyncResult(
            stock_rows=stock_rows,
            calendar_rows=calendar_rows,
            daily_rows=daily_rows,
            dividend_rows=dividend_rows,
            stock_dividend_rows=stock_dividend_rows,
            daily_basic_rows=daily_basic_rows,
            financial_indicator_rows=financial_indicator_rows,
            summary_rows=summary_rows,
            yearly_rows=yearly_rows,
        )

    def calculate_backtest(self, params: DividendReinvestmentSyncParams) -> tuple[int, int]:
        """基于本地数据计算分红再投入回测结果。

        创建日期：2026-05-29
        author: sunshengxian
        """

        run = self._create_backtest_run(params)
        try:
            stocks = self._candidate_stocks(params)
            latest_basic = self._latest_daily_basic_map()
            latest_financials = self._latest_financial_indicator_map()
            summary_rows: list[dict[str, Any]] = []
            yearly_rows: list[dict[str, Any]] = []
            for stock in stocks:
                # 每只股票独立读取日线和分红，估值和 ROE 只使用本地 Tushare 落地基础表；
                # 这样计算阶段不会访问外部接口，也不会把 LLM 选股快照混入全市场分红回测。
                summary, yearly = self._calculate_stock(
                    stock,
                    params,
                    run.id,
                    latest_basic.get(stock.ts_code),
                    latest_financials.get(stock.ts_code),
                )
                if summary:
                    summary_rows.append(summary)
                    yearly_rows.extend(yearly)
            self._upsert_many_chunked(
                DividendReinvestmentBacktestSummary,
                summary_rows,
            )
            self._upsert_many_chunked(
                DividendReinvestmentBacktestYearly,
                yearly_rows,
            )
            run.status = "SUCCESS"
            run.stock_count = len(stocks)
            run.summary_count = len(summary_rows)
            run.finished_at = self._now()
            self._prune_non_latest_backtest_results(run.id)
            self.db.commit()
            return len(summary_rows), len(yearly_rows)
        except Exception as exc:
            self.db.rollback()
            run = self.db.merge(run)
            run.status = "FAILED"
            run.error_message = str(exc)[:4000]
            run.finished_at = self._now()
            self.db.commit()
            raise

    def _prune_non_latest_backtest_results(self, latest_run_id: int) -> None:
        """清理旧回测批次，只保留最新成功批次供筛选页和导出使用。

        创建日期：2026-06-02
        author: sunshengxian
        """

        # 清理动作只在新批次结果已完整写入且即将提交成功时执行；
        # 失败任务不会进入这里，因此不会误删上一份可用榜单数据。
        self.db.execute(
            delete(DividendReinvestmentBacktestYearly).where(
                DividendReinvestmentBacktestYearly.run_id != latest_run_id
            )
        )
        self.db.execute(
            delete(DividendReinvestmentBacktestSummary).where(
                DividendReinvestmentBacktestSummary.run_id != latest_run_id
            )
        )
        self.db.execute(
            delete(DividendReinvestmentBacktestRun).where(
                DividendReinvestmentBacktestRun.id != latest_run_id
            )
        )

    def _normalize_params(self, params: dict[str, Any]) -> DividendReinvestmentSyncParams:
        """标准化同步参数并约束第一版支持的分红口径。

        创建日期：2026-05-29
        author: sunshengxian
        """

        mode = str(params.get("mode") or "incremental")
        requested_start = self._coerce_date(params.get("start_date"))
        requested_end = self._coerce_date(params.get("end_date")) or date.today()
        # 回测起点是计算口径，不等同于各阶段的同步断点；增量任务仍应用固定起点计算完整榜单。
        start_date = requested_start or DEFAULT_BACKTEST_START_DATE
        initial_amount = to_decimal(params.get("initial_amount")) or DEFAULT_INITIAL_AMOUNT
        cash_div_field = str(params.get("cash_div_field") or "cash_div_tax")
        supplement_dividend_by_stock = self._coerce_bool(
            params.get("supplement_dividend_by_stock")
        )
        supplement_financial_indicator_by_stock = self._coerce_bool(
            params.get("supplement_financial_indicator_by_stock")
        )
        if mode not in {"incremental", "full", "calculate_only"}:
            raise ValueError("分红再投入同步模式仅支持 incremental、full 或 calculate_only")
        if cash_div_field not in {"cash_div_tax", "cash_div"}:
            raise ValueError("现金分红口径仅支持 cash_div_tax 或 cash_div")
        if mode == "calculate_only":
            # 仅计算模式的业务承诺是不访问外部接口，因此统一关闭逐股补数开关；
            # 回测仍会读取本地 a_daily_quote、a_dividend、a_daily_basic 和 a_financial_indicator。
            supplement_dividend_by_stock = False
            supplement_financial_indicator_by_stock = False
        return DividendReinvestmentSyncParams(
            mode=mode,
            start_date=start_date,
            end_date=requested_end,
            initial_amount=initial_amount,
            cash_div_field=cash_div_field,
            supplement_dividend_by_stock=supplement_dividend_by_stock,
            supplement_financial_indicator_by_stock=supplement_financial_indicator_by_stock,
        )

    def _sync_stock_basic(self) -> int:
        result = self.client.query(
            "stock_basic",
            params={"exchange": "", "list_status": "L"},
            fields=self.stock_basic_fields,
        )
        rows = [self._normalize_stock_basic_row(row) for row in result.rows]
        row_count = self.repository.upsert_many(AStockBasic, rows)
        self._update_checkpoint("stock_basic", "default", date.today())
        self.db.commit()
        return row_count

    def _sync_trade_calendar(self, start_date: date, end_date: date) -> int:
        result = self.client.query(
            "trade_cal",
            params={
                "exchange": "SSE",
                "start_date": format_tushare_date(start_date),
                "end_date": format_tushare_date(end_date + timedelta(days=370)),
            },
            fields=self.trade_calendar_fields,
        )
        rows = [self._normalize_trade_calendar_row(row) for row in result.rows]
        row_count = self.repository.upsert_many(ATradeCalendar, rows)
        self._update_checkpoint("trade_cal", "default", end_date)
        self.db.commit()
        return row_count

    def _sync_daily_quotes(self, params: DividendReinvestmentSyncParams) -> int:
        row_count = 0
        start_date = (
            params.start_date
            if params.mode == "full"
            else self._checkpoint_next_date("daily", params.start_date)
        )
        for trade_date in self._open_trade_dates(start_date, params.end_date):
            result = self.client.query(
                "daily",
                params={"trade_date": format_tushare_date(trade_date)},
                fields=self.daily_fields,
            )
            rows = [self._normalize_daily_quote_row(row) for row in result.rows]
            row_count += self.repository.upsert_many(ADailyQuote, rows)
            self._update_checkpoint("daily", "default", trade_date)
            self.db.commit()
        return row_count

    def _sync_dividends(self, params: DividendReinvestmentSyncParams) -> int:
        row_count = 0
        start_date = (
            params.start_date
            if params.mode == "full"
            else self._checkpoint_next_date("dividend", params.start_date)
        )
        for current_date in self._open_trade_dates(start_date, params.end_date):
            # 除权除息日按交易日发生，按开市日请求可跳过周末和节假日，减少无效调用并继续遵守限流。
            result = self.client.query(
                "dividend",
                params={"ex_date": format_tushare_date(current_date)},
                fields=self.dividend_fields,
            )
            rows = [
                normalized
                for row in result.rows
                if (normalized := self._normalize_dividend_row(row)) is not None
            ]
            row_count += self.repository.upsert_many(ADividend, rows)
            self._update_checkpoint("dividend", "default", current_date)
            self.db.commit()
        return row_count

    def _sync_candidate_dividends_by_stock(
        self,
        params: DividendReinvestmentSyncParams,
    ) -> int:
        """按股票代码补齐候选池历史分红，修复按 ex_date 回补早期历史覆盖不足。

        创建日期：2026-05-30
        author: sunshengxian
        """

        row_count = 0
        for stock in self._candidate_stocks(params):
            result = self.client.query(
                "dividend",
                params={"ts_code": stock.ts_code},
                fields=self.dividend_fields,
            )
            rows = []
            for row in result.rows:
                normalized = self._normalize_dividend_row(row)
                if not normalized:
                    continue
                ex_date = normalized["ex_date"]
                if params.start_date <= ex_date <= params.end_date:
                    rows.append(normalized)
            # 股票维度补齐只在显式修复任务中启用；每只股票独立提交，失败后可直接重跑并幂等覆盖。
            row_count += self.repository.upsert_many(ADividend, rows)
            self.db.commit()
        return row_count

    def _sync_latest_daily_basic(self, end_date: date) -> int:
        for offset in range(20):
            current_date = end_date - timedelta(days=offset)
            result = self.client.query(
                "daily_basic",
                params={"trade_date": format_tushare_date(current_date)},
                fields=self.daily_basic_fields,
            )
            if not result.rows:
                continue
            rows = [self._normalize_daily_basic_row(row) for row in result.rows]
            row_count = self.repository.upsert_many(ADailyBasic, rows)
            self._update_checkpoint("daily_basic", "default", current_date)
            self.db.commit()
            return row_count
        return 0

    def _sync_candidate_financial_indicators_by_stock(
        self,
        params: DividendReinvestmentSyncParams,
    ) -> int:
        """按候选股票逐只补齐 A 股财务指标，给 ROE 提供全市场基础表来源。

        创建日期：2026-06-02
        author: sunshengxian
        """

        row_count = 0
        for stock in self._candidate_stocks(params):
            result = self.client.query(
                "fina_indicator",
                params={"ts_code": stock.ts_code},
                fields=self.financial_indicator_fields,
            )
            rows = [
                normalized
                for row in result.rows
                if (normalized := self._normalize_financial_indicator_row(row)) is not None
            ]
            # 财务指标补数是显式修复任务；逐股提交可降低长跑任务中断后的重跑成本。
            row_count += self.repository.upsert_many(AFinancialIndicator, rows)
            self.db.commit()
        return row_count

    def _create_backtest_run(
        self,
        params: DividendReinvestmentSyncParams,
    ) -> DividendReinvestmentBacktestRun:
        run = DividendReinvestmentBacktestRun(
            run_key=(
                f"{params.start_date.isoformat()}_{params.end_date.isoformat()}_"
                f"{params.cash_div_field}_{self._now().strftime('%Y%m%d%H%M%S')}"
            ),
            start_date=params.start_date,
            end_date=params.end_date,
            initial_amount=params.initial_amount,
            cash_div_field=params.cash_div_field,
            status="RUNNING",
            started_at=self._now(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _candidate_stocks(self, params: DividendReinvestmentSyncParams) -> list[AStockBasic]:
        statement = (
            select(AStockBasic)
            .where(AStockBasic.list_status == "L")
            .order_by(AStockBasic.ts_code)
        )
        stocks = []
        for stock in self.db.scalars(statement).all():
            # 第一版主榜单只计算回测期前已上市且非 ST 的股票，短历史股票会影响横向可比性。
            if stock.list_date and stock.list_date > params.start_date:
                continue
            if "ST" in stock.name.upper() or "退" in stock.name:
                continue
            stocks.append(stock)
        return stocks

    def _latest_daily_basic_map(self) -> dict[str, ADailyBasic]:
        rows = self.db.scalars(select(ADailyBasic).order_by(desc(ADailyBasic.trade_date))).all()
        latest: dict[str, ADailyBasic] = {}
        for row in rows:
            latest.setdefault(row.ts_code, row)
        return latest

    def _latest_financial_indicator_map(self) -> dict[str, AFinancialIndicator]:
        """按股票读取最新 A 股财务指标，作为分红再投 ROE 的唯一财务口径来源。

        创建日期：2026-06-02
        author: sunshengxian
        """

        rows = self.db.scalars(
            select(AFinancialIndicator).order_by(
                desc(AFinancialIndicator.end_date),
                desc(AFinancialIndicator.id),
            )
        ).all()
        latest: dict[str, AFinancialIndicator] = {}
        for row in rows:
            # 财务指标可能来自通用同步、分红再投补数或 LLM 单股研究链路；倒序去重取最新报告期。
            latest.setdefault(row.ts_code, row)
        return latest

    def _calculate_stock(
        self,
        stock: AStockBasic,
        params: DividendReinvestmentSyncParams,
        run_id: int,
        latest_basic: ADailyBasic | None,
        latest_financial: AFinancialIndicator | None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        quotes = self._stock_quotes(stock.ts_code, params.start_date, params.end_date)
        if not quotes:
            return None, []
        quote_dates = [item.trade_date for item in quotes]
        quote_by_date = {item.trade_date: item for item in quotes}
        start_quote = self._quote_on_or_after(quotes, quote_dates, params.start_date)
        final_quote = self._quote_on_or_before(quotes, quote_dates, params.end_date)
        if start_quote is None or final_quote is None or not start_quote.close:
            return None, []
        holding_shares = params.initial_amount / start_quote.close
        initial_shares = holding_shares
        dividends = self._stock_dividends(stock.ts_code, params.start_date, params.end_date)
        dividends_by_year: dict[int, list[ADividend]] = {}
        for dividend in dividends:
            if dividend.ex_date and dividend.ex_date >= start_quote.trade_date:
                dividends_by_year.setdefault(dividend.ex_date.year, []).append(dividend)

        yearly_rows: list[dict[str, Any]] = []
        total_cash_dividend = Decimal("0")
        total_reinvested_amount = Decimal("0")
        total_reinvested_shares = Decimal("0")
        dividend_years: set[int] = set()
        event_count = 0
        for year in range(start_quote.trade_date.year, final_quote.trade_date.year + 1):
            year_result = self._calculate_year(
                run_id,
                stock.ts_code,
                year,
                holding_shares,
                params,
                dividends_by_year.get(year, []),
                quotes,
                quote_dates,
                quote_by_date,
                start_quote.trade_date,
            )
            holding_shares = year_result["holding_shares"] or holding_shares
            total_cash_dividend += year_result["cash_div_amount"] or Decimal("0")
            total_reinvested_amount += year_result["cash_div_amount"] or Decimal("0")
            total_reinvested_shares += year_result["reinvested_shares"] or Decimal("0")
            event_count += year_result["dividend_event_count"]
            if year_result["dividend_event_count"]:
                dividend_years.add(year)
            yearly_rows.append(year_result)

        final_market_value = holding_shares * final_quote.close
        total_return_amount = final_market_value - params.initial_amount
        total_return_pct = total_return_amount / params.initial_amount * Decimal("100")
        annualized = self._annualized_return(
            params.initial_amount,
            final_market_value,
            start_quote.trade_date,
            final_quote.trade_date,
        )
        ten_year_avg_annualized = self._ten_year_avg_annualized_return(yearly_rows)
        latest_pe = latest_basic.pe if latest_basic else None
        latest_pe_ttm = latest_basic.pe_ttm if latest_basic else None
        latest_roe = latest_financial.roe if latest_financial else None
        data_quality = "COMPLETE" if event_count else "NO_DIVIDEND"
        summary = {
            "run_id": run_id,
            "ts_code": stock.ts_code,
            "symbol": stock.symbol,
            "name": stock.name,
            "industry": stock.industry,
            "list_date": stock.list_date,
            "start_trade_date": start_quote.trade_date,
            "end_trade_date": final_quote.trade_date,
            "initial_amount": quantize_decimal(params.initial_amount, "0.000001"),
            "initial_price": quantize_decimal(start_quote.close, "0.000001"),
            "initial_shares": quantize_decimal(initial_shares),
            "final_price": quantize_decimal(final_quote.close, "0.000001"),
            "final_shares": quantize_decimal(holding_shares),
            "final_market_value": quantize_decimal(final_market_value, "0.000001"),
            "total_cash_dividend": quantize_decimal(total_cash_dividend, "0.000001"),
            "total_reinvested_amount": quantize_decimal(total_reinvested_amount, "0.000001"),
            "total_reinvested_shares": quantize_decimal(total_reinvested_shares),
            "dividend_event_count": event_count,
            "dividend_year_count": len(dividend_years),
            "consecutive_dividend_years": self._consecutive_dividend_years(dividend_years),
            "total_return_amount": quantize_decimal(total_return_amount, "0.000001"),
            "total_return_pct": quantize_decimal(total_return_pct),
            "annualized_return_pct": annualized,
            "ten_year_avg_annualized_return_pct": ten_year_avg_annualized,
            "latest_dividend_yield_ttm": latest_basic.dv_ttm if latest_basic else None,
            "latest_total_mv": latest_basic.total_mv if latest_basic else None,
            "latest_pe": latest_pe,
            "latest_pe_ttm": latest_pe_ttm,
            "latest_pb": latest_basic.pb if latest_basic else None,
            "latest_roe": latest_roe,
            "rank_score": self._rank_score(
                annualized,
                ten_year_avg_annualized,
                len(dividend_years),
                latest_basic,
                latest_pe,
                latest_roe,
            ),
            "data_quality": data_quality,
            "data_issue": None if event_count else "回测期内无有效实施分红",
        }
        return summary, yearly_rows

    def _calculate_year(
        self,
        run_id: int,
        ts_code: str,
        year: int,
        starting_shares: Decimal,
        params: DividendReinvestmentSyncParams,
        dividends: list[ADividend],
        quotes: list[ADailyQuote],
        quote_dates: list[date],
        quote_by_date: dict[date, ADailyQuote],
        start_trade_date: date,
    ) -> dict[str, Any]:
        holding_shares = starting_shares
        cash_div_per_share = Decimal("0")
        cash_div_amount = Decimal("0")
        stock_div_per_share = Decimal("0")
        stock_div_shares = Decimal("0")
        reinvested_shares = Decimal("0")
        reinvest_price_amount = Decimal("0")
        note_parts: list[str] = []
        valid_events = 0
        for dividend in sorted(dividends, key=lambda item: item.ex_date or date.min):
            if not self._is_implemented_dividend(dividend):
                continue
            per_share_cash = getattr(dividend, params.cash_div_field) or Decimal("0")
            per_share_stock = dividend.stk_div or Decimal("0")
            if per_share_cash == 0 and per_share_stock == 0:
                continue
            # 同一除权除息日同时有送转和现金分红时，先按送转增加持股，再用新的持股数计算现金再投入；
            # 这个口径在文档中固定，后续若要改成登记日持股口径，需要新增批次参数区分。
            added_stock = holding_shares * per_share_stock
            holding_shares += added_stock
            stock_div_per_share += per_share_stock
            stock_div_shares += added_stock
            event_cash_amount = holding_shares * per_share_cash
            cash_div_per_share += per_share_cash
            cash_div_amount += event_cash_amount
            reinvest_quote = self._quote_on_or_after(
                quotes,
                quote_dates,
                dividend.ex_date or start_trade_date,
                max_days=MAX_REINVEST_PRICE_LOOKAHEAD_DAYS,
            )
            if reinvest_quote is None or not reinvest_quote.close:
                note_parts.append(f"{dividend.ex_date} 缺少再投入价格")
                continue
            bought_shares = event_cash_amount / reinvest_quote.close
            holding_shares += bought_shares
            reinvested_shares += bought_shares
            reinvest_price_amount += reinvest_quote.close * bought_shares
            valid_events += 1

        year_end_target = min(date(year, 12, 31), params.end_date)
        year_end_quote = self._quote_on_or_before(quotes, quote_dates, year_end_target)
        year_end_price = year_end_quote.close if year_end_quote else None
        market_value = holding_shares * year_end_price if year_end_price else None
        return_amount = market_value - params.initial_amount if market_value else None
        return_pct = (
            return_amount / params.initial_amount * Decimal("100")
            if return_amount is not None
            else None
        )
        reinvest_price_avg = (
            reinvest_price_amount / reinvested_shares if reinvested_shares else None
        )
        annualized = (
            self._annualized_return(
                params.initial_amount,
                market_value,
                start_trade_date,
                year_end_quote.trade_date,
            )
            if market_value is not None and year_end_quote
            else None
        )
        return {
            "run_id": run_id,
            "ts_code": ts_code,
            "year": year,
            "year_end_trade_date": year_end_quote.trade_date if year_end_quote else None,
            "year_end_price": (
                quantize_decimal(year_end_price, "0.000001") if year_end_price else None
            ),
            "cash_div_per_share": quantize_decimal(cash_div_per_share),
            "cash_div_amount": quantize_decimal(cash_div_amount, "0.000001"),
            "stock_div_per_share": quantize_decimal(stock_div_per_share),
            "stock_div_shares": quantize_decimal(stock_div_shares),
            "reinvest_price_avg": quantize_decimal(reinvest_price_avg, "0.000001"),
            "reinvested_shares": quantize_decimal(reinvested_shares),
            "holding_shares": quantize_decimal(holding_shares),
            "market_value": quantize_decimal(market_value, "0.000001") if market_value else None,
            "return_amount": quantize_decimal(return_amount, "0.000001") if return_amount else None,
            "return_pct": quantize_decimal(return_pct) if return_pct else None,
            "annualized_return_pct": annualized,
            "dividend_event_count": valid_events,
            "note": "；".join(note_parts) or None,
        }

    def _stock_quotes(self, ts_code: str, start_date: date, end_date: date) -> list[ADailyQuote]:
        return list(
            self.db.scalars(
                select(ADailyQuote)
                .where(
                    ADailyQuote.ts_code == ts_code,
                    ADailyQuote.trade_date >= start_date,
                    ADailyQuote.trade_date <= end_date,
                    ADailyQuote.close.is_not(None),
                )
                .order_by(ADailyQuote.trade_date)
            ).all()
        )

    def _stock_dividends(self, ts_code: str, start_date: date, end_date: date) -> list[ADividend]:
        return list(
            self.db.scalars(
                select(ADividend)
                .where(
                    ADividend.ts_code == ts_code,
                    ADividend.ex_date >= start_date,
                    ADividend.ex_date <= end_date,
                )
                .order_by(ADividend.ex_date)
            ).all()
        )

    def _quote_on_or_after(
        self,
        quotes: list[ADailyQuote],
        quote_dates: list[date],
        target_date: date,
        max_days: int | None = None,
    ) -> ADailyQuote | None:
        index = bisect_left(quote_dates, target_date)
        if index >= len(quotes):
            return None
        quote = quotes[index]
        if max_days is not None and (quote.trade_date - target_date).days > max_days:
            return None
        return quote

    def _quote_on_or_before(
        self,
        quotes: list[ADailyQuote],
        quote_dates: list[date],
        target_date: date,
    ) -> ADailyQuote | None:
        index = bisect_right(quote_dates, target_date) - 1
        return quotes[index] if index >= 0 else None

    def _is_implemented_dividend(self, dividend: ADividend) -> bool:
        proc = (dividend.div_proc or "").strip()
        return not proc or "实施" in proc

    def _ten_year_avg_annualized_return(
        self, yearly_rows: list[dict[str, Any]]
    ) -> Decimal | None:
        """计算最近最多十个年度明细的平均年化收益率。

        创建日期：2026-06-02
        author: sunshengxian
        """

        annualized_values = [
            row["annualized_return_pct"]
            for row in sorted(yearly_rows, key=lambda item: item["year"], reverse=True)
            if row.get("annualized_return_pct") is not None
        ][:TEN_YEAR_AVG_WINDOW]
        if not annualized_values:
            return None
        # 年度明细中已按“从买入日至当年末”计算平均年化收益率；摘要聚合只做最近十年算术平均，
        # 保证导出年度明细后可以逐行复核，不再引入另一套难以解释的收益口径。
        return quantize_decimal(
            sum(annualized_values, Decimal("0")) / Decimal(len(annualized_values))
        )

    def _rank_score(
        self,
        annualized_return_pct: Decimal | None,
        ten_year_avg_annualized_return_pct: Decimal | None,
        dividend_year_count: int,
        latest_basic: ADailyBasic | None,
        latest_pe: Decimal | None,
        latest_roe: Decimal | None,
    ) -> Decimal | None:
        if annualized_return_pct is None:
            return None
        # 综合分服务默认排序兜底：长期收益是主因子，分红连续性、股息率、ROE 和低 PE 只做温和加分，
        # 避免单一估值或短期收益异常把榜单推向不可解释的结果。
        score = annualized_return_pct + Decimal(dividend_year_count)
        if ten_year_avg_annualized_return_pct is not None:
            score += ten_year_avg_annualized_return_pct * Decimal("0.5")
        if latest_basic and latest_basic.dv_ttm:
            score += latest_basic.dv_ttm
        if latest_roe is not None:
            if latest_roe >= Decimal("15"):
                score += Decimal("8")
            elif latest_roe >= Decimal("10"):
                score += Decimal("4")
        if latest_pe is not None:
            if latest_pe <= Decimal("10"):
                score += Decimal("6")
            elif latest_pe <= Decimal("15"):
                score += Decimal("3")
        return quantize_decimal(score)

    def _annualized_return(
        self,
        initial_amount: Decimal,
        market_value: Decimal,
        start_date: date,
        end_date: date,
    ) -> Decimal | None:
        years = max((end_date - start_date).days / 365.25, 0)
        if years <= 0 or initial_amount <= 0 or market_value <= 0:
            return None
        value = (float(market_value / initial_amount) ** (1 / years) - 1) * 100
        return quantize_decimal(Decimal(str(value)))

    def _consecutive_dividend_years(self, dividend_years: set[int]) -> int:
        """按最近一个实际分红年份向前统计连续年数。

        创建日期：2026-05-30
        author: sunshengxian
        """

        if not dividend_years:
            return 0
        count = 0
        # 当前年度可能还没除权除息，不能因为 2026 这类未完整年度无分红就把连续年数打成 0；
        # 因此从最近一个实际发生分红的年份开始倒推，遇到第一个缺口即停止。
        for year in range(max(dividend_years), min(dividend_years) - 1, -1):
            if year not in dividend_years:
                break
            count += 1
        return count

    def _open_trade_dates(self, start_date: date, end_date: date) -> list[date]:
        return list(
            self.db.scalars(
                select(ATradeCalendar.cal_date)
                .where(
                    ATradeCalendar.exchange == "SSE",
                    ATradeCalendar.is_open == 1,
                    ATradeCalendar.cal_date >= start_date,
                    ATradeCalendar.cal_date <= end_date,
                )
                .order_by(ATradeCalendar.cal_date)
            ).all()
        )

    def _iter_dates(self, start_date: date, end_date: date) -> list[date]:
        if start_date > end_date:
            return []
        return [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        ]

    def _checkpoint_next_date(self, scope_key: str, fallback: date) -> date:
        checkpoint = self.db.get(
            SyncCheckpoint,
            {"dataset": DIVIDEND_REINVESTMENT_DATASET, "scope_key": scope_key},
        )
        if checkpoint and checkpoint.last_success_date:
            return checkpoint.last_success_date + timedelta(days=1)
        return fallback

    def _update_checkpoint(self, scope_key: str, stage: str, success_date: date) -> None:
        checkpoint = self.db.get(
            SyncCheckpoint,
            {"dataset": DIVIDEND_REINVESTMENT_DATASET, "scope_key": scope_key},
        )
        if checkpoint is None:
            checkpoint = SyncCheckpoint(
                dataset=DIVIDEND_REINVESTMENT_DATASET,
                scope_key=scope_key,
            )
            self.db.add(checkpoint)
        checkpoint.last_success_date = success_date
        checkpoint.last_run_id = None
        # checkpoint 只保存日期，阶段名通过 scope_key 区分，确保重跑时按阶段续跑。
        _ = stage

    def _normalize_stock_basic_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["list_date"] = parse_tushare_date(normalized.get("list_date"))
        normalized["delist_date"] = parse_tushare_date(normalized.get("delist_date"))
        return self._model_row(AStockBasic, normalized)

    def _normalize_trade_calendar_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["cal_date"] = parse_tushare_date(normalized.get("cal_date"))
        normalized["pretrade_date"] = parse_tushare_date(normalized.get("pretrade_date"))
        normalized.setdefault("exchange", "SSE")
        return self._model_row(ATradeCalendar, normalized)

    def _normalize_daily_quote_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["trade_date"] = parse_tushare_date(normalized.get("trade_date"))
        normalized["change_amount"] = normalized.pop("change", None)
        for field in (
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change_amount",
            "pct_chg",
            "vol",
            "amount",
        ):
            normalized[field] = to_decimal(normalized.get(field))
        return self._model_row(ADailyQuote, normalized)

    def _normalize_dividend_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        normalized = dict(row)
        for field in ("end_date", "ann_date", "record_date", "ex_date", "pay_date"):
            normalized[field] = parse_tushare_date(normalized.get(field))
        if (
            normalized.get("ex_date") is None
            or normalized.get("end_date") is None
            or normalized.get("ann_date") is None
        ):
            return None
        for field in ("stk_div", "cash_div", "cash_div_tax"):
            normalized[field] = to_decimal(normalized.get(field))
        return self._model_row(ADividend, normalized)

    def _normalize_daily_basic_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["trade_date"] = parse_tushare_date(normalized.get("trade_date"))
        for field in (
            "close",
            "turnover_rate",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ps_ttm",
            "dv_ratio",
            "dv_ttm",
            "total_share",
            "float_share",
            "free_share",
            "total_mv",
            "circ_mv",
        ):
            normalized[field] = to_decimal(normalized.get(field))
        return self._model_row(ADailyBasic, normalized)

    def _normalize_financial_indicator_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """标准化 A 股财务指标行，过滤缺少报告期的异常返回。

        创建日期：2026-06-02
        author: sunshengxian
        """

        normalized = dict(row)
        normalized["ann_date"] = parse_tushare_date(normalized.get("ann_date"))
        normalized["end_date"] = parse_tushare_date(normalized.get("end_date"))
        if normalized.get("end_date") is None:
            return None
        for field in (
            "eps",
            "dt_eps",
            "roe",
            "roe_waa",
            "roe_dt",
            "roa",
            "grossprofit_margin",
            "netprofit_margin",
            "sales_gpr",
            "profit_to_gr",
            "debt_to_assets",
            "current_ratio",
            "quick_ratio",
            "assets_to_eqt",
            "or_yoy",
            "q_sales_yoy",
            "netprofit_yoy",
            "q_netprofit_yoy",
            "ocf_to_revenue",
            "ocfps",
            "roe_yoy",
            "bps",
            "profit_dedt",
        ):
            normalized[field] = to_decimal(normalized.get(field))
        return self._model_row(AFinancialIndicator, normalized)

    def _model_row(self, model: type, row: dict[str, Any]) -> dict[str, Any]:
        columns = set(model.__table__.columns.keys())
        # 批量 upsert 要求同一批行的字段集合稳定；这里保留 None 值，让 SQLAlchemy
        # 显式写入 NULL，避免某些股票缺少地区/行业等可空字段时导致批量插入失败。
        return {key: value for key, value in row.items() if key in columns}

    def _upsert_many_chunked(
        self,
        model: type,
        rows: list[dict[str, Any]],
        chunk_size: int = RESULT_UPSERT_CHUNK_SIZE,
    ) -> int:
        """分块写入大批量回测结果，避免单条 SQL 过大导致 MySQL 断连。

        创建日期：2026-05-30
        author: sunshengxian
        """

        total = 0
        for start in range(0, len(rows), chunk_size):
            # 每个分块仍走幂等 upsert；失败时外层事务整体回滚，重跑不会产生重复结果。
            total += self.repository.upsert_many(model, rows[start : start + chunk_size])
        return total

    def _coerce_date(self, value: date | str | None) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        return parse_tushare_date(str(value).replace("-", ""))

    def _coerce_bool(self, value: Any) -> bool:
        """解析同步参数中的布尔开关，兼容前端表单和脚本传入的字符串值。

        创建日期：2026-05-30
        author: sunshengxian
        """

        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def health_snapshot(self) -> dict[str, Any]:
        """返回红利再投数据落地健康快照，供 API 和测试验收复用。

        创建日期：2026-05-29
        author: sunshengxian
        """

        return {
            "stock_count": self.db.scalar(select(func.count()).select_from(AStockBasic)) or 0,
            "daily_quote": self._range_count(ADailyQuote.trade_date, ADailyQuote),
            "dividend": self._range_count(ADividend.ex_date, ADividend),
            "daily_basic": self._range_count(ADailyBasic.trade_date, ADailyBasic),
            "latest_success_run_id": self.db.scalar(
                select(func.max(DividendReinvestmentBacktestRun.id)).where(
                    DividendReinvestmentBacktestRun.status == "SUCCESS"
                )
            ),
        }

    def _range_count(self, column: Any, model: type) -> dict[str, Any]:
        row = self.db.execute(
            select(func.count(), func.min(column), func.max(column)).select_from(model)
        ).one()
        return {
            "row_count": row[0] or 0,
            "min_date": row[1].isoformat() if row[1] else None,
            "max_date": row[2].isoformat() if row[2] else None,
        }

    def sync_result_payload(self, result: DividendReinvestmentSyncResult) -> str:
        """生成同步运行记录中的阶段结果摘要。

        创建日期：2026-05-29
        author: sunshengxian
        """

        return json.dumps(
            {
                "stock_rows": result.stock_rows,
                "calendar_rows": result.calendar_rows,
                "daily_rows": result.daily_rows,
                "dividend_rows": result.dividend_rows,
                "stock_dividend_rows": result.stock_dividend_rows,
                "daily_basic_rows": result.daily_basic_rows,
                "financial_indicator_rows": result.financial_indicator_rows,
                "summary_rows": result.summary_rows,
                "yearly_rows": result.yearly_rows,
            },
            ensure_ascii=False,
        )

    def latest_success_run(self) -> DividendReinvestmentBacktestRun | None:
        """读取最近一次成功回测批次。

        创建日期：2026-05-30
        author: sunshengxian
        """

        return self.db.scalars(
            select(DividendReinvestmentBacktestRun)
            .where(DividendReinvestmentBacktestRun.status == "SUCCESS")
            .order_by(desc(DividendReinvestmentBacktestRun.id))
            .limit(1)
        ).first()

    def list_backtest_runs(self, limit: int = 20) -> list[DividendReinvestmentBacktestRun]:
        """按时间倒序列出成功的分红再投入回测批次。

        创建日期：2026-05-30
        author: sunshengxian
        """

        return list(
            self.db.scalars(
                select(DividendReinvestmentBacktestRun)
                .where(DividendReinvestmentBacktestRun.status == "SUCCESS")
                .order_by(desc(DividendReinvestmentBacktestRun.id))
                .limit(limit)
            ).all()
        )

    def query_summaries(
        self,
        run_id: int | None,
        keyword: str | None,
        industry: str | None,
        data_quality: str | None,
        min_annualized_return_pct: Decimal | None,
        min_ten_year_avg_annualized_return_pct: Decimal | None,
        min_dividend_year_count: int | None,
        min_consecutive_dividend_years: int | None,
        min_latest_dividend_yield_ttm: Decimal | None,
        max_latest_pb: Decimal | None,
        max_latest_pe: Decimal | None,
        max_latest_pe_ttm: Decimal | None,
        min_latest_roe: Decimal | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> tuple[int | None, int, list[DividendReinvestmentBacktestSummary]]:
        """查询股票级分红再投入筛选结果。

        创建日期：2026-05-30
        author: sunshengxian
        """

        target_run_id = run_id
        if target_run_id is None:
            latest_run = self.latest_success_run()
            target_run_id = latest_run.id if latest_run else None
        if target_run_id is None:
            return None, 0, []

        filters = [DividendReinvestmentBacktestSummary.run_id == target_run_id]
        clean_keyword = (keyword or "").strip()
        if clean_keyword:
            pattern = f"%{clean_keyword}%"
            filters.append(
                or_(
                    DividendReinvestmentBacktestSummary.ts_code.like(pattern),
                    DividendReinvestmentBacktestSummary.symbol.like(pattern),
                    DividendReinvestmentBacktestSummary.name.like(pattern),
                    DividendReinvestmentBacktestSummary.industry.like(pattern),
                )
            )
        if industry:
            filters.append(DividendReinvestmentBacktestSummary.industry == industry)
        if data_quality:
            filters.append(DividendReinvestmentBacktestSummary.data_quality == data_quality)
        if min_annualized_return_pct is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.annualized_return_pct
                >= min_annualized_return_pct
            )
        if min_ten_year_avg_annualized_return_pct is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.ten_year_avg_annualized_return_pct
                >= min_ten_year_avg_annualized_return_pct
            )
        if min_dividend_year_count is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.dividend_year_count
                >= min_dividend_year_count
            )
        if min_consecutive_dividend_years is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.consecutive_dividend_years
                >= min_consecutive_dividend_years
            )
        if min_latest_dividend_yield_ttm is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.latest_dividend_yield_ttm
                >= min_latest_dividend_yield_ttm
            )
        if max_latest_pb is not None:
            # PB 与 PE 一样属于低估值上限筛选，使用“最高值”避免把市净率越高误判为越符合条件。
            filters.append(DividendReinvestmentBacktestSummary.latest_pb <= max_latest_pb)
        if max_latest_pe is not None:
            filters.append(DividendReinvestmentBacktestSummary.latest_pe <= max_latest_pe)
        if max_latest_pe_ttm is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.latest_pe_ttm <= max_latest_pe_ttm
            )
        if min_latest_roe is not None:
            filters.append(DividendReinvestmentBacktestSummary.latest_roe >= min_latest_roe)
        sort_columns = {
            "annualized_return_pct": DividendReinvestmentBacktestSummary.annualized_return_pct,
            "ten_year_avg_annualized_return_pct": (
                DividendReinvestmentBacktestSummary.ten_year_avg_annualized_return_pct
            ),
            "total_return_pct": DividendReinvestmentBacktestSummary.total_return_pct,
            "total_cash_dividend": DividendReinvestmentBacktestSummary.total_cash_dividend,
            "latest_dividend_yield_ttm": (
                DividendReinvestmentBacktestSummary.latest_dividend_yield_ttm
            ),
            "latest_pb": DividendReinvestmentBacktestSummary.latest_pb,
            "latest_pe": DividendReinvestmentBacktestSummary.latest_pe,
            "latest_pe_ttm": DividendReinvestmentBacktestSummary.latest_pe_ttm,
            "latest_roe": DividendReinvestmentBacktestSummary.latest_roe,
        }
        # 前端默认关注累计分红，非法排序字段兜底回累计分红，避免旧链接或手写参数回到过时口径。
        sort_column = sort_columns.get(sort_by) or sort_columns["total_cash_dividend"]
        sort_direction = asc if sort_order == "asc" else desc

        total = self.db.scalar(
            select(func.count()).select_from(DividendReinvestmentBacktestSummary).where(*filters)
        ) or 0
        rows = list(
            self.db.scalars(
                select(DividendReinvestmentBacktestSummary)
                .where(*filters)
                .order_by(
                    # 可空指标先按“是否为空”升序排序，保证 PE、ROE 等补数不足字段在升序和降序下都稳定置底；
                    # 再按用户选择的指标方向、综合分和股票代码排序，避免分页时同值或空值记录跨页跳动。
                    asc(sort_column.is_(None)),
                    # 榜单排序只开放收益指标，避免前端传入任意字段造成不可控 SQL 排序。
                    sort_direction(sort_column),
                    asc(DividendReinvestmentBacktestSummary.rank_score.is_(None)),
                    desc(DividendReinvestmentBacktestSummary.rank_score),
                    DividendReinvestmentBacktestSummary.ts_code,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return target_run_id, total, rows

    def export_summaries_xlsx(
        self,
        run_id: int | None,
        keyword: str | None,
        industry: str | None,
        data_quality: str | None,
        min_annualized_return_pct: Decimal | None,
        min_ten_year_avg_annualized_return_pct: Decimal | None,
        min_dividend_year_count: int | None,
        min_consecutive_dividend_years: int | None,
        min_latest_dividend_yield_ttm: Decimal | None,
        max_latest_pb: Decimal | None,
        max_latest_pe: Decimal | None,
        max_latest_pe_ttm: Decimal | None,
        min_latest_roe: Decimal | None,
        sort_by: str,
        sort_order: str,
    ) -> tuple[int | None, bytes]:
        """导出筛选结果和年度明细 Excel。

        创建日期：2026-06-02
        author: sunshengxian
        """

        target_run_id, _total, summaries = self.query_summaries(
            run_id=run_id,
            keyword=keyword,
            industry=industry,
            data_quality=data_quality,
            min_annualized_return_pct=min_annualized_return_pct,
            min_ten_year_avg_annualized_return_pct=min_ten_year_avg_annualized_return_pct,
            min_dividend_year_count=min_dividend_year_count,
            min_consecutive_dividend_years=min_consecutive_dividend_years,
            min_latest_dividend_yield_ttm=min_latest_dividend_yield_ttm,
            max_latest_pb=max_latest_pb,
            max_latest_pe=max_latest_pe,
            max_latest_pe_ttm=max_latest_pe_ttm,
            min_latest_roe=min_latest_roe,
            sort_by=sort_by,
            sort_order=sort_order,
            page=1,
            page_size=1_000_000,
        )
        summary_rows = [
            [self._export_value(summary, key) for key, _label in SUMMARY_EXPORT_COLUMNS]
            for summary in summaries
        ]
        yearly_rows = self._export_yearly_rows(target_run_id, summaries)
        workbook = self._build_xlsx(
            sheets=[
                (
                    "筛选结果",
                    [label for _key, label in SUMMARY_EXPORT_COLUMNS],
                    summary_rows,
                ),
                (
                    "年度明细",
                    [label for _key, label in YEARLY_EXPORT_COLUMNS],
                    yearly_rows,
                ),
            ]
        )
        return target_run_id, workbook

    def _export_yearly_rows(
        self,
        run_id: int | None,
        summaries: list[DividendReinvestmentBacktestSummary],
    ) -> list[list[Any]]:
        """按榜单顺序拼接年度明细，确保同一股票的导出行天然聚在一起。

        创建日期：2026-06-02
        author: sunshengxian
        """

        if run_id is None or not summaries:
            return []
        summary_by_code = {summary.ts_code: summary for summary in summaries}
        order_by_code = {summary.ts_code: index for index, summary in enumerate(summaries)}
        yearly_rows = list(
            self.db.scalars(
                select(DividendReinvestmentBacktestYearly).where(
                    DividendReinvestmentBacktestYearly.run_id == run_id,
                    DividendReinvestmentBacktestYearly.ts_code.in_(order_by_code),
                )
            ).all()
        )
        yearly_rows.sort(key=lambda row: (order_by_code[row.ts_code], row.year))
        export_rows: list[list[Any]] = []
        for yearly in yearly_rows:
            summary = summary_by_code[yearly.ts_code]
            row_context = {
                "ts_code": yearly.ts_code,
                "name": summary.name,
                "industry": summary.industry,
                **yearly.__dict__,
            }
            export_rows.append(
                [self._export_value(row_context, key) for key, _label in YEARLY_EXPORT_COLUMNS]
            )
        return export_rows

    def _export_value(self, source: Any, key: str) -> Any:
        """统一读取 ORM 或字典字段，屏蔽 SQLAlchemy 内部状态对导出的干扰。

        创建日期：2026-06-02
        author: sunshengxian
        """

        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def _build_xlsx(self, sheets: list[tuple[str, list[str], list[list[Any]]]]) -> bytes:
        """使用标准库生成最小 XLSX，避免为筛选导出额外引入运行时依赖。

        创建日期：2026-06-02
        author: sunshengxian
        """

        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                self._xlsx_content_types(len(sheets)),
            )
            archive.writestr("_rels/.rels", self._xlsx_root_rels())
            archive.writestr("xl/workbook.xml", self._xlsx_workbook(sheets))
            archive.writestr("xl/_rels/workbook.xml.rels", self._xlsx_workbook_rels(len(sheets)))
            for index, (sheet_name, headers, rows) in enumerate(sheets, start=1):
                archive.writestr(
                    f"xl/worksheets/sheet{index}.xml",
                    self._xlsx_sheet(sheet_name, headers, rows),
                )
        return buffer.getvalue()

    def _xlsx_content_types(self, sheet_count: int) -> str:
        worksheet_overrides = "".join(
            (
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            for index in range(1, sheet_count + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f"{worksheet_overrides}</Types>"
        )

    def _xlsx_root_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    def _xlsx_workbook(self, sheets: list[tuple[str, list[str], list[list[Any]]]]) -> str:
        sheet_nodes = "".join(
            (
                f'<sheet name="{escape(sheet_name)}" sheetId="{index}" '
                f'r:id="rId{index}"/>'
            )
            for index, (sheet_name, _headers, _rows) in enumerate(sheets, start=1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_nodes}</sheets></workbook>"
        )

    def _xlsx_workbook_rels(self, sheet_count: int) -> str:
        rel_nodes = "".join(
            (
                f'<Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
            )
            for index in range(1, sheet_count + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rel_nodes}</Relationships>"
        )

    def _xlsx_sheet(self, _sheet_name: str, headers: list[str], rows: list[list[Any]]) -> str:
        all_rows = [headers, *rows]
        row_nodes = []
        for row_index, row in enumerate(all_rows, start=1):
            cells = "".join(
                self._xlsx_cell(self._xlsx_column_name(column_index), row_index, value)
                for column_index, value in enumerate(row, start=1)
            )
            row_nodes.append(f'<row r="{row_index}">{cells}</row>')
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(row_nodes)}</sheetData></worksheet>"
        )

    def _xlsx_cell(self, column_name: str, row_index: int, value: Any) -> str:
        cell_ref = f"{column_name}{row_index}"
        if value is None:
            return f'<c r="{cell_ref}"/>'
        if isinstance(value, Decimal):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        if isinstance(value, int | float) and not isinstance(value, bool):
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        if isinstance(value, date | datetime):
            value = value.isoformat()
        text = escape(str(value), {'"': "&quot;"})
        return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    def _xlsx_column_name(self, index: int) -> str:
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    def yearly_rows(
        self,
        run_id: int | None,
        ts_code: str,
    ) -> list[DividendReinvestmentBacktestYearly]:
        """读取单股年度分红再投入明细。

        创建日期：2026-05-30
        author: sunshengxian
        """

        target_run_id = run_id
        if target_run_id is None:
            latest_run = self.latest_success_run()
            target_run_id = latest_run.id if latest_run else None
        if target_run_id is None:
            return []
        return list(
            self.db.scalars(
                select(DividendReinvestmentBacktestYearly)
                .where(
                    DividendReinvestmentBacktestYearly.run_id == target_run_id,
                    DividendReinvestmentBacktestYearly.ts_code == ts_code,
                )
                .order_by(DividendReinvestmentBacktestYearly.year)
            ).all()
        )
