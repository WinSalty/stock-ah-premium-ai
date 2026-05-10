from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.xueqiu_publish_service import XueqiuPublishService

logger = logging.getLogger(__name__)


def register_xueqiu_publish_jobs(scheduler: BackgroundScheduler, settings: Settings) -> None:
    """注册雪球长文草稿/发布任务。

    创建日期：2026-05-10
    author: sunshengxian
    """

    # 雪球发布属于第三方公开内容写入，进程级调度总开关默认关闭；
    # 注册后每个工作日分钟级检查一次，具体时点、动作和封面由页面落库配置实时决定。
    scheduler.add_job(
        xueqiu_publish_latest_job,
        trigger="cron",
        id="xueqiu-publish-latest-limit-up",
        name="保存或发布最新打板报告到雪球",
        day_of_week="mon-fri",
        hour="*",
        minute="*",
        second=0,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=900,
    )


def xueqiu_publish_latest_job() -> None:
    """执行最新打板报告的雪球草稿/发布任务。

    创建日期：2026-05-10
    author: sunshengxian
    """

    with SessionLocal() as db:
        record = XueqiuPublishService(db).save_or_publish_latest_by_scheduler()
        if record is not None:
            logger.info("雪球发布任务完成 record_id=%s status=%s", record.id, record.status)
