from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    ATradeCalendar,
    HKTradeCalendar,
    OfficialAHComparison,
)
from app.services.sync_service import DATASET_SPECS, SyncService


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
