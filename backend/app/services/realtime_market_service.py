from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.market import RealtimeQuoteSnapshot

REALTIME_MARKET_A = "A"
REALTIME_MARKET_HK = "HK"
REALTIME_MARKET_FX = "FX"
HKD_CNY_SYMBOL = "HKD/CNY"
DEFAULT_QUOTE_QUALITY = "UNAVAILABLE"
REALTIME_QUOTE_QUALITY = "REALTIME"
STALE_QUOTE_QUALITY = "STALE"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class RealtimeQuote:
    """实时行情标准化报价。

    创建日期：2026-05-05
    author: sunshengxian
    """

    market: str
    symbol: str
    last_price: Decimal | None
    currency: str
    quote_time: datetime | None
    source: str | None
    quality: str = DEFAULT_QUOTE_QUALITY


class RealtimeQuoteProvider(Protocol):
    """实时行情 provider 协议。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def get_a_quote(self, ts_code: str) -> RealtimeQuote | None:
        """读取 A 股实时行情。"""

    def get_hk_quote(self, hk_ts_code: str) -> RealtimeQuote | None:
        """读取港股实时行情。"""

    def get_fx_rate(self, pair: str = HKD_CNY_SYMBOL) -> RealtimeQuote | None:
        """读取实时汇率。"""


class DbRealtimeQuoteProvider:
    """基于实时行情快照表的 provider。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(self, db: Session, local_today: date | None = None) -> None:
        self.db = db
        self.local_today = local_today

    def get_a_quote(self, ts_code: str) -> RealtimeQuote | None:
        """读取 A 股最新快照。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return self._latest_quote(REALTIME_MARKET_A, ts_code)

    def get_hk_quote(self, hk_ts_code: str) -> RealtimeQuote | None:
        """读取港股最新快照。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return self._latest_quote(REALTIME_MARKET_HK, hk_ts_code)

    def get_fx_rate(self, pair: str = HKD_CNY_SYMBOL) -> RealtimeQuote | None:
        """读取汇率最新快照。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return self._latest_quote(REALTIME_MARKET_FX, pair)

    def _latest_quote(self, market: str, symbol: str) -> RealtimeQuote | None:
        snapshot = self.db.scalar(
            select(RealtimeQuoteSnapshot)
            .where(
                RealtimeQuoteSnapshot.market == market,
                RealtimeQuoteSnapshot.symbol == symbol.upper(),
                RealtimeQuoteSnapshot.is_active.is_(True),
            )
            .order_by(
                desc(RealtimeQuoteSnapshot.quote_time),
                desc(RealtimeQuoteSnapshot.id),
            )
            .limit(1)
        )
        if snapshot is None:
            return None
        return RealtimeQuote(
            market=snapshot.market,
            symbol=snapshot.symbol,
            last_price=snapshot.last_price,
            currency=snapshot.currency,
            quote_time=snapshot.quote_time,
            source=snapshot.source,
            quality=self._effective_quality(snapshot.quote_time, snapshot.quality),
        )

    def _effective_quality(self, quote_time: datetime | None, quality: str) -> str:
        if (quality or "").upper() != REALTIME_QUOTE_QUALITY:
            return quality
        if quote_time is None or self._quote_date(quote_time) != self._local_today():
            return STALE_QUOTE_QUALITY
        return REALTIME_QUOTE_QUALITY

    def _quote_date(self, quote_time: datetime) -> date:
        if quote_time.tzinfo is None:
            return quote_time.date()
        return quote_time.astimezone(LOCAL_TZ).date()

    def _local_today(self) -> date:
        if self.local_today is not None:
            return self.local_today
        return datetime.now(LOCAL_TZ).date()


class RealtimeMarketDataService:
    """实时行情读取服务。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(self, provider: RealtimeQuoteProvider) -> None:
        self.provider = provider

    @classmethod
    def from_db(
        cls,
        db: Session,
        local_today: date | None = None,
    ) -> RealtimeMarketDataService:
        """构建读取实时行情表的服务实例。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return cls(DbRealtimeQuoteProvider(db, local_today))

    def get_pair_quotes(
        self,
        a_ts_code: str,
        hk_ts_code: str,
    ) -> tuple[RealtimeQuote | None, RealtimeQuote | None, RealtimeQuote | None]:
        """读取单个 AH 配对所需三类报价。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return (
            self.provider.get_a_quote(a_ts_code.upper()),
            self.provider.get_hk_quote(hk_ts_code.upper()),
            self.provider.get_fx_rate(),
        )


def quote_sources(quotes: Sequence[RealtimeQuote | None]) -> str | None:
    """合并实时报价来源。

    创建日期：2026-05-05
    author: sunshengxian
    """

    sources = [quote.source for quote in quotes if quote is not None and quote.source]
    return ",".join(dict.fromkeys(sources)) if sources else None
