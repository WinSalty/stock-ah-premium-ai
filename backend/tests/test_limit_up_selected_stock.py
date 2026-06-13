from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
from app.schemas.limit_up_watchlist import (
    WATCHLIST_SCHEMA_VERSION,
    LimitUpWatchlistItem,
    LimitUpWatchlistResponse,
)


def _session() -> Session:
    """创建内存 SQLite 测试会话。

    创建日期：2026-06-13
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _parent_analysis(db: Session) -> int:
    """插入一行 READY 报告作为外键父行，返回其 id。"""

    cache = LimitUpAnalysisCache(
        trade_date=date(2026, 6, 12),
        model="deepseek-v4-pro",
        prompt_version="limit-up-multi-stage-v3",
        data_snapshot_hash="hash-1",
        status="READY",
        title="打板复盘 2026-06-12",
    )
    db.add(cache)
    db.flush()
    return cache.id


def _sample_row(analysis_id: int) -> LimitUpSelectedStock:
    """构造一只创业板连板入选股样例（含 JSON / Decimal 字段）。"""

    return LimitUpSelectedStock(
        trade_date=date(2026, 6, 12),
        target_trade_date=date(2026, 6, 15),
        ts_code="300750.SZ",
        name="宁德时代",
        board="GEM",
        tier="CHAIN",
        board_level=2,
        limit_type="换手",
        leader_strength_score=Decimal("78.50"),
        strength_dim_json={"seal_quality": 80, "theme": 70},
        role_tags=["板块前排"],
        strategy_family="连板接力",
        setup="放量突破",
        action="重点观察",
        sentiment_cycle="发酵",
        market_state="发酵",
        continuation_prob=Decimal("0.3500"),
        next_day_premium_prob=Decimal("0.6000"),
        boost_conditions=[{"type": "竞价", "text": "高开3-6%"}],
        fail_conditions=[{"type": "破位", "text": "破开盘价"}],
        suggested_hold_thesis="题材龙头赌主升",
        seal_ratio_pct=Decimal("12.3000"),
        close=Decimal("45.040000"),
        priority=1,
        item_json={"raw": "snapshot"},
        selection_reason="封板质量好、资金净流入",
        source_analysis_id=analysis_id,
        schema_version=WATCHLIST_SCHEMA_VERSION,
        model="deepseek-v4-pro",
        prompt_version="limit-up-multi-stage-v3",
    )


def test_selected_stock_roundtrip_with_json() -> None:
    """一股一行落库后可读回，JSON / Decimal / 默认 tradable_flag 字段正确。

    创建日期：2026-06-13
    author: claude
    """

    db = _session()
    aid = _parent_analysis(db)
    db.add(_sample_row(aid))
    db.commit()

    got = db.query(LimitUpSelectedStock).filter_by(ts_code="300750.SZ").one()
    assert got.board == "GEM" and got.tier == "CHAIN" and got.board_level == 2
    assert got.role_tags == ["板块前排"]
    assert got.boost_conditions[0]["text"] == "高开3-6%"
    assert got.strength_dim_json["seal_quality"] == 80
    assert got.leader_strength_score == Decimal("78.50")
    # tradable_flag 未显式赋值时走默认 TRADABLE
    assert got.tradable_flag == "TRADABLE"
    assert got.advice_degraded is False


def test_selected_stock_unique_constraint() -> None:
    """同 (trade_date, ts_code, prompt_version) 唯一——整组 delete-then-insert 幂等的依据。

    创建日期：2026-06-13
    author: claude
    """

    db = _session()
    aid = _parent_analysis(db)
    db.add(_sample_row(aid))
    db.commit()
    db.add(_sample_row(aid))
    with pytest.raises(IntegrityError):
        db.commit()


def test_watchlist_contract_from_orm() -> None:
    """契约可从 ORM 行序列化，且对外不暴露 item_json（审计快照）。

    创建日期：2026-06-13
    author: claude
    """

    db = _session()
    aid = _parent_analysis(db)
    db.add(_sample_row(aid))
    db.commit()
    got = db.query(LimitUpSelectedStock).filter_by(ts_code="300750.SZ").one()

    item = LimitUpWatchlistItem.model_validate(got)
    assert item.ts_code == "300750.SZ"
    assert item.board == "GEM"
    assert item.schema_version == WATCHLIST_SCHEMA_VERSION
    assert item.continuation_prob == Decimal("0.3500")
    # 契约不含内部审计 blob
    assert "item_json" not in item.model_dump()

    resp = LimitUpWatchlistResponse(
        trade_date=date(2026, 6, 12),
        target_trade_date=date(2026, 6, 15),
        market_state="发酵",
        count=1,
        items=[item],
    )
    assert resp.count == 1
    assert resp.items[0].tier == "CHAIN"
    assert resp.schema_version == WATCHLIST_SCHEMA_VERSION
