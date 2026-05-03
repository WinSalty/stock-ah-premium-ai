from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.market import FxRateDaily


@dataclass(frozen=True)
class RateLookup:
    """汇率查询结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    rate: Decimal
    rate_date: date
    source: str
    fallback: bool


class FxRateService:
    """港币兑人民币汇率服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_hkd_cny(self, target_date: date) -> RateLookup | None:
        """查询目标日期可用的 HKD/CNY 汇率。

        创建日期：2026-05-04
        author: sunshengxian
        """

        direct = self._latest_rate(("HKD_CNY", "HKD_CNH"), target_date)
        if direct is not None and direct.mid_rate is not None:
            return RateLookup(
                rate=direct.mid_rate,
                rate_date=direct.rate_date,
                source=direct.source,
                fallback=direct.rate_date != target_date,
            )
        usd_cnh = self._latest_rate(("USD_CNH", "USD_CNY"), target_date)
        usd_hkd = self._latest_rate(("USD_HKD",), target_date)
        if (
            usd_cnh is None
            or usd_hkd is None
            or usd_cnh.mid_rate is None
            or usd_hkd.mid_rate is None
        ):
            return None
        return RateLookup(
            rate=usd_cnh.mid_rate / usd_hkd.mid_rate,
            rate_date=min(usd_cnh.rate_date, usd_hkd.rate_date),
            source=f"CROSS:{usd_cnh.source}+{usd_hkd.source}",
            fallback=usd_cnh.rate_date != target_date or usd_hkd.rate_date != target_date,
        )

    def _latest_rate(self, pairs: tuple[str, ...], target_date: date) -> FxRateDaily | None:
        statement = (
            select(FxRateDaily)
            .where(FxRateDaily.rate_pair.in_(pairs), FxRateDaily.rate_date <= target_date)
            .order_by(desc(FxRateDaily.rate_date))
            .limit(1)
        )
        return self.db.scalar(statement)
