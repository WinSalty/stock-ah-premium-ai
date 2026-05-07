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

    guarded = service.validate(
        "select ts_code, close from v_stock_research_context_latest where ts_code = '600036.SH'",
        default_limit=10,
    )

    assert "v_stock_research_context_latest" in guarded.tables


def test_sql_guard_rejects_write_sql() -> None:
    with pytest.raises(SqlGuardError):
        SqlGuardService().validate("delete from v_latest_ah_premium")
