from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import OfficialAHComparison, RealtimeQuoteSnapshot, WatchlistStock
from app.services.realtime_market_service import RealtimeMarketDataService
from app.services.realtime_premium_service import RealtimePremiumService


def test_realtime_premium_service_calculates_from_quote_snapshot_table(monkeypatch) -> None:
    """确认实时溢价服务从实时行情快照表读取并计算 AH/H/A。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    quote_time = datetime.combine(date.today(), datetime.min.time())
    monkeypatch.setattr(
        RealtimePremiumService,
        "_is_ah_overlap_realtime_session",
        lambda self: True,
    )
    with Session(engine) as db:
        db.add(AppUser(id=1, username="tester", password_hash="hash", role="ADMIN"))
        watchlist = WatchlistStock(
            user_id=1,
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
            display_name="招商银行",
            preferred_direction="AH",
            target_premium_pct=Decimal("35"),
            is_active=True,
        )
        db.add(watchlist)
        db.add_all(
            [
                RealtimeQuoteSnapshot(
                    market="A",
                    symbol="600036.SH",
                    last_price=Decimal("40.00"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="HK",
                    symbol="03968.HK",
                    last_price=Decimal("32.00"),
                    currency="HKD",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="FX",
                    symbol="HKD/CNY",
                    last_price=Decimal("0.92"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL_FX",
                    quality="REALTIME",
                ),
            ]
        )
        db.commit()

        result = RealtimePremiumService(db).list_realtime_premiums(
            user_id=1,
            only_watchlist=True,
        )
        realtime_row = db.query(OfficialAHComparison).one()

    assert result.total == 1
    item = result.items[0]
    assert item.is_realtime is True
    assert item.quote_quality == "REALTIME"
    assert item.ah_ratio == Decimal("1.35869565")
    assert item.ah_premium_pct == Decimal("35.86956500")
    assert item.ha_ratio == Decimal("0.73529412")
    assert item.ha_premium_pct == Decimal("-26.47058800")
    assert item.metric_direction == "AH"
    assert item.opportunity_status == "TRIGGERED"
    assert item.distance_to_target_pct == Decimal("-0.86956500")
    assert item.source == "MANUAL,MANUAL_FX"
    assert realtime_row.a_close == Decimal("40.000000")
    assert realtime_row.hk_close == Decimal("32.000000")
    assert realtime_row.ah_comparison == Decimal("1.36000000")
    assert realtime_row.ah_premium == Decimal("36.00000000")
    assert realtime_row.ha_comparison == Decimal("0.73529412")
    assert realtime_row.ha_premium == Decimal("-26.47058800")
    assert realtime_row.trade_date == quote_time.date()
    assert realtime_row.is_realtime is True
    assert realtime_row.data_source == "REALTIME_CALC"


def test_realtime_premium_service_does_not_calculate_stale_snapshot_date() -> None:
    """确认历史快照不参与实时溢价计算，也不回写官方 AH 主表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    stale_quote_time = datetime.combine(
        date.today() - timedelta(days=14),
        datetime.min.time(),
    )
    with Session(engine) as db:
        db.add_all(
            [
                RealtimeQuoteSnapshot(
                    market="A",
                    symbol="600036.SH",
                    last_price=Decimal("40.00"),
                    currency="CNY",
                    quote_time=stale_quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="HK",
                    symbol="03968.HK",
                    last_price=Decimal("32.00"),
                    currency="HKD",
                    quote_time=stale_quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="FX",
                    symbol="HKD/CNY",
                    last_price=Decimal("0.92"),
                    currency="CNY",
                    quote_time=stale_quote_time,
                    source="MANUAL_FX",
                    quality="REALTIME",
                ),
            ]
        )
        db.commit()

        item = RealtimePremiumService(db).calculate_pair(
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
            a_name="招商银行",
            hk_name="招商银行",
        )
        realtime_rows = db.query(OfficialAHComparison).all()

    assert item.quote_quality == "STALE"
    assert item.ah_ratio is None
    assert item.ha_premium_pct is None
    assert item.opportunity_status == "DATA_UNAVAILABLE"
    assert realtime_rows == []


def test_realtime_premium_service_rejects_stale_fx_date() -> None:
    """确认 A/H 当天但汇率为旧日期时，不计算实时溢价和阈值距离。

    创建日期：2026-05-08
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    quote_time = datetime.combine(date.today(), datetime.min.time())
    stale_fx_time = datetime.combine(date.today() - timedelta(days=14), datetime.min.time())
    with Session(engine) as db:
        db.add_all(
            [
                RealtimeQuoteSnapshot(
                    market="A",
                    symbol="600036.SH",
                    last_price=Decimal("40.00"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="HK",
                    symbol="03968.HK",
                    last_price=Decimal("32.00"),
                    currency="HKD",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="FX",
                    symbol="HKD/CNY",
                    last_price=Decimal("0.92"),
                    currency="CNY",
                    quote_time=stale_fx_time,
                    source="MANUAL_FX",
                    quality="REALTIME",
                ),
            ]
        )
        db.commit()

        item = RealtimePremiumService(db).calculate_pair(
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
            a_name="招商银行",
            hk_name="招商银行",
        )
        realtime_rows = db.query(OfficialAHComparison).all()

    assert item.quote_quality == "STALE"
    assert item.ah_ratio is None
    assert item.metric_premium_pct is None
    assert item.distance_to_target_pct is None
    assert item.opportunity_status == "DATA_UNAVAILABLE"
    assert realtime_rows == []


def test_realtime_premium_service_skips_persist_outside_trading_session(monkeypatch) -> None:
    """确认非 A/H 重叠交易时段不把实时计算结果写回官方主表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    quote_time = datetime.combine(date.today(), datetime.min.time())
    monkeypatch.setattr(
        RealtimePremiumService,
        "_is_ah_overlap_realtime_session",
        lambda self: False,
    )
    with Session(engine) as db:
        db.add_all(
            [
                RealtimeQuoteSnapshot(
                    market="A",
                    symbol="600036.SH",
                    last_price=Decimal("40.00"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="HK",
                    symbol="03968.HK",
                    last_price=Decimal("32.00"),
                    currency="HKD",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="FX",
                    symbol="HKD/CNY",
                    last_price=Decimal("0.92"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL_FX",
                    quality="REALTIME",
                ),
            ]
        )
        db.commit()

        item = RealtimePremiumService(db).calculate_pair(
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
            a_name="招商银行",
            hk_name="招商银行",
        )
        realtime_rows = db.query(OfficialAHComparison).all()

    assert item.quote_quality == "REALTIME"
    assert item.ah_ratio == Decimal("1.35869565")
    assert realtime_rows == []


def test_realtime_premium_service_keeps_official_row_after_sync(monkeypatch) -> None:
    """确认官方 AH 比价已落库后，实时接口不再覆盖当天官方结果。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    quote_time = datetime.combine(date.today(), datetime.min.time())
    monkeypatch.setattr(
        RealtimePremiumService,
        "_is_ah_overlap_realtime_session",
        lambda self: True,
    )
    with Session(engine) as db:
        db.add(
            OfficialAHComparison(
                trade_date=quote_time.date(),
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                a_name="招商银行",
                hk_name="招商银行",
                a_close=Decimal("37.50"),
                hk_close=Decimal("47.20"),
                ah_comparison=Decimal("0.91000000"),
                ah_premium=Decimal("-9.00000000"),
                ha_comparison=Decimal("1.09890110"),
                ha_premium=Decimal("9.89011000"),
                is_realtime=False,
                data_source="TUSHARE_OFFICIAL",
            )
        )
        db.add_all(
            [
                RealtimeQuoteSnapshot(
                    market="A",
                    symbol="600036.SH",
                    last_price=Decimal("40.00"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="HK",
                    symbol="03968.HK",
                    last_price=Decimal("32.00"),
                    currency="HKD",
                    quote_time=quote_time,
                    source="MANUAL",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="FX",
                    symbol="HKD/CNY",
                    last_price=Decimal("0.92"),
                    currency="CNY",
                    quote_time=quote_time,
                    source="MANUAL_FX",
                    quality="REALTIME",
                ),
            ]
        )
        db.commit()

        item = RealtimePremiumService(db).calculate_pair(
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
            a_name="招商银行",
            hk_name="招商银行",
        )
        official_row = db.query(OfficialAHComparison).one()

    assert item.quote_quality == "REALTIME"
    assert item.ah_ratio == Decimal("1.35869565")
    assert official_row.a_close == Decimal("37.500000")
    assert official_row.hk_close == Decimal("47.200000")
    assert official_row.ah_comparison == Decimal("0.91000000")
    assert official_row.is_realtime is False
    assert official_row.data_source == "TUSHARE_OFFICIAL"


def test_realtime_market_provider_marks_stale_snapshot_quality() -> None:
    """确认旧日期快照即使入库标记 REALTIME，读取时也降级为 STALE。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            RealtimeQuoteSnapshot(
                market="A",
                symbol="600036.SH",
                last_price=Decimal("40.00"),
                currency="CNY",
                quote_time=datetime.combine(
                    date.today() - timedelta(days=1),
                    datetime.min.time(),
                ),
                source="MANUAL",
                quality="REALTIME",
            )
        )
        db.commit()

        quote = RealtimeMarketDataService.from_db(db).provider.get_a_quote("600036.SH")

    assert quote is not None
    assert quote.quality == "STALE"


def test_realtime_premium_service_marks_partial_when_quote_is_missing() -> None:
    """确认缺少任一报价时返回 PARTIAL，不计算阈值触发。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            RealtimeQuoteSnapshot(
                market="A",
                symbol="600036.SH",
                last_price=Decimal("40.00"),
                currency="CNY",
                quote_time=datetime(2026, 5, 5, 10, 30, 0),
                source="MANUAL",
                quality="REALTIME",
            )
        )
        db.commit()

        item = RealtimePremiumService(db).calculate_pair(
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
        )

    assert item.quote_quality == "PARTIAL"
    assert item.ah_premium_pct is None
    assert item.opportunity_status == "DATA_UNAVAILABLE"
