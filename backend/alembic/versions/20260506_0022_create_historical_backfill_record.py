from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260506_0022"
down_revision = "20260506_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 记录 water-stock/Baidu 历史补数是否已按 A/H 股票对成功执行，避免定时任务重复请求外部行情接口。
    op.create_table(
        "historical_premium_backfill_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("a_ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("hk_ts_code", sa.String(length=16), nullable=False, comment="H 股 Tushare 代码"),
        sa.Column("data_source", sa.String(length=32), nullable=False, comment="补数来源标记"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="补数状态: RUNNING、COMPLETED、FAILED"),
        sa.Column("candidate_rows", sa.Integer(), nullable=False, server_default="0", comment="三方数据交集候选行数"),
        sa.Column("inserted_rows", sa.Integer(), nullable=False, server_default="0", comment="实际新增行数"),
        sa.Column("skipped_existing_rows", sa.Integer(), nullable=False, server_default="0", comment="唯一键已存在跳过行数"),
        sa.Column("skipped_invalid_rows", sa.Integer(), nullable=False, server_default="0", comment="价格或汇率无效跳过行数"),
        sa.Column("first_trade_date", sa.Date(), nullable=True, comment="本轮候选最早交易日期"),
        sa.Column("last_trade_date", sa.Date(), nullable=True, comment="本轮候选最晚交易日期"),
        sa.Column("last_error", sa.String(length=512), nullable=True, comment="失败原因摘要"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="最近一次开始时间"),
        sa.Column("completed_at", sa.DateTime(), nullable=True, comment="最近一次成功完成时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("a_ts_code", "hk_ts_code", "data_source", name="uk_hist_premium_backfill_pair"),
    )
    op.create_index(
        "idx_hist_premium_backfill_status",
        "historical_premium_backfill_record",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("idx_hist_premium_backfill_status", table_name="historical_premium_backfill_record")
    op.drop_table("historical_premium_backfill_record")
