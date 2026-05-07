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


def test_orchestrator_skips_multi_stock_demands() -> None:
    """确认多股票需求不会自动补数，保护低积分 Tushare 权限。

    创建日期：2026-05-07
    author: sunshengxian
    """

    db = _session()
    db.add(AStockBasic(ts_code="600036.SH", symbol="600036", name="招商银行", list_status="L"))
    db.commit()
    fetcher = RecordingFetcher()
    service = MarketDataOrchestrator(db, fetcher=fetcher)  # type: ignore[arg-type]

    result = service.ensure_for_question(
        "比较招商银行和平安银行",
        {},
        (
            MarketDataDemand("600036.SH", ("quote_valuation",)),
            MarketDataDemand("000001.SZ", ("quote_valuation",)),
        ),
    )

    assert result.status == "SKIPPED"
    assert fetcher.calls == []
