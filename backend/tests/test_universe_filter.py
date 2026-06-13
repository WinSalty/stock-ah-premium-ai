from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import AStockBasic, AStockSt, ATradeCalendar
from app.services.universe_filter import (
    build_universe_context,
    evaluate_universe,
    filter_for_trade_date,
    limit_down_price,
    limit_up_price,
)


def _session() -> Session:
    """创建内存 SQLite 测试会话。

    创建日期：2026-06-13
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_l1_whitelist_and_board() -> None:
    """L1：主板/创业板通过且 board 正确；科创/北交/B 股落选 NOT_WHITELIST，且不因缺数据报错。"""

    v_main = evaluate_universe(
        "600000.SH", "浦发银行", date(2026, 6, 12),
        is_st_on_date=False, list_date=date(1999, 11, 10), trade_days_since_list=9999,
    )
    assert v_main.passed and v_main.board == "MAIN"
    v_gem = evaluate_universe(
        "300750.SZ", "宁德时代", date(2026, 6, 12),
        is_st_on_date=False, list_date=date(2018, 6, 11), trade_days_since_list=9999,
    )
    assert v_gem.passed and v_gem.board == "GEM"
    # 科创 688/689、北交 8xx/920、B 股 900 全部落选；list_date/trade_days 缺失也不报错（短路）
    for code in ["688981.SH", "689009.SH", "830001.BJ", "920001.BJ", "900001.SH"]:
        v = evaluate_universe(
            code, "示例", date(2026, 6, 12),
            is_st_on_date=False, list_date=None, trade_days_since_list=None,
        )
        assert not v.passed and v.reason == "NOT_WHITELIST" and v.board is None


def test_l2_st_point_in_time() -> None:
    """L2：当日 ST 落选；同票历史非 ST 日通过（验证按 T 当日而非当前状态，无未来函数）。"""

    today = evaluate_universe(
        "600000.SH", "示例", date(2026, 6, 12),
        is_st_on_date=True, list_date=date(2000, 1, 1), trade_days_since_list=9999,
    )
    assert not today.passed and today.reason == "ST"
    history = evaluate_universe(
        "600000.SH", "示例", date(2020, 1, 1),
        is_st_on_date=False, list_date=date(2000, 1, 1), trade_days_since_list=9999,
    )
    assert history.passed


def test_l2_suspect_st_by_name() -> None:
    """L2 兜底：a_stock_st 未命中但名称含 ST → SUSPECT_ST（防同步滞后）。"""

    v = evaluate_universe(
        "600000.SH", "ST长油", date(2026, 6, 12),
        is_st_on_date=False, list_date=date(2000, 1, 1), trade_days_since_list=9999,
    )
    assert not v.passed and v.reason == "SUSPECT_ST"


def test_l3_new_listing_boundary() -> None:
    """L3：上市未满 6 个交易日落选；恰好 6 个通过；list_date 缺失保守落选。"""

    v5 = evaluate_universe(
        "600001.SH", "次新", date(2026, 6, 12),
        is_st_on_date=False, list_date=date(2026, 6, 1), trade_days_since_list=5,
    )
    assert not v5.passed and v5.reason == "NEW_LISTING"
    v6 = evaluate_universe(
        "600001.SH", "次新", date(2026, 6, 12),
        is_st_on_date=False, list_date=date(2026, 6, 1), trade_days_since_list=6,
    )
    assert v6.passed
    vno = evaluate_universe(
        "600001.SH", "次新", date(2026, 6, 12),
        is_st_on_date=False, list_date=None, trade_days_since_list=None,
    )
    assert not vno.passed and vno.reason == "NO_LIST_DATE"


def test_limit_prices() -> None:
    """涨跌停按 board 两档，四舍五入到分。"""

    assert limit_up_price("10.00", "MAIN") == Decimal("11.00")
    assert limit_up_price("10.00", "GEM") == Decimal("12.00")
    assert limit_down_price("10.00", "MAIN") == Decimal("9.00")
    assert limit_down_price("10.00", "GEM") == Decimal("8.00")
    # 四舍五入边界：9.99×1.1=10.989→10.99；9.99×1.2=11.988→11.99
    assert limit_up_price("9.99", "MAIN") == Decimal("10.99")
    assert limit_up_price("9.99", "GEM") == Decimal("11.99")


def test_db_wrappers_and_batch_consistency() -> None:
    """DB 封装与批量上下文判定一致，按 T 当日查 ST、按交易日数次新。

    创建日期：2026-06-13
    author: claude
    """

    db = _session()
    # 交易日历：2026-06-01 至 06-12 共 12 个开市日（简化，全部开市）
    for d in range(1, 13):
        db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 6, d), is_open=1))
    db.add(AStockBasic(ts_code="600000.SH", name="浦发银行", list_date=date(1999, 11, 10)))
    db.add(AStockBasic(ts_code="301999.SZ", name="次新创业", list_date=date(2026, 6, 9)))
    db.add(AStockBasic(ts_code="600519.SH", name="ST示例", list_date=date(2001, 8, 27)))
    # 600000.SH 当日 ST
    db.add(AStockSt(ts_code="600000.SH", trade_date=date(2026, 6, 12)))
    db.commit()

    aod = date(2026, 6, 12)
    # 单票：ST / 次新(6/9..6/12=4 开市日<6) / 名称兜底
    assert filter_for_trade_date(db, "600000.SH", "浦发银行", aod).reason == "ST"
    assert filter_for_trade_date(db, "301999.SZ", "次新创业", aod).reason == "NEW_LISTING"
    assert filter_for_trade_date(db, "600519.SH", "ST示例", aod).reason == "SUSPECT_ST"

    # 批量与单票结果一致（同名同代码）
    ctx = build_universe_context(db, aod)
    names = {"600000.SH": "浦发银行", "301999.SZ": "次新创业", "600519.SH": "ST示例"}
    for ts_code, name in names.items():
        batch = ctx.evaluate(ts_code, name)
        single = filter_for_trade_date(db, ts_code, name, aod)
        assert batch.reason == single.reason
        assert batch.passed == single.passed
