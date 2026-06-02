from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.sync import SyncRun
from app.services import sync_service
from app.services.dividend_reinvestment_service import DividendReinvestmentSyncResult
from app.services.sync_service import SyncService


@dataclass(frozen=True)
class FakeTencentUnadjustedResult:
    """腾讯不复权补数服务测试替身返回值。

    创建日期：2026-05-07
    author: sunshengxian
    """

    inserted_rows: int


class FakeTencentUnadjustedSyncBatchService:
    """用于确认通用同步入口正确转发到腾讯不复权补数服务。

    创建日期：2026-05-07
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_pending_watchlist(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FakeTencentUnadjustedResult:
        """模拟腾讯补数服务写入 sync_run 并返回插入行数。

        创建日期：2026-05-07
        author: sunshengxian
        """

        self.db.add(
            SyncRun(
                dataset="tencent_unadjusted_backfill",
                params_json=f'{{"start_date": "{start_date}", "end_date": "{end_date}"}}',
                status="SUCCESS",
                row_count=7,
            )
        )
        self.db.commit()
        return FakeTencentUnadjustedResult(inserted_rows=7)


class FakeDividendReinvestmentDataLandingService:
    """用于确认通用同步入口正确转发到分红再投入落地服务。

    创建日期：2026-05-29
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync(self, params: dict) -> DividendReinvestmentSyncResult:
        """模拟分红再投入服务返回阶段行数。

        创建日期：2026-05-29
        author: sunshengxian
        """

        assert params["mode"] == "full"
        return DividendReinvestmentSyncResult(
            stock_rows=1,
            calendar_rows=2,
            daily_rows=3,
            dividend_rows=4,
            stock_dividend_rows=0,
            daily_basic_rows=5,
            financial_indicator_rows=0,
            summary_rows=6,
            yearly_rows=7,
        )

    def sync_result_payload(self, result: DividendReinvestmentSyncResult) -> str:
        """复用真实结果结构，避免测试依赖外部 Tushare 和 MySQL upsert。

        创建日期：2026-05-29
        author: sunshengxian
        """

        return '{"summary_rows": 6, "yearly_rows": 7}'


def test_run_sync_supports_tencent_unadjusted_dataset(monkeypatch) -> None:
    """确认通用“执行同步”入口支持腾讯不复权补数数据集。

    创建日期：2026-05-07
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        sync_service,
        "TencentUnadjustedSyncBatchService",
        FakeTencentUnadjustedSyncBatchService,
    )
    with Session(engine) as db:
        run = SyncService(db).run_sync(
            "tencent_unadjusted_backfill",
            {"start_date": date(2018, 1, 1), "end_date": date(2026, 5, 7)},
        )

    assert run.status == "SUCCESS"
    assert run.row_count == 7
    assert run.dataset == "tencent_unadjusted_backfill"


def test_run_sync_supports_dividend_reinvestment_dataset(monkeypatch) -> None:
    """确认通用“执行同步”入口支持分红再投入数据落地数据集。

    创建日期：2026-05-29
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        sync_service,
        "DividendReinvestmentDataLandingService",
        FakeDividendReinvestmentDataLandingService,
    )
    with Session(engine) as db:
        run = SyncService(db).run_sync(
            "dividend_reinvestment_data_landing",
            {"mode": "full", "start_date": date(2026, 1, 1), "end_date": date(2026, 1, 5)},
        )

    assert run.status == "SUCCESS"
    assert run.row_count == 28
    assert run.dataset == "dividend_reinvestment_data_landing"
    assert '"summary_rows": 6' in (run.params_json or "")
