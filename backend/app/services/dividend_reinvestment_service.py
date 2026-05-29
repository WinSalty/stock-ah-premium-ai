from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.market import (
    ADailyBasic,
    ADailyQuote,
    ADividend,
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
    daily_basic_rows: int
    summary_rows: int
    yearly_rows: int

    @property
    def total_rows(self) -> int:
        return (
            self.stock_rows
            + self.calendar_rows
            + self.daily_rows
            + self.dividend_rows
            + self.daily_basic_rows
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
        # 阶段顺序固定为“基础资料、交易日历、日线、分红、最新指标、回测计算”，
        # 这样失败时可通过各阶段 checkpoint 定位缺口，计算阶段也不会再访问外部接口。
        stock_rows = self._sync_stock_basic()
        calendar_rows = self._sync_trade_calendar(normalized.start_date, normalized.end_date)
        daily_rows = self._sync_daily_quotes(normalized)
        dividend_rows = self._sync_dividends(normalized)
        daily_basic_rows = self._sync_latest_daily_basic(normalized.end_date)
        summary_rows, yearly_rows = self.calculate_backtest(normalized)
        return DividendReinvestmentSyncResult(
            stock_rows=stock_rows,
            calendar_rows=calendar_rows,
            daily_rows=daily_rows,
            dividend_rows=dividend_rows,
            daily_basic_rows=daily_basic_rows,
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
            summary_rows: list[dict[str, Any]] = []
            yearly_rows: list[dict[str, Any]] = []
            for stock in stocks:
                # 每只股票独立读取日线和分红，避免一次性把千万级日线全部装入内存。
                summary, yearly = self._calculate_stock(
                    stock,
                    params,
                    run.id,
                    latest_basic.get(stock.ts_code),
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
        if cash_div_field not in {"cash_div_tax", "cash_div"}:
            raise ValueError("现金分红口径仅支持 cash_div_tax 或 cash_div")
        return DividendReinvestmentSyncParams(
            mode=mode,
            start_date=start_date,
            end_date=requested_end,
            initial_amount=initial_amount,
            cash_div_field=cash_div_field,
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

    def _calculate_stock(
        self,
        stock: AStockBasic,
        params: DividendReinvestmentSyncParams,
        run_id: int,
        latest_basic: ADailyBasic | None,
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
            "consecutive_dividend_years": self._consecutive_dividend_years(
                dividend_years,
                final_quote.trade_date.year,
            ),
            "total_return_amount": quantize_decimal(total_return_amount, "0.000001"),
            "total_return_pct": quantize_decimal(total_return_pct),
            "annualized_return_pct": annualized,
            "latest_dividend_yield_ttm": latest_basic.dv_ttm if latest_basic else None,
            "latest_total_mv": latest_basic.total_mv if latest_basic else None,
            "latest_pe_ttm": latest_basic.pe_ttm if latest_basic else None,
            "latest_pb": latest_basic.pb if latest_basic else None,
            "rank_score": self._rank_score(annualized, len(dividend_years), latest_basic),
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

    def _rank_score(
        self,
        annualized_return_pct: Decimal | None,
        dividend_year_count: int,
        latest_basic: ADailyBasic | None,
    ) -> Decimal | None:
        if annualized_return_pct is None:
            return None
        score = annualized_return_pct + Decimal(dividend_year_count)
        if latest_basic and latest_basic.dv_ttm:
            score += latest_basic.dv_ttm
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

    def _consecutive_dividend_years(self, dividend_years: set[int], final_year: int) -> int:
        count = 0
        for year in range(final_year, min(dividend_years or {final_year}) - 1, -1):
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
                "daily_basic_rows": result.daily_basic_rows,
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
        """按时间倒序列出分红再投入回测批次。

        创建日期：2026-05-30
        author: sunshengxian
        """

        return list(
            self.db.scalars(
                select(DividendReinvestmentBacktestRun)
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
        min_dividend_year_count: int | None,
        min_consecutive_dividend_years: int | None,
        min_latest_dividend_yield_ttm: Decimal | None,
        max_latest_pe_ttm: Decimal | None,
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
        if max_latest_pe_ttm is not None:
            filters.append(
                DividendReinvestmentBacktestSummary.latest_pe_ttm <= max_latest_pe_ttm
            )

        total = self.db.scalar(
            select(func.count()).select_from(DividendReinvestmentBacktestSummary).where(*filters)
        ) or 0
        rows = list(
            self.db.scalars(
                select(DividendReinvestmentBacktestSummary)
                .where(*filters)
                .order_by(
                    desc(DividendReinvestmentBacktestSummary.rank_score),
                    desc(DividendReinvestmentBacktestSummary.annualized_return_pct),
                    DividendReinvestmentBacktestSummary.ts_code,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return target_run_id, total, rows

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
