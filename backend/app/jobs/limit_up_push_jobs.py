from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.limit_up_push_service import LimitUpPushService

logger = logging.getLogger(__name__)


def register_limit_up_push_jobs(scheduler: BackgroundScheduler, settings: Settings) -> None:
    """注册打板报告生成与复推任务。

    创建日期：2026-05-08
    author: sunshengxian
    """

    # 早盘轮询只负责等待 KPL 次日数据落地；每次运行都通过报告缓存和推送流水做幂等，
    # 即使调度器重启或同一分钟重复触发，也不会重复调用 LLM 或重复发送同一业务计划。
    scheduler.add_job(
        generate_and_push_limit_up_job,
        trigger="cron",
        id="limit-up-generate-and-push",
        name="KPL 数据就绪后生成并推送打板报告",
        day_of_week="mon-sun",
        hour=settings.limit_up_push_poll_hours,
        minute=settings.limit_up_push_poll_minutes,
        second=0,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    # 周六和周日晚上复用最近周五报告缓存，满足周末重复阅读需求；
    # 该任务不重新抓数据、不调用 LLM，只根据缓存和接收人配置派发。
    scheduler.add_job(
        weekend_replay_limit_up_job,
        trigger="cron",
        id="limit-up-weekend-replay",
        name="周末复推周五打板报告",
        day_of_week="sat,sun",
        hour=settings.limit_up_push_weekend_replay_hour,
        minute=0,
        second=0,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=1800,
    )


def generate_and_push_limit_up_job() -> None:
    """执行 KPL 数据就绪后的打板报告生成和推送。

    创建日期：2026-05-08
    author: sunshengxian
    """

    with SessionLocal() as db:
        analysis, pushed = LimitUpPushService(db).ensure_latest_analysis_and_push()
        if analysis is not None:
            logger.info("打板报告检查完成 report_id=%s status=%s pushed=%s", analysis.id, analysis.status, pushed)


def weekend_replay_limit_up_job() -> None:
    """执行周末打板报告复推。

    创建日期：2026-05-08
    author: sunshengxian
    """

    with SessionLocal() as db:
        analysis, pushed = LimitUpPushService(db).push_weekend_replay()
        if analysis is not None:
            logger.info("周末打板报告复推完成 report_id=%s pushed=%s", analysis.id, pushed)
