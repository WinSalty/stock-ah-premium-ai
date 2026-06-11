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
from app.services.agent.tools.database import build_query_database_tool
from app.services.agent.tools.market_data import build_get_stock_data_tool
from app.services.agent.tools.threshold import build_recommend_threshold_tool


def build_tools(db: Session, settings: Settings, turn_state: TurnState) -> list[ToolSpec]:
    """组装本轮可用工具清单。

    recommend_threshold 仅在前端透传了阈值上下文时才进目录：
    没有上下文时工具必然失败，不如从能力声明里整体拿掉。

    创建日期：2026-06-12
    author: claude
    """

    tools: list[ToolSpec] = [
        build_query_database_tool(db, turn_state, settings),
        build_get_stock_data_tool(db, turn_state),
    ]
    if turn_state.threshold_context:
        tools.append(build_recommend_threshold_tool(turn_state))
    return tools
