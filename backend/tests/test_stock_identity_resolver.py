from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import AHStockPair, AStockBasic
from app.services.stock_identity_resolver import StockIdentityResolver


def _session() -> Session:
    """创建轻量 SQLite 会话用于股票解析单测。

    创建日期：2026-05-07
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_resolver_resolves_explicit_a_share_code() -> None:
    """确认显式 A 股代码必须回查本地基础表后才算解析成功。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
    db.commit()

    result = StockIdentityResolver(db).resolve("帮我分析 600036.SH")

    assert result.resolved is True
    assert result.identity is not None
    assert result.identity.name == "招商银行"


def test_resolver_stops_on_ambiguous_name() -> None:
    """确认名称命中多只股票时不自动补数，避免消耗 15000 积分权限。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add_all(
        [
            AStockBasic(ts_code="000001.SZ", symbol="000001", name="平安银行", list_status="L"),
            AStockBasic(ts_code="601318.SH", symbol="601318", name="中国平安", list_status="L"),
        ]
    )
    db.commit()

    result = StockIdentityResolver(db).resolve("平安怎么看")

    assert result.resolved is False
    assert len(result.ambiguous_candidates) == 2


def test_resolver_maps_ah_hk_name_to_a_code() -> None:
    """确认 AH 港股简称可以保守映射回单只 A 股代码。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
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

    result = StockIdentityResolver(db).resolve("03968 港股招商银行投资报告")

    assert result.resolved is True
    assert result.identity is not None
    assert result.identity.ts_code == "600036.SH"
