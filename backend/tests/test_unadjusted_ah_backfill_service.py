from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    HistoricalAhUnadjustedBackfillRun,
    OfficialAHComparison,
    TencentUnadjustedDailyQuote,
    WatchlistStock,
    WaterstockFxRateDaily,
)
from app.services.unadjusted_ah_backfill_service import (
    UNADJUSTED_BACKFILL_SOURCE,
    UnadjustedAhBackfillService,
)
from app.services.watchlist_unadjusted_backfill_trigger_service import (
    WatchlistUnadjustedBackfillTriggerService,
)


def test_unadjusted_backfill_replaces_baidu_without_overwriting_tushare() -> None:
    """确认不复权追跑会替换 Baidu 行但不覆盖 Tushare 官方行。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            WatchlistStock(a_ts_code="600036.SH", hk_ts_code="03968.HK", is_active=True)
        )
        db.add_all(
            [
                TencentUnadjustedDailyQuote(
                    market="A",
                    ts_code="600036.SH",
                    tencent_symbol="sh600036",
                    trade_date=date(2025, 8, 11),
                    close=Decimal("40"),
                    adjust_type="NONE",
                ),
                TencentUnadjustedDailyQuote(
                    market="HK",
                    ts_code="03968.HK",
                    tencent_symbol="hk03968",
                    trade_date=date(2025, 8, 11),
                    close=Decimal("30"),
                    adjust_type="NONE",
                ),
                WaterstockFxRateDaily(
                    currency_pair="HKDCNY",
                    rate_date=date(2025, 8, 11),
                    close=Decimal("0.91"),
                ),
                OfficialAHComparison(
                    trade_date=date(2025, 8, 11),
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    data_source="BAIDU_HISTORY_BACKFILL",
                ),
                OfficialAHComparison(
                    trade_date=date(2025, 8, 12),
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    data_source="TUSHARE_OFFICIAL",
                ),
            ]
        )
        db.commit()

        result = UnadjustedAhBackfillService(db).backfill_watchlist(force=True)
        rows = list(db.query(OfficialAHComparison).all())

    assert result.replaced_baidu_rows == 1
    assert result.inserted_rows == 1
    assert len(rows) == 2
    assert {row.data_source for row in rows} == {
        "TENCENT_UNADJUSTED_BACKFILL",
        "TUSHARE_OFFICIAL",
    }


def test_unadjusted_backfill_requires_a_h_and_fx_same_date() -> None:
    """确认 A/H/汇率三方同日齐全时才写入官方 AH 主表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(WatchlistStock(a_ts_code="600036.SH", hk_ts_code="03968.HK", is_active=True))
        db.add_all(
            [
                TencentUnadjustedDailyQuote(
                    market="A",
                    ts_code="600036.SH",
                    tencent_symbol="sh600036",
                    trade_date=date(2025, 8, 11),
                    close=Decimal("40"),
                    adjust_type="NONE",
                ),
                TencentUnadjustedDailyQuote(
                    market="HK",
                    ts_code="03968.HK",
                    tencent_symbol="hk03968",
                    trade_date=date(2025, 8, 11),
                    close=Decimal("30"),
                    adjust_type="NONE",
                ),
                TencentUnadjustedDailyQuote(
                    market="A",
                    ts_code="600036.SH",
                    tencent_symbol="sh600036",
                    trade_date=date(2025, 8, 12),
                    close=Decimal("41"),
                    adjust_type="NONE",
                ),
                TencentUnadjustedDailyQuote(
                    market="HK",
                    ts_code="03968.HK",
                    tencent_symbol="hk03968",
                    trade_date=date(2025, 8, 12),
                    close=Decimal("31"),
                    adjust_type="NONE",
                ),
                WaterstockFxRateDaily(
                    currency_pair="HKDCNY",
                    rate_date=date(2025, 8, 11),
                    close=Decimal("0.91"),
                ),
            ]
        )
        db.commit()

        result = UnadjustedAhBackfillService(db).backfill_watchlist(force=True)
        rows = list(db.query(OfficialAHComparison).all())

    assert result.candidate_rows == 1
    assert result.inserted_rows == 1
    assert len(rows) == 1
    assert rows[0].trade_date == date(2025, 8, 11)


def test_unadjusted_pending_pairs_skip_completed_watchlist_pair() -> None:
    """确认合并同步只处理关注表中未完成追跑的股票对。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                WatchlistStock(
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    is_active=True,
                ),
                WatchlistStock(
                    a_ts_code="000001.SZ",
                    hk_ts_code="00001.HK",
                    is_active=True,
                ),
                HistoricalAhUnadjustedBackfillRun(
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    data_source=UNADJUSTED_BACKFILL_SOURCE,
                    status="COMPLETED",
                ),
            ]
        )
        db.commit()

        pairs = UnadjustedAhBackfillService(db).list_pending_watchlist_pairs()

    assert pairs == [("000001.SZ", "00001.HK")]


def test_watchlist_backfill_trigger_reserves_running_pair_and_allows_failed_retry() -> None:
    """确认关注触发会预占 RUNNING 记录，失败后允许后续重试。

    创建日期：2026-05-07
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = UnadjustedAhBackfillService(db)

        assert WatchlistUnadjustedBackfillTriggerService(db).should_trigger(
            "600036.SH",
            "03968.HK",
        )
        assert service.reserve_pair_for_backfill("600036.SH", "03968.HK")
        assert not WatchlistUnadjustedBackfillTriggerService(db).should_trigger(
            "600036.SH",
            "03968.HK",
        )
        assert not service.reserve_pair_for_backfill("600036.SH", "03968.HK")

        service.mark_pair_failed("600036.SH", "03968.HK", "腾讯接口临时失败")

        assert WatchlistUnadjustedBackfillTriggerService(db).should_trigger(
            "600036.SH",
            "03968.HK",
        )
