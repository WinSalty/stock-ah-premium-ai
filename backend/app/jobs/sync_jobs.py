from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.services.sync_service import SyncService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncrementalSyncJobSpec:
    """增量同步定时任务规格。

    创建日期：2026-05-04
    author: sunshengxian
    """

    job_id: str
    name: str
    dataset: str
    params: dict[str, Any]
    hour: int
    minute: int
    day_of_week: str = "mon-fri"
    doc_note: str = ""


INCREMENTAL_SYNC_JOB_SPECS: tuple[IncrementalSyncJobSpec, ...] = (
    IncrementalSyncJobSpec(
        job_id="sync-stock-basic-daily",
        name="刷新 A 股基础信息",
        dataset="stock_basic",
        params={"mode": "incremental"},
        hour=9,
        minute=5,
        doc_note="基础清单接口不带日期范围，工作日早盘前刷新当前全表。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-hk-basic-daily",
        name="刷新港股基础信息",
        dataset="hk_basic",
        params={"mode": "incremental"},
        hour=9,
        minute=10,
        doc_note="基础清单接口不带日期范围，工作日早盘前刷新当前全表。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-trade-cal-weekly",
        name="补齐 A 股交易日历",
        dataset="trade_cal",
        params={"mode": "incremental"},
        hour=8,
        minute=35,
        day_of_week="mon",
        doc_note="交易日历支持日期范围，每周补齐并保持未来日历窗口。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-hk-tradecal-weekly",
        name="补齐港股交易日历",
        dataset="hk_tradecal",
        params={"mode": "incremental"},
        hour=8,
        minute=40,
        day_of_week="mon",
        doc_note="港股交易日历支持日期范围，每周补齐并保持未来日历窗口。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-stock-hsgt-sh-hk",
        name="同步沪港通港股通名单",
        dataset="stock_hsgt",
        params={"mode": "incremental", "type": "SH_HK"},
        hour=9,
        minute=25,
        doc_note="Tushare stock_hsgt 文档提示每天 9:20 更新。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-stock-hsgt-sz-hk",
        name="同步深港通港股通名单",
        dataset="stock_hsgt",
        params={"mode": "incremental", "type": "SZ_HK"},
        hour=9,
        minute=28,
        doc_note="Tushare stock_hsgt 文档提示每天 9:20 更新。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-a-daily",
        name="同步 A 股日线行情",
        dataset="a_daily",
        params={"mode": "incremental"},
        hour=16,
        minute=15,
        doc_note="Tushare daily 文档提示交易日 15:00-16:00 入库。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-ah-comparison",
        name="同步官方 AH 比价",
        dataset="ah_comparison",
        params={"mode": "incremental"},
        hour=17,
        minute=10,
        doc_note="Tushare stk_ah_comparison 文档提示每天盘后 17:00 更新。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-fx-daily",
        name="同步外汇日线",
        dataset="fx_daily",
        params={"mode": "incremental"},
        hour=7,
        minute=30,
        day_of_week="mon-sat",
        doc_note="外汇日线按 GMT 交易日更新，东八区早间补齐上一 GMT 交易日。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-a-financial-indicator-weekly",
        name="同步 A 股财务指标",
        dataset="a_financial_indicator",
        params={"mode": "incremental"},
        hour=22,
        minute=20,
        day_of_week="sat",
        doc_note="普通 fina_indicator 需按单股请求，周末夜间逐股补齐 ROE 等最新财务指标。",
    ),
    IncrementalSyncJobSpec(
        job_id="sync-a-stock-st-daily",
        name="同步 A 股每日 ST 名单",
        dataset="a_stock_st",
        params={"mode": "incremental"},
        hour=16,
        minute=30,
        # stock_st 按交易日返回 point-in-time ST 名单，供 universe 按"信号日当日"判 ST、杜绝前视；
        # 排在 a_daily(16:15) 之后错开 Tushare 限流，增量靠 SyncCheckpoint 断点续传。
        doc_note="stock_st 按交易日返回 point-in-time 快照，盘后逐交易日同步避免回测前视偏差。",
    ),
)


def register_incremental_sync_jobs(scheduler: BackgroundScheduler) -> None:
    """注册 AH 分析所需数据的东八区定时增量任务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    for spec in INCREMENTAL_SYNC_JOB_SPECS:
        scheduler.add_job(
            sync_dataset_job,
            trigger="cron",
            id=spec.job_id,
            name=spec.name,
            kwargs={"dataset": spec.dataset, "params": spec.params},
            day_of_week=spec.day_of_week,
            hour=spec.hour,
            minute=spec.minute,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )


def sync_dataset_job(
    dataset: str,
    trade_date: date | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    """执行单个数据集同步定时任务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    sync_params = dict(params or {})
    if trade_date:
        sync_params["trade_date"] = trade_date
    with SessionLocal() as db:
        run = SyncService(db).run_sync(dataset, sync_params)
        if run.status == "FAILED":
            logger.error(
                "定时同步失败 dataset=%s run_id=%s error=%s",
                dataset,
                run.id,
                run.error_message,
            )
            return
        logger.info(
            "定时同步完成 dataset=%s run_id=%s row_count=%s",
            dataset,
            run.id,
            run.row_count,
        )
