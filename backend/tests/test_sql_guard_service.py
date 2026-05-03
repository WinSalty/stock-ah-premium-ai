from __future__ import annotations

import pytest

from app.services.sql_guard_service import SqlGuardError, SqlGuardService


def test_sql_guard_accepts_whitelisted_select() -> None:
    guarded = SqlGuardService().validate("select * from v_latest_ah_premium", default_limit=10)
    assert "LIMIT 10" in guarded.sql.upper()


def test_sql_guard_rejects_write_sql() -> None:
    with pytest.raises(SqlGuardError):
        SqlGuardService().validate("delete from v_latest_ah_premium")
