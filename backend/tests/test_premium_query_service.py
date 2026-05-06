from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import (
    ATradeCalendar,
    HKTradeCalendar,
    HsgtConstituent,
    OfficialAHComparison,
    WatchlistStock,
)
from app.services.premium_query_service import PremiumQueryFilters, PremiumQueryService


def add_joint_trade_day(db: Session, trade_date: date) -> None:
    """写入测试用 A/H 联合交易日历。

    创建日期：2026-05-04
    author: sunshengxian
    """

    db.add_all(
        [
            ATradeCalendar(exchange="SSE", cal_date=trade_date, is_open=1),
            HKTradeCalendar(cal_date=trade_date, is_open=1),
        ]
    )


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
            add_joint_trade_day(db, trade_date)
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
            OfficialAHComparison(
                trade_date=latest + timedelta(days=1),
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                a_name="招商银行",
                hk_name="招商银行",
                ah_comparison=Decimal("1.50"),
                ah_premium=Decimal("50"),
                ha_comparison=Decimal("0.66666667"),
                ha_premium=Decimal("-33.33"),
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

        service = PremiumQueryService(db)
        result = service.list_premiums(
            PremiumQueryFilters(trade_date=latest, only_hk_connect=True, direction="HA"),
            page=1,
            page_size=10,
        )
        latest_trade_date = service.latest_trade_date()

    assert result.total == 1
    assert latest_trade_date == latest
    item = result.items[0]
    assert item.hk_ts_code == "03968.HK"
    assert item.connect_channels == "SH_HK"
    assert item.is_watchlist is True
    assert item.metric_direction == "HA"
    assert item.premium_percentile_60 is not None
    assert item.premium_median_60 == Decimal("-16.00000000")
    assert item.premium_p20_60 == Decimal("-16.60000000")
    assert item.premium_p80_60 == Decimal("-15.40000000")
    assert item.opportunity_status == "REACHED"


def test_premium_query_uses_latest_hsgt_date_for_connect_channels() -> None:
    """确认只保留最新港股通名单时，历史 AH 比价仍可按最新名单判断通道。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    premium_date = date(2026, 5, 4)
    latest_hsgt_date = date(2026, 5, 5)
    with Session(engine) as db:
        add_joint_trade_day(db, premium_date)
        db.add(
            OfficialAHComparison(
                trade_date=premium_date,
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                a_name="招商银行",
                hk_name="招商银行",
                ah_comparison=Decimal("1.20"),
                ah_premium=Decimal("20"),
                ha_comparison=Decimal("0.83333333"),
                ha_premium=Decimal("-16.67"),
                is_realtime=False,
                data_source="TUSHARE_OFFICIAL",
            )
        )
        db.add(
            HsgtConstituent(
                trade_date=latest_hsgt_date,
                ts_code="03968.HK",
                connect_type="SZ_HK",
                name="招商银行",
            )
        )
        db.commit()

        service = PremiumQueryService(db)
        result = service.list_premiums(
            PremiumQueryFilters(trade_date=premium_date, only_hk_connect=True),
            page=1,
            page_size=10,
        )

    assert result.total == 1
    assert result.items[0].connect_channels == "SZ_HK"


def test_latest_trade_date_ignores_realtime_only_date_for_full_market_query() -> None:
    """确认少量实时写回日期不会顶掉 AH 机会筛选的最新官方批量日期。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    official_date = date(2026, 5, 4)
    realtime_date = date(2026, 5, 5)
    with Session(engine) as db:
        add_joint_trade_day(db, official_date)
        add_joint_trade_day(db, realtime_date)
        db.add_all(
            [
                OfficialAHComparison(
                    trade_date=official_date,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    a_name="招商银行",
                    hk_name="招商银行",
                    ah_comparison=Decimal("1.20"),
                    ah_premium=Decimal("20"),
                    ha_comparison=Decimal("0.83333333"),
                    ha_premium=Decimal("-16.67"),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                ),
                OfficialAHComparison(
                    trade_date=realtime_date,
                    a_ts_code="601398.SH",
                    hk_ts_code="01398.HK",
                    a_name="工商银行",
                    hk_name="工商银行",
                    ah_comparison=Decimal("1.10"),
                    ah_premium=Decimal("10"),
                    ha_comparison=Decimal("0.90909091"),
                    ha_premium=Decimal("-9.09"),
                    is_realtime=True,
                    data_source="REALTIME_CALC",
                ),
                HsgtConstituent(
                    trade_date=official_date,
                    ts_code="03968.HK",
                    connect_type="SH_HK",
                    name="招商银行",
                ),
            ]
        )
        db.commit()

        service = PremiumQueryService(db)
        result = service.list_premiums(
            PremiumQueryFilters(only_hk_connect=True),
            page=1,
            page_size=10,
        )

    assert service.latest_trade_date() == official_date
    assert service.latest_trade_date(include_realtime=True) == realtime_date
    assert result.total == 1
    assert result.items[0].trade_date == official_date
    assert result.items[0].hk_ts_code == "03968.HK"


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
                ATradeCalendar(exchange="SSE", cal_date=latest, is_open=1),
                HKTradeCalendar(cal_date=latest, is_open=1),
                ATradeCalendar(exchange="SSE", cal_date=latest - timedelta(days=1), is_open=1),
                HKTradeCalendar(cal_date=latest - timedelta(days=1), is_open=1),
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
