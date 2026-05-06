from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import EastmoneyUnadjustedDailyQuote, WatchlistStock
from app.services.eastmoney_kline_service import EastmoneyKlineService
from app.services.repository import UpsertRepository

TENCENT_HK_FALLBACK_SOURCE_MARKER = "TENCENT_HK_KLINE"


@dataclass(frozen=True)
class UnadjustedQuoteSyncResult:
    """东方财富不复权日线同步结果。

    创建日期：2026-05-06
    author: sunshengxian
    """

    pair_count: int
    quote_rows: int


class UnadjustedQuoteSyncService:
    """东方财富不复权日线同步服务。

    创建日期：2026-05-06
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        client: EastmoneyKlineService | None = None,
    ) -> None:
        self.db = db
        self.client = client or EastmoneyKlineService()
        self.repository = UpsertRepository(db)

    def sync_watchlist_quotes(
        self,
        start_date: date,
        end_date: date,
        a_ts_code: str | None = None,
        hk_ts_code: str | None = None,
        pairs: list[tuple[str, str]] | None = None,
    ) -> UnadjustedQuoteSyncResult:
        """同步用户自选 A/H 股票对的不复权日线。

        创建日期：2026-05-06
        author: sunshengxian
        """

        pairs = pairs or self._list_pairs(a_ts_code, hk_ts_code)
        row_count = 0
        for a_code, hk_code in pairs:
            # A/H 两侧分别拉取并写入独立表，重跑时按 market、ts_code、
            # trade_date、adjust_type upsert。
            a_rows = self.client.fetch_unadjusted_daily(a_code, start_date, end_date)
            hk_rows = self.client.fetch_unadjusted_daily(hk_code, start_date, end_date)
            # 港股历史 K 线在东方财富公开端偶发断连时会使用腾讯未复权日线降级；
            # 写库时按 raw_payload_json 中的来源标记区分，便于后续审计具体行的数据出处。
            row_count += self.repository.upsert_many(
                EastmoneyUnadjustedDailyQuote,
                [self._to_model_row(item) for item in [*a_rows, *hk_rows]],
            )
            self.db.commit()
        return UnadjustedQuoteSyncResult(pair_count=len(pairs), quote_rows=row_count)

    def _to_model_row(self, item) -> dict[str, Any]:
        # 同步表唯一键不包含来源字段，重跑时仍按股票、日期和复权类型幂等覆盖；
        # data_source 只表达本次落库所用行情源，方便排查东方财富港股端点不可用的日期范围。
        data_source = (
            "TENCENT_HK_KLINE"
            if TENCENT_HK_FALLBACK_SOURCE_MARKER in item.raw_payload_json
            else "EASTMONEY_KLINE"
        )
        return item.to_model_row(data_source=data_source)

    def _list_pairs(
        self,
        a_ts_code: str | None,
        hk_ts_code: str | None,
    ) -> list[tuple[str, str]]:
        # 默认只同步用户自选且启用的股票对，避免东方财富公开端点被全市场扫描式请求压垮。
        statement = select(WatchlistStock.a_ts_code, WatchlistStock.hk_ts_code).where(
            WatchlistStock.is_active.is_(True)
        )
        if a_ts_code:
            statement = statement.where(WatchlistStock.a_ts_code == a_ts_code.upper())
        if hk_ts_code:
            statement = statement.where(WatchlistStock.hk_ts_code == hk_ts_code.upper())
        rows = self.db.execute(statement).all()
        unique_pairs: dict[tuple[str, str], tuple[str, str]] = {}
        for a_code, hk_code in rows:
            if not a_code or not hk_code:
                continue
            pair = (a_code.upper(), hk_code.upper())
            unique_pairs[pair] = pair
        if not unique_pairs and a_ts_code and hk_ts_code:
            # 指定单票调试允许不依赖自选表，便于新标的先拉取行情再加入自选。
            pair = (a_ts_code.upper(), hk_ts_code.upper())
            unique_pairs[pair] = pair
        return list(unique_pairs.values())
