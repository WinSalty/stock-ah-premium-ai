from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import RealtimeQuoteSnapshot, WatchlistStock
from app.services.realtime_premium_service import RealtimePremiumService


def test_realtime_premium_service_calculates_from_quote_snapshot_table() -> None:
    """确认实时溢价服务从实时行情快照表读取并计算 AH/H/A。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    quote_time = datetime(2026, 5, 5, 10, 30, 0)
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

    assert result.total == 1
    item = result.items[0]
    assert item.is_realtime is True
    assert item.quote_quality == "REALTIME"
    assert item.ah_ratio == Decimal("1.35869565")
    assert item.ah_premium_pct == Decimal("35.86956500")
    assert item.metric_direction == "AH"
    assert item.opportunity_status == "TRIGGERED"
    assert item.distance_to_target_pct == Decimal("-0.86956500")
    assert item.source == "MANUAL,MANUAL_FX"


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
