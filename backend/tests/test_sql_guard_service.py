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


def test_sql_guard_accepts_keyword_in_string_literal() -> None:
    """确认字符串字面量中的写操作关键字不再误伤合法 SELECT（旧评审 R6 回归）。

    旧实现用关键字黑名单正则扫描整条 SQL，会把字面量里的 UPDATE/DELETE
    误判为写操作；改为 sqlglot AST 判定后，字面量内容不参与语句类型判断。

    创建日期：2026-06-12
    author: claude
    """

    service = SqlGuardService()

    guarded = service.validate(
        "select * from v_latest_ah_premium "
        "where name = '业绩预告:UPDATE' or name = '已delete归档'",
        default_limit=10,
    )

    assert "v_latest_ah_premium" in guarded.tables


def test_sql_guard_accepts_cte_and_excludes_alias_from_tables() -> None:
    """确认 WITH ... AS 形式的 CTE 可通过校验，且别名不计入真实表清单。

    CTE 别名只是查询内部的临时结果集，不应触发白名单拒绝，
    也不应出现在 guarded.tables 里污染审计口径。

    创建日期：2026-06-12
    author: claude
    """

    guarded = SqlGuardService().validate(
        "with t as (select * from v_latest_ah_premium) select * from t",
        default_limit=10,
    )

    assert "v_latest_ah_premium" in guarded.tables
    assert "t" not in guarded.tables


def test_sql_guard_rejects_non_whitelist_table_inside_cte() -> None:
    """确认 CTE 体内引用非白名单表时仍被拒绝。

    排除 CTE 别名不能放松真实表校验：CTE 体内的真实表
    必须照常参与白名单比对，否则会形成绕过通道。

    创建日期：2026-06-12
    author: claude
    """

    with pytest.raises(SqlGuardError):
        SqlGuardService().validate(
            "with t as (select * from secret_table) select * from t"
        )


def test_sql_guard_rejects_multiple_statements() -> None:
    """确认多语句 SQL 被拒绝（基于 sqlglot 解析出的语句数量判定）。

    多语句判定不再依赖分号字符串包含，而是看 sqlglot 解析结果
    是否超过一条语句，避免误伤字面量含分号的合法查询。

    创建日期：2026-06-12
    author: claude
    """

    with pytest.raises(SqlGuardError):
        SqlGuardService().validate("SELECT 1; SELECT 2")


def test_sql_guard_rejects_write_and_ddl_statements_by_ast() -> None:
    """确认 INSERT/UPDATE/DELETE/DROP/CREATE 均被 AST 判定拒绝。

    删除关键字黑名单正则后，写操作与 DDL 必须完全由 sqlglot AST
    节点类型识别并拒绝，这里逐类锁住只读边界。

    创建日期：2026-06-12
    author: claude
    """

    service = SqlGuardService()

    write_statements = [
        "insert into v_latest_ah_premium (ts_code) values ('600036.SH')",
        "update v_latest_ah_premium set name = 'x'",
        "delete from v_latest_ah_premium",
        "drop table v_latest_ah_premium",
        "create table evil_table (id int)",
    ]
    for statement in write_statements:
        with pytest.raises(SqlGuardError):
            service.validate(statement)


def test_sql_guard_rejects_non_whitelist_table_in_subquery() -> None:
    """确认子查询中出现非白名单表时被拒绝。

    白名单校验基于整棵 AST 的 find_all(exp.Table)，
    子查询里夹带的非白名单表同样会被发现并拒绝。

    创建日期：2026-06-12
    author: claude
    """

    with pytest.raises(SqlGuardError):
        SqlGuardService().validate(
            "select * from v_latest_ah_premium "
            "where ts_code in (select ts_code from secret_table)"
        )
