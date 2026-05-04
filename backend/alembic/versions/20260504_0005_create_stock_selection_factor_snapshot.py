from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260504_0005"
down_revision = "20260504_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_selection_factor_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("factor_date", sa.Date(), nullable=False, comment="因子快照日期"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("symbol", sa.String(length=16), nullable=True, comment="股票交易代码"),
        sa.Column("name", sa.String(length=64), nullable=False, comment="股票简称"),
        sa.Column("industry", sa.String(length=128), nullable=True, comment="所属行业"),
        sa.Column("area", sa.String(length=64), nullable=True, comment="所属地域"),
        sa.Column("market", sa.String(length=64), nullable=True, comment="市场板块"),
        sa.Column("selection_tags", sa.String(length=128), nullable=False, comment="筛选标签"),
        sa.Column("selection_score", sa.DECIMAL(20, 8), nullable=True, comment="综合筛选分"),
        sa.Column("selection_reason", sa.Text(), nullable=True, comment="入选原因说明"),
        sa.Column(
            "is_hs300",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否沪深300成分",
        ),
        sa.Column(
            "is_sse50",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否上证50成分",
        ),
        sa.Column(
            "is_csi300_value",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否沪深300价值指数成分",
        ),
        sa.Column(
            "is_csi_dividend",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否中证红利指数成分",
        ),
        sa.Column(
            "is_sse_dividend",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否上证红利指数成分",
        ),
        sa.Column(
            "is_sz_dividend",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否深证红利指数成分",
        ),
        sa.Column("close", sa.DECIMAL(20, 6), nullable=True, comment="最新收盘价"),
        sa.Column("pct_chg", sa.DECIMAL(12, 6), nullable=True, comment="最新涨跌幅"),
        sa.Column("turnover_rate", sa.DECIMAL(20, 8), nullable=True, comment="换手率"),
        sa.Column("pe_ttm", sa.DECIMAL(20, 8), nullable=True, comment="滚动市盈率"),
        sa.Column("pb", sa.DECIMAL(20, 8), nullable=True, comment="市净率"),
        sa.Column("ps_ttm", sa.DECIMAL(20, 8), nullable=True, comment="滚动市销率"),
        sa.Column("dividend_yield_ttm", sa.DECIMAL(20, 8), nullable=True, comment="滚动股息率"),
        sa.Column("total_mv", sa.DECIMAL(24, 6), nullable=True, comment="总市值，单位万元"),
        sa.Column("circ_mv", sa.DECIMAL(24, 6), nullable=True, comment="流通市值，单位万元"),
        sa.Column("roe", sa.DECIMAL(20, 8), nullable=True, comment="最近报告期 ROE"),
        sa.Column("grossprofit_margin", sa.DECIMAL(20, 8), nullable=True, comment="毛利率"),
        sa.Column("netprofit_margin", sa.DECIMAL(20, 8), nullable=True, comment="净利率"),
        sa.Column("debt_to_assets", sa.DECIMAL(20, 8), nullable=True, comment="资产负债率"),
        sa.Column("revenue_yoy", sa.DECIMAL(20, 8), nullable=True, comment="营业收入同比"),
        sa.Column("latest_report_period", sa.Date(), nullable=True, comment="最近财报报告期"),
        sa.Column("return_20d", sa.DECIMAL(20, 8), nullable=True, comment="近 20 个交易日涨跌幅"),
        sa.Column("return_60d", sa.DECIMAL(20, 8), nullable=True, comment="近 60 个交易日涨跌幅"),
        sa.Column("return_120d", sa.DECIMAL(20, 8), nullable=True, comment="近 120 个交易日涨跌幅"),
        sa.Column(
            "latest_dividend_year", sa.String(length=16), nullable=True, comment="最近分红年度"
        ),
        sa.Column(
            "latest_cash_div_tax", sa.DECIMAL(20, 8), nullable=True, comment="最近税后现金分红"
        ),
        sa.Column(
            "latest_dividend_proc", sa.String(length=64), nullable=True, comment="最近分红进度"
        ),
        sa.Column("forecast_type", sa.String(length=64), nullable=True, comment="最近业绩预告类型"),
        sa.Column("forecast_summary", sa.Text(), nullable=True, comment="最近业绩预告摘要"),
        sa.Column(
            "data_source",
            sa.String(length=32),
            nullable=False,
            server_default="TUSHARE",
            comment="数据来源",
        ),
        sa.Column("source_trade_date", sa.Date(), nullable=True, comment="行情来源交易日"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("factor_date", "ts_code", name="uk_stock_selection_factor"),
        comment="A 股选股因子快照宽表",
    )
    op.create_index(
        "idx_selection_factor_date_score",
        "stock_selection_factor_snapshot",
        ["factor_date", "selection_score"],
    )
    op.create_index(
        "idx_selection_factor_tags",
        "stock_selection_factor_snapshot",
        ["selection_tags"],
    )
    op.create_index(
        "idx_selection_factor_industry",
        "stock_selection_factor_snapshot",
        ["industry"],
    )


def downgrade() -> None:
    op.drop_index("idx_selection_factor_industry", table_name="stock_selection_factor_snapshot")
    op.drop_index("idx_selection_factor_tags", table_name="stock_selection_factor_snapshot")
    op.drop_index("idx_selection_factor_date_score", table_name="stock_selection_factor_snapshot")
    op.drop_table("stock_selection_factor_snapshot")
