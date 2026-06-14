"""QMT 实盘复盘看板只读接口测试（权限 / 当日汇总 / 成交信号 join / 持仓 / 历史绩效）。

口径：SQLite 内存库，挂真实 routes_qmt_review 路由 + 真实 require_permission("qmt_review")，
仅覆盖 get_db 与 get_current_user（用 ADMIN/USER 两种角色用户走真实权限模板），验证：
- 非 admin（USER 角色，无 qmt_review）→ 403；admin → 200。
- 当日汇总盈亏/成交/委托统计口径正确。
- 成交明细回挂信号侧策略/角色/名称。
- 历史净值归一、累计收益、回撤、日胜率正确。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.api.routes_qmt_review as review_module
import app.db.models  # noqa: F401 注册全部 ORM 到 Base.metadata
from app.api.deps_auth import get_current_user
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import AStockBasic
from app.db.models.notification import LimitUpSelectedStock
from app.db.models.qmt import (
    QmtAccountDaily,
    QmtDecisionLog,
    QmtOrder,
    QmtPositionSnapshot,
    QmtTrade,
)
from app.db.session import get_db

ACCOUNT = "A1"
D1 = date(2026, 6, 12)  # 历史首日
D2 = date(2026, 6, 13)  # 当日
SIG = date(2026, 6, 11)  # 信号日 T


def _make_db() -> Session:
    """内存库 + 建表 + 种子数据。"""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    _seed(db)
    return db


def _seed(db: Session) -> None:
    """构造一套自洽的复盘场景。"""
    # 用户：admin（有 qmt_review）/ user（无）。
    db.add_all(
        [
            AppUser(id=1, username="admin", password_hash="x", role="ADMIN", is_active=True),
            AppUser(id=2, username="user", password_hash="x", role="USER", is_active=True),
        ]
    )
    # 证券名称兜底。
    db.add_all(
        [
            AStockBasic(ts_code="600000.SH", name="浦发银行"),
            AStockBasic(ts_code="600001.SH", name="测试卖出股"),
            AStockBasic(ts_code="600002.SH", name="买不进股"),
        ]
    )
    # 账户日快照（CLOSE）：D1 起点，D2 +2%。
    db.add_all(
        [
            QmtAccountDaily(
                account_id=ACCOUNT, trade_date=D1, snapshot_type="CLOSE",
                total_asset=Decimal("1000000"), cash=Decimal("1000000"),
                market_value=Decimal("0"), net_cash_flow=Decimal("0"),
            ),
            QmtAccountDaily(
                account_id=ACCOUNT, trade_date=D2, snapshot_type="CLOSE",
                total_asset=Decimal("1020000"), cash=Decimal("995000"),
                market_value=Decimal("15000"), net_cash_flow=Decimal("0"),
                prev_total_asset=Decimal("1000000"), daily_pnl=Decimal("20000"),
                daily_return=Decimal("0.02"),
            ),
        ]
    )
    # D2 收盘持仓：浮盈 5000。
    db.add(
        QmtPositionSnapshot(
            account_id=ACCOUNT, trade_date=D2, snapshot_type="CLOSE",
            ts_code="600000.SH", qmt_stock_code="600000.SH", volume=1000, can_use_volume=0,
            avg_price=Decimal("10"), last_price=Decimal("15"), market_value=Decimal("15000"),
            float_profit=Decimal("5000"), profit_rate=Decimal("0.5"),
        )
    )
    # D2 成交：1 买 1 卖。
    db.add_all(
        [
            QmtTrade(
                account_id=ACCOUNT, trade_date=D2, ts_code="600000.SH", qmt_stock_code="600000.SH",
                traded_id="TR1", order_id=1001, trade_side="BUY", traded_price=Decimal("10"),
                traded_volume=1000, traded_amount=Decimal("10000"),
                traded_time=datetime(2026, 6, 13, 1, 30), traded_time_east8=datetime(2026, 6, 13, 9, 30),
                signal_trade_date=SIG,
            ),
            QmtTrade(
                account_id=ACCOUNT, trade_date=D2, ts_code="600001.SH", qmt_stock_code="600001.SH",
                traded_id="TR2", order_id=1002, trade_side="SELL", traded_price=Decimal("12"),
                traded_volume=500, traded_amount=Decimal("6000"),
                traded_time=datetime(2026, 6, 13, 2, 0), traded_time_east8=datetime(2026, 6, 13, 10, 0),
            ),
        ]
    )
    # D2 BUY 委托：一成一撤（买不进），用于成功率/买不进口径。
    db.add_all(
        [
            QmtOrder(
                account_id=ACCOUNT, trade_date=D2, ts_code="600000.SH", qmt_stock_code="600000.SH",
                order_id=1001, trade_side="BUY", order_volume=1000, traded_volume=1000,
                order_status="TRADED",
            ),
            QmtOrder(
                account_id=ACCOUNT, trade_date=D2, ts_code="600002.SH", qmt_stock_code="600002.SH",
                order_id=1003, trade_side="BUY", order_volume=1000, traded_volume=0,
                order_status="CANCELLED",
            ),
        ]
    )
    # 信号侧 join 来源（TR1 的 signal_trade_date + ts_code）。
    db.add(
        LimitUpSelectedStock(
            trade_date=SIG, target_trade_date=D2, ts_code="600000.SH", name="浦发银行",
            tier="CORE", strategy_family="打板", setup="首板", role_tags=["龙头"],
            market_state="进攻", leader_strength_score=Decimal("88"),
            # 审计/版本字段 NOT NULL（FK 在 SQLite 默认不校验，给占位值即可）。
            source_analysis_id=1, schema_version="1", model="test", prompt_version="v1",
        )
    )
    # 决策链路：达标 → 买入提交（order_id=1001 串联 TR1 成交）。
    db.add_all(
        [
            QmtDecisionLog(
                account_id=ACCOUNT, trade_date=D2, decision_id="DEC1", signal_trade_date=SIG,
                ts_code="600000.SH", decision_type="SIGNAL_QUALIFIED", decision_stage="STRATEGY",
                action="CHASE_LIMIT_UP", strategy_family="打板", reason="封流比达标", reason_code="qualified",
                decided_time=datetime(2026, 6, 13, 1, 25), decided_time_east8=datetime(2026, 6, 13, 9, 25),
            ),
            QmtDecisionLog(
                account_id=ACCOUNT, trade_date=D2, decision_id="DEC2", signal_trade_date=SIG,
                ts_code="600000.SH", decision_type="BUY_SUBMIT", decision_stage="ORDER",
                action="CHASE_LIMIT_UP", strategy_family="打板", reason="挂涨停价买入", reason_code="order_submitted",
                order_id=1001, limit_price=Decimal("10"), plan_volume=1000,
                decided_time=datetime(2026, 6, 13, 1, 31), decided_time_east8=datetime(2026, 6, 13, 9, 31),
            ),
        ]
    )
    db.commit()


def _client(db: Session, user_id: int) -> TestClient:
    """挂真实路由，覆盖 get_db 与 get_current_user（按 user_id 选角色）。"""
    app = FastAPI()
    app.include_router(review_module.router, prefix="/api")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: db.get(AppUser, user_id)
    return TestClient(app)


# ----------------------------- 权限 -----------------------------
def test_user_forbidden() -> None:
    """USER 角色无 qmt_review → 403。"""
    db = _make_db()
    resp = _client(db, user_id=2).get("/api/review/accounts")
    assert resp.status_code == 403


def test_admin_lists_accounts() -> None:
    """ADMIN → 200，返回已回流账户。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["account_id"] == ACCOUNT
    assert data[0]["latest_trade_date"] == D2.isoformat()


# ----------------------------- 当日汇总 -----------------------------
def test_daily_summary() -> None:
    """当日盈亏/浮动/已实现近似/成交/委托统计口径正确。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/daily", params={"trade_date": D2.isoformat()})
    assert resp.status_code == 200
    d = resp.json()
    assert d["has_data"] is True
    assert Decimal(d["daily_pnl"]) == Decimal("20000")
    assert Decimal(d["float_pnl"]) == Decimal("5000")
    assert Decimal(d["realized_pnl_approx"]) == Decimal("15000")
    assert d["buy_count"] == 1 and d["sell_count"] == 1
    assert Decimal(d["buy_amount"]) == Decimal("10000")
    assert Decimal(d["sell_amount"]) == Decimal("6000")
    assert Decimal(d["order_success_rate"]) == Decimal("0.5")  # 2 单 1 成
    assert d["no_fill_count"] == 1  # 撤单零成交


def test_daily_summary_defaults_to_latest() -> None:
    """不传 trade_date 默认取最新交易日（D2）。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/daily")
    assert resp.status_code == 200
    assert resp.json()["trade_date"] == D2.isoformat()


# ----------------------------- 成交明细 + 信号 join -----------------------------
def test_trades_signal_join() -> None:
    """成交明细回挂信号侧策略/角色/名称；TR1 命中信号，TR2 仅名称兜底。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/trades", params={"trade_date": D2.isoformat()})
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 2
    by_id = {it["traded_id"]: it for it in page["items"]}
    tr1 = by_id["TR1"]
    assert tr1["name"] == "浦发银行"
    assert tr1["strategy_family"] == "打板"
    assert tr1["setup"] == "首板"
    assert tr1["role"] == "龙头"
    assert tr1["market_state"] == "进攻"
    tr2 = by_id["TR2"]
    assert tr2["name"] == "测试卖出股"  # a_stock_basic 兜底
    assert tr2["strategy_family"] is None  # 无回挂信号


def test_trades_side_filter() -> None:
    """方向过滤只返回 BUY。"""
    db = _make_db()
    resp = _client(db, user_id=1).get(
        "/api/review/trades", params={"trade_date": D2.isoformat(), "side": "BUY"}
    )
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 1
    assert page["items"][0]["trade_side"] == "BUY"


# ----------------------------- 持仓 -----------------------------
def test_positions() -> None:
    """收盘持仓返回含浮盈与名称。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/positions", params={"trade_date": D2.isoformat()})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["ts_code"] == "600000.SH"
    assert rows[0]["name"] == "浦发银行"
    assert Decimal(rows[0]["float_profit"]) == Decimal("5000")


def test_positions_carry_forward() -> None:
    """指定无快照日时回退到 ≤该日 最近 CLOSE 日。"""
    db = _make_db()
    resp = _client(db, user_id=1).get(
        "/api/review/positions", params={"trade_date": date(2026, 6, 20).isoformat()}
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1  # 回退到 D2 持仓


# ----------------------------- 历史净值 -----------------------------
def test_history_metrics() -> None:
    """净值归一 + 累计收益 + 回撤 + 日胜率口径正确。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/history")
    assert resp.status_code == 200
    h = resp.json()
    assert h["trading_days"] == 2
    assert len(h["points"]) == 2
    assert Decimal(h["points"][0]["nav"]) == Decimal("1")  # 起点归一
    assert Decimal(h["points"][1]["nav"]) == Decimal("1.02")
    assert Decimal(h["cumulative_return"]) == Decimal("0.02")
    assert Decimal(h["max_drawdown"]) == Decimal("0")  # 单调上行无回撤
    assert Decimal(h["win_rate"]) == Decimal("1")  # 唯一一日上涨
    assert h["sharpe"] is None  # 仅 1 个收益样本无法算标准差


def test_history_empty_account() -> None:
    """未知账户返回空净值。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/history", params={"account_id": "NOPE"})
    assert resp.status_code == 200
    assert resp.json()["trading_days"] == 0


# ----------------------------- 信号选股 -----------------------------
def test_selection() -> None:
    """信号选股视图返回入选股决策字段（无 READY 缓存时回落到选股表最新版本）。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/selection")
    assert resp.status_code == 200
    d = resp.json()
    assert d["trade_date"] == SIG.isoformat()
    assert d["prompt_version"] == "v1"  # 无 READY 缓存 → 回落选股表版本
    assert d["count"] == 1
    item = d["items"][0]
    assert item["ts_code"] == "600000.SH"
    assert item["strategy_family"] == "打板"
    assert item["setup"] == "首板"
    assert item["role_tags"] == ["龙头"]
    assert item["tradable_flag"] == "TRADABLE"


def test_selection_forbidden_for_user() -> None:
    """USER 角色无 qmt_review → 选股接口 403。"""
    db = _make_db()
    assert _client(db, user_id=2).get("/api/review/selection").status_code == 403


# ----------------------------- 决策流水 / 闭环 -----------------------------
def test_decisions() -> None:
    """决策流水按交易日返回，按决策时刻倒序（BUY_SUBMIT 在 SIGNAL_QUALIFIED 之前）。"""
    db = _make_db()
    resp = _client(db, user_id=1).get("/api/review/decisions", params={"trade_date": D2.isoformat()})
    assert resp.status_code == 200
    d = resp.json()
    assert d["total"] == 2
    assert d["items"][0]["decision_type"] == "BUY_SUBMIT"  # 09:31 在前
    assert d["items"][0]["name"] == "浦发银行"
    assert d["items"][1]["decision_type"] == "SIGNAL_QUALIFIED"


def test_decisions_type_filter() -> None:
    """按决策类型过滤。"""
    db = _make_db()
    resp = _client(db, user_id=1).get(
        "/api/review/decisions", params={"decision_type": "BUY_SUBMIT"}
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["total"] == 1
    assert d["items"][0]["order_id"] == 1001


def test_decision_closeloop() -> None:
    """单票闭环串联：入选信号 + 决策时间线(升序) + 关联成交(order_id=1001→TR1)。"""
    db = _make_db()
    resp = _client(db, user_id=1).get(
        "/api/review/decision-closeloop",
        params={"ts_code": "600000.SH", "signal_date": SIG.isoformat()},
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["name"] == "浦发银行"
    assert d["selection"] is not None
    assert d["selection"]["strategy_family"] == "打板"
    # 时间线升序：SIGNAL_QUALIFIED(09:25) 在 BUY_SUBMIT(09:31) 之前
    assert [t["decision_type"] for t in d["timeline"]] == ["SIGNAL_QUALIFIED", "BUY_SUBMIT"]
    # 关联成交：order_id=1001 命中 TR1 买入
    assert len(d["fills"]) == 1
    assert d["fills"][0]["traded_id"] == "TR1"
    assert d["fills"][0]["trade_side"] == "BUY"


def test_decisions_forbidden_for_user() -> None:
    """USER 角色无 qmt_review → 决策接口 403。"""
    db = _make_db()
    assert _client(db, user_id=2).get("/api/review/decisions").status_code == 403


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
