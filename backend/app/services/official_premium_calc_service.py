from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import OfficialAHComparison
from app.services.decimal_utils import quantize_decimal
from app.services.premium_calc_service import PremiumCalcResult


class OfficialPremiumCalcService:
    """官方 AH 比价表内的比价与溢价计算服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def calculate_range(self, start_date: date, end_date: date) -> PremiumCalcResult:
        """按日期区间重算官方表的 AH/H/A 指标。

        创建日期：2026-05-04
        author: sunshengxian
        """

        calculated_rows = 0
        issue_rows = 0
        current = start_date
        while current <= end_date:
            result = self.calculate_date(current)
            calculated_rows += result.calculated_rows
            issue_rows += result.issue_rows
            current += timedelta(days=1)
        return PremiumCalcResult(start_date, end_date, calculated_rows, 0, issue_rows)

    def calculate_date(self, trade_date: date) -> PremiumCalcResult:
        """重算单日官方表，当前日计算结果标记为实时。

        创建日期：2026-05-04
        author: sunshengxian
        """

        rows = list(
            self.db.scalars(
                select(OfficialAHComparison).where(OfficialAHComparison.trade_date == trade_date)
            ).all()
        )
        issue_rows = 0
        is_realtime = trade_date >= date.today()
        source_updated_at = datetime.now(UTC).replace(tzinfo=None)
        for row in rows:
            if not self._recalculate_row(row, is_realtime, source_updated_at):
                issue_rows += 1
        self.db.commit()
        return PremiumCalcResult(trade_date, trade_date, len(rows), 0, issue_rows)

    def _recalculate_row(
        self,
        row: OfficialAHComparison,
        is_realtime: bool,
        source_updated_at: datetime,
    ) -> bool:
        ah_ratio = row.ah_comparison
        if ah_ratio is None and row.ah_premium is not None:
            ah_ratio = Decimal("1") + row.ah_premium / Decimal("100")
            row.ah_comparison = quantize_decimal(ah_ratio)
        if ah_ratio is None or ah_ratio == Decimal("0"):
            return False
        if row.ah_premium is None:
            row.ah_premium = quantize_decimal((ah_ratio - Decimal("1")) * Decimal("100"))
        row.ha_comparison = quantize_decimal(Decimal("1") / ah_ratio)
        row.ha_premium = (
            quantize_decimal((row.ha_comparison - Decimal("1")) * Decimal("100"))
            if row.ha_comparison is not None
            else None
        )
        if is_realtime:
            row.is_realtime = True
            row.data_source = "REALTIME_CALC"
            row.source_updated_at = source_updated_at
        return True
