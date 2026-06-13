from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.market import AStockBasic, AStockSt, ATradeCalendar
from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
from app.services.limit_up_push_service import LimitUpPushService


def _make_db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _service(db: Session) -> LimitUpPushService:
    return LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
    )


def _seed_base(db: Session) -> None:
    """交易日历(6/1~6/12 开市 + 6/15 T+1) + 基础信息 + ST 名单。"""

    for d in range(1, 13):
        db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 6, d), is_open=1))
    db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 6, 15), is_open=1))
    db.add_all(
        [
            AStockBasic(ts_code="300750.SZ", name="宁德时代", list_date=date(2026, 6, 1)),
            AStockBasic(ts_code="688001.SH", name="科创龙头", list_date=date(2026, 6, 1)),
            AStockBasic(ts_code="600519.SH", name="ST示例", list_date=date(2020, 1, 1)),
        ]
    )
    # 600519 当日 ST → universe 落选
    db.add(AStockSt(ts_code="600519.SH", trade_date=date(2026, 6, 12)))
    db.commit()


def _analysis(db: Session) -> LimitUpAnalysisCache:
    cache = LimitUpAnalysisCache(
        trade_date=date(2026, 6, 12),
        model="deepseek-v4-pro",
        prompt_version="limit-up-multi-stage-v3",
        data_snapshot_hash="h1",
        status="READY",
        title="复盘",
    )
    db.add(cache)
    db.flush()
    return cache


def _stock(ts_code: str, name: str, board_level: int) -> dict:
    return {
        "ts_code": ts_code,
        "name": name,
        "status": f"{board_level}连板",
        "board_level": board_level,
        "limit_type": "换手",
        "seal_ratio_pct": 8.0,
        "first_limit_time": "09:40:00",
        "turnover_rate": 12.0,
        "theme": "人工智能",
        "technical": {"amount_ratio_5d": 2.5, "close": 45.0},
        "selection": {"theme_role": "板块前排", "score_detail": "强", "priority": 1,
                      "selection_reason": "封板质量好"},
    }


def _context(market_emotion: dict) -> dict:
    """含三只入选(创业板正常/科创/主板ST) + chain 先验 + 市场情绪。"""

    return {
        "trade_date": date(2026, 6, 12),
        "market_emotion": market_emotion,
        "pipeline": {
            "selected_first_board_stocks": [],
            "selected_chain_stocks": [
                _stock("300750.SZ", "宁德时代", 2),
                _stock("688001.SH", "科创龙头", 2),
                _stock("600519.SH", "ST示例", 2),
            ],
            "selected_high_board_stocks": [],
            "chain_focus_priors": [
                {
                    "ts_code": "300750.SZ",
                    "continuation_prob": "中",
                    "next_day_premium_prob": "高",
                    "boost_conditions": ["竞价高开3-5%"],
                    "fail_conditions": ["破开盘价"],
                    "suggested_hold_thesis": "打板试错",
                }
            ],
            "stock_supplements": {},
        },
    }


def _healthy_emotion() -> dict:
    """非空仓的市场情绪(启动/发酵档)。"""

    return {
        "limit_up_count": 60,
        "limit_down_count": 3,
        "highest_chain": 3,
        "emotion_cycle": {
            "broken_board_rate_pct": 10.0,
            "highest_chain_change": 0,
            "prev_limit_up_premium": {"avg_pct_chg": 1.5},
            "advancement": {"1进2": {"rate_pct": 30.0, "prev_count": 50}},
        },
    }


def _empty_emotion() -> dict:
    """触发硬否决(涨停枯竭)的空仓市场情绪。"""

    return {
        "limit_up_count": 10,
        "limit_down_count": 3,
        "highest_chain": 1,
        "emotion_cycle": {
            "broken_board_rate_pct": 10.0,
            "highest_chain_change": 0,
            "prev_limit_up_premium": {"avg_pct_chg": 0.2},
            "advancement": {"1进2": {"rate_pct": 30.0, "prev_count": 50}},
        },
    }


def test_persist_writes_passing_stock_with_fields_and_filters() -> None:
    """落表：universe 通过的创业板股写入(字段正确)；科创/ST 被过滤不入表；T+1 映射正确。

    创建日期：2026-06-13
    author: claude
    """

    db = _make_db()
    _seed_base(db)
    svc = _service(db)
    analysis = _analysis(db)
    svc._do_persist_selected_stocks(analysis, _context(_healthy_emotion()))
    db.commit()

    rows = db.query(LimitUpSelectedStock).all()
    # 仅 300750.SZ 入表(688001 科创 NOT_WHITELIST、600519 当日 ST 均落选)
    assert [r.ts_code for r in rows] == ["300750.SZ"]
    row = rows[0]
    assert row.board == "GEM" and row.tier == "CHAIN" and row.board_level == 2
    assert row.target_trade_date == date(2026, 6, 15)  # T+1 经日历映射
    assert row.source_analysis_id == analysis.id
    assert row.leader_strength_score is not None
    assert row.role_tags  # 非空
    assert row.action in {"重点观察", "谨慎观察", "放弃观察"}
    assert row.market_state != "空仓"
    # 连板先验档位 → 数值(中=0.5)，原档位入 item_json/先验
    assert row.continuation_prob is not None
    assert row.boost_conditions == ["竞价高开3-5%"]
    # gate_reasons / threshold_version 折叠进 strength_dim_json
    assert "threshold_version" in row.strength_dim_json
    assert "gate_reasons" in row.strength_dim_json


def test_persist_empty_gate_blocks_all_rows() -> None:
    """空仓闸门：当日所有入表行 action=放弃观察、tradable_flag=BLOCKED、market_state=空仓。"""

    db = _make_db()
    _seed_base(db)
    svc = _service(db)
    analysis = _analysis(db)
    svc._do_persist_selected_stocks(analysis, _context(_empty_emotion()))
    db.commit()

    rows = db.query(LimitUpSelectedStock).all()
    assert rows  # 空仓日仍落表留痕(只是关闸)
    for row in rows:
        assert row.market_state == "空仓"
        assert row.action == "放弃观察"
        assert row.tradable_flag == "BLOCKED"
        assert row.sentiment_cycle in {"冰点", "退潮"}


def test_persist_idempotent_group_replace() -> None:
    """整组 delete-then-insert：同信号日同 prompt_version 重跑不产生重复行(latest-wins)。"""

    db = _make_db()
    _seed_base(db)
    svc = _service(db)
    analysis = _analysis(db)
    ctx = _context(_healthy_emotion())
    svc._do_persist_selected_stocks(analysis, ctx)
    db.commit()
    first_count = db.query(LimitUpSelectedStock).count()
    # 二次重跑(同 trade_date/prompt_version)
    svc._do_persist_selected_stocks(analysis, ctx)
    db.commit()
    assert db.query(LimitUpSelectedStock).count() == first_count == 1


def test_persist_failure_savepoint_does_not_block_report(monkeypatch) -> None:
    """落表中途异常：savepoint 回滚已写部分行、外壳吞异常不抛，报告 READY 不受影响。"""

    db = _make_db()
    _seed_base(db)
    svc = _service(db)
    analysis = _analysis(db)

    def _boom(an, ctx):
        # 模拟落表中途已 add 部分行后抛异常
        svc.db.add(
            LimitUpSelectedStock(
                trade_date=date(2026, 6, 12),
                target_trade_date=date(2026, 6, 15),
                ts_code="300750.SZ",
                tier="CHAIN",
                source_analysis_id=analysis.id,
                schema_version="1.0.0",
                model="m",
                prompt_version="p",
            )
        )
        svc.db.flush()
        raise RuntimeError("落表中途失败")

    monkeypatch.setattr(svc, "_do_persist_selected_stocks", _boom)
    # 不应抛异常(外壳吞掉)
    svc._persist_selected_stocks(analysis, _context(_healthy_emotion()))
    db.commit()
    # savepoint 回滚 → 中途已写的部分行不残留
    assert db.query(LimitUpSelectedStock).count() == 0


def test_backfill_persists_when_missing_and_idempotent() -> None:
    """READY 缓存命中守卫：缺选股行时补落一次；已有则跳过不重复(对齐附录修正#5)。"""

    db = _make_db()
    _seed_base(db)
    svc = _service(db)
    analysis = _analysis(db)
    db.commit()
    ctx = _context(_healthy_emotion())
    assert db.query(LimitUpSelectedStock).count() == 0  # 初始无行
    svc._backfill_selected_stocks_if_missing(analysis, ctx)
    n1 = db.query(LimitUpSelectedStock).count()
    assert n1 == 1  # 补落
    svc._backfill_selected_stocks_if_missing(analysis, ctx)
    assert db.query(LimitUpSelectedStock).count() == n1  # 已有 → 幂等跳过
