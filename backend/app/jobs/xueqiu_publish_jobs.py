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
    # 触发窗口：KPL 次日 08:30 更新、页面默认发布时点为 08:35，整条 T-1 早盘链路集中在
    # 08:30~09:00 之间，因此外层 cron 收窄为“仅 08:30~08:55、每 5 分钟一次”
    # （hour="8", minute="30-59/5" → 08:30/08:35/08:40/08:45/08:50/08:55，每天 6 次），
    # 给期望发送时点约半小时冗余以兜底报告/建议晚就绪，窗口外不再空跑。
    # 外层 cron 只决定“窗口内多久检查一次”，真正的发布时点仍由页面配置的
    # poll_hours/poll_minutes 在服务层 _scheduler_time_reached 内判定；配合服务层
    # “按交易日去重前移”，到点发布成功后同窗口内剩余调度只做一次轻量查重即返回，
    # 不再重新生成报告或重复请求雪球接口。
    # 注意耦合：该窗口需覆盖页面配置的发布时点（当前 08:35）。若管理员把页面发布时点
    # 调整到 08:30~08:55 之外，需同步调整此处 cron 的 hour/minute，否则当天不会自动发布。
    scheduler.add_job(
        xueqiu_publish_latest_job,
        trigger="cron",
        id="xueqiu-publish-latest-limit-up",
        name="保存或发布最新打板报告到雪球",
        day_of_week="tue-sat",
        hour="8",
        minute="30-59/5",
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
