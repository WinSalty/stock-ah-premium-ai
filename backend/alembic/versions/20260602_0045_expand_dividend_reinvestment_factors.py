from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260602_0045"
down_revision = "20260601_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """扩充分红再投入筛选摘要因子。

    创建日期：2026-06-02
    author: sunshengxian
    """

    # 摘要表用于页面筛选和 Excel 导出，新增字段均为回测计算阶段写入；
    # 迁移只补列和索引，不回填历史批次，避免在结构升级时改动既有回测结果。
    op.add_column(
        "dividend_reinvestment_backtest_summary",
        sa.Column(
            "ten_year_avg_annualized_return_pct",
            sa.DECIMAL(20, 8),
            nullable=True,
            comment="近十年平均年化收益率",
        ),
    )
    op.add_column(
        "dividend_reinvestment_backtest_summary",
        sa.Column("latest_pe", sa.DECIMAL(20, 8), nullable=True, comment="最新 PE"),
    )
    op.add_column(
        "dividend_reinvestment_backtest_summary",
        sa.Column("latest_roe", sa.DECIMAL(20, 8), nullable=True, comment="最新 ROE"),
    )
    op.create_index(
        "idx_div_reinvest_summary_ten_year_return",
        "dividend_reinvestment_backtest_summary",
        ["run_id", "ten_year_avg_annualized_return_pct"],
    )
    op.create_index(
        "idx_div_reinvest_summary_pe",
        "dividend_reinvestment_backtest_summary",
        ["run_id", "latest_pe"],
    )
    op.create_index(
        "idx_div_reinvest_summary_roe",
        "dividend_reinvestment_backtest_summary",
        ["run_id", "latest_roe"],
    )


def downgrade() -> None:
    """回滚分红再投入筛选摘要因子扩展。

    创建日期：2026-06-02
    author: sunshengxian
    """

    # 回滚只移除本迁移新增结构，不删除回测批次和年度明细，方便重新升级后再计算。
    op.drop_index(
        "idx_div_reinvest_summary_roe",
        table_name="dividend_reinvestment_backtest_summary",
    )
    op.drop_index(
        "idx_div_reinvest_summary_pe",
        table_name="dividend_reinvestment_backtest_summary",
    )
    op.drop_index(
        "idx_div_reinvest_summary_ten_year_return",
        table_name="dividend_reinvestment_backtest_summary",
    )
    op.drop_column("dividend_reinvestment_backtest_summary", "latest_roe")
    op.drop_column("dividend_reinvestment_backtest_summary", "latest_pe")
    op.drop_column(
        "dividend_reinvestment_backtest_summary",
        "ten_year_avg_annualized_return_pct",
    )
