from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def register_alert_jobs(scheduler: BackgroundScheduler, settings: Settings) -> None:
    """注册交易日提醒扫描任务。

    创建日期：2026-05-05
    author: sunshengxian
    """

    interval = max(1, min(settings.alert_scan_seconds, 59))
    scheduler.add_job(
        scan_alerts_job,
        trigger="cron",
        id="scan-trading-day-alerts",
        name="扫描交易日提醒并推送",
        day_of_week="mon-fri",
        hour=settings.alert_scan_hours,
        minute="*",
        second=f"*/{interval}",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )


def scan_alerts_job() -> None:
    """执行交易日提醒扫描。

    创建日期：2026-05-05
    author: sunshengxian
    """

    with SessionLocal() as db:
        events = NotificationService(db).scan_alerts_for_day()
        if events:
            logger.info("交易日提醒扫描完成 pushed_events=%s", len(events))
