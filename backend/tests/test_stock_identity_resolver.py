from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import AHStockPair, AStockBasic, HKStockBasic
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
    """确认名称命中多只股票时返回候选，交给后续语义消歧处理。

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


def test_resolver_returns_local_candidates_for_semantic_selection() -> None:
    """确认本地股票名称表可召回简称候选，供 LLM 按用户语义筛选。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add_all(
        [
            AStockBasic(ts_code="000001.SZ", symbol="000001", name="平安银行", list_status="L"),
            AStockBasic(ts_code="601318.SH", symbol="601318", name="中国平安", list_status="L"),
            AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"),
        ]
    )
    db.commit()

    candidates = StockIdentityResolver(db).resolve_candidates("招商和平安银行对比")

    assert {candidate.ts_code for candidate in candidates} == {
        "000001.SZ",
        "601318.SH",
        "600036.SH",
    }


def test_resolver_prioritizes_exact_stock_name_before_generic_suffix() -> None:
    """确认完整股票简称不会被同后缀的宽松片段候选挤出消歧列表。

    创建日期：2026-06-02
    author: codex
    """

    db = _session()
    db.add_all(
        [
            AStockBasic(ts_code="000027.SZ", symbol="000027", name="深圳能源", list_status="L"),
            AStockBasic(ts_code="000096.SZ", symbol="000096", name="广聚能源", list_status="L"),
            AStockBasic(ts_code="000600.SZ", symbol="000600", name="建投能源", list_status="L"),
            AStockBasic(ts_code="601101.SH", symbol="601101", name="昊华能源", list_status="L"),
        ]
    )
    db.commit()

    resolver = StockIdentityResolver(db)
    result = resolver.resolve("帮我分析一下昊华能源")
    candidates = resolver.resolve_candidates("帮我分析一下昊华能源", limit=3)

    # 用户完整点名“昊华能源”时，应直接解析到该股，并在候选截断前排第一；
    # 否则“能源”泛后缀会召回大量同名尾缀股票，导致后续模型没有机会选择 601101.SH。
    assert result.resolved is True
    assert result.identity is not None
    assert result.identity.ts_code == "601101.SH"
    assert [candidate.ts_code for candidate in candidates] == [
        "601101.SH",
        "000027.SZ",
        "000096.SZ",
    ]


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


def test_resolver_returns_ah_pair_for_hk_connect_question() -> None:
    """确认港股通/AH 问法会同时召回 A 股和 H 股候选。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
    db.add(HKStockBasic(ts_code="03968.HK", name="招商银行", list_status="L"))
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

    candidates = StockIdentityResolver(db).resolve_candidates("招商银行港股通和 A/H 价差怎么看")

    assert {candidate.ts_code for candidate in candidates} == {"600036.SH", "03968.HK"}


def test_resolver_resolves_explicit_hk_code() -> None:
    """确认显式港股代码可以回查港股基础表并触发港股补数候选。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add(HKStockBasic(ts_code="02380.HK", name="中国电力", list_status="L"))
    db.commit()

    result = StockIdentityResolver(db).resolve("帮我分析 02380.HK 中国电力")

    assert result.resolved is True
    assert result.identity is not None
    assert result.identity.ts_code == "02380.HK"
    assert result.identity.source == "HK_STOCK_BASIC"


def test_resolver_returns_hk_name_candidate_for_semantic_selection() -> None:
    """确认港股名称可进入语义消歧候选，避免被 A 股基础表边界排除。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add(HKStockBasic(ts_code="02380.HK", name="中国电力", list_status="L"))
    db.commit()

    candidates = StockIdentityResolver(db).resolve_candidates("中国电力怎么看")

    assert [candidate.ts_code for candidate in candidates] == ["02380.HK"]
