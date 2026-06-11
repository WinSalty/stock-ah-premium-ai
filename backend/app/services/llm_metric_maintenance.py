"""LLM 调用指标表治理：保留期清理（旧评审 R4）。

背景：llm_call_metric 每次外部调用都写入完整 request payload 与响应全文（LONGTEXT），
表膨胀速度远超业务表。本模块提供按保留天数删除过期指标的清理能力，
由独立脚本 scripts/cleanup-llm-metrics.sh 手动或通过 cron 触发，不挂进主进程调度，
契合个人项目"按需清理"口径。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.chat import LlmCallMetric

logger = logging.getLogger(__name__)

_METRIC_TIMEZONE = ZoneInfo("Asia/Shanghai")
# 分批删除批量：单次大删除会长时间持锁，分批降低对在线写入的影响。
_DELETE_BATCH_SIZE = 2000


def cleanup_expired_metrics(db: Session, settings: Settings | None = None) -> int:
    """删除早于保留天数的 llm_call_metric 记录，返回删除总条数。

    口径：
    - 保留天数取 settings.llm_metric_retention_days，<=0 表示不清理（直接返回 0）；
    - 截止时间按东八区自然日计算（与指标展示时区一致），删除 created_at < 截止日 的记录；
    - 分批删除避免长事务持锁；每批独立 commit，中途失败已删批次不回滚。

    创建日期：2026-06-12
    author: claude
    """

    settings = settings or get_settings()
    retention_days = settings.llm_metric_retention_days
    if retention_days <= 0:
        logger.info("指标保留天数 <= 0，跳过清理")
        return 0
    now = datetime.now(_METRIC_TIMEZONE).replace(tzinfo=None)
    cutoff = datetime.combine(now.date(), datetime.min.time()) - timedelta(days=retention_days)
    total_deleted = 0
    while True:
        # 先选出一批待删 id，再按 id 删除：兼容不支持 DELETE ... LIMIT 的方言（如 SQLite）。
        batch_ids = list(
            db.scalars(
                select(LlmCallMetric.id)
                .where(LlmCallMetric.created_at < cutoff)
                .limit(_DELETE_BATCH_SIZE)
            ).all()
        )
        if not batch_ids:
            break
        db.execute(delete(LlmCallMetric).where(LlmCallMetric.id.in_(batch_ids)))
        db.commit()
        total_deleted += len(batch_ids)
        if len(batch_ids) < _DELETE_BATCH_SIZE:
            break
    logger.info(
        "指标清理完成：删除 %s 条 created_at < %s 的记录", total_deleted, cutoff.date()
    )
    return total_deleted
