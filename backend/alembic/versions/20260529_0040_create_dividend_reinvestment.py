from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260529_0040"
down_revision = "20260527_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 回测批次表保存本次分红再投入计算口径，后续摘要和年度明细都挂到 run_id；
    # 这样同一批原始数据可以按税前/税后、起止日期等不同口径反复计算并留痕。
    op.create_table(
        "dividend_reinvestment_backtest_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键 ID"),
        sa.Column("run_key", sa.String(length=128), nullable=False, comment="回测批次业务键"),
        sa.Column("start_date", sa.Date(), nullable=False, comment="回测开始日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="回测结束日期"),
        sa.Column("initial_amount", sa.DECIMAL(24, 6), nullable=False, comment="初始投入金额"),
        sa.Column(
            "cash_div_field",
            sa.String(length=32),
            nullable=False,
            server_default="cash_div_tax",
            comment="现金分红字段口径",
        ),
        sa.Column(
            "reinvest_price_policy",
            sa.String(length=64),
            nullable=False,
            server_default="EX_DATE_OR_NEXT_CLOSE",
            comment="再投入价格口径",
        ),
        sa.Column(
            "share_rounding_policy",
            sa.String(length=64),
            nullable=False,
            server_default="FRACTIONAL_SHARES",
            comment="持股取整口径",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="RUNNING", comment="批次状态"),
        sa.Column("stock_count", sa.Integer(), nullable=False, server_default="0", comment="参与计算股票数"),
        sa.Column("summary_count", sa.Integer(), nullable=False, server_default="0", comment="摘要结果行数"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败摘要"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="结束时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="分红再投入回测批次表",
    )
    op.create_index(
        "idx_div_reinvest_run_status_started",
        "dividend_reinvestment_backtest_run",
        ["status", "started_at"],
    )
    op.create_index(
        "idx_div_reinvest_run_key",
        "dividend_reinvestment_backtest_run",
        ["run_key"],
    )

    # 摘要表面向筛选榜单，一只股票在一个批次中只保留一行；
    # 所有指标均由本地日线、分红和每日指标计算得到，不在查询时实时访问 Tushare。
    op.create_table(
        "dividend_reinvestment_backtest_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键 ID"),
        sa.Column("run_id", sa.Integer(), nullable=False, comment="回测批次 ID"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("symbol", sa.String(length=16), nullable=True, comment="股票代码"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="股票名称"),
        sa.Column("industry", sa.String(length=128), nullable=True, comment="所属行业"),
        sa.Column("list_date", sa.Date(), nullable=True, comment="上市日期"),
        sa.Column("start_trade_date", sa.Date(), nullable=True, comment="实际起始交易日"),
        sa.Column("end_trade_date", sa.Date(), nullable=True, comment="实际结束交易日"),
        sa.Column("initial_amount", sa.DECIMAL(24, 6), nullable=False, comment="初始投入金额"),
        sa.Column("initial_price", sa.DECIMAL(20, 6), nullable=True, comment="起始买入价"),
        sa.Column("initial_shares", sa.DECIMAL(24, 8), nullable=True, comment="初始持股数"),
        sa.Column("final_price", sa.DECIMAL(20, 6), nullable=True, comment="结束日价格"),
        sa.Column("final_shares", sa.DECIMAL(24, 8), nullable=True, comment="结束日持股数"),
        sa.Column("final_market_value", sa.DECIMAL(24, 6), nullable=True, comment="结束市值"),
        sa.Column("total_cash_dividend", sa.DECIMAL(24, 6), nullable=True, comment="累计现金分红"),
        sa.Column("total_reinvested_amount", sa.DECIMAL(24, 6), nullable=True, comment="累计再投入金额"),
        sa.Column("total_reinvested_shares", sa.DECIMAL(24, 8), nullable=True, comment="累计再投入股数"),
        sa.Column("dividend_event_count", sa.Integer(), nullable=False, server_default="0", comment="分红事件数"),
        sa.Column("dividend_year_count", sa.Integer(), nullable=False, server_default="0", comment="有分红年份数"),
        sa.Column("consecutive_dividend_years", sa.Integer(), nullable=False, server_default="0", comment="连续分红年数"),
        sa.Column("total_return_amount", sa.DECIMAL(24, 6), nullable=True, comment="累计收益金额"),
        sa.Column("total_return_pct", sa.DECIMAL(20, 8), nullable=True, comment="累计收益率"),
        sa.Column("annualized_return_pct", sa.DECIMAL(20, 8), nullable=True, comment="年化收益率"),
        sa.Column("latest_dividend_yield_ttm", sa.DECIMAL(20, 8), nullable=True, comment="最新 TTM 股息率"),
        sa.Column("latest_total_mv", sa.DECIMAL(24, 6), nullable=True, comment="最新总市值"),
        sa.Column("latest_pe_ttm", sa.DECIMAL(20, 8), nullable=True, comment="最新 PE TTM"),
        sa.Column("latest_pb", sa.DECIMAL(20, 8), nullable=True, comment="最新 PB"),
        sa.Column("rank_score", sa.DECIMAL(20, 8), nullable=True, comment="综合排序分"),
        sa.Column("data_quality", sa.String(length=32), nullable=False, server_default="UNKNOWN", comment="数据质量标记"),
        sa.Column("data_issue", sa.Text(), nullable=True, comment="数据问题说明"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["dividend_reinvestment_backtest_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ts_code", name="uk_div_reinvest_summary_run_code"),
        comment="分红再投入回测摘要表",
    )
    op.create_index(
        "idx_div_reinvest_summary_return",
        "dividend_reinvestment_backtest_summary",
        ["run_id", "annualized_return_pct"],
    )
    op.create_index(
        "idx_div_reinvest_summary_industry",
        "dividend_reinvestment_backtest_summary",
        ["run_id", "industry"],
    )
    op.create_index(
        "idx_div_reinvest_summary_quality",
        "dividend_reinvestment_backtest_summary",
        ["run_id", "data_quality"],
    )

    # 年度明细表服务于截图中的逐年分红再投入表格，字段按年度聚合；
    # 分红事件的逐笔计算留在服务层，年度表只保存可展示、可复核的汇总结果。
    op.create_table(
        "dividend_reinvestment_backtest_yearly",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键 ID"),
        sa.Column("run_id", sa.Integer(), nullable=False, comment="回测批次 ID"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("year", sa.Integer(), nullable=False, comment="年份"),
        sa.Column("year_end_trade_date", sa.Date(), nullable=True, comment="年度估值交易日"),
        sa.Column("year_end_price", sa.DECIMAL(20, 6), nullable=True, comment="年末收盘价"),
        sa.Column("cash_div_per_share", sa.DECIMAL(20, 8), nullable=True, comment="当年每股现金分红"),
        sa.Column("cash_div_amount", sa.DECIMAL(24, 6), nullable=True, comment="当年现金分红金额"),
        sa.Column("stock_div_per_share", sa.DECIMAL(20, 8), nullable=True, comment="当年每股送转"),
        sa.Column("stock_div_shares", sa.DECIMAL(24, 8), nullable=True, comment="当年送转增加股数"),
        sa.Column("reinvest_price_avg", sa.DECIMAL(20, 6), nullable=True, comment="当年再投入加权价格"),
        sa.Column("reinvested_shares", sa.DECIMAL(24, 8), nullable=True, comment="当年再投入买入股数"),
        sa.Column("holding_shares", sa.DECIMAL(24, 8), nullable=True, comment="年末持股数"),
        sa.Column("market_value", sa.DECIMAL(24, 6), nullable=True, comment="年末市值"),
        sa.Column("return_amount", sa.DECIMAL(24, 6), nullable=True, comment="累计收益金额"),
        sa.Column("return_pct", sa.DECIMAL(20, 8), nullable=True, comment="累计收益率"),
        sa.Column("annualized_return_pct", sa.DECIMAL(20, 8), nullable=True, comment="年化收益率"),
        sa.Column("dividend_event_count", sa.Integer(), nullable=False, server_default="0", comment="当年分红事件数"),
        sa.Column("note", sa.Text(), nullable=True, comment="补充说明"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["dividend_reinvestment_backtest_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ts_code", "year", name="uk_div_reinvest_yearly"),
        comment="分红再投入年度明细表",
    )
    op.create_index(
        "idx_div_reinvest_yearly_code",
        "dividend_reinvestment_backtest_yearly",
        ["ts_code", "year"],
    )
    op.create_index(
        "idx_div_reinvest_yearly_run_year",
        "dividend_reinvestment_backtest_yearly",
        ["run_id", "year"],
    )


def downgrade() -> None:
    op.drop_index("idx_div_reinvest_yearly_run_year", table_name="dividend_reinvestment_backtest_yearly")
    op.drop_index("idx_div_reinvest_yearly_code", table_name="dividend_reinvestment_backtest_yearly")
    op.drop_table("dividend_reinvestment_backtest_yearly")
    op.drop_index("idx_div_reinvest_summary_quality", table_name="dividend_reinvestment_backtest_summary")
    op.drop_index("idx_div_reinvest_summary_industry", table_name="dividend_reinvestment_backtest_summary")
    op.drop_index("idx_div_reinvest_summary_return", table_name="dividend_reinvestment_backtest_summary")
    op.drop_table("dividend_reinvestment_backtest_summary")
    op.drop_index("idx_div_reinvest_run_key", table_name="dividend_reinvestment_backtest_run")
    op.drop_index("idx_div_reinvest_run_status_started", table_name="dividend_reinvestment_backtest_run")
    op.drop_table("dividend_reinvestment_backtest_run")
