from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260612_0048"
down_revision = "20260605_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """问答 Agent 化重构：消息表新增工具轨迹与图表列，指标表新增提示词版本列。

    创建日期：2026-06-12
    author: claude
    """

    # Agent 引擎一轮回答可能串联多次工具调用，单一 sql_text 列无法承载全过程；
    # 工具轨迹与图表 ChartSpec 以 JSON 文本整体落在消息行上，历史消息接口按需解析返回。
    # 两列均可空：历史消息与非 Agent 链路写入的消息没有轨迹，读取侧需回退空列表。
    op.add_column(
        "llm_chat_message",
        sa.Column(
            "tool_trace_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="本条回答的工具执行轨迹（工具名/入参摘要/结果摘要/耗时/是否成功）",
        ),
    )
    op.add_column(
        "llm_chat_message",
        sa.Column(
            "charts_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="本条回答登记的图表 ChartSpec 列表",
        ),
    )
    # 指标表记录 Agent 系统提示词版本：同一 phase 在不同提示词版本下的耗时与成功率
    # 可在 LLM 耗时页对比，支撑提示词迭代效果评估；旧链路与历史数据保持 NULL。
    op.add_column(
        "llm_call_metric",
        sa.Column(
            "prompt_version",
            sa.String(length=32),
            nullable=True,
            comment="Agent 系统提示词版本号，用于提示词迭代效果对比",
        ),
    )


def downgrade() -> None:
    """回滚问答 Agent 化重构新增列。

    创建日期：2026-06-12
    author: claude
    """

    # 回滚按新增逆序删除列，只移除本次新增的可空列，不影响既有消息与指标数据。
    op.drop_column("llm_call_metric", "prompt_version")
    op.drop_column("llm_chat_message", "charts_json")
    op.drop_column("llm_chat_message", "tool_trace_json")
