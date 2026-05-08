from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import ADailyBasic, AStockBasic, HKFinancialIndicator, HKStockBasic
from app.services.market_data_orchestrator import MarketDataDemand, MarketDataOrchestrator


class RecordingFetcher:
    """记录是否发生真实抓取的测试替身。

    创建日期：2026-05-07
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch_package(self, ts_code: str, package_name: str, run_id: int | None = None) -> int:
        self.calls.append((ts_code, package_name))
        return 0


def _session() -> Session:
    """创建包含本次按需补数表结构的 SQLite 会话。

    创建日期：2026-05-07
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_orchestrator_uses_cache_for_recent_quote_package(monkeypatch) -> None:
    """确认估值数据足够新时不会再次调用 Tushare。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
    db.add(ADailyBasic(ts_code="600036.SH", trade_date=date(2026, 5, 6), close=1))
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_context", lambda ts_code, packages: {"ts_code": ts_code})

    result = service.ensure_for_question(
        "招商银行 600036.SH 估值怎么看",
        {},
        (MarketDataDemand("600036.SH", ("quote_valuation",)),),
    )

    assert result.cache_hit is True
    assert result.fetched_rows == 0
    assert fetcher.calls == []


def test_orchestrator_allows_multi_stock_demands_within_limit(monkeypatch) -> None:
    """确认 5 只以内多股票对比会逐只构造完整市场上下文。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add_all(
        [
            AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"),
            AStockBasic(ts_code="000001.SZ", symbol="000001", name="平安银行", list_status="L"),
        ]
    )
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_context", lambda ts_code, packages: {"ts_code": ts_code})

    result = service.ensure_for_question(
        "比较招商银行和平安银行",
        {},
        (
            MarketDataDemand("600036.SH", ("quote_valuation",)),
            MarketDataDemand("000001.SZ", ("quote_valuation",)),
        ),
    )

    assert result.status == "COMPLETED"
    assert result.context["scope"] == "A_STOCK_MULTI"
    assert [item["stock"].ts_code for item in result.context["items"]] == [
        "600036.SH",
        "000001.SZ",
    ]
    assert fetcher.calls == [("600036.SH", "quote_valuation"), ("000001.SZ", "quote_valuation")]


def test_orchestrator_limits_multi_stock_demands_to_five(monkeypatch) -> None:
    """确认多股补数最多接受 5 只，避免对权限边界内接口做大批量调用。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    stocks = [
        AStockBasic(
            ts_code=f"00000{index}.SZ",
            symbol=f"00000{index}",
            name=f"测试{index}",
            list_status="L",
        )
        for index in range(1, 7)
    ]
    db.add_all(stocks)
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_context", lambda ts_code, packages: {"ts_code": ts_code})

    result = service.ensure_for_question(
        "比较 6 只股票",
        {},
        tuple(
            MarketDataDemand(stock.ts_code, ("quote_valuation",))
            for stock in stocks
        ),
    )

    assert result.status == "COMPLETED"
    assert len(result.stocks) == 5
    assert len(fetcher.calls) == 5


def test_orchestrator_corrects_wrong_routed_code_by_local_name(monkeypatch) -> None:
    """确认路由模型给错股票代码时，本地唯一名称命中优先生效。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add_all(
        [
            AStockBasic(ts_code="600188.SH", symbol="600188", name="兖矿能源", list_status="L"),
            AStockBasic(ts_code="601225.SH", symbol="601225", name="陕西煤业", list_status="L"),
        ]
    )
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_context", lambda ts_code, packages: {"ts_code": ts_code})

    result = service.ensure_for_question(
        "分析一下陕西煤业",
        {},
        (
            MarketDataDemand(
                "600188.SH",
                ("quote_valuation", "financial_statement"),
                market="A",
            ),
        ),
    )

    assert result.stock is not None
    assert result.stock.ts_code == "601225.SH"
    assert fetcher.calls == [
        ("601225.SH", "quote_valuation"),
        ("601225.SH", "financial_statement"),
    ]


def test_orchestrator_report_question_requests_enhanced_research_packages() -> None:
    """确认个股报告问题会自动带上主营、治理和资金流数据包。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = MarketDataOrchestrator(_session(), fetcher=RecordingFetcher())  # type: ignore[arg-type]

    # 报告类问题通常需要从商业结构、财务质量、股东治理和短期资金面交叉验证，
    # 这里锁住关键词触发口径，避免后续只补行情估值导致报告证据链退化。
    packages = service._packages_for_question(  # noqa: SLF001
        "给我写一份招商银行投资分析报告，关注主营业务、股东质押和资金流向"
    )

    assert packages == (
        "quote_valuation",
        "financial_statement",
        "business_profile",
        "dividend_forecast",
        "shareholder_governance",
        "capital_flow_light",
    )


def test_orchestrator_allows_hk_financial_demand(monkeypatch) -> None:
    """确认港股研究问题可触发港股财务包，并按港股市场范围写审计上下文。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add(HKStockBasic(ts_code="02380.HK", name="中国电力", list_status="L"))
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_build_context",
        lambda ts_code, packages: {"ts_code": ts_code, "financial_periods": []},
    )

    result = service.ensure_for_question(
        "中国电力 02380.HK 财务质量怎么看",
        {},
        (MarketDataDemand("02380.HK", ("financial_statement",), market="HK"),),
    )

    assert result.status == "COMPLETED"
    assert result.context["scope"] == "HK_STOCK_SINGLE"
    assert fetcher.calls == [("02380.HK", "financial_statement")]


def test_orchestrator_uses_hk_financial_cache(monkeypatch) -> None:
    """确认港股财务指标足够新时不会重复请求 Tushare。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add(HKStockBasic(ts_code="02380.HK", name="中国电力", list_status="L"))
    db.add(
        HKFinancialIndicator(
            ts_code="02380.HK",
            name="中国电力",
            end_date=date(2026, 3, 31),
            report_type="2026年一季报",
        )
    )
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_context", lambda ts_code, packages: {"ts_code": ts_code})

    result = service.ensure_for_question(
        "中国电力 02380.HK 财务质量怎么看",
        {},
        (MarketDataDemand("02380.HK", ("financial_statement",), market="HK"),),
    )

    assert result.cache_hit is True
    assert fetcher.calls == []


def test_orchestrator_aggregates_ah_cross_market_context(monkeypatch) -> None:
    """确认 A/H 混合上下文会追加港股通和官方价差信息。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
    db.add(HKStockBasic(ts_code="03968.HK", name="招商银行", list_status="L"))
    db.commit()
    service = MarketDataOrchestrator(db, fetcher=RecordingFetcher())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_context", lambda ts_code, packages: {"ts_code": ts_code})
    monkeypatch.setattr(
        service,
        "_build_ah_cross_market_context",
        lambda stocks: [
            {
                "a_ts_code": "600036.SH",
                "hk_ts_code": "03968.HK",
                "is_hk_connect": 1,
                "ha_premium_pct": "-8.5",
            }
        ],
    )

    result = service.ensure_for_question(
        "招商银行港股通和 A/H 价差怎么看",
        {},
        (
            MarketDataDemand("600036.SH", ("financial_statement",), market="A"),
            MarketDataDemand("03968.HK", ("financial_statement",), market="HK"),
        ),
    )

    assert result.context["scope"] == "CROSS_MARKET_MULTI"
    assert result.context["ah_cross_market"][0]["is_hk_connect"] == 1
