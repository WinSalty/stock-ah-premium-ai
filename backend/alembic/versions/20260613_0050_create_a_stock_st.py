from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260613_0050"
down_revision = "20260612_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新建 A 股每日 ST 名单表 a_stock_st。

    业务意图：universe_filter L2 层按"信号日 T 当日"判 ST，杜绝用当前状态造成回测未来函数。
    数据来源：Tushare stock_st 接口（按 trade_date 返回当日 ST 名单，已实测为 point-in-time）。
    幂等：按 (ts_code, trade_date) 唯一，重跑/历史回填均 upsert 覆盖，不产生重复行。

    创建日期：2026-06-13
    author: claude
    """

    op.create_table(
        "a_stock_st",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column(
            "ts_code",
            sa.String(length=16),
            nullable=False,
            comment="标准证券代码，如 600000.SH",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            nullable=False,
            comment="ST 状态所属交易日（东八区，与 a_trade_calendar.cal_date 对齐）",
        ),
        sa.Column(
            "name",
            sa.String(length=64),
            nullable=True,
            comment="当日证券简称（通常含 ST/*ST 前缀，供名称兜底校验）",
        ),
        sa.Column(
            "st_type",
            sa.String(length=16),
            nullable=True,
            comment="ST 类别原始代码（stock_st.type，取值以官方为准）",
        ),
        sa.Column(
            "st_type_name",
            sa.String(length=32),
            nullable=True,
            comment="ST 类别中文名（stock_st.type_name，便于人读核对）",
        ),
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
        sa.UniqueConstraint("ts_code", "trade_date", name="uk_a_stock_st"),
        comment="A 股每日 ST 名单表（universe_filter 按 T 当日判 ST 的数据源）",
    )
    # 按 trade_date 建索引：universe_filter 批量预取当日 ST 名单（build_universe_context）走此索引。
    op.create_index("idx_a_stock_st_trade_date", "a_stock_st", ["trade_date"])


def downgrade() -> None:
    """回滚：删除 a_stock_st 表。

    创建日期：2026-06-13
    author: claude
    """

    op.drop_index("idx_a_stock_st_trade_date", table_name="a_stock_st")
    op.drop_table("a_stock_st")
