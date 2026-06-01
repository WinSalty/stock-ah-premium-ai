from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import Settings
from app.db.session import SessionLocal
from app.services.nine_turn_push_service import NineTurnPushService

logger = logging.getLogger(__name__)


def register_nine_turn_push_jobs(scheduler: BackgroundScheduler, settings: Settings) -> None:
    """注册神奇九转报告生成、推送和雪球发布任务。

    创建日期：2026-06-01
    author: sunshengxian
    """

    # 当前 Tushare `stk_nineturn` 接口权限尚未开通，先注释自动同步、推送和雪球发布入口；
    # 底层服务和原调度代码继续保留，待权限开通后删除本段 return 即可恢复晚间轮询。
    logger.info("神奇九转定时同步暂未启用：stk_nineturn 接口权限尚未开通")
    return

    # Tushare 文档说明 stk_nineturn 涉及分钟数据、每日 21 点更新；这里在 21-22 点轮询，
    # 并依靠报告快照、推送流水和雪球流水幂等，避免接口延迟恢复后重复调用 LLM 或重复发文。
    scheduler.add_job(
        generate_push_and_publish_nine_turn_job,
        trigger="cron",
        id="nine-turn-generate-push-publish",
        name="神奇九转数据就绪后生成推送并发布雪球",
        day_of_week="mon-sun",
        hour=settings.nine_turn_push_poll_hours,
        minute=settings.nine_turn_push_poll_minutes,
        second=0,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=900,
    )


def generate_push_and_publish_nine_turn_job() -> None:
    """执行神奇九转报告生成、PushPlus 推送和雪球发文。

    创建日期：2026-06-01
    author: sunshengxian
    """

    with SessionLocal() as db:
        analysis, pushed, xueqiu_record_id = NineTurnPushService(
            db
        ).ensure_latest_analysis_push_and_publish()
        if analysis is not None:
            logger.info(
                "神奇九转报告检查完成 report_id=%s status=%s pushed=%s xueqiu_record_id=%s",
                analysis.id,
                analysis.status,
                pushed,
                xueqiu_record_id,
            )
