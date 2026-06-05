from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260605_0046"
down_revision = "20260602_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增打板报告多阶段分析与筹码补数缓存表。

    创建日期：2026-06-05
    author: sunshengxian
    """

    # 阶段缓存用于多轮 LLM 生成失败后的幂等重跑；
    # 同一交易日、阶段、模型、提示词版本和输入哈希只保留一份结果，避免重复消耗 LLM 调用。
    op.create_table(
        "limit_up_analysis_stage_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column(
            "analysis_id",
            sa.Integer(),
            nullable=True,
            comment="关联最终打板报告缓存 ID，报告创建前可为空",
        ),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="阶段分析对应 A 股交易日"),
        sa.Column("stage_key", sa.String(length=64), nullable=False, comment="阶段标识"),
        sa.Column("model", sa.String(length=64), nullable=False, comment="阶段调用 LLM 模型"),
        sa.Column("prompt_version", sa.String(length=64), nullable=False, comment="阶段提示词版本"),
        sa.Column("input_hash", sa.String(length=64), nullable=False, comment="阶段输入 JSON 哈希"),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="阶段状态",
        ),
        sa.Column("output_json", mysql.LONGTEXT(), nullable=True, comment="阶段结构化输出 JSON"),
        sa.Column("content_html", mysql.LONGTEXT(), nullable=True, comment="阶段 HTML 片段"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="阶段失败摘要"),
        sa.Column("generated_at", sa.DateTime(), nullable=True, comment="阶段生成完成时间"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="记录更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["limit_up_analysis_cache.id"],
            name="fk_limit_up_stage_analysis",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trade_date",
            "stage_key",
            "model",
            "prompt_version",
            "input_hash",
            name="uk_limit_up_stage_once",
        ),
    )
    op.create_index(
        "idx_limit_up_stage_trade_stage",
        "limit_up_analysis_stage_cache",
        ["trade_date", "stage_key", "status"],
    )
    op.create_index(
        "idx_limit_up_stage_analysis",
        "limit_up_analysis_stage_cache",
        ["analysis_id"],
    )
    # 筹码补数缓存按股票和窗口幂等；单股失败不阻断报告，但保留质量记录便于复盘接口权限或空数据问题。
    op.create_table(
        "limit_up_stock_supplement_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="打板报告对应 A 股交易日"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="重点股票代码"),
        sa.Column("start_date", sa.Date(), nullable=False, comment="筹码补数窗口开始日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="筹码补数窗口结束日期"),
        sa.Column(
            "cyq_perf_json",
            mysql.LONGTEXT(),
            nullable=True,
            comment="cyq_perf 原始或精简数据 JSON",
        ),
        sa.Column(
            "cyq_chips_summary_json",
            mysql.LONGTEXT(),
            nullable=True,
            comment="cyq_chips 压缩摘要 JSON",
        ),
        sa.Column(
            "data_quality_json",
            mysql.LONGTEXT(),
            nullable=True,
            comment="单股补数质量记录 JSON",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="补数状态",
        ),
        sa.Column("error_message", sa.Text(), nullable=True, comment="补数失败摘要"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="记录更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trade_date",
            "ts_code",
            "start_date",
            "end_date",
            name="uk_limit_up_stock_supplement_once",
        ),
    )
    op.create_index(
        "idx_limit_up_stock_supplement_trade",
        "limit_up_stock_supplement_cache",
        ["trade_date", "status"],
    )
    op.create_index(
        "idx_limit_up_stock_supplement_code",
        "limit_up_stock_supplement_cache",
        ["ts_code", "trade_date"],
    )


def downgrade() -> None:
    """回滚打板报告多阶段缓存表。

    创建日期：2026-06-05
    author: sunshengxian
    """

    # 回滚只移除本次新增缓存表，不改动已生成的最终打板报告和推送流水。
    op.drop_index(
        "idx_limit_up_stock_supplement_code",
        table_name="limit_up_stock_supplement_cache",
    )
    op.drop_index(
        "idx_limit_up_stock_supplement_trade",
        table_name="limit_up_stock_supplement_cache",
    )
    op.drop_table("limit_up_stock_supplement_cache")
    op.drop_index("idx_limit_up_stage_analysis", table_name="limit_up_analysis_stage_cache")
    op.drop_index("idx_limit_up_stage_trade_stage", table_name="limit_up_analysis_stage_cache")
    op.drop_table("limit_up_analysis_stage_cache")
