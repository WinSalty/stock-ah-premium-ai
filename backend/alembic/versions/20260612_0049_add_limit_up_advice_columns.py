from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260612_0049"
down_revision = "20260612_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """打板推送投资建议重构：报告缓存表新增建议五列。

    创建日期：2026-06-12
    author: claude
    """

    # 投资建议是报告的附加产物：PushPlus/雪球推送内容从整报切换为建议时，
    # 推送、发布与详情链路都只读主表，因此建议正文必须落在主表列上，
    # 阶段缓存表仅承担生成幂等。存量行随 server_default 落 PENDING，
    # 推送层视作"缺失待回填"，按需补生成，不触发报告本体重算。
    op.add_column(
        "limit_up_analysis_cache",
        sa.Column(
            "advice_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="投资建议状态：PENDING/GENERATING/READY/FAILED",
        ),
    )
    op.add_column(
        "limit_up_analysis_cache",
        sa.Column(
            "advice_html",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="投资建议正文 HTML（规整后，PushPlus/雪球/详情页共用）",
        ),
    )
    op.add_column(
        "limit_up_analysis_cache",
        sa.Column(
            "advice_markdown",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="投资建议 LLM 原始输出（对齐 content_markdown 双存惯例）",
        ),
    )
    op.add_column(
        "limit_up_analysis_cache",
        sa.Column(
            "advice_generated_at",
            sa.DateTime(),
            nullable=True,
            comment="投资建议生成时间（UTC-naive，与报告 generated_at 同口径）",
        ),
    )
    op.add_column(
        "limit_up_analysis_cache",
        sa.Column(
            "advice_error",
            sa.Text(),
            nullable=True,
            comment="投资建议生成失败原因（截断 1000 字）",
        ),
    )


def downgrade() -> None:
    """回滚打板投资建议新增列。

    创建日期：2026-06-12
    author: claude
    """

    # 回滚按新增逆序删除列；建议列均为附加产物，删除不影响既有报告数据，
    # 推送链路在 REPORT 模式下不依赖这些列。
    op.drop_column("limit_up_analysis_cache", "advice_error")
    op.drop_column("limit_up_analysis_cache", "advice_generated_at")
    op.drop_column("limit_up_analysis_cache", "advice_markdown")
    op.drop_column("limit_up_analysis_cache", "advice_html")
    op.drop_column("limit_up_analysis_cache", "advice_status")
