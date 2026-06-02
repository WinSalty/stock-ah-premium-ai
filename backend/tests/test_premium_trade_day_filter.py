from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    AFinancialIndicator,
    AStockBasic,
    ATradeCalendar,
    HKTradeCalendar,
    HsgtConstituent,
    OfficialAHComparison,
)
from app.services.sync_service import DATASET_SPECS, SyncService
from app.services.tushare_client import TushareResult


class FakeTushareClient:
    """测试用 Tushare 客户端。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.called = False

    def query(self, api_name: str, params: dict, fields: list[str]) -> object:
        self.called = True
        return object()


class FakeRepository:
    """测试用写库仓储。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.called = False

    def upsert_many(self, model: type, rows: list[dict]) -> int:
        self.called = True
        return len(rows)


class RecordingFinancialIndicatorClient:
    """记录财务指标同步请求的 Tushare 客户端替身。

    创建日期：2026-06-02
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def query(self, api_name: str, params: dict, fields: list[str]) -> TushareResult:
        """按股票代码返回一条最小财务指标数据，用于验证逐股同步。

        创建日期：2026-06-02
        author: sunshengxian
        """

        self.calls.append({"api_name": api_name, "params": dict(params), "fields": fields})
        return TushareResult(
            fields=fields,
            rows=[
                {
                    "ts_code": params["ts_code"],
                    "ann_date": "20260430",
                    "end_date": "20260331",
                    "roe": "12.5",
                }
            ],
        )


class SqliteRepository:
    """SQLite 测试仓储，直接插入同步结果。

    创建日期：2026-06-02
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_many(self, model: type, rows: list[dict]) -> int:
        """测试样本无重复键，直接写入即可覆盖同步编排。

        创建日期：2026-06-02
        author: sunshengxian
        """

        self.db.add_all(model(**row) for row in rows)
        return len(rows)


def test_ah_comparison_sync_skips_non_joint_trade_day() -> None:
    """确认官方 AH 溢价同步跳过 A 股或港股任一休市日。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_date = date(2026, 5, 1)
    with Session(engine) as db:
        db.add_all(
            [
                ATradeCalendar(exchange="SSE", cal_date=target_date, is_open=0),
                HKTradeCalendar(cal_date=target_date, is_open=1),
                OfficialAHComparison(
                    trade_date=target_date,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    ah_comparison=Decimal("1.20"),
                    ah_premium=Decimal("20"),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                ),
            ]
        )
        db.commit()
        client = FakeTushareClient()
        repository = FakeRepository()
        service = SyncService.__new__(SyncService)
        service.db = db
        service.client = client
        service.repository = repository

        row_count = service._sync_spec(DATASET_SPECS["ah_comparison"], {"trade_date": target_date})

    assert row_count == 0
    assert client.called is False
    assert repository.called is False
    with Session(engine) as db:
        remaining = db.scalar(
            select(OfficialAHComparison).where(OfficialAHComparison.trade_date == target_date)
        )
    assert remaining is None


def test_financial_indicator_sync_uses_local_stock_basic_for_stock_loop() -> None:
    """确认 A 股财务指标同步基于本地基础表逐只请求 Tushare。

    创建日期：2026-06-02
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                AStockBasic(
                    ts_code="000001.SZ",
                    symbol="000001",
                    name="平安银行",
                    list_status="L",
                ),
                AStockBasic(
                    ts_code="600000.SH",
                    symbol="600000",
                    name="浦发银行",
                    list_status="L",
                ),
                AStockBasic(
                    ts_code="000002.SZ",
                    symbol="000002",
                    name="万科A",
                    list_status="D",
                ),
            ]
        )
        db.commit()
        client = RecordingFinancialIndicatorClient()
        service = SyncService.__new__(SyncService)
        service.db = db
        service.client = client
        service.repository = SqliteRepository(db)

        row_count = service._sync_spec(
            DATASET_SPECS["a_financial_indicator"],
            {"start_date": date(2026, 1, 1), "end_date": date(2026, 3, 31)},
        )

        stored_rows = db.scalars(select(AFinancialIndicator)).all()

    assert row_count == 2
    assert [item["api_name"] for item in client.calls] == ["fina_indicator", "fina_indicator"]
    assert [item["params"]["ts_code"] for item in client.calls] == ["000001.SZ", "600000.SH"]
    assert all(item["params"]["start_date"] == "20260101" for item in client.calls)
    assert all(item["params"]["end_date"] == "20260331" for item in client.calls)
    assert len(stored_rows) == 2
    assert {item.ts_code for item in stored_rows} == {"000001.SZ", "600000.SH"}


def test_hsgt_sync_prunes_old_constituent_dates() -> None:
    """确认港股通名单同步后只保留最新生效日期。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    old_date = date(2026, 5, 4)
    latest_date = date(2026, 5, 5)
    with Session(engine) as db:
        db.add_all(
            [
                HsgtConstituent(
                    trade_date=old_date,
                    ts_code="03968.HK",
                    connect_type="SH_HK",
                    name="招商银行",
                ),
                HsgtConstituent(
                    trade_date=latest_date,
                    ts_code="03968.HK",
                    connect_type="SH_HK",
                    name="招商银行",
                ),
                HsgtConstituent(
                    trade_date=latest_date,
                    ts_code="03968.HK",
                    connect_type="SZ_HK",
                    name="招商银行",
                ),
            ]
        )
        db.commit()
        service = SyncService.__new__(SyncService)
        service.db = db

        service._prune_hsgt_to_latest_date()
        db.commit()

        rows = list(db.scalars(select(HsgtConstituent).order_by(HsgtConstituent.connect_type)))

    assert {item.trade_date for item in rows} == {latest_date}
    assert [item.connect_type for item in rows] == ["SH_HK", "SZ_HK"]
