from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.market import (
    ADailyQuote,
    AHPremiumDaily,
    AHStockPair,
    HKDailyQuote,
    HsgtConstituent,
    OfficialAHComparison,
)
from app.services.decimal_utils import quantize_decimal
from app.services.fx_rate_service import FxRateService
from app.services.repository import UpsertRepository


@dataclass(frozen=True)
class PremiumCalcResult:
    """溢价计算汇总结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    start_date: date
    end_date: date
    calculated_rows: int
    skipped_not_connect: int
    issue_rows: int


class PremiumCalcService:
    """港股通 A/H 溢价计算服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.fx_rate_service = FxRateService(db)
        self.repository = UpsertRepository(db)

    def calculate_range(self, start_date: date, end_date: date) -> PremiumCalcResult:
        """按日期区间计算 A/H 溢价。

        创建日期：2026-05-04
        author: sunshengxian
        """

        total = 0
        skipped = 0
        issues = 0
        current = start_date
        while current <= end_date:
            result = self.calculate_date(current)
            total += result.calculated_rows
            skipped += result.skipped_not_connect
            issues += result.issue_rows
            current += timedelta(days=1)
        return PremiumCalcResult(start_date, end_date, total, skipped, issues)

    def calculate_date(self, trade_date: date) -> PremiumCalcResult:
        """计算单日港股通 AH 溢价。

        创建日期：2026-05-04
        author: sunshengxian
        """

        pairs = self._active_pairs(trade_date)
        rows: list[dict] = []
        skipped_not_connect = 0
        issue_rows = 0
        for pair in pairs:
            channels = self._connect_channels(pair.hk_ts_code, trade_date)
            if not channels:
                skipped_not_connect += 1
                continue
            row = self._calculate_pair(pair, trade_date, channels)
            if row["calc_status"] != "OK":
                issue_rows += 1
            rows.append(row)
        count = self.repository.upsert_many(AHPremiumDaily, rows)
        self.db.commit()
        return PremiumCalcResult(trade_date, trade_date, count, skipped_not_connect, issue_rows)

    def _active_pairs(self, trade_date: date) -> list[AHStockPair]:
        statement = select(AHStockPair).where(
            AHStockPair.is_active.is_(True),
            (
                AHStockPair.effective_start_date.is_(None)
                | (AHStockPair.effective_start_date <= trade_date)
            ),
            (
                AHStockPair.effective_end_date.is_(None)
                | (AHStockPair.effective_end_date >= trade_date)
            ),
        )
        return list(self.db.scalars(statement).all())

    def _connect_channels(self, hk_ts_code: str, trade_date: date) -> list[str]:
        statement = (
            select(HsgtConstituent.connect_type)
            .where(
                HsgtConstituent.ts_code == hk_ts_code,
                HsgtConstituent.trade_date == trade_date,
                HsgtConstituent.connect_type.in_(("SH_HK", "SZ_HK")),
            )
            .order_by(HsgtConstituent.connect_type)
        )
        return list(self.db.scalars(statement).all())

    def _calculate_pair(self, pair: AHStockPair, trade_date: date, channels: list[str]) -> dict:
        a_quote = self.db.scalar(
            select(ADailyQuote).where(
                ADailyQuote.ts_code == pair.a_ts_code,
                ADailyQuote.trade_date == trade_date,
            )
        )
        h_quote = self.db.scalar(
            select(HKDailyQuote).where(
                HKDailyQuote.ts_code == pair.hk_ts_code,
                HKDailyQuote.trade_date == trade_date,
            )
        )
        official = self.db.scalar(
            select(OfficialAHComparison).where(
                and_(
                    OfficialAHComparison.trade_date == trade_date,
                    OfficialAHComparison.a_ts_code == pair.a_ts_code,
                    OfficialAHComparison.hk_ts_code == pair.hk_ts_code,
                )
            )
        )
        base_row = {
            "trade_date": trade_date,
            "a_ts_code": pair.a_ts_code,
            "hk_ts_code": pair.hk_ts_code,
            "a_name": pair.a_name,
            "hk_name": pair.hk_name,
            "is_hk_connect": True,
            "connect_channels": ",".join(channels),
            "official_ah_ratio": official.ah_comparison if official else None,
            "official_ah_premium_pct": official.ah_premium if official else None,
            "official_ha_ratio": official.ha_comparison if official else None,
            "official_ha_premium_pct": official.ha_premium if official else None,
        }
        if a_quote is None or a_quote.close is None:
            return {
                **base_row,
                "calc_status": "MISSING_A_QUOTE",
                "error_message": "缺少 A 股收盘价",
            }
        if h_quote is None or h_quote.close is None:
            return {
                **base_row,
                "calc_status": "MISSING_H_QUOTE",
                "error_message": "缺少 H 股收盘价",
            }
        rate = self.fx_rate_service.get_hkd_cny(trade_date)
        if rate is None:
            return {
                **base_row,
                "a_close_cny": a_quote.close,
                "h_close_hkd": h_quote.close,
                "calc_status": "MISSING_RATE",
                "error_message": "缺少 HKD/CNY 汇率",
            }

        h_close_cny = h_quote.close * rate.rate
        if h_close_cny == Decimal("0"):
            return {
                **base_row,
                "calc_status": "ZERO_H_PRICE",
                "error_message": "H 股人民币价格为 0",
            }
        ah_ratio = a_quote.close / h_close_cny
        premium_pct = (ah_ratio - Decimal("1")) * Decimal("100")
        ha_ratio = self._reverse_ratio(ah_ratio)
        ha_premium_pct = (
            (ha_ratio - Decimal("1")) * Decimal("100") if ha_ratio is not None else None
        )
        official_premium = official.ah_premium if official else None
        official_ha_premium = official.ha_premium if official else None
        diff = premium_pct - official_premium if official_premium is not None else None
        diff_ha = (
            ha_premium_pct - official_ha_premium
            if ha_premium_pct is not None and official_ha_premium is not None
            else None
        )
        return {
            **base_row,
            "a_close_cny": quantize_decimal(a_quote.close, "0.000001"),
            "h_close_hkd": quantize_decimal(h_quote.close, "0.000001"),
            "hkd_cny": quantize_decimal(rate.rate),
            "h_close_cny": quantize_decimal(h_close_cny, "0.000001"),
            "ah_ratio": quantize_decimal(ah_ratio),
            "ah_premium_pct": quantize_decimal(premium_pct),
            "ha_ratio": quantize_decimal(ha_ratio),
            "ha_premium_pct": quantize_decimal(ha_premium_pct),
            "rate_date": rate.rate_date,
            "rate_source": rate.source,
            "rate_fallback": rate.fallback,
            "diff_from_official_pct": quantize_decimal(diff),
            "diff_from_official_ha_pct": quantize_decimal(diff_ha),
            "calc_status": "OK",
        }

    def _reverse_ratio(self, value: Decimal | None) -> Decimal | None:
        if value is None or value == Decimal("0"):
            return None
        return Decimal("1") / value
