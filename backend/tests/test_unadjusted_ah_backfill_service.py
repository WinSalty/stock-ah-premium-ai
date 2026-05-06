from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    EastmoneyUnadjustedDailyQuote,
    OfficialAHComparison,
    WatchlistStock,
    WaterstockFxRateDaily,
)
from app.services.unadjusted_ah_backfill_service import UnadjustedAhBackfillService


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
                EastmoneyUnadjustedDailyQuote(
                    market="A",
                    ts_code="600036.SH",
                    eastmoney_secid="1.600036",
                    trade_date=date(2025, 8, 11),
                    close=Decimal("40"),
                    adjust_type="NONE",
                ),
                EastmoneyUnadjustedDailyQuote(
                    market="HK",
                    ts_code="03968.HK",
                    eastmoney_secid="116.03968",
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
        "EASTMONEY_UNADJUSTED_BACKFILL",
        "TUSHARE_OFFICIAL",
    }
