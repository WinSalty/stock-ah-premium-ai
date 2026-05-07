from __future__ import annotations

import re
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
        "v_market_data_fetch_health",
        "v_sync_health",
        "v_data_quality_issues",
    }

    forbidden_pattern = re.compile(
        r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|call|load)\b",
        re.IGNORECASE,
    )

    def validate(self, sql: str, default_limit: int = 200, max_limit: int = 1000) -> GuardedSql:
        """校验并限制 SQL。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = sql.strip().rstrip(";")
        if ";" in normalized:
            raise SqlGuardError("不允许多语句 SQL")
        if self.forbidden_pattern.search(normalized):
            raise SqlGuardError("只允许 SELECT 查询")
        try:
            expression = sqlglot.parse_one(normalized, read="mysql")
        except sqlglot.errors.SqlglotError as exc:
            raise SqlGuardError(f"SQL 解析失败：{exc}") from exc
        if not isinstance(expression, exp.Select):
            raise SqlGuardError("只允许 SELECT 查询")
        tables = sorted({table.name for table in expression.find_all(exp.Table)})
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
