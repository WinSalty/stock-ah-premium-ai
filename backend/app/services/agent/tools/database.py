"""query_database 工具：白名单只读 SQL 查询（SqlGuard 强制）。

口径：
- 安全完全复用 SqlGuardService（白名单视图 + 只读校验 + LIMIT 注入），
  工具层不做第二套安全判断；
- 完整结果缓存进 turn_state.sql_results 供 run_python 沙箱注入（阶段 3），
  回填给模型的材料按预算截断（≤60 行）；
- 分红再投批次 status 的 COMPLETED/SUCCESS 兼容口径写在数据字典与工具描述里，
  由模型直接写出正确 SQL，不再做旧链路那样的静默改写。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.agent.budget import SQL_RESULT_MAX_ROWS, TurnState
from app.services.agent.tool_registry import ToolResult, ToolSpec
from app.services.sql_guard_service import SqlGuardError, SqlGuardService

logger = logging.getLogger(__name__)


def _rows_to_json(rows: list[dict[str, Any]], limit: int) -> str:
    """行数据序列化为 JSON 文本：Decimal/日期统一转字符串，超限截断。

    创建日期：2026-06-12
    author: claude
    """

    return json.dumps(rows[:limit], ensure_ascii=False, default=str)


def build_query_database_tool(
    db: Session,
    turn_state: TurnState,
    settings: Settings | None = None,
) -> ToolSpec:
    """构造 query_database 工具：闭包持有请求级 db 会话与注入的配置。

    创建日期：2026-06-12
    author: claude
    """

    settings = settings or get_settings()
    sql_guard = SqlGuardService()
    user_id = turn_state.user_id

    def handler(args: dict[str, Any], state: TurnState) -> ToolResult:
        """校验并执行只读 SQL：SqlGuard 拒绝时把原因回填给模型修正。

        创建日期：2026-06-12
        author: claude
        """

        sql = str(args.get("sql") or "").strip()
        purpose = str(args.get("purpose") or "").strip() or "数据查询"
        if not sql:
            return ToolResult(ok=False, payload="缺少 sql 参数。", summary="缺少 SQL")
        try:
            guarded = sql_guard.validate(
                sql,
                default_limit=settings.query_limit_default,
                max_limit=settings.query_limit_max,
            )
        except SqlGuardError as exc:
            # 校验失败原因直接回填：常见为表不在白名单/出现写操作，模型可据此改写。
            return ToolResult(
                ok=False,
                payload=f"SQL 未通过安全校验：{exc}",
                summary="SQL 校验未通过",
            )
        try:
            result = db.execute(text(guarded.sql))
            rows = [dict(row._mapping) for row in result.fetchall()]
        except Exception as exc:  # noqa: BLE001
            # 执行错误（字段名拼错等）回填错误信息，让模型自行修复重试（替代旧 repair_sql）。
            db.rollback()
            logger.warning(
                "Agent SQL 执行失败 question_id=%s error=%s",
                state.question_id,
                exc,
            )
            return ToolResult(
                ok=False,
                payload=f"SQL 执行失败：{exc}。请根据报错修正后重试。",
                summary="SQL 执行失败",
            )
        # 完整结果缓存供沙箱计算用；回填模型的材料截断到预算行数。
        state.sql_results.append((len(state.sql_results) + 1, purpose, rows))
        truncated_note = (
            f"（共 {len(rows)} 行，已截断展示前 {SQL_RESULT_MAX_ROWS} 行；"
            "完整结果可在 run_python 沙箱的 data/ 目录读取）"
            if len(rows) > SQL_RESULT_MAX_ROWS
            else f"（共 {len(rows)} 行）"
        )
        payload = f"{truncated_note}\n{_rows_to_json(rows, SQL_RESULT_MAX_ROWS)}"
        return ToolResult(ok=True, payload=payload, summary=f"返回 {len(rows)} 行")

    user_filter_note = (
        f"当前用户 user_id={user_id}，查询 v_watchlist_opportunity 必须带 "
        f"WHERE user_id = {user_id} 过滤。"
        if user_id is not None
        else "当前请求未携带用户身份，不要查询 v_watchlist_opportunity。"
    )
    return ToolSpec(
        name="query_database",
        description=(
            "执行单条只读 SELECT 查询本地行情/财务/溢价/分红再投回测/打板报告数据库。"
            "可用视图与字段见系统提示词的数据字典附录。"
            f"{user_filter_note}"
            "常用查询示例："
            "①自选股机会（按距阈值距离）：SELECT * FROM v_watchlist_opportunity "
            f"WHERE user_id = {user_id if user_id is not None else 0} "
            "ORDER BY ABS(distance_to_target_pct) ASC LIMIT 30；"
            "②全市场 H/A 折溢价候选：SELECT * FROM v_latest_hk_connect_official_ah_premium "
            "ORDER BY ha_premium_pct DESC LIMIT 20；"
            "③最新打板报告：SELECT id,trade_date,title,content_markdown FROM "
            "limit_up_analysis_cache WHERE status='READY' "
            "ORDER BY trade_date DESC,id DESC LIMIT 1；"
            "④分红再投最新批次：先查 SELECT id FROM dividend_reinvestment_backtest_run "
            "WHERE status IN ('COMPLETED','SUCCESS') "
            "ORDER BY finished_at DESC,id DESC LIMIT 1，再按 run_id 查 summary/yearly。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "单条只读 SELECT，禁止写操作与多语句",
                },
                "purpose": {
                    "type": "string",
                    "description": "一句话说明查询用途，用于界面展示",
                },
            },
            "required": ["sql", "purpose"],
        },
        handler=handler,
        summarize=lambda args: f"查询：{str(args.get('purpose') or '数据查询')[:50]}",
        capability_note=(
            "query_database：用只读 SQL 查询本地 A/H 溢价、行情估值、财务、"
            "分红再投回测、打板报告与自选股阈值数据。"
        ),
    )
