"""打板回测引擎单测。

覆盖：撮合(B开买/S开卖)、一字买不进剔除、空仓日记0留痕、无量跌停顺延、对照组超额、
    幂等重跑、评估汇总(分布/胜率/分组/IC)、主板vs创业板涨停价。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.market import (
    ATradeCalendar,
    LimitUpBacktestResult,
    LimitUpBacktestRun,
    LimitUpMarketPool,
    TencentUnadjustedDailyQuote,
)
from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
from app.services.limit_up_backtest_service import (
    BacktestConfig,
    LimitUpBacktestService,
    _pearson,
    _percentile,
)


def _make_db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_calendar(db: Session, days: list[int]) -> None:
    """注入 2026-06 指定开市日(回测全程靠日历映射 T→B→S)。"""

    for d in days:
        db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 6, d), is_open=1))
    db.commit()


def _quote(
    db: Session,
    ts_code: str,
    day: int,
    *,
    o: float,
    c: float,
    hi: float,
    lo: float,
    pct: float,
    chg: float,
) -> None:
    """造一条不复权日线(adjust_type='NONE')；o/c/hi/lo=开收高低，pct=涨跌幅，chg=涨跌额。"""

    db.add(
        TencentUnadjustedDailyQuote(
            market="A",
            ts_code=ts_code,
            tencent_symbol=ts_code.replace(".", "").lower(),
            trade_date=date(2026, 6, day),
            open=Decimal(str(o)),
            close=Decimal(str(c)),
            high=Decimal(str(hi)),
            low=Decimal(str(lo)),
            pct_chg=Decimal(str(pct)),
            change_amount=Decimal(str(chg)),
            adjust_type="NONE",
            data_source="TEST",
        )
    )


def _signal(
    db: Session,
    ts_code: str,
    trade_day: int,
    target_day: int,
    *,
    board: str = "MAIN",
    market_state: str = "正常",
    limit_type: str | None = "封板",
    leader_strength_score: float | None = 80.0,
    role: str | None = "MAIN_LEADER",
    strategy_family: str | None = "连板首阴",
    prompt_version: str = "limit-up-multi-stage-v3",
) -> None:
    """造一条选股信号(落 limit_up_selected_stock)。"""

    db.add(
        LimitUpSelectedStock(
            trade_date=date(2026, 6, trade_day),
            target_trade_date=date(2026, 6, target_day),
            ts_code=ts_code,
            tier="FOCUS",
            board=board,
            limit_type=limit_type,
            leader_strength_score=(
                Decimal(str(leader_strength_score)) if leader_strength_score is not None else None
            ),
            role_tags=[role] if role else None,
            strategy_family=strategy_family,
            market_state=market_state,
            tradable_flag=1,
            source_analysis_id=1,
            schema_version="1.0.0",
            model="deepseek-v4-pro",
            prompt_version=prompt_version,
            advice_degraded=False,
        )
    )


# ---------------- 撮合核心 ----------------


def test_basic_match_buy_open_sell_open() -> None:
    """正常撮合：B日开盘买、S日开盘卖，毛收益=(卖-买)/买。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])  # T=10, B=11, S=12
    _signal(db, "600000.SH", trade_day=10, target_day=11)
    # B(11) 非一字：open=10, 振幅有
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    # S(12) open=11.0
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert res.tradable_flag == 1
    assert res.miss_reason is None
    assert float(res.buy_price) == 10.0
    assert float(res.sell_price) == 11.0
    # (11-10)/10 = 0.10
    assert abs(float(res.gross_return_pct) - 0.10) < 1e-9
    assert res.target_trade_date == date(2026, 6, 11)
    assert res.sell_date == date(2026, 6, 12)


def test_one_word_board_not_tradable() -> None:
    """一字/秒封(买入日 hi==low 且上涨)买不进：tradable=0, miss=ONE_WORD, 不计收益。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "600000.SH", trade_day=10, target_day=11, limit_type="一字板")
    # B(11) 一字涨停：open=hi=lo=close, pct_chg>0
    _quote(db, "600000.SH", 11, o=11.0, c=11.0, hi=11.0, lo=11.0, pct=10.0, chg=1.0)
    _quote(db, "600000.SH", 12, o=11.5, c=11.5, hi=11.8, lo=11.2, pct=4.5, chg=0.5)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert res.tradable_flag == 0
    assert res.miss_reason == "ONE_WORD"
    assert res.gross_return_pct is None
    run = db.get(LimitUpBacktestRun, run_id)
    assert run.signal_count == 1
    assert run.tradable_count == 0


def test_empty_gate_day_records_zero() -> None:
    """空仓日(market_state=空仓)：is_empty_day=1, miss=EMPTY_GATE, 不参与不计收益但留痕入分母。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "600000.SH", trade_day=10, target_day=11, market_state="空仓")
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert res.is_empty_day == 1
    assert res.miss_reason == "EMPTY_GATE"
    assert res.tradable_flag == 0
    run = db.get(LimitUpBacktestRun, run_id)
    assert run.empty_day_count == 1
    assert run.signal_count == 1


def test_limit_down_sell_rollover() -> None:
    """卖出日无量跌停封死(hi==low 且下跌)→顺延至下一开市日成交。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12, 15])  # S 原定 12，跌停顺延到 15
    _signal(db, "600000.SH", trade_day=10, target_day=11)
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    # S0(12) 一字跌停：hi==low 且下跌 → 顺延
    _quote(db, "600000.SH", 12, o=9.45, c=9.45, hi=9.45, lo=9.45, pct=-10.0, chg=-1.05)
    # S1(15) 可成交：open=9.6
    _quote(db, "600000.SH", 15, o=9.6, c=9.7, hi=9.9, lo=9.5, pct=1.6, chg=0.15)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert res.limit_down_rollover_days == 1
    assert res.sell_date == date(2026, 6, 15)
    assert float(res.sell_price) == 9.6
    assert float(res.buy_price) == 10.0


def test_gem_limit_up_price() -> None:
    """创业板(300/301前缀)涨停价按 ±20% 计算。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "300750.SZ", trade_day=10, target_day=11, board="GEM")
    # pre_close = close - change = 10.5 - 0.5 = 10.0 → 涨停价 10.0*1.2 = 12.0
    _quote(db, "300750.SZ", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "300750.SZ", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert res.board == "GEM"
    assert float(res.limit_up_price) == 12.0


# ---------------- 对照组 + 超额 ----------------


def _seed_cache_pool(db: Session) -> None:
    """造一份 READY 报告，context_json.limit_up_stocks 含两只涨停票(供对照组回填)。"""

    context = {
        "limit_up_stocks": [
            {"ts_code": "600000.SH", "name": "甲", "board_level": 2, "limit_type": "封板"},
            {"ts_code": "600001.SH", "name": "乙", "board_level": 1, "limit_type": "封板"},
        ]
    }
    db.add(
        LimitUpAnalysisCache(
            trade_date=date(2026, 6, 10),
            model="deepseek-v4-pro",
            prompt_version="limit-up-multi-stage-v3",
            data_snapshot_hash="h1",
            status="READY",
            title="复盘",
            context_json=json.dumps(context, ensure_ascii=False),
        )
    )
    db.commit()


def test_backfill_market_pool_and_excess() -> None:
    """对照组回填(B开→S开同口径)并据此算信号的相对超额。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _seed_cache_pool(db)
    # 对照池两只票行情：600000 隔日 +10%、600001 隔日 0%
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    _quote(db, "600001.SH", 11, o=20.0, c=20.5, hi=20.8, lo=19.9, pct=2.5, chg=0.5)
    _quote(db, "600001.SH", 12, o=20.0, c=20.2, hi=20.4, lo=19.8, pct=-1.5, chg=-0.3)
    db.commit()

    svc = LimitUpBacktestService(db)
    cfg = BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    written = svc.backfill_market_pool(cfg.start_date, cfg.end_date)
    assert written == 2
    pool = db.execute(select(LimitUpMarketPool)).scalars().all()
    assert {p.ts_code for p in pool} == {"600000.SH", "600001.SH"}
    # 对照组当日均值 = (0.10 + 0.0)/2 = 0.05

    # 信号买 600000(隔日 +10%)，相对对照组超额 = 0.10 - 0.05 = 0.05
    _signal(db, "600000.SH", trade_day=10, target_day=11)
    db.commit()
    run_id = svc.run(cfg)
    res = db.execute(
        select(LimitUpBacktestResult).where(
            LimitUpBacktestResult.run_id == run_id,
            LimitUpBacktestResult.ts_code == "600000.SH",
        )
    ).scalar_one()
    assert abs(float(res.control_excess_pct) - 0.05) < 1e-9


def test_idempotent_rerun_same_run_id_no_dup() -> None:
    """同口径重跑复用 run_id 且先清旧明细，无重复行。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "600000.SH", trade_day=10, target_day=11)
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    db.commit()

    svc = LimitUpBacktestService(db)
    cfg = BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    run_id_1 = svc.run(cfg)
    run_id_2 = svc.run(cfg)
    assert run_id_1 == run_id_2
    rows = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id_1)
    ).scalars().all()
    assert len(rows) == 1
    runs = db.execute(select(LimitUpBacktestRun)).scalars().all()
    assert len(runs) == 1


def test_summary_distribution_and_ic() -> None:
    """评估汇总：分布/胜率/分组/IC 均产出且口径正确。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    # 两只可成交：A 龙头高分 +10%，B 杂毛低分 -? ；构造正相关 IC
    _signal(
        db, "600000.SH", trade_day=10, target_day=11, leader_strength_score=90.0, role="MAIN_LEADER"
    )
    _signal(
        db, "600001.SH", trade_day=10, target_day=11, leader_strength_score=40.0, role="STRAGGLER"
    )
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    _quote(db, "600001.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600001.SH", 12, o=9.5, c=9.6, hi=9.9, lo=9.4, pct=-4.0, chg=-0.4)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    run = db.get(LimitUpBacktestRun, run_id)
    summary = json.loads(run.summary_json)
    assert summary["signal_count"] == 2
    assert summary["tradable_count"] == 2
    assert summary["distribution"]["hit_rate"] == 0.5  # 一正一负
    assert "by_role" in summary
    assert summary["by_role"]["MAIN_LEADER"]["mean"] > 0
    assert summary["by_role"]["STRAGGLER"]["mean"] < 0


def _quote_tencent(
    db: Session,
    ts_code: str,
    day: int,
    *,
    o: float,
    c: float,
    hi: float,
    lo: float,
) -> None:
    """造一条腾讯口径不复权日线：change_amount/pct_chg 均为 None(腾讯端点不提供)。"""

    db.add(
        TencentUnadjustedDailyQuote(
            market="A",
            ts_code=ts_code,
            tencent_symbol=ts_code.replace(".", "").lower(),
            trade_date=date(2026, 6, day),
            open=Decimal(str(o)),
            close=Decimal(str(c)),
            high=Decimal(str(hi)),
            low=Decimal(str(lo)),
            pct_chg=None,
            change_amount=None,
            adjust_type="NONE",
            data_source="TENCENT_KLINE",
        )
    )


def test_one_word_detected_via_prev_close_when_no_change_amount() -> None:
    """腾讯数据无 change_amount/pct_chg 时，仍能用前一交易日收盘推导前收盘、判出一字买不进。

    这是真实数据(腾讯只给开收高低量)下"回测不计一字/秒封"硬要求的回归保护。
    """

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])  # T=10, B=11, S=12; 前一开市日(B)=10
    _signal(db, "600000.SH", trade_day=10, target_day=11, limit_type="封板")
    # 前一交易日(10)收盘=10.0 → B(11)前收盘=10.0 → 主板涨停价=11.0
    _quote_tencent(db, "600000.SH", 10, o=9.8, c=10.0, hi=10.1, lo=9.7)
    # B(11) 一字涨停：开=高=低=收=11.0，且 change_amount/pct_chg 均 None
    _quote_tencent(db, "600000.SH", 11, o=11.0, c=11.0, hi=11.0, lo=11.0)
    _quote_tencent(db, "600000.SH", 12, o=11.5, c=11.6, hi=11.8, lo=11.3)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert res.tradable_flag == 0
    assert res.miss_reason == "ONE_WORD"  # 靠前收盘推导出涨停价后判出一字
    assert res.gross_return_pct is None
    assert res.limit_up_price is not None and float(res.limit_up_price) == 11.0


# ---------------- 口径版本(exec/cost/sell) ----------------


def test_seconds_seal_excluded_only_in_v_exec_1() -> None:
    """秒封(高开贴涨停且收盘封死)：v_exec.1 剔除买不进，v_exec.0 视为可成交。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "600000.SH", trade_day=10, target_day=11, limit_type="封板")
    # pre_close=10.0(=11.0-1.0)，涨停价 11.0；开 10.9(距涨停 1%)、收=高=11.0 封死 → 秒封
    _quote(db, "600000.SH", 11, o=10.9, c=11.0, hi=11.0, lo=10.85, pct=10.0, chg=1.0)
    _quote(db, "600000.SH", 12, o=11.5, c=11.6, hi=11.8, lo=11.3, pct=5.0, chg=0.6)
    db.commit()

    d10 = date(2026, 6, 10)
    # v_exec.1(默认)：秒封剔除
    rid1 = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=d10, end_date=d10, exec_version="v_exec.1")
    )
    r1 = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == rid1)
    ).scalar_one()
    assert r1.tradable_flag == 0
    assert r1.miss_reason == "SECONDS_SEAL"

    # v_exec.0：秒封视为可成交(按开盘价买入)
    rid0 = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=d10, end_date=d10, exec_version="v_exec.0")
    )
    r0 = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == rid0)
    ).scalar_one()
    assert r0.tradable_flag == 1
    assert float(r0.buy_price) == 10.9


def test_sell_price_policy_next_close() -> None:
    """sell_price_policy=NEXT_CLOSE：卖出价取 S 日收盘价而非开盘价。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "600000.SH", trade_day=10, target_day=11)
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(
            start_date=date(2026, 6, 10), end_date=date(2026, 6, 10), sell_price_policy="NEXT_CLOSE"
        )
    )
    res = db.execute(
        select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id)
    ).scalar_one()
    assert float(res.sell_price) == 11.2  # S 日收盘价
    assert abs(float(res.gross_return_pct) - (11.2 - 10.0) / 10.0) < 1e-9


def test_unsupported_version_rejected() -> None:
    """日线无法如实实现的口径(VWAP 等)入口直接拒绝，避免静默退化。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    svc = LimitUpBacktestService(db)
    d10 = date(2026, 6, 10)
    with pytest.raises(ValueError, match="cost_version"):
        svc.run(BacktestConfig(start_date=d10, end_date=d10, cost_version="v_cost.2"))
    with pytest.raises(ValueError, match="sell_price_policy"):
        svc.run(BacktestConfig(start_date=d10, end_date=d10, sell_price_policy="VWAP"))


def test_portfolio_metrics_empty_day_zero() -> None:
    """组合级口径：空仓日按 0 计入分母，拉低组合日均收益(而非被排除)。"""

    db = _make_db()
    _seed_calendar(db, [9, 10, 11, 12])
    # T=9 正常日，买入 +10%
    _signal(db, "600000.SH", trade_day=9, target_day=10)
    _quote(db, "600000.SH", 10, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 11, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    # T=10 空仓日，记 0
    _signal(db, "600001.SH", trade_day=10, target_day=11, market_state="空仓")
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 9), end_date=date(2026, 6, 10))
    )
    summary = json.loads(db.get(LimitUpBacktestRun, run_id).summary_json)
    pf = summary["portfolio"]
    assert pf["day_count"] == 2  # 两个信号日
    assert pf["zero_days"] == 1  # 空仓日记 0
    # 组合日均 = (0.10 + 0.0)/2 = 0.05；若错误排除空仓日则会是 0.10
    assert abs(pf["mean_daily"] - 0.05) < 1e-9
    assert pf["day_hit_rate"] == 0.5


def test_prompt_version_dedup_latest_wins() -> None:
    """同票同日跨 prompt_version 并存时：默认只回测最新一批，不双计、不撞唯一键。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    # 旧版本(先写, id 小)：市场状态=参与；新版本(后写, id 大)：市场状态=空仓
    _signal(db, "600000.SH", 10, 11, market_state="参与", prompt_version="v_old")
    _signal(db, "600000.SH", 10, 11, market_state="空仓", prompt_version="v_new")
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(start_date=date(2026, 6, 10), end_date=date(2026, 6, 10))
    )
    rows = (
        db.execute(select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # 仅取最新一批，不双计/不撞唯一键
    assert rows[0].market_state == "空仓"  # 最新版本(v_new)的状态
    assert rows[0].is_empty_day == 1


def test_prompt_version_explicit_selects_that_version() -> None:
    """cfg.prompt_version 指定时只回测该版本(A/B 回放)。"""

    db = _make_db()
    _seed_calendar(db, [10, 11, 12])
    _signal(db, "600000.SH", 10, 11, market_state="参与", prompt_version="v_old")
    _signal(db, "600000.SH", 10, 11, market_state="空仓", prompt_version="v_new")
    _quote(db, "600000.SH", 11, o=10.0, c=10.5, hi=10.8, lo=9.9, pct=5.0, chg=0.5)
    _quote(db, "600000.SH", 12, o=11.0, c=11.2, hi=11.5, lo=10.8, pct=6.0, chg=0.6)
    db.commit()

    run_id = LimitUpBacktestService(db).run(
        BacktestConfig(
            start_date=date(2026, 6, 10), end_date=date(2026, 6, 10), prompt_version="v_old"
        )
    )
    rows = (
        db.execute(select(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run_id))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].market_state == "参与"  # 指定的 v_old


# ---------------- 纯函数 ----------------


def test_percentile_and_pearson() -> None:
    """分位与 Pearson 辅助函数。"""

    assert _percentile([1, 2, 3, 4, 5], 0.0) == 1
    assert _percentile([1, 2, 3, 4, 5], 1.0) == 5
    assert _percentile([1, 2, 3, 4, 5], 0.5) == 3
    # 完全正相关
    ic = _pearson([(1.0, 2.0), (2.0, 4.0), (3.0, 6.0), (4.0, 8.0)])
    assert ic is not None and abs(ic - 1.0) < 1e-9
    # 样本不足
    assert _pearson([(1.0, 2.0)]) is None


# ---------------------------------------------------------------------------
# 评审 D1：go/no-go 结构化裁决（原本只产指标、无判定出口）
# ---------------------------------------------------------------------------
def test_go_no_go_insufficient_sample():
    from app.services.limit_up_backtest_service import evaluate_go_no_go

    v = evaluate_go_no_go({"buyable_return_count": 5, "portfolio": {"day_count": 3}})
    assert v["verdict"] == "INSUFFICIENT"


def test_go_no_go_pass_all_conditions():
    from app.services.limit_up_backtest_service import evaluate_go_no_go

    summary = {
        "buyable_return_count": 50, "control_excess_mean": 0.02,
        "distribution": {"hit_rate": 0.55, "mean": 0.03, "p10": -0.05},
        "portfolio": {"day_count": 20, "cumulative": 0.5},
    }
    assert evaluate_go_no_go(summary)["verdict"] == "GO"


def test_go_no_go_fail_negative_excess():
    from app.services.limit_up_backtest_service import evaluate_go_no_go

    summary = {
        "buyable_return_count": 50, "control_excess_mean": -0.01,
        "distribution": {"hit_rate": 0.55, "mean": 0.03, "p10": -0.05},
        "portfolio": {"day_count": 20, "cumulative": 0.5},
    }
    v = evaluate_go_no_go(summary)
    assert v["verdict"] == "NO_GO"
    assert any("control_excess" in r for r in v["reasons"])


def test_go_no_go_fail_p10_tail_breach():
    from app.services.limit_up_backtest_service import evaluate_go_no_go

    summary = {
        "buyable_return_count": 50, "control_excess_mean": 0.02,
        "distribution": {"hit_rate": 0.55, "mean": 0.03, "p10": -0.20},  # 破 -10% 尾部限
        "portfolio": {"day_count": 20, "cumulative": 0.5},
    }
    assert evaluate_go_no_go(summary)["verdict"] == "NO_GO"
