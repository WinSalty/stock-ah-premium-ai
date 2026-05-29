from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    DividendReinvestmentBacktestSummary,
    DividendReinvestmentBacktestYearly,
)
from app.services.dividend_reinvestment_service import DividendReinvestmentDataLandingService
from app.services.tushare_client import TushareResult


@dataclass
class FakeTushareClient:
    """分红再投入测试用 Tushare 客户端替身。

    创建日期：2026-05-29
    author: sunshengxian
    """

    calls: list[tuple[str, dict[str, Any]]]

    def query(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: list[str] | None = None,
    ) -> TushareResult:
        """按接口名返回最小可计算样本，覆盖股票、日线、分红和估值四类数据。

        创建日期：2026-05-29
        author: sunshengxian
        """

        clean_params = params or {}
        self.calls.append((api_name, clean_params))
        rows_by_api = {
            "stock_basic": [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "industry": "银行",
                    "list_status": "L",
                    "list_date": "19910403",
                }
            ],
            "trade_cal": [
                {
                    "exchange": "SSE",
                    "cal_date": "20260102",
                    "is_open": 1,
                    "pretrade_date": "20251231",
                },
                {
                    "exchange": "SSE",
                    "cal_date": "20260105",
                    "is_open": 1,
                    "pretrade_date": "20260102",
                },
            ],
        }
        if api_name in rows_by_api:
            return TushareResult(fields=fields or [], rows=rows_by_api[api_name])
        if api_name == "daily":
            return TushareResult(
                fields=fields or [],
                rows=self._daily_rows(clean_params.get("trade_date")),
            )
        if api_name == "dividend":
            return TushareResult(
                fields=fields or [],
                rows=self._dividend_rows(clean_params.get("ex_date")),
            )
        if api_name == "daily_basic":
            return TushareResult(
                fields=fields or [],
                rows=self._daily_basic_rows(clean_params.get("trade_date")),
            )
        return TushareResult(fields=fields or [], rows=[])

    def _daily_rows(self, trade_date: str | None) -> list[dict[str, Any]]:
        """只在测试交易日返回行情，确保日线按交易日拆分请求。

        创建日期：2026-05-29
        author: sunshengxian
        """

        prices = {"20260102": Decimal("10"), "20260105": Decimal("12")}
        if trade_date not in prices:
            return []
        close = prices[trade_date]
        return [
            {
                "ts_code": "000001.SZ",
                "trade_date": trade_date,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "pre_close": close,
                "change": Decimal("0"),
                "pct_chg": Decimal("0"),
                "vol": Decimal("1"),
                "amount": Decimal("1"),
            }
        ]

    def _dividend_rows(self, ex_date: str | None) -> list[dict[str, Any]]:
        """只在一个除权除息日返回现金分红，便于精确断言再投入结果。

        创建日期：2026-05-29
        author: sunshengxian
        """

        if ex_date != "20260103":
            return []
        return [
            {
                "ts_code": "000001.SZ",
                "end_date": "20251231",
                "ann_date": "20251230",
                "div_proc": "实施",
                "stk_div": Decimal("0"),
                "cash_div": Decimal("1"),
                "cash_div_tax": Decimal("1"),
                "record_date": "20260102",
                "ex_date": "20260103",
                "pay_date": "20260103",
            }
        ]

    def _daily_basic_rows(self, trade_date: str | None) -> list[dict[str, Any]]:
        """最新估值指标只在最后一个交易日返回，验证服务会向前回看可用数据。

        创建日期：2026-05-29
        author: sunshengxian
        """

        if trade_date != "20260105":
            return []
        return [
            {
                "ts_code": "000001.SZ",
                "trade_date": trade_date,
                "close": Decimal("12"),
                "pe_ttm": Decimal("8"),
                "pb": Decimal("1"),
                "dv_ttm": Decimal("5"),
                "total_mv": Decimal("1000000"),
            }
        ]


class SqliteUpsertRepository:
    """SQLite 测试仓库，用 add_all 替代 MySQL 专用 upsert。

    创建日期：2026-05-29
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_many(self, model: type, rows: list[dict[str, Any]]) -> int:
        """测试样本无重复主键，直接插入即可覆盖服务编排和计算逻辑。

        创建日期：2026-05-29
        author: sunshengxian
        """

        self.db.add_all(model(**row) for row in rows)
        return len(rows)


def test_dividend_reinvestment_sync_lands_data_and_calculates_backtest() -> None:
    """确认分红再投入同步会落基础数据并生成股票级和年度回测结果。

    创建日期：2026-05-29
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        client = FakeTushareClient(calls=[])
        service = DividendReinvestmentDataLandingService(
            db,
            client=client,
            repository=SqliteUpsertRepository(db),
        )

        result = service.sync(
            {
                "mode": "full",
                "start_date": date(2026, 1, 2),
                "end_date": date(2026, 1, 5),
                "initial_amount": Decimal("100000"),
                "cash_div_field": "cash_div_tax",
            }
        )
        summary = db.scalars(select(DividendReinvestmentBacktestSummary)).one()
        yearly = db.scalars(select(DividendReinvestmentBacktestYearly)).one()

    assert result.stock_rows == 1
    assert result.daily_rows == 2
    assert result.dividend_rows == 1
    assert result.summary_rows == 1
    assert summary.ts_code == "000001.SZ"
    assert summary.dividend_event_count == 1
    assert summary.total_cash_dividend == Decimal("10000.000000")
    assert summary.final_market_value == Decimal("130000.000000")
    assert summary.total_return_pct == Decimal("30.00000000")
    assert yearly.year == 2026
    assert yearly.reinvested_shares == Decimal("833.33333333")
    assert ("daily", {"trade_date": "20260102"}) in client.calls
    assert ("daily", {"trade_date": "20260105"}) in client.calls
