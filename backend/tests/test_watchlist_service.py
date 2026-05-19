from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import AHStockPair, AStockBasic, HKStockBasic
from app.schemas.watchlist import WatchlistCreate
from app.services.watchlist_service import WatchlistService


def _session() -> Session:
    """创建自选服务测试会话。

    创建日期：2026-05-19
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_create_a_only_watchlist_clears_pair_only_alerts() -> None:
    """确认单 A 股关注只保留 A 股股价提醒，不保存溢价阈值和 H 股提醒。

    创建日期：2026-05-19
    author: sunshengxian
    """

    db = _session()
    item = WatchlistService(db).create(
        WatchlistCreate(
            target_type="A_ONLY",
            a_ts_code="600519.SH",
            target_premium_pct=Decimal("20"),
            push_enabled=False,
            a_price_alert_enabled=True,
            a_price_alert_target_price=Decimal("1600"),
            h_price_alert_enabled=True,
            h_price_alert_target_price=Decimal("100"),
        )
    )

    assert item.target_type == "A_ONLY"
    assert item.target_key == "600519.SH"
    assert item.a_ts_code == "600519.SH"
    assert item.hk_ts_code is None
    assert item.target_premium_pct is None
    assert item.a_price_alert_enabled is True
    assert item.h_price_alert_enabled is False
    assert item.h_price_alert_target_price is None
    assert item.holding_market == "A"


def test_search_watchlist_candidates_by_target_type() -> None:
    """确认新增关注候选可分别从 A 股、港股和 AH 配对基础表召回。

    创建日期：2026-05-19
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
    db.add(HKStockBasic(ts_code="00700.HK", name="腾讯控股", list_status="L"))
    db.add(
        AHStockPair(
            a_ts_code="600036.SH",
            hk_ts_code="03968.HK",
            a_name="招商银行",
            hk_name="招商银行",
            is_active=True,
        )
    )
    db.commit()
    service = WatchlistService(db)

    a_candidates = service.search_candidates("A_ONLY", "招商", 10)
    h_candidates = service.search_candidates("H_ONLY", "腾讯", 10)
    pair_candidates = service.search_candidates("PAIR", "03968", 10)

    assert a_candidates[0].a_ts_code == "600036.SH"
    assert h_candidates[0].hk_ts_code == "00700.HK"
    assert pair_candidates[0].a_ts_code == "600036.SH"
    assert pair_candidates[0].hk_ts_code == "03968.HK"
