from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    DividendReinvestmentBacktestRun,
    DividendReinvestmentBacktestSummary,
    DividendReinvestmentBacktestYearly,
)
from app.db.models.sync import SyncCheckpoint
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
                    "area": None,
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

        if ex_date != "20260105":
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
                "ex_date": "20260105",
                "pay_date": "20260105",
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


class RecordingRepository:
    """记录分块写入批次的测试仓储。

    创建日期：2026-05-30
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def upsert_many(self, model: type, rows: list[dict[str, Any]]) -> int:
        """只记录每次写入行数，用于验证大结果集会被拆分提交。

        创建日期：2026-05-30
        author: sunshengxian
        """

        self.batch_sizes.append(len(rows))
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
    assert ("dividend", {"ex_date": "20260105"}) in client.calls
    assert ("dividend", {"ex_date": "20260103"}) not in client.calls


def test_model_row_keeps_null_values_for_bulk_upsert() -> None:
    """确认可空字段不会被过滤，避免 MySQL 批量 upsert 字段集合不一致。

    创建日期：2026-05-29
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = DividendReinvestmentDataLandingService(
            db,
            client=FakeTushareClient(calls=[]),
            repository=SqliteUpsertRepository(db),
        )
        row = service._normalize_stock_basic_row(
            {
                "ts_code": "000001.SZ",
                "symbol": "000001",
                "name": "平安银行",
                "area": None,
                "industry": "银行",
                "list_status": "L",
                "list_date": "19910403",
            }
        )

    assert "area" in row
    assert row["area"] is None


def test_incremental_params_keep_backtest_start_when_daily_checkpoint_exists() -> None:
    """确认增量断点只影响数据同步阶段，不改变分红再投入回测起点。

    创建日期：2026-05-30
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            SyncCheckpoint(
                dataset="dividend_reinvestment_data_landing",
                scope_key="daily",
                last_success_date=date(2026, 5, 29),
            )
        )
        db.commit()
        service = DividendReinvestmentDataLandingService(
            db,
            client=FakeTushareClient(calls=[]),
            repository=SqliteUpsertRepository(db),
        )

        params = service._normalize_params({"mode": "incremental"})

    assert params.start_date == date(2016, 1, 1)


def test_upsert_many_chunked_splits_large_backtest_result() -> None:
    """确认回测结果按固定大小分块写入，避免真实 MySQL 大 SQL 断连。

    创建日期：2026-05-30
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = RecordingRepository()
    with Session(engine) as db:
        service = DividendReinvestmentDataLandingService(
            db,
            client=FakeTushareClient(calls=[]),
            repository=repository,  # type: ignore[arg-type]
        )

        total = service._upsert_many_chunked(
            DividendReinvestmentBacktestSummary,
            [{"run_id": 1}, {"run_id": 1}, {"run_id": 1}, {"run_id": 1}, {"run_id": 1}],
            chunk_size=2,
        )

    assert total == 5
    assert repository.batch_sizes == [2, 2, 1]


def test_query_summaries_uses_latest_success_run_and_filters() -> None:
    """确认分红再投榜单默认读取最新成功批次并支持核心筛选条件。

    创建日期：2026-05-30
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        run = DividendReinvestmentBacktestRun(
            run_key="test-run",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 5),
            initial_amount=Decimal("100000"),
            cash_div_field="cash_div_tax",
            status="SUCCESS",
        )
        db.add(run)
        db.flush()
        db.add_all(
            [
                DividendReinvestmentBacktestSummary(
                    run_id=run.id,
                    ts_code="000001.SZ",
                    symbol="000001",
                    name="平安银行",
                    industry="银行",
                    initial_amount=Decimal("100000"),
                    dividend_year_count=10,
                    consecutive_dividend_years=8,
                    annualized_return_pct=Decimal("12.5"),
                    latest_dividend_yield_ttm=Decimal("4.2"),
                    latest_pe_ttm=Decimal("8.5"),
                    rank_score=Decimal("24.7"),
                    data_quality="COMPLETE",
                ),
                DividendReinvestmentBacktestSummary(
                    run_id=run.id,
                    ts_code="000002.SZ",
                    symbol="000002",
                    name="万科A",
                    industry="房地产",
                    initial_amount=Decimal("100000"),
                    dividend_year_count=2,
                    consecutive_dividend_years=0,
                    annualized_return_pct=Decimal("1.2"),
                    latest_dividend_yield_ttm=Decimal("0.5"),
                    latest_pe_ttm=Decimal("40"),
                    rank_score=Decimal("3.7"),
                    data_quality="COMPLETE",
                ),
            ]
        )
        db.commit()

        target_run_id, total, rows = DividendReinvestmentDataLandingService(db).query_summaries(
            run_id=None,
            keyword="银行",
            industry=None,
            data_quality="COMPLETE",
            min_annualized_return_pct=Decimal("10"),
            min_dividend_year_count=5,
            min_consecutive_dividend_years=5,
            min_latest_dividend_yield_ttm=Decimal("3"),
            max_latest_pe_ttm=Decimal("12"),
            page=1,
            page_size=10,
        )

    assert target_run_id == run.id
    assert total == 1
    assert rows[0].ts_code == "000001.SZ"
