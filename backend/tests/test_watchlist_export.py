from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.routes_watchlist_export as export_module
from app.core.config import Settings
from app.db.base import Base
from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
from app.db.session import get_db
from app.schemas.limit_up_watchlist import WATCHLIST_SCHEMA_VERSION


def _make_db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session) -> None:
    """一行 READY 报告(pv1) + 两行选股(pv1)。"""

    cache = LimitUpAnalysisCache(
        trade_date=date(2026, 6, 12),
        model="deepseek-v4-pro",
        prompt_version="pv1",
        data_snapshot_hash="h1",
        status="READY",
        title="复盘",
    )
    db.add(cache)
    db.flush()
    for code, tier, prio in (("300750.SZ", "CHAIN", 1), ("002985.SZ", "FIRST_BOARD", 2)):
        db.add(
            LimitUpSelectedStock(
                trade_date=date(2026, 6, 12),
                target_trade_date=date(2026, 6, 15),
                ts_code=code,
                name="标的",
                board="GEM" if code.startswith("3") else "MAIN",
                tier=tier,
                priority=prio,
                role_tags=["SECTOR_LEADER"],
                boost_conditions=["竞价高开3-5%"],
                market_state="谨慎参与",
                sentiment_cycle="分歧",
                source_analysis_id=cache.id,
                schema_version=WATCHLIST_SCHEMA_VERSION,
                model="deepseek-v4-pro",
                prompt_version="pv1",
            )
        )
    db.commit()


def _client(db: Session, monkeypatch, token: str | None) -> TestClient:
    """最小 app：仅挂导出路由，覆盖 get_db、按需注入内网 token。"""

    app = FastAPI()
    app.include_router(export_module.router, prefix="/api")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr(
        export_module,
        "get_settings",
        lambda: Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            tushare_token="t",
            tushare_token_file=None,
            watchlist_export_internal_token=token,
            watchlist_export_internal_token_file=None,
        ),
    )
    return TestClient(app)


def test_export_503_when_token_not_configured(monkeypatch) -> None:
    """未配置内网 token → 503(默认关闭)。"""

    client = _client(_make_db(), monkeypatch, token=None)
    resp = client.get("/api/internal/watchlist", params={"date": "2026-06-12"})
    assert resp.status_code == 503


def test_export_401_on_bad_or_missing_token(monkeypatch) -> None:
    """配置了 token 但请求头缺失或不符 → 401。"""

    client = _client(_make_db(), monkeypatch, token="secret")
    assert client.get("/api/internal/watchlist", params={"date": "2026-06-12"}).status_code == 401
    bad = client.get(
        "/api/internal/watchlist",
        params={"date": "2026-06-12"},
        headers={"X-Internal-Token": "wrong"},
    )
    assert bad.status_code == 401


def test_export_200_with_data(monkeypatch) -> None:
    """正确 token + 有数据 → 200，契约字段与库内一致(缺省取最新 READY 报告版本)。"""

    db = _make_db()
    _seed(db)
    client = _client(db, monkeypatch, token="secret")
    resp = client.get(
        "/api/internal/watchlist",
        params={"date": "2026-06-12"},
        headers={"X-Internal-Token": "secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == WATCHLIST_SCHEMA_VERSION
    assert body["count"] == 2
    assert body["target_trade_date"] == "2026-06-15"
    assert body["market_state"] == "谨慎参与"
    codes = {it["ts_code"] for it in body["items"]}
    assert codes == {"300750.SZ", "002985.SZ"}
    # 契约不暴露内部审计 blob
    assert "item_json" not in body["items"][0]


def test_export_200_empty_when_no_data(monkeypatch) -> None:
    """无数据 → 200 空集(非 404)，外部轮询友好。"""

    client = _client(_make_db(), monkeypatch, token="secret")
    resp = client.get(
        "/api/internal/watchlist",
        params={"date": "2026-06-12"},
        headers={"X-Internal-Token": "secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
