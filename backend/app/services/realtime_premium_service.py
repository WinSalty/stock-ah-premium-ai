from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import AHStockPair, OfficialAHComparison, WatchlistStock
from app.schemas.market import (
    RealtimePremiumListResponse,
    RealtimePremiumResponse,
    RealtimeQuoteItem,
)
from app.services.decimal_utils import quantize_decimal
from app.services.realtime_market_service import (
    DEFAULT_QUOTE_QUALITY,
    RealtimeMarketDataService,
    RealtimeQuote,
    quote_sources,
)

REALTIME_QUALITY = "REALTIME"
DELAYED_QUALITY = "DELAYED"
STALE_FX_QUALITY = "STALE_FX"
PARTIAL_QUALITY = "PARTIAL"
UNAVAILABLE_QUALITY = "UNAVAILABLE"
STALE_QUALITY = "STALE"
ERROR_QUALITY = "ERROR"
OFFICIAL_AH_COMPARISON_SCALE = "0.01"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class RealtimePremiumService:
    """实时 AH/H/A 溢价计算服务。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        market_data_service: RealtimeMarketDataService | None = None,
    ) -> None:
        self.db = db
        self.market_data_service = market_data_service or RealtimeMarketDataService.from_db(db)

    def list_realtime_premiums(
        self,
        *,
        user_id: int,
        a_ts_code: str | None = None,
        hk_ts_code: str | None = None,
        only_watchlist: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> RealtimePremiumListResponse:
        """查询实时 AH/H/A 溢价列表。

        创建日期：2026-05-05
        author: sunshengxian
        """

        targets = self._query_targets(user_id, a_ts_code, hk_ts_code, only_watchlist)
        items = [self.calculate_pair(**target) for target in targets]
        start = (page - 1) * page_size
        return RealtimePremiumListResponse(total=len(items), items=items[start : start + page_size])

    def calculate_pair(
        self,
        *,
        a_ts_code: str,
        hk_ts_code: str,
        a_name: str | None = None,
        hk_name: str | None = None,
        watchlist: WatchlistStock | None = None,
    ) -> RealtimePremiumResponse:
        """计算单个 AH 配对实时溢价。

        创建日期：2026-05-05
        author: sunshengxian
        """

        a_quote, hk_quote, fx_quote = self.market_data_service.get_pair_quotes(
            a_ts_code,
            hk_ts_code,
        )
        ah_ratio, ah_premium_pct, ha_ratio, ha_premium_pct = self._premium_values(
            a_quote,
            hk_quote,
            fx_quote,
        )
        direction = self._normalize_direction(watchlist.preferred_direction if watchlist else "HA")
        metric_premium = ah_premium_pct if direction == "AH" else ha_premium_pct
        target = watchlist.target_premium_pct if watchlist else None
        distance = (
            quantize_decimal(target - metric_premium)
            if target is not None and metric_premium is not None
            else None
        )
        quality = self._quote_quality(a_quote, hk_quote, fx_quote)
        result = RealtimePremiumResponse(
            a_ts_code=a_ts_code,
            hk_ts_code=hk_ts_code,
            a_name=a_name,
            hk_name=hk_name,
            display_name=watchlist.display_name if watchlist else a_name or hk_name,
            a_last_price=a_quote.last_price if a_quote else None,
            hk_last_price=hk_quote.last_price if hk_quote else None,
            hkd_cny_rate=fx_quote.last_price if fx_quote else None,
            ah_ratio=ah_ratio,
            ah_premium_pct=ah_premium_pct,
            ha_ratio=ha_ratio,
            ha_premium_pct=ha_premium_pct,
            metric_direction=direction,
            metric_premium_pct=metric_premium,
            target_premium_pct=target,
            distance_to_target_pct=distance,
            opportunity_status=self._opportunity_status(distance, quality),
            quote_quality=quality,
            is_realtime=quality == REALTIME_QUALITY,
            source=quote_sources((a_quote, hk_quote, fx_quote)),
            calculated_at=datetime.now(UTC).replace(tzinfo=None),
            a_quote=self._quote_item(a_quote),
            hk_quote=self._quote_item(hk_quote),
            fx_quote=self._quote_item(fx_quote),
            watchlist_id=watchlist.id if watchlist else None,
            is_watchlist=watchlist is not None,
        )
        self._persist_realtime_result(result)
        return result

    def _query_targets(
        self,
        user_id: int,
        a_ts_code: str | None,
        hk_ts_code: str | None,
        only_watchlist: bool,
    ) -> list[dict[str, object]]:
        if only_watchlist:
            statement = select(WatchlistStock).where(
                WatchlistStock.user_id == user_id,
                WatchlistStock.is_active.is_(True),
            )
            if a_ts_code:
                statement = statement.where(WatchlistStock.a_ts_code == a_ts_code.upper())
            if hk_ts_code:
                statement = statement.where(WatchlistStock.hk_ts_code == hk_ts_code.upper())
            rows = list(
                self.db.scalars(
                    statement.order_by(WatchlistStock.sort_order, WatchlistStock.id)
                ).all()
            )
            return [
                {
                    "a_ts_code": item.a_ts_code,
                    "hk_ts_code": item.hk_ts_code,
                    "a_name": item.display_name,
                    "hk_name": None,
                    "watchlist": item,
                }
                for item in rows
            ]
        if a_ts_code and hk_ts_code:
            watchlist = self._watchlist_for_pair(user_id, a_ts_code.upper(), hk_ts_code.upper())
            official = self._latest_official_pair(a_ts_code.upper(), hk_ts_code.upper())
            a_name = official.a_name if official else None
            if a_name is None and watchlist is not None:
                a_name = watchlist.display_name
            return [
                {
                    "a_ts_code": a_ts_code.upper(),
                    "hk_ts_code": hk_ts_code.upper(),
                    "a_name": a_name,
                    "hk_name": official.hk_name if official else None,
                    "watchlist": watchlist,
                }
            ]
        statement = select(AHStockPair).where(AHStockPair.is_active.is_(True))
        if a_ts_code:
            statement = statement.where(AHStockPair.a_ts_code == a_ts_code.upper())
        if hk_ts_code:
            statement = statement.where(AHStockPair.hk_ts_code == hk_ts_code.upper())
        rows = list(self.db.scalars(statement.order_by(AHStockPair.a_ts_code)).all())
        return [
            {
                "a_ts_code": item.a_ts_code,
                "hk_ts_code": item.hk_ts_code,
                "a_name": item.a_name,
                "hk_name": item.hk_name,
                "watchlist": self._watchlist_for_pair(user_id, item.a_ts_code, item.hk_ts_code),
            }
            for item in rows
        ]

    def _premium_values(
        self,
        a_quote: RealtimeQuote | None,
        hk_quote: RealtimeQuote | None,
        fx_quote: RealtimeQuote | None,
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        if (
            a_quote is None
            or hk_quote is None
            or fx_quote is None
            or a_quote.last_price is None
            or hk_quote.last_price is None
            or fx_quote.last_price is None
            or a_quote.last_price <= 0
            or hk_quote.last_price <= 0
            or fx_quote.last_price <= 0
        ):
            return None, None, None, None
        ah_ratio = quantize_decimal(
            a_quote.last_price / (hk_quote.last_price * fx_quote.last_price)
        )
        if ah_ratio is None or ah_ratio == 0:
            return None, None, None, None
        ah_premium_pct = quantize_decimal((ah_ratio - Decimal("1")) * Decimal("100"))
        official_ah_comparison = quantize_decimal(ah_ratio, OFFICIAL_AH_COMPARISON_SCALE)
        if official_ah_comparison is None or official_ah_comparison == 0:
            return ah_ratio, ah_premium_pct, None, None
        ha_ratio = quantize_decimal(Decimal("1") / official_ah_comparison)
        ha_premium_pct = (
            quantize_decimal((ha_ratio - Decimal("1")) * Decimal("100"))
            if ha_ratio is not None
            else None
        )
        return ah_ratio, ah_premium_pct, ha_ratio, ha_premium_pct

    def _quote_quality(
        self,
        a_quote: RealtimeQuote | None,
        hk_quote: RealtimeQuote | None,
        fx_quote: RealtimeQuote | None,
    ) -> str:
        if a_quote is None and hk_quote is None and fx_quote is None:
            return UNAVAILABLE_QUALITY
        if (
            a_quote is None
            or hk_quote is None
            or fx_quote is None
            or a_quote.last_price is None
            or hk_quote.last_price is None
            or fx_quote.last_price is None
        ):
            return PARTIAL_QUALITY
        qualities = {
            (a_quote.quality or DEFAULT_QUOTE_QUALITY).upper(),
            (hk_quote.quality or DEFAULT_QUOTE_QUALITY).upper(),
            (fx_quote.quality or DEFAULT_QUOTE_QUALITY).upper(),
        }
        if ERROR_QUALITY in qualities or UNAVAILABLE_QUALITY in qualities:
            return UNAVAILABLE_QUALITY
        if any((quote.quality or "").upper() != REALTIME_QUALITY for quote in (a_quote, hk_quote)):
            return DELAYED_QUALITY
        if (fx_quote.quality or "").upper() == STALE_QUALITY:
            return STALE_FX_QUALITY
        if (fx_quote.quality or "").upper() != REALTIME_QUALITY:
            return STALE_FX_QUALITY
        return REALTIME_QUALITY

    def _opportunity_status(self, distance: Decimal | None, quality: str) -> str:
        if quality in {PARTIAL_QUALITY, UNAVAILABLE_QUALITY}:
            return "DATA_UNAVAILABLE"
        if quality == DELAYED_QUALITY:
            return "DELAYED_ONLY"
        if distance is None:
            return "NO_TARGET"
        if distance <= 0:
            return "TRIGGERED"
        if distance <= Decimal("3"):
            return "NEAR_TARGET"
        return "WATCHING"

    def _quote_item(self, quote: RealtimeQuote | None) -> RealtimeQuoteItem | None:
        if quote is None:
            return None
        return RealtimeQuoteItem(
            market=quote.market,
            symbol=quote.symbol,
            last_price=quote.last_price,
            currency=quote.currency,
            quote_time=quote.quote_time,
            source=quote.source,
            quality=quote.quality,
        )

    def _persist_realtime_result(self, result: RealtimePremiumResponse) -> None:
        """将可用实时计算结果写回官方 AH 比价表，供页面统一读取主口径。

        创建日期：2026-05-06
        author: sunshengxian
        """

        if (
            result.quote_quality not in {REALTIME_QUALITY, STALE_FX_QUALITY}
            or result.a_last_price is None
            or result.hk_last_price is None
            or result.ah_ratio is None
        ):
            return
        ah_comparison = quantize_decimal(result.ah_ratio, OFFICIAL_AH_COMPARISON_SCALE)
        if ah_comparison is None or ah_comparison == Decimal("0"):
            return
        ah_premium = quantize_decimal((ah_comparison - Decimal("1")) * Decimal("100"))
        ha_comparison = quantize_decimal(Decimal("1") / ah_comparison)
        ha_premium = (
            quantize_decimal((ha_comparison - Decimal("1")) * Decimal("100"))
            if ha_comparison is not None
            else None
        )
        trade_date = self._realtime_data_date(result)
        if trade_date is None:
            return
        if trade_date != self._local_today():
            return
        row = self.db.scalar(
            select(OfficialAHComparison).where(
                OfficialAHComparison.trade_date == trade_date,
                OfficialAHComparison.a_ts_code == result.a_ts_code,
                OfficialAHComparison.hk_ts_code == result.hk_ts_code,
            )
        )
        if row is not None and not row.is_realtime:
            return
        if row is None:
            row = OfficialAHComparison(
                trade_date=trade_date,
                a_ts_code=result.a_ts_code,
                hk_ts_code=result.hk_ts_code,
                a_name=result.a_name or result.display_name,
                hk_name=result.hk_name,
            )
            self.db.add(row)
        elif result.a_name and not row.a_name:
            row.a_name = result.a_name
        if result.hk_name and not row.hk_name:
            row.hk_name = result.hk_name
        row.a_close = result.a_last_price
        row.hk_close = result.hk_last_price
        row.ah_comparison = ah_comparison
        row.ah_premium = ah_premium
        row.ha_comparison = ha_comparison
        row.ha_premium = ha_premium
        row.is_realtime = True
        row.data_source = "REALTIME_CALC"
        row.source_updated_at = result.calculated_at
        self.db.commit()

    def _realtime_data_date(self, result: RealtimePremiumResponse) -> date | None:
        """从 A/H 报价时间推导数据日期，避免把记录生成日期误写成行情日期。

        创建日期：2026-05-06
        author: sunshengxian
        """

        quote_dates = [
            self._quote_data_date(quote)
            for quote in (result.a_quote, result.hk_quote)
        ]
        valid_dates = [item for item in quote_dates if item is not None]
        if len(valid_dates) != len(quote_dates) or len(set(valid_dates)) != 1:
            return None
        return valid_dates[0]

    def _local_today(self) -> date:
        return datetime.now(LOCAL_TZ).date()

    def _quote_data_date(self, quote: RealtimeQuoteItem | None) -> date | None:
        if quote is None or quote.quote_time is None:
            return None
        if quote.quote_time.tzinfo is None:
            return quote.quote_time.date()
        return quote.quote_time.astimezone(LOCAL_TZ).date()

    def _watchlist_for_pair(
        self,
        user_id: int,
        a_ts_code: str,
        hk_ts_code: str,
    ) -> WatchlistStock | None:
        return self.db.scalar(
            select(WatchlistStock).where(
                WatchlistStock.user_id == user_id,
                WatchlistStock.a_ts_code == a_ts_code,
                WatchlistStock.hk_ts_code == hk_ts_code,
                WatchlistStock.is_active.is_(True),
            )
        )

    def _latest_official_pair(
        self,
        a_ts_code: str,
        hk_ts_code: str,
    ) -> OfficialAHComparison | None:
        return self.db.scalar(
            select(OfficialAHComparison)
            .where(
                OfficialAHComparison.a_ts_code == a_ts_code,
                OfficialAHComparison.hk_ts_code == hk_ts_code,
            )
            .order_by(OfficialAHComparison.trade_date.desc())
            .limit(1)
        )

    def _normalize_direction(self, value: str) -> str:
        return "AH" if value.upper() == "AH" else "HA"
