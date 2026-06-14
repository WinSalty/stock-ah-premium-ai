"""QMT 回流 ingest 接口测试（鉴权 / 幂等 / COALESCE / 类型反序列化 / 校验 / 批量）。

口径：用 SQLite 内存库 + dialect-aware upsert（生产 MySQL ON DUPLICATE KEY UPDATE，单测 SQLite
ON CONFLICT DO UPDATE，语义一致），覆盖接口的幂等与不被空覆盖行为。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.routes_qmt_ingest as ingest_module
import app.db.models  # noqa: F401 注册全部 ORM 到 Base.metadata（含 qmt_* 四表）
from app.core.config import Settings
from app.db.base import Base
from app.db.models.qmt import (
    QmtAccountDaily,
    QmtDecisionLog,
    QmtOrder,
    QmtPositionSnapshot,
    QmtTrade,
)
from app.db.session import get_db


def _make_db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _client(db: Session, monkeypatch, token: str | None) -> TestClient:
    """最小 app：仅挂回流路由，覆盖 get_db、按需注入内网 token。"""

    app = FastAPI()
    app.include_router(ingest_module.router, prefix="/api")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr(
        ingest_module,
        "get_settings",
        lambda: Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            tushare_token="t",
            tushare_token_file=None,
            qmt_ingest_internal_token=token,
            qmt_ingest_internal_token_file=None,
            watchlist_export_internal_token=None,
            watchlist_export_internal_token_file=None,
        ),
    )
    return TestClient(app)


def _trade_data(traded_id: str = "TR1", **over) -> dict:
    """构造一条 qmt_trade 行（mappers.trade_to_row 口径：JSON 友好值）。"""
    data = {
        "account_id": "A1", "trade_date": "2026-06-13", "ts_code": "600000.SH",
        "qmt_stock_code": "600000.SH", "traded_id": traded_id, "order_id": 1001,
        "trade_side": "BUY", "traded_price": "10.50", "traded_volume": 1000,
        "traded_amount": "10500.00", "traded_time": "2026-06-13T01:30:00",
        "traded_time_east8": "2026-06-13T09:30:00", "signal_trade_date": "2026-06-12",
        "data_source": "CALLBACK",
    }
    data.update(over)
    return data


def _post(client: TestClient, records: list[dict], token: str | None = "secret"):
    headers = {"X-Internal-Token": token} if token else {}
    return client.post(
        "/api/internal/qmt/ingest",
        json={"account_id": "A1", "trade_date": "2026-06-13", "records": records},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


def _decision_data(decision_id: str = "DEC1", **over) -> dict:
    """构造一条 qmt_decision_log 行（JSON 友好值）。"""
    data = {
        "account_id": "A1", "trade_date": "2026-06-13", "decision_id": decision_id,
        "signal_trade_date": "2026-06-12", "ts_code": "600000.SH",
        "decision_type": "BUY_SUBMIT", "decision_stage": "ORDER", "action": "CHASE_LIMIT_UP",
        "strategy_family": "DABAN", "reason": "挂涨停价买入", "reason_code": "order_submitted",
        "factors_snapshot": {"open_pct": 4.1, "seal_to_float_ratio": 0.83},
        "limit_price": "10.50", "plan_volume": 1000, "order_id": 1001,
        "biz_order_no": "20260613_600000.SH_DABAN_1",
        "decided_time": "2026-06-13T01:31:00", "decided_time_east8": "2026-06-13T09:31:00",
    }
    data.update(over)
    return data


def test_ingest_decision_log(monkeypatch) -> None:
    """决策明细表在白名单内、按唯一键幂等 upsert、JSON/数值/时间列正确反序列化。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    r = _post(client, [{"table": "qmt_decision_log", "data": _decision_data()}])
    assert r.status_code == 200
    assert r.json()["by_table"] == {"qmt_decision_log": 1}
    row = db.execute(select(QmtDecisionLog)).scalars().one()
    assert row.decision_type == "BUY_SUBMIT"
    assert row.order_id == 1001
    assert row.limit_price == Decimal("10.50")
    assert row.factors_snapshot["seal_to_float_ratio"] == 0.83
    assert row.decided_time == datetime(2026, 6, 13, 1, 31, 0)
    assert row.decided_time_east8 == datetime(2026, 6, 13, 9, 31, 0)
    # 幂等：同 (account_id, trade_date, decision_id) 重传只更新不新增。
    r2 = _post(client, [{"table": "qmt_decision_log", "data": _decision_data(reason="改了原因")}])
    assert r2.status_code == 200
    rows2 = db.execute(select(QmtDecisionLog)).scalars().all()
    assert len(rows2) == 1
    assert rows2[0].reason == "改了原因"


def test_ingest_503_when_token_not_configured(monkeypatch) -> None:
    """未配置内网 token → 503（默认关闭）。"""
    client = _client(_make_db(), monkeypatch, token=None)
    resp = _post(client, [{"table": "qmt_trade", "data": _trade_data()}], token="x")
    assert resp.status_code == 503


def test_ingest_401_on_bad_or_missing_token(monkeypatch) -> None:
    """配置了 token 但请求头缺失/不符 → 401。"""
    client = _client(_make_db(), monkeypatch, token="secret")
    rec = [{"table": "qmt_trade", "data": _trade_data()}]
    assert _post(client, rec, token=None).status_code == 401
    assert _post(client, rec, token="wrong").status_code == 401


# ---------------------------------------------------------------------------
# 幂等 / 类型 / COALESCE
# ---------------------------------------------------------------------------


def test_ingest_idempotent_latest_wins_and_types(monkeypatch) -> None:
    """同一唯一键重传只更新不新增；非键列后到覆盖；类型按列正确反序列化。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")

    r1 = _post(client, [{"table": "qmt_trade", "data": _trade_data(traded_price="10.50")}])
    assert r1.status_code == 200
    # 同 (account_id, trade_date, traded_id) 重传，改价
    r2 = _post(client, [{"table": "qmt_trade", "data": _trade_data(traded_price="10.80")}])
    assert r2.status_code == 200
    assert r2.json()["by_table"] == {"qmt_trade": 1}

    rows = db.execute(select(QmtTrade)).scalars().all()
    assert len(rows) == 1  # 幂等：未新增第二行
    row = rows[0]
    assert row.traded_price == Decimal("10.80")  # 后到覆盖
    assert isinstance(row.traded_price, Decimal)
    assert row.trade_date == date(2026, 6, 13)
    assert row.traded_time == datetime(2026, 6, 13, 1, 30, 0)
    assert row.traded_volume == 1000
    assert row.signal_trade_date == date(2026, 6, 12)


def test_ingest_coalesce_keeps_filled_signal_trade_date(monkeypatch) -> None:
    """COALESCE 列：已回填的 signal_trade_date 不被后到的显式 None 覆盖。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")

    assert _post(
        client, [{"table": "qmt_trade", "data": _trade_data(signal_trade_date="2026-06-12")}]
    ).status_code == 200
    # 二次回流显式带 signal_trade_date=None（模拟回报阶段尚未回填信号日）
    data2 = _trade_data(signal_trade_date=None, traded_price="11.00")
    assert _post(client, [{"table": "qmt_trade", "data": data2}]).status_code == 200

    row = db.execute(select(QmtTrade)).scalars().one()
    assert row.signal_trade_date == date(2026, 6, 12)  # 不被空覆盖
    assert row.traded_price == Decimal("11.00")        # 普通列仍后到覆盖


def test_ingest_cancel_failed_bool_coerced(monkeypatch) -> None:
    """qmt_order 的 cancel_failed 0/1 → bool 正确落库。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    order = {
        "account_id": "A1", "trade_date": "2026-06-13", "ts_code": "600000.SH",
        "qmt_stock_code": "600000.SH", "order_id": 1001, "trade_side": "BUY",
        "order_volume": 1000, "traded_volume": 1000, "order_status": "TRADED",
        "cancel_failed": 1, "data_source": "CALLBACK",
    }
    assert _post(client, [{"table": "qmt_order", "data": order}]).status_code == 200
    row = db.execute(select(QmtOrder)).scalars().one()
    assert row.cancel_failed is True
    assert row.order_status == "TRADED"


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def test_ingest_422_unknown_table(monkeypatch) -> None:
    """未知表名 → 422（白名单外不落库）。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    resp = _post(client, [{"table": "limit_up_selected_stock", "data": {"x": 1}}])
    assert resp.status_code == 422


def test_ingest_422_missing_unique_key(monkeypatch) -> None:
    """缺唯一键列（traded_id）→ 422（无法去重，杜绝串号）。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    bad = _trade_data()
    bad.pop("traded_id")
    resp = _post(client, [{"table": "qmt_trade", "data": bad}])
    assert resp.status_code == 422


def test_ingest_422_account_id_mismatch_with_envelope(monkeypatch) -> None:
    """评审 P1#9：record.data.account_id 与信封 account_id 不一致 → 422，不静默串账户落库。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    # 信封 account_id=A1（_post 固定），data 里却是 A2。
    resp = _post(client, [{"table": "qmt_trade", "data": _trade_data(account_id="A2")}])
    assert resp.status_code == 422


def test_ingest_422_trade_date_mismatch_with_envelope(monkeypatch) -> None:
    """评审 P1#9：record.data.trade_date 与信封 trade_date 不一致 → 422，不串日落库。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    resp = _post(client, [{"table": "qmt_trade", "data": _trade_data(trade_date="2026-06-14")}])
    assert resp.status_code == 422


def test_ingest_empty_records_ok(monkeypatch) -> None:
    """空 records → 200 空结果（避免执行侧把空批当失败重试）。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    resp = _post(client, [])
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# 批量（多表混合）
# ---------------------------------------------------------------------------


def test_ingest_batch_multi_table(monkeypatch) -> None:
    """一次请求混合四表 → 各表各落 1 行，by_table 计数正确。"""
    db = _make_db()
    client = _client(db, monkeypatch, token="secret")
    records = [
        {"table": "qmt_trade", "data": _trade_data()},
        {
            "table": "qmt_order",
            "data": {
                "account_id": "A1", "trade_date": "2026-06-13", "ts_code": "600000.SH",
                "qmt_stock_code": "600000.SH", "order_id": 1001, "trade_side": "BUY",
                "order_volume": 1000, "traded_volume": 1000, "order_status": "TRADED",
                "cancel_failed": 0, "data_source": "CALLBACK",
            },
        },
        {
            "table": "qmt_position_snapshot",
            "data": {
                "account_id": "A1", "trade_date": "2026-06-13", "snapshot_type": "CLOSE",
                "ts_code": "600000.SH", "qmt_stock_code": "600000.SH", "volume": 1000,
                "can_use_volume": 0, "data_source": "QUERY",
            },
        },
        {
            "table": "qmt_account_daily",
            "data": {
                "account_id": "A1", "trade_date": "2026-06-13", "snapshot_type": "CLOSE",
                "total_asset": "100000.00", "cash": "50000.00", "data_source": "QUERY",
            },
        },
    ]
    resp = _post(client, records)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert body["by_table"] == {
        "qmt_trade": 1, "qmt_order": 1, "qmt_position_snapshot": 1, "qmt_account_daily": 1,
    }
    assert db.execute(select(QmtPositionSnapshot)).scalars().one().volume == 1000
    assert db.execute(select(QmtAccountDaily)).scalars().one().total_asset == Decimal("100000.00")
