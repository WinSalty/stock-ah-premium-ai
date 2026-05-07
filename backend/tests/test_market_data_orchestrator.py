from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import ADailyBasic, AStockBasic
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
