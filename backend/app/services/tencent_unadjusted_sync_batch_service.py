from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.db.models.sync import SyncRun
from app.services.unadjusted_ah_backfill_service import (
    UnadjustedAhBackfillResult,
    UnadjustedAhBackfillService,
)
from app.services.unadjusted_quote_sync_service import (
    UnadjustedQuoteSyncResult,
    UnadjustedQuoteSyncService,
)

TENCENT_UNADJUSTED_DEFAULT_START_DATE = date(2018, 1, 1)


@dataclass(frozen=True)
class TencentUnadjustedSyncBatchResult:
    """腾讯不复权日线同步与 AH 追跑合并结果。

    创建日期：2026-05-06
    author: sunshengxian
    """

    start_date: date
    end_date: date
    pending_pair_count: int
    quote_rows: int
    backfill_pair_count: int
    candidate_rows: int
    inserted_rows: int
    skipped_existing_rows: int
    replaced_baidu_rows: int
    skipped_invalid_rows: int


class TencentUnadjustedSyncBatchService:
    """腾讯不复权日线同步与 AH 比价追跑编排服务。

    创建日期：2026-05-06
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_pending_watchlist(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TencentUnadjustedSyncBatchResult:
        """同步被关注且尚未完成追跑的股票对，并立即计算 AH 比价。

        创建日期：2026-05-06
        author: sunshengxian
        """

        resolved_start_date = start_date or TENCENT_UNADJUSTED_DEFAULT_START_DATE
        resolved_end_date = end_date or date.today()
        run = self._create_run(resolved_start_date, resolved_end_date)
        try:
            result = self._sync_pending_watchlist(resolved_start_date, resolved_end_date)
            run.status = "SUCCESS"
            run.row_count = result.inserted_rows
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            run = self.db.merge(run)
            run.status = "FAILED"
            run.error_message = str(exc)[:4000]
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            self.db.commit()
            raise

    def sync_pair_if_needed(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TencentUnadjustedSyncBatchResult:
        """关注新股票后按单个 A/H 股票对触发腾讯不复权追跑。

        创建日期：2026-05-07
        author: sunshengxian
        """

        resolved_start_date = start_date or TENCENT_UNADJUSTED_DEFAULT_START_DATE
        resolved_end_date = end_date or date.today()
        pair = (a_ts_code.upper(), hk_ts_code.upper())
        backfill_service = UnadjustedAhBackfillService(self.db)
        if not backfill_service.reserve_pair_for_backfill(pair[0], pair[1]):
            return self._empty_result(resolved_start_date, resolved_end_date)
        run = self._create_run(resolved_start_date, resolved_end_date, pairs=[pair])
        try:
            result = self._sync_pairs(resolved_start_date, resolved_end_date, [pair])
            run.status = "SUCCESS"
            run.row_count = result.inserted_rows
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            run = self.db.merge(run)
            run.status = "FAILED"
            run.error_message = str(exc)[:4000]
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            self.db.commit()
            backfill_service.mark_pair_failed(pair[0], pair[1], str(exc))
            raise

    def _sync_pending_watchlist(
        self,
        resolved_start_date: date,
        resolved_end_date: date,
    ) -> TencentUnadjustedSyncBatchResult:
        # 只处理 watchlist_stock 启用且追跑记录未 COMPLETED 的股票对，避免重复同步已完成标的。
        backfill_service = UnadjustedAhBackfillService(self.db)
        pending_pairs = backfill_service.list_pending_watchlist_pairs()
        if not pending_pairs:
            return self._empty_result(resolved_start_date, resolved_end_date)
        return self._sync_pairs(resolved_start_date, resolved_end_date, pending_pairs)

    def _sync_pairs(
        self,
        resolved_start_date: date,
        resolved_end_date: date,
        pairs: list[tuple[str, str]],
    ) -> TencentUnadjustedSyncBatchResult:
        # 同步阶段只请求指定的待追跑股票对，避免重复打腾讯公开 K 线端点；
        # 该方法同时服务同步页批量补数和关注新标的后的单票后台补数。
        backfill_service = UnadjustedAhBackfillService(self.db)
        quote_result = UnadjustedQuoteSyncService(self.db).sync_watchlist_quotes(
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            pairs=pairs,
        )
        # 追跑阶段继续使用相同股票对集合；只取 A/H/汇率同日交集，且仅替换 Baidu 前复权行。
        backfill_result = backfill_service.backfill_watchlist(
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            pairs=pairs,
        )
        return self._merge_result(
            resolved_start_date,
            resolved_end_date,
            quote_result,
            backfill_result,
            pending_pair_count=len(pairs),
        )

    def _create_run(
        self,
        start_date: date,
        end_date: date,
        pairs: list[tuple[str, str]] | None = None,
    ) -> SyncRun:
        # 合并补数不是 Tushare 数据集同步，但仍写 sync_run，方便同步页查看执行窗口和失败原因。
        run = SyncRun(
            dataset="tencent_unadjusted_backfill",
            params_json=json.dumps(
                {"start_date": start_date, "end_date": end_date, "pairs": pairs or None},
                ensure_ascii=False,
                default=str,
            ),
            status="RUNNING",
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _empty_result(
        self,
        start_date: date,
        end_date: date,
    ) -> TencentUnadjustedSyncBatchResult:
        return TencentUnadjustedSyncBatchResult(
            start_date=start_date,
            end_date=end_date,
            pending_pair_count=0,
            quote_rows=0,
            backfill_pair_count=0,
            candidate_rows=0,
            inserted_rows=0,
            skipped_existing_rows=0,
            replaced_baidu_rows=0,
            skipped_invalid_rows=0,
        )

    def _merge_result(
        self,
        start_date: date,
        end_date: date,
        quote_result: UnadjustedQuoteSyncResult,
        backfill_result: UnadjustedAhBackfillResult,
        pending_pair_count: int,
    ) -> TencentUnadjustedSyncBatchResult:
        return TencentUnadjustedSyncBatchResult(
            start_date=start_date,
            end_date=end_date,
            pending_pair_count=pending_pair_count,
            quote_rows=quote_result.quote_rows,
            backfill_pair_count=backfill_result.pair_count,
            candidate_rows=backfill_result.candidate_rows,
            inserted_rows=backfill_result.inserted_rows,
            skipped_existing_rows=backfill_result.skipped_existing_rows,
            replaced_baidu_rows=backfill_result.replaced_baidu_rows,
            skipped_invalid_rows=backfill_result.skipped_invalid_rows,
        )
