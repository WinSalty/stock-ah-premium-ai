from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import AStockSt
from app.services.sync_service import DATASET_SPECS


def _session() -> Session:
    """创建内存 SQLite 测试会话。

    创建日期：2026-06-13
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_a_stock_st_insert_and_query() -> None:
    """ST 名单按 (ts_code, trade_date) 落库后可读回，字段口径正确。

    创建日期：2026-06-13
    author: claude
    """

    db = _session()
    db.add(
        AStockSt(
            ts_code="600000.SH",
            trade_date=date(2026, 6, 12),
            name="ST示例",
            st_type="P",
            st_type_name="*ST",
        )
    )
    db.commit()
    row = (
        db.query(AStockSt)
        .filter_by(ts_code="600000.SH", trade_date=date(2026, 6, 12))
        .one()
    )
    assert row.name == "ST示例"
    assert row.st_type == "P"
    assert row.st_type_name == "*ST"


def test_a_stock_st_unique_constraint() -> None:
    """同 (ts_code, trade_date) 唯一，重复插入触发约束——这是同步 upsert 幂等的依据。

    创建日期：2026-06-13
    author: claude
    """

    db = _session()
    db.add(AStockSt(ts_code="600000.SH", trade_date=date(2026, 6, 12)))
    db.commit()
    db.add(AStockSt(ts_code="600000.SH", trade_date=date(2026, 6, 12)))
    with pytest.raises(IntegrityError):
        db.commit()


def test_a_stock_st_dataset_spec_registered() -> None:
    """a_stock_st 同步规格已注册，接口名/模型/字段映射/逐日同步口径正确。

    创建日期：2026-06-13
    author: claude
    """

    spec = DATASET_SPECS["a_stock_st"]
    assert spec.api_name == "stock_st"
    assert spec.model is AStockSt
    assert "trade_date" in spec.date_fields
    assert spec.split_by_trade_date is True
    assert spec.rename_map == {"type": "st_type", "type_name": "st_type_name"}
    assert set(spec.fields) >= {"ts_code", "name", "trade_date", "type", "type_name"}
