from __future__ import annotations

from app.jobs.sync_jobs import INCREMENTAL_SYNC_JOB_SPECS


def test_incremental_sync_jobs_skip_disabled_hk_daily() -> None:
    """确认定时增量任务不会调用已禁用的 hk_daily。

    创建日期：2026-05-04
    author: sunshengxian
    """

    datasets = {spec.dataset for spec in INCREMENTAL_SYNC_JOB_SPECS}

    assert "hk_daily" not in datasets
    assert {"a_daily", "ah_comparison", "stock_hsgt"}.issubset(datasets)
