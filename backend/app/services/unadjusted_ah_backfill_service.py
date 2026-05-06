from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.db.models.market import (
    EastmoneyUnadjustedDailyQuote,
    HistoricalAhUnadjustedBackfillRun,
    OfficialAHComparison,
    WatchlistStock,
    WaterstockFxRateDaily,
)
from app.services.decimal_utils import quantize_decimal

UNADJUSTED_BACKFILL_SOURCE = "EASTMONEY_UNADJUSTED_BACKFILL"
BAIDU_BACKFILL_SOURCE = "BAIDU_HISTORY_BACKFILL"
HKD_CNY_PAIR = "HKDCNY"
WATERSTOCK_FX_SOURCE = "WATER_STOCK_BAIDU_FX"


@dataclass(frozen=True)
class UnadjustedAhBackfillResult:
    """不复权 AH 比价追跑汇总结果。

    创建日期：2026-05-06
    author: sunshengxian
    """

    pair_count: int
    skipped_completed_pairs: int
    candidate_rows: int
    inserted_rows: int
    skipped_existing_rows: int
    replaced_baidu_rows: int
    skipped_invalid_rows: int


class UnadjustedAhBackfillService:
    """东方财富不复权历史 AH 比价追跑服务。

    创建日期：2026-05-06
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def backfill_watchlist(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        a_ts_code: str | None = None,
        hk_ts_code: str | None = None,
        force: bool = False,
    ) -> UnadjustedAhBackfillResult:
        """按自选或指定 A/H 股票对追跑不复权 AH 比价。

        创建日期：2026-05-06
        author: sunshengxian
        """

        pair_count = 0
        skipped_completed_pairs = 0
        candidate_rows = 0
        inserted_rows = 0
        skipped_existing_rows = 0
        replaced_baidu_rows = 0
        skipped_invalid_rows = 0
        for pair in self._list_pairs(a_ts_code, hk_ts_code):
            pair_count += 1
            if not force and self._is_completed(pair[0], pair[1]):
                skipped_completed_pairs += 1
                continue
            stats = self._backfill_pair(pair[0], pair[1], start_date, end_date)
            candidate_rows += stats.candidate_rows
            inserted_rows += stats.inserted_rows
            skipped_existing_rows += stats.skipped_existing_rows
            replaced_baidu_rows += getattr(stats, "_replaced_baidu_rows", 0)
            skipped_invalid_rows += stats.skipped_invalid_rows
        return UnadjustedAhBackfillResult(
            pair_count=pair_count,
            skipped_completed_pairs=skipped_completed_pairs,
            candidate_rows=candidate_rows,
            inserted_rows=inserted_rows,
            skipped_existing_rows=skipped_existing_rows,
            replaced_baidu_rows=replaced_baidu_rows,
            skipped_invalid_rows=skipped_invalid_rows,
        )

    def _backfill_pair(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        start_date: date | None,
        end_date: date | None,
    ) -> HistoricalAhUnadjustedBackfillRun:
        run = self._mark_started(a_ts_code, hk_ts_code)
        try:
            rows = self._build_candidate_rows(a_ts_code, hk_ts_code, start_date, end_date)
            snapshots: list[dict[str, object]] = []
            skipped_invalid_rows = 0
            for row in rows:
                snapshot = self._build_snapshot(row)
                if snapshot is None:
                    skipped_invalid_rows += 1
                    continue
                snapshots.append(snapshot)
            inserted_rows, replaced_baidu_rows = self._insert_snapshots_if_missing(snapshots)
            run.status = "COMPLETED"
            run.candidate_rows = len(rows)
            run.inserted_rows = inserted_rows
            run.skipped_existing_rows = len(snapshots) - inserted_rows
            run.skipped_invalid_rows = skipped_invalid_rows
            run.first_trade_date = rows[0]["trade_date"] if rows else None
            run.last_trade_date = rows[-1]["trade_date"] if rows else None
            run.completed_at = datetime.now(UTC).replace(tzinfo=None)
            run.last_error = None
            self.db.commit()
            self.db.refresh(run)
            # 复用记录模型承载响应时补充运行期统计，不落库，避免为一次替换计数扩表。
            run._replaced_baidu_rows = replaced_baidu_rows
            return run
        except Exception as exc:
            self.db.rollback()
            run = self._mark_started(a_ts_code, hk_ts_code)
            run.status = "FAILED"
            run.last_error = str(exc)[:512]
            self.db.commit()
            self.db.refresh(run)
            raise

    def _build_candidate_rows(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, object]]:
        # 不依赖交易日历，只取 A 股不复权日线、H 股不复权日线和 HKD/CNY 汇率三方日期交集。
        a_quote = aliased(EastmoneyUnadjustedDailyQuote)
        hk_quote = aliased(EastmoneyUnadjustedDailyQuote)
        fx = WaterstockFxRateDaily
        statement = (
            select(
                a_quote.trade_date.label("trade_date"),
                a_quote.ts_code.label("a_ts_code"),
                hk_quote.ts_code.label("hk_ts_code"),
                a_quote.close.label("a_close"),
                a_quote.pct_chg.label("a_pct_chg"),
                hk_quote.close.label("hk_close"),
                hk_quote.pct_chg.label("hk_pct_chg"),
                fx.close.label("hkd_cny_close"),
            )
            .join(
                hk_quote,
                (hk_quote.trade_date == a_quote.trade_date)
                & (hk_quote.ts_code == hk_ts_code)
                & (hk_quote.market == "HK")
                & (hk_quote.adjust_type == "NONE"),
            )
            .join(
                fx,
                (fx.rate_date == a_quote.trade_date)
                & (fx.currency_pair == HKD_CNY_PAIR)
                & (fx.data_source == WATERSTOCK_FX_SOURCE),
            )
            .where(
                a_quote.ts_code == a_ts_code,
                a_quote.market == "A",
                a_quote.adjust_type == "NONE",
            )
            .order_by(a_quote.trade_date)
        )
        if start_date:
            statement = statement.where(a_quote.trade_date >= start_date)
        if end_date:
            statement = statement.where(a_quote.trade_date <= end_date)
        return [dict(row._mapping) for row in self.db.execute(statement).all()]

    def _build_snapshot(self, row: dict[str, object]) -> dict[str, object] | None:
        a_close = row.get("a_close")
        hk_close = row.get("hk_close")
        hkd_cny_close = row.get("hkd_cny_close")
        if (
            not isinstance(a_close, Decimal)
            or not isinstance(hk_close, Decimal)
            or not isinstance(hkd_cny_close, Decimal)
            or a_close <= 0
            or hk_close <= 0
            or hkd_cny_close <= 0
        ):
            return None
        ah_comparison = quantize_decimal(a_close / (hk_close * hkd_cny_close))
        if ah_comparison is None or ah_comparison <= 0:
            return None
        ah_premium = quantize_decimal((ah_comparison - Decimal("1")) * Decimal("100"))
        official_ah_comparison = ah_comparison.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if official_ah_comparison <= 0:
            return None
        ha_comparison = quantize_decimal(Decimal("1") / official_ah_comparison)
        ha_premium = (
            quantize_decimal((ha_comparison - Decimal("1")) * Decimal("100"))
            if ha_comparison is not None
            else None
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        return {
            "trade_date": row["trade_date"],
            "a_ts_code": row["a_ts_code"],
            "hk_ts_code": row["hk_ts_code"],
            "a_close": a_close,
            "a_pct_chg": row.get("a_pct_chg"),
            "hk_close": hk_close,
            "hk_pct_chg": row.get("hk_pct_chg"),
            "ah_comparison": ah_comparison,
            "ah_premium": ah_premium,
            "ha_comparison": ha_comparison,
            "ha_premium": ha_premium,
            "is_realtime": False,
            "data_source": UNADJUSTED_BACKFILL_SOURCE,
            "source_updated_at": now,
        }

    def _insert_snapshots_if_missing(self, snapshots: list[dict[str, object]]) -> tuple[int, int]:
        if not snapshots:
            return 0, 0
        # Baidu 前复权补数是本次替换对象：先按同日同股票对删除 Baidu 行，再插入东方财富不复权行。
        # Tushare 官方、实时计算或人工行不删除，仍由主表唯一键和 insert ignore
        # 保护，避免覆盖可信来源。
        replaced_baidu_rows = 0
        for snapshot in snapshots:
            result = self.db.execute(
                delete(OfficialAHComparison).where(
                    OfficialAHComparison.trade_date == snapshot["trade_date"],
                    OfficialAHComparison.a_ts_code == snapshot["a_ts_code"],
                    OfficialAHComparison.hk_ts_code == snapshot["hk_ts_code"],
                    OfficialAHComparison.data_source == BAIDU_BACKFILL_SOURCE,
                )
            )
            replaced_baidu_rows += int(result.rowcount or 0)
        dialect_name = self.db.get_bind().dialect.name
        if dialect_name == "sqlite":
            statement = sqlite_insert(OfficialAHComparison).values(snapshots)
            statement = statement.on_conflict_do_nothing(
                index_elements=["trade_date", "a_ts_code", "hk_ts_code"]
            )
        else:
            statement = mysql_insert(OfficialAHComparison).values(snapshots).prefix_with("IGNORE")
        result = self.db.execute(statement)
        return int(result.rowcount or 0), replaced_baidu_rows

    def _mark_started(self, a_ts_code: str, hk_ts_code: str) -> HistoricalAhUnadjustedBackfillRun:
        run = self.db.scalar(
            select(HistoricalAhUnadjustedBackfillRun).where(
                HistoricalAhUnadjustedBackfillRun.a_ts_code == a_ts_code,
                HistoricalAhUnadjustedBackfillRun.hk_ts_code == hk_ts_code,
                HistoricalAhUnadjustedBackfillRun.data_source == UNADJUSTED_BACKFILL_SOURCE,
            )
        )
        if run is None:
            run = HistoricalAhUnadjustedBackfillRun(
                a_ts_code=a_ts_code,
                hk_ts_code=hk_ts_code,
                data_source=UNADJUSTED_BACKFILL_SOURCE,
                status="RUNNING",
            )
            self.db.add(run)
        run.status = "RUNNING"
        run.started_at = datetime.now(UTC).replace(tzinfo=None)
        run.last_error = None
        self.db.commit()
        self.db.refresh(run)
        return run

    def _is_completed(self, a_ts_code: str, hk_ts_code: str) -> bool:
        status = self.db.scalar(
            select(HistoricalAhUnadjustedBackfillRun.status).where(
                HistoricalAhUnadjustedBackfillRun.a_ts_code == a_ts_code,
                HistoricalAhUnadjustedBackfillRun.hk_ts_code == hk_ts_code,
                HistoricalAhUnadjustedBackfillRun.data_source == UNADJUSTED_BACKFILL_SOURCE,
            )
        )
        return status == "COMPLETED"

    def _list_pairs(
        self,
        a_ts_code: str | None,
        hk_ts_code: str | None,
    ) -> list[tuple[str, str]]:
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
            pair = (a_ts_code.upper(), hk_ts_code.upper())
            unique_pairs[pair] = pair
        return list(unique_pairs.values())

    def count_existing_rows(self, a_ts_code: str, hk_ts_code: str) -> int:
        """统计指定股票对主表已有行数，用于测试或人工核验重跑幂等效果。

        创建日期：2026-05-06
        author: sunshengxian
        """

        return int(
            self.db.scalar(
                select(func.count()).select_from(OfficialAHComparison).where(
                    OfficialAHComparison.a_ts_code == a_ts_code,
                    OfficialAHComparison.hk_ts_code == hk_ts_code,
                )
            )
            or 0
        )
