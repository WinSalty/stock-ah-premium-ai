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


def test_sql_guard_rejects_write_sql() -> None:
    with pytest.raises(SqlGuardError):
        SqlGuardService().validate("delete from v_latest_ah_premium")
