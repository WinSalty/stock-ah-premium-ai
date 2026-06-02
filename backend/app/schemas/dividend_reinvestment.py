from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.schemas.common import OrmModel


class DataRangeHealth(OrmModel):
    """分红再投入原始数据覆盖范围。

    创建日期：2026-05-30
    author: sunshengxian
    """

    row_count: int
    min_date: str | None
    max_date: str | None


class DividendReinvestmentHealthResponse(OrmModel):
    """分红再投入数据健康概览响应。

    创建日期：2026-05-30
    author: sunshengxian
    """

    stock_count: int
    daily_quote: DataRangeHealth
    dividend: DataRangeHealth
    daily_basic: DataRangeHealth
    latest_success_run_id: int | None


class DividendReinvestmentRunResponse(OrmModel):
    """分红再投入回测批次响应。

    创建日期：2026-05-30
    author: sunshengxian
    """

    id: int
    run_key: str
    start_date: date
    end_date: date
    initial_amount: Decimal
    cash_div_field: str
    status: str
    stock_count: int
    summary_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class DividendReinvestmentSummaryItem(OrmModel):
    """分红再投入股票级筛选条目。

    创建日期：2026-05-30
    author: sunshengxian
    """

    run_id: int
    ts_code: str
    symbol: str | None
    name: str
    industry: str | None
    list_date: date | None
    start_trade_date: date | None
    end_trade_date: date | None
    initial_amount: Decimal
    initial_price: Decimal | None
    initial_shares: Decimal | None
    final_price: Decimal | None
    final_shares: Decimal | None
    final_market_value: Decimal | None
    total_cash_dividend: Decimal | None
    total_reinvested_amount: Decimal | None
    total_reinvested_shares: Decimal | None
    dividend_event_count: int
    dividend_year_count: int
    consecutive_dividend_years: int
    total_return_amount: Decimal | None
    total_return_pct: Decimal | None
    annualized_return_pct: Decimal | None
    ten_year_avg_annualized_return_pct: Decimal | None
    latest_dividend_yield_ttm: Decimal | None
    latest_total_mv: Decimal | None
    latest_pe: Decimal | None
    latest_pe_ttm: Decimal | None
    latest_pb: Decimal | None
    latest_roe: Decimal | None
    rank_score: Decimal | None
    data_quality: str
    data_issue: str | None


class DividendReinvestmentSummaryResponse(OrmModel):
    """分红再投入筛选列表响应。

    创建日期：2026-05-30
    author: sunshengxian
    """

    run_id: int | None
    total: int
    page: int
    page_size: int
    items: list[DividendReinvestmentSummaryItem]


class DividendReinvestmentYearlyItem(OrmModel):
    """分红再投入年度明细响应。

    创建日期：2026-05-30
    author: sunshengxian
    """

    run_id: int
    ts_code: str
    year: int
    year_end_trade_date: date | None
    year_end_price: Decimal | None
    cash_div_per_share: Decimal | None
    cash_div_amount: Decimal | None
    stock_div_per_share: Decimal | None
    stock_div_shares: Decimal | None
    reinvest_price_avg: Decimal | None
    reinvested_shares: Decimal | None
    holding_shares: Decimal | None
    market_value: Decimal | None
    return_amount: Decimal | None
    return_pct: Decimal | None
    annualized_return_pct: Decimal | None
    dividend_event_count: int
    note: str | None
