from __future__ import annotations

from datetime import date

from app.db.session import SessionLocal
from app.services.sync_service import SyncService


def sync_dataset_job(dataset: str, trade_date: date | None = None) -> None:
    """执行单个数据集同步定时任务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    params = {"trade_date": trade_date} if trade_date else {}
    with SessionLocal() as db:
        SyncService(db).run_sync(dataset, params)
