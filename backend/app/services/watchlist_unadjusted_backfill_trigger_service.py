from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.tencent_unadjusted_sync_batch_service import (
    TencentUnadjustedSyncBatchResult,
    TencentUnadjustedSyncBatchService,
)
from app.services.unadjusted_ah_backfill_service import UnadjustedAhBackfillService

logger = logging.getLogger(__name__)


class WatchlistUnadjustedBackfillTriggerService:
    """自选股关注后的腾讯不复权追跑触发服务。

    创建日期：2026-05-07
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def should_trigger(self, a_ts_code: str, hk_ts_code: str) -> bool:
        """判断关注股票对是否缺少有效追跑记录。

        创建日期：2026-05-07
        author: sunshengxian
        """

        # 关注入口只做轻量判断：无记录或失败记录可以触发；RUNNING/COMPLETED
        # 说明已有后台任务或历史补数成果，避免用户重复保存时连续打腾讯接口。
        return UnadjustedAhBackfillService(self.db).is_pair_waiting_for_backfill(
            a_ts_code,
            hk_ts_code,
        )

    def run_if_needed(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TencentUnadjustedSyncBatchResult | None:
        """在后台执行单个关注股票对的腾讯不复权追跑。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if not self.should_trigger(a_ts_code, hk_ts_code):
            return None
        return TencentUnadjustedSyncBatchService(self.db).sync_pair_if_needed(
            a_ts_code=a_ts_code,
            hk_ts_code=hk_ts_code,
            start_date=start_date,
            end_date=end_date,
        )


def run_watchlist_unadjusted_backfill_if_needed(a_ts_code: str, hk_ts_code: str) -> None:
    """FastAPI 后台任务入口：关注新标的后立即补腾讯不复权历史数据。

    创建日期：2026-05-07
    author: sunshengxian
    """

    # 后台任务不能复用请求中的 Session；这里单独开会话，保证响应返回后仍能提交追跑结果。
    with SessionLocal() as db:
        try:
            result = WatchlistUnadjustedBackfillTriggerService(db).run_if_needed(
                a_ts_code,
                hk_ts_code,
            )
        except Exception:
            logger.error(
                "关注股票触发腾讯不复权追跑失败 a_ts_code=%s hk_ts_code=%s",
                a_ts_code,
                hk_ts_code,
                exc_info=True,
            )
            return
        if result is None:
            logger.info(
                "关注股票已存在腾讯不复权追跑记录，跳过触发 a_ts_code=%s hk_ts_code=%s",
                a_ts_code,
                hk_ts_code,
            )
            return
        logger.info(
            "关注股票腾讯不复权追跑完成 a_ts_code=%s hk_ts_code=%s quote_rows=%s inserted_rows=%s",
            a_ts_code,
            hk_ts_code,
            result.quote_rows,
            result.inserted_rows,
        )
