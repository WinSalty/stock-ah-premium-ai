"""Agent 工具集：按配置可用性组装本轮工具清单。

build_tools 是工具目录的单点入口：阶段 1 提供本地三工具（query_database /
get_stock_data / recommend_threshold），阶段 2~4 在此追加联网搜索、沙箱与图表。
工具因 key 缺失或日配额用尽不可用时直接不进清单，系统提示词能力声明随之收敛。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.agent.budget import TurnState
from app.services.agent.tool_registry import ToolSpec
from app.services.agent.tools.chart import build_render_chart_tool
from app.services.agent.tools.database import build_query_database_tool
from app.services.agent.tools.market_data import build_get_stock_data_tool
from app.services.agent.tools.python_runner import (
    build_run_python_tool,
    run_python_daily_quota_exhausted,
)
from app.services.agent.tools.threshold import build_recommend_threshold_tool
from app.services.agent.tools.web_search import (
    build_fetch_url_tool,
    build_web_search_tool,
    web_daily_quota_exhausted,
)


def build_tools(db: Session, settings: Settings, turn_state: TurnState) -> list[ToolSpec]:
    """组装本轮可用工具清单。

    可用性裁剪口径：
    - recommend_threshold 仅在前端透传了阈值上下文时进目录（无上下文必然失败）；
    - web_search / fetch_url 需要博查 key 存在且当日配额未用尽，否则整体降级移除，
      系统提示词能力声明随之收敛为"无联网能力"。

    创建日期：2026-06-12
    author: claude
    """

    tools: list[ToolSpec] = [
        build_query_database_tool(db, turn_state, settings),
        build_get_stock_data_tool(db, turn_state),
    ]
    if turn_state.threshold_context:
        tools.append(build_recommend_threshold_tool(turn_state))
    bocha_key = settings.resolve_bocha_api_key()
    if bocha_key and not web_daily_quota_exhausted(db, settings):
        tools.append(build_web_search_tool(settings, bocha_key))
        tools.append(build_fetch_url_tool(settings))
    # run_python：日配额未用尽即可用（沙箱本身无外部依赖，不需要 key）。
    if not run_python_daily_quota_exhausted(db, settings):
        tools.append(build_run_python_tool(settings, turn_state))
    # render_chart：始终可用，轮内 4 张配额由 budget 强制，无外部依赖与日配额。
    tools.append(build_render_chart_tool(turn_state))
    return tools
