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


def test_incremental_sync_jobs_include_a_stock_st_daily() -> None:
    """确认 A 股每日 ST 名单已纳入盘后增量同步(供 universe point-in-time 判 ST)。

    创建日期：2026-06-13
    author: claude
    """

    specs = {spec.job_id: spec for spec in INCREMENTAL_SYNC_JOB_SPECS}
    assert "sync-a-stock-st-daily" in specs
    st_spec = specs["sync-a-stock-st-daily"]
    assert st_spec.dataset == "a_stock_st"
    assert st_spec.params == {"mode": "incremental"}
    # 排在 a_daily(16:15) 之后错开限流
    assert (st_spec.hour, st_spec.minute) == (16, 30)
    assert st_spec.day_of_week == "mon-fri"
