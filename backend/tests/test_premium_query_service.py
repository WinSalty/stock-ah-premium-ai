from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import HsgtConstituent, OfficialAHComparison, WatchlistStock
from app.services.premium_query_service import PremiumQueryFilters, PremiumQueryService


def test_premium_query_filters_hk_connect_and_returns_metrics() -> None:
    """确认官方溢价查询返回港股通通道、自选和分位指标。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    latest = date(2026, 5, 4)
    with Session(engine) as db:
        for offset in range(3):
            trade_date = latest - timedelta(days=2 - offset)
            db.add(
                OfficialAHComparison(
                    trade_date=trade_date,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    a_name="招商银行",
                    hk_name="招商银行",
                    ah_comparison=Decimal("1.20"),
                    ah_premium=Decimal(str(20 + offset)),
                    ha_comparison=Decimal("0.83333333"),
                    ha_premium=Decimal(str(-17 + offset)),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                )
            )
        db.add(
            OfficialAHComparison(
                trade_date=latest,
                a_ts_code="000001.SZ",
                hk_ts_code="00001.HK",
                a_name="非通",
                hk_name="非通",
                ah_comparison=Decimal("1.10"),
                ah_premium=Decimal("10"),
                ha_comparison=Decimal("0.90909091"),
                ha_premium=Decimal("-9.09"),
                is_realtime=False,
                data_source="TUSHARE_OFFICIAL",
            )
        )
        db.add(
            HsgtConstituent(
                trade_date=latest,
                ts_code="03968.HK",
                connect_type="SH_HK",
                name="招商银行",
            )
        )
        db.add(
            WatchlistStock(
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                display_name="招行",
                preferred_direction="HA",
                target_premium_pct=Decimal("-16"),
                holding_market="A",
                sort_order=1,
                is_active=True,
            )
        )
        db.commit()

        result = PremiumQueryService(db).list_premiums(
            PremiumQueryFilters(trade_date=latest, only_hk_connect=True, direction="HA"),
            page=1,
            page_size=10,
        )

    assert result.total == 1
    item = result.items[0]
    assert item.hk_ts_code == "03968.HK"
    assert item.connect_channels == "SH_HK"
    assert item.is_watchlist is True
    assert item.metric_direction == "HA"
    assert item.premium_percentile_60 is not None
    assert item.opportunity_status == "REACHED"


def test_list_pairs_deduplicates_ex_right_names() -> None:
    """确认 AH 配对下拉按代码去重，并优先展示非除权除息临时名称。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    latest = date(2026, 5, 4)
    with Session(engine) as db:
        db.add_all(
            [
                OfficialAHComparison(
                    trade_date=latest,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    a_name="XD招商银",
                    hk_name="招商银行",
                    ah_comparison=Decimal("1.20"),
                    ah_premium=Decimal("20"),
                    ha_comparison=Decimal("0.83333333"),
                    ha_premium=Decimal("-16.67"),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                ),
                OfficialAHComparison(
                    trade_date=latest - timedelta(days=1),
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    a_name="招商银行",
                    hk_name="招商银行",
                    ah_comparison=Decimal("1.18"),
                    ah_premium=Decimal("18"),
                    ha_comparison=Decimal("0.84745763"),
                    ha_premium=Decimal("-15.25"),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                ),
            ]
        )
        db.commit()

        pairs = PremiumQueryService(db).list_pairs(limit=10)

    assert len(pairs) == 1
    assert pairs[0].a_ts_code == "600036.SH"
    assert pairs[0].hk_ts_code == "03968.HK"
    assert pairs[0].a_name == "招商银行"
    assert pairs[0].latest_trade_date == latest
