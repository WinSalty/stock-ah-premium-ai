from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp


class SqlGuardError(ValueError):
    """SQL 安全校验异常。

    创建日期：2026-05-04
    author: sunshengxian
    """


@dataclass(frozen=True)
class GuardedSql:
    """通过安全校验后的 SQL。

    创建日期：2026-05-04
    author: sunshengxian
    """

    sql: str
    tables: list[str]


class SqlGuardService:
    """LLM SQL 白名单和只读保护服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    whitelist_tables = {
        "v_latest_ah_premium",
        "v_ah_premium_trend",
        "v_latest_official_ah_premium",
        "v_official_ah_premium_trend",
        "v_latest_hk_connect_official_ah_premium",
        "v_watchlist_opportunity",
        "v_stock_quote_valuation_trend",
        "v_stock_financial_period_summary",
        "v_stock_business_profile_summary",
        "v_stock_shareholder_governance_summary",
        "v_stock_moneyflow_recent",
        "v_stock_research_context_latest",
        "v_hk_financial_period_summary",
        "v_hk_financial_statement_item_summary",
        "v_hk_stock_research_context_latest",
        "dividend_reinvestment_backtest_run",
        "dividend_reinvestment_backtest_summary",
        "dividend_reinvestment_backtest_yearly",
        "limit_up_analysis_cache",
        "v_market_data_fetch_health",
        "v_sync_health",
        "v_data_quality_issues",
    }

    # 写操作 / DDL / 权限 / 会话控制等危险 AST 节点类型。语句类型完全依赖 sqlglot AST 判定，
    # 取代原先的关键字黑名单正则（旧评审 R6：正则会误伤字符串字面量中的关键字，
    # 如 WHERE note = '业绩预告:UPDATE' 的合法 SELECT 会被误拒）。
    # 节点类名按 sqlglot 25.34.1 实际存在的类选取；REVOKE、LOAD DATA INFILE 等
    # sqlglot 无法解析的语句会在解析阶段直接抛错被拒，无需在此枚举。
    # CALL、REPLACE INTO 等不受支持的语法会回退解析为 exp.Command，因此 Command 必须在列。
    # 创建日期：2026-06-12
    # author: claude
    forbidden_node_types: tuple[type[exp.Expression], ...] = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.TruncateTable,
        exp.Grant,
        exp.Merge,
        exp.LoadData,
        exp.Set,
        exp.Use,
        exp.Kill,
        exp.Transaction,
        exp.Commit,
        exp.Rollback,
        exp.Command,
    )

    def validate(self, sql: str, default_limit: int = 200, max_limit: int = 1000) -> GuardedSql:
        """校验并限制 SQL。

        校验顺序：先用 sqlglot 整体解析判定多语句，再校验顶层语句必须是 SELECT，
        然后遍历 AST 拒绝任何写操作/DDL 节点，最后做表白名单比对（排除 CTE 别名）
        并注入 LIMIT。任一环节不通过即抛出 SqlGuardError，保证只读边界。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = sql.strip().rstrip(";")
        # 多语句判定改用 sqlglot 解析结果数量，取代原先的 `";" in sql` 字符串包含判断：
        # 字符串包含会误伤字面量内含分号的合法查询（如 WHERE note = 'a;b'），
        # 而 sqlglot 解析能正确区分语句分隔符与字面量内容。
        # 解析失败（含 sqlglot 不支持的语法，如 REVOKE）统一按非法 SQL 拒绝。
        # 创建日期：2026-06-12
        # author: claude
        try:
            parsed = sqlglot.parse(normalized, read="mysql")
        except sqlglot.errors.SqlglotError as exc:
            raise SqlGuardError(f"SQL 解析失败：{exc}") from exc
        # sqlglot 对空语句段（如纯空白、连续分号）会返回 None 占位，需要先过滤，
        # 避免 "SELECT 1;;SELECT 2" 这类输入因 None 干扰统计口径。
        statements = [statement for statement in parsed if statement is not None]
        if not statements:
            raise SqlGuardError("SQL 解析失败：空语句")
        if len(statements) > 1:
            raise SqlGuardError("不允许多语句 SQL")
        expression = statements[0]
        if not isinstance(expression, exp.Select):
            raise SqlGuardError("只允许 SELECT 查询")
        # 防御性深度校验：即使顶层是 SELECT，也遍历整棵 AST 拒绝嵌入的写操作/DDL 节点，
        # 防止方言扩展或 sqlglot 回退解析（exp.Command）夹带非只读语义。
        # 创建日期：2026-06-12
        # author: claude
        forbidden_node = next(expression.find_all(*self.forbidden_node_types), None)
        if forbidden_node is not None:
            raise SqlGuardError("只允许 SELECT 查询")
        # 收集整条语句（含嵌套子查询）里所有 CTE 别名：find_all 会递归遍历整棵 AST，
        # 因此嵌套 CTE（WITH 内再套 WITH）的别名也能一并收集。
        # MySQL 的 CTE 名称不区分大小写，统一转小写比对，避免 WITH T ... FROM t 漏判。
        # 创建日期：2026-06-12
        # author: claude
        cte_aliases = {cte.alias.lower() for cte in expression.find_all(exp.CTE) if cte.alias}
        # 白名单比对时排除 CTE 别名引用：CTE 别名只是查询内部的临时结果集，不是真实表，
        # 不应触发白名单拒绝；但 CTE 体内引用的真实表仍会被 find_all(exp.Table) 找到并校验。
        # 边界条件：仅未带库名限定（table.db 为空）的表引用才可能解析为 CTE 别名，
        # 带库名的同名引用（如 otherdb.t）指向真实表，必须照常参与白名单校验。
        # 创建日期：2026-06-12
        # author: claude
        tables = sorted(
            {
                table.name
                for table in expression.find_all(exp.Table)
                if not (not table.db and table.name.lower() in cte_aliases)
            }
        )
        disallowed = [table for table in tables if table not in self.whitelist_tables]
        if disallowed:
            raise SqlGuardError(f"查询表不在白名单内：{', '.join(disallowed)}")
        guarded_sql = self._ensure_limit(expression, default_limit, max_limit)
        return GuardedSql(sql=guarded_sql, tables=tables)

    def _ensure_limit(self, expression: exp.Select, default_limit: int, max_limit: int) -> str:
        limit_expression = expression.args.get("limit")
        if limit_expression is None:
            expression.set("limit", exp.Limit(expression=exp.Literal.number(default_limit)))
        else:
            try:
                current_limit = int(limit_expression.expression.name)
            except (AttributeError, ValueError):
                current_limit = default_limit
            if current_limit > max_limit:
                expression.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
        return expression.sql(dialect="mysql")
