from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler() -> BackgroundScheduler:
    """创建后台调度器。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return BackgroundScheduler(timezone="Asia/Shanghai")
