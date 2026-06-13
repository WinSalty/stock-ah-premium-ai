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

    # 雪球发布任务只在周二到周六唤起：Tushare/KPL 打板报告按 T-1 交易日生成，
    # 周二早上对应周一报告，周六早上对应周五报告；具体时点、动作和封面仍由页面配置决定。
    #
    # 触发频率：由原来的每分钟（minute="*"，每天 1440 次）收窄为每 10 分钟一次。
    # 这里的外层 cron 只决定“多久检查一次”，真正的发布时点仍由页面配置的
    # poll_hours/poll_minutes 在服务层 _scheduler_time_reached 内判定，因此保持
    # hour="*" 以兼容管理员把发布时点配置到任意小时；收窄到 10 分钟步长后，发布相对
    # 配置时点最多延后约 10 分钟（如配置 08:35 实际约 08:40 发出），对 T-1 早盘报告可接受。
    # 配合服务层“按交易日去重前移”，到点发布成功后剩余调度只做一次轻量查重即返回，
    # 不再每分钟重新生成报告或重复请求雪球接口。
    scheduler.add_job(
        xueqiu_publish_latest_job,
        trigger="cron",
        id="xueqiu-publish-latest-limit-up",
        name="保存或发布最新打板报告到雪球",
        day_of_week="tue-sat",
        hour="*",
        minute="*/10",
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
