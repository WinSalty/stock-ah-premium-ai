from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.sync import SyncRun
from app.services import sync_service
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
