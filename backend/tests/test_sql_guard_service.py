from __future__ import annotations

import pytest

from app.services.sql_guard_service import SqlGuardError, SqlGuardService


def test_sql_guard_accepts_whitelisted_select() -> None:
    guarded = SqlGuardService().validate("select * from v_latest_ah_premium", default_limit=10)
    assert "LIMIT 10" in guarded.sql.upper()


def test_sql_guard_accepts_official_and_watchlist_views() -> None:
    """确认官方主口径和自选机会视图在白名单内。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = SqlGuardService()

    official = service.validate("select * from v_latest_official_ah_premium", default_limit=10)
    watchlist = service.validate("select * from v_watchlist_opportunity", default_limit=10)

    assert "v_latest_official_ah_premium" in official.tables
    assert "v_watchlist_opportunity" in watchlist.tables


def test_sql_guard_accepts_stock_research_views() -> None:
    """确认个股研究视图纳入 LLM 只读白名单。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = SqlGuardService()

    # 新增主营、股东治理和资金流视图后，需要用测试锁住白名单边界，
    # 避免提示词推荐了数据源但 SQL 安全层误拦截。
    expected_tables = {
        "v_stock_research_context_latest",
        "v_stock_business_profile_summary",
        "v_stock_shareholder_governance_summary",
        "v_stock_moneyflow_recent",
    }

    for table in expected_tables:
        guarded = service.validate(
            f"select * from {table} where ts_code = '600036.SH'",
            default_limit=10,
        )
        assert table in guarded.tables


def test_sql_guard_accepts_dividend_reinvestment_tables() -> None:
    """确认分红再投入回测结果表纳入 LLM 只读白名单。

    创建日期：2026-06-03
    author: sunshengxian
    """

    service = SqlGuardService()

    # 分红再投问答会由模型直接生成 SELECT 查询；这里锁住安全层白名单，
    # 避免提示词允许的回测表在执行前被误判为非白名单对象。
    guarded = service.validate(
        "select s.ts_code,s.name from dividend_reinvestment_backtest_summary s "
        "join dividend_reinvestment_backtest_run r on r.id=s.run_id "
        "where r.status='COMPLETED'",
        default_limit=10,
    )

    assert "dividend_reinvestment_backtest_summary" in guarded.tables
    assert "dividend_reinvestment_backtest_run" in guarded.tables


def test_sql_guard_accepts_limit_up_analysis_cache() -> None:
    """确认风险高收益型推荐可读取最新打板报告缓存。

    创建日期：2026-06-03
    author: codex
    """

    service = SqlGuardService()

    # 打板报告只作为短线风险偏好推荐的数据源，安全层仍限制为只读 SELECT。
    guarded = service.validate(
        "select title,content_markdown from limit_up_analysis_cache "
        "where status='READY' order by trade_date desc limit 1",
        default_limit=10,
    )

    assert "limit_up_analysis_cache" in guarded.tables


def test_sql_guard_rejects_write_sql() -> None:
    with pytest.raises(SqlGuardError):
        SqlGuardService().validate("delete from v_latest_ah_premium")


def test_sql_guard_rejects_legacy_stock_selection_views() -> None:
    """确认 LLM 问答不再允许查询旧选股因子宽表视图。

    创建日期：2026-05-07
    author: sunshengxian
    """

    with pytest.raises(SqlGuardError):
        SqlGuardService().validate("select * from v_stock_selection_latest")
