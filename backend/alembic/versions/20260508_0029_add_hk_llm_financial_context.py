from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260508_0029"
down_revision = "20260507_0028"
branch_labels = None
depends_on = None


def _create_hk_context_views() -> None:
    # 港股问答只暴露摘要视图，隐藏 Tushare 底层接口名；MySQL 5.7 环境避免窗口函数。
    op.execute(
        """
        CREATE OR REPLACE VIEW v_hk_financial_period_summary AS
        SELECT
          fi.ts_code,
          COALESCE(fi.name, b.name) AS name,
          b.market,
          fi.end_date,
          fi.report_type,
          fi.std_report_date,
          fi.currency,
          fi.org_type,
          fi.basic_eps,
          fi.diluted_eps,
          fi.bps,
          fi.operate_income,
          fi.operate_income_yoy,
          fi.operate_income_qoq,
          fi.gross_profit,
          fi.gross_profit_yoy,
          fi.gross_profit_qoq,
          fi.holder_profit,
          fi.holder_profit_yoy,
          fi.holder_profit_qoq,
          fi.net_profit_ratio,
          fi.roe_avg,
          fi.roe_yearly,
          fi.roa,
          fi.roic_yearly,
          fi.total_assets,
          fi.total_liabilities,
          fi.total_parent_equity,
          fi.debt_asset_ratio,
          fi.current_ratio,
          fi.currentdebt_debt,
          fi.netcash_operate,
          fi.netcash_invest,
          fi.netcash_finance,
          fi.end_cash,
          fi.ocf_sales,
          fi.per_netcash_operate,
          fi.divi_ratio,
          fi.dividend_rate,
          fi.dps_hkd,
          fi.total_market_cap,
          fi.hksk_market_cap,
          fi.pe_ttm,
          fi.pb_ttm,
          fi.equity_multiplier,
          fi.equity_ratio
        FROM hk_financial_indicator fi
        LEFT JOIN hk_stock_basic b
          ON b.ts_code = fi.ts_code
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_hk_financial_statement_item_summary AS
        SELECT
          si.ts_code,
          COALESCE(si.name, b.name) AS name,
          b.market,
          si.end_date,
          si.statement_type,
          si.ind_name,
          si.ind_value
        FROM hk_financial_statement_item si
        LEFT JOIN hk_stock_basic b
          ON b.ts_code = si.ts_code
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_hk_stock_research_context_latest AS
        SELECT
          b.ts_code,
          SUBSTRING_INDEX(b.ts_code, '.', 1) AS symbol,
          b.name,
          b.fullname,
          b.market,
          b.curr_type,
          fi.end_date AS latest_report_period,
          fi.report_type AS latest_report_type,
          fi.currency,
          fi.operate_income AS latest_operate_income,
          fi.operate_income_yoy,
          fi.holder_profit AS latest_holder_profit,
          fi.holder_profit_yoy,
          fi.roe_avg,
          fi.roa,
          fi.total_assets,
          fi.total_liabilities,
          fi.debt_asset_ratio,
          fi.netcash_operate,
          fi.netcash_invest,
          fi.netcash_finance,
          fi.end_cash,
          fi.dividend_rate AS latest_dividend_rate,
          fi.dps_hkd,
          fi.pe_ttm AS latest_pe_ttm,
          fi.pb_ttm AS latest_pb_ttm,
          fi.total_market_cap,
          fi.hksk_market_cap
        FROM hk_stock_basic b
        LEFT JOIN hk_financial_indicator fi
          ON fi.ts_code = b.ts_code
         AND fi.end_date = (
           SELECT MAX(fi2.end_date)
           FROM hk_financial_indicator fi2
           WHERE fi2.ts_code = b.ts_code
         )
        """
    )


def upgrade() -> None:
    # 港股财务接口在 15000 积分权限内可用；落库为摘要指标表和窄表项目明细，
    # 按 ts_code + 报告期幂等覆盖，避免问答重复触发时产生重复行。
    op.create_table(
        "hk_financial_indicator",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="港股 Tushare 代码"),
        sa.Column("name", sa.String(length=128), nullable=True, comment="港股名称"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("report_type", sa.String(length=64), nullable=False, server_default="", comment="报告类型"),
        sa.Column("std_report_date", sa.Date(), nullable=True, comment="标准报告期"),
        sa.Column("start_date", sa.Date(), nullable=True, comment="报告起始日"),
        sa.Column("fiscal_year", sa.Integer(), nullable=True, comment="财政年度月份"),
        sa.Column("currency", sa.String(length=16), nullable=True, comment="币种"),
        sa.Column("org_type", sa.String(length=64), nullable=True, comment="公司类型"),
        sa.Column("per_netcash_operate", sa.DECIMAL(20, 8), nullable=True, comment="每股经营现金流"),
        sa.Column("per_oi", sa.DECIMAL(20, 8), nullable=True, comment="每股营业收入"),
        sa.Column("bps", sa.DECIMAL(20, 8), nullable=True, comment="每股净资产"),
        sa.Column("basic_eps", sa.DECIMAL(20, 8), nullable=True, comment="基本每股收益"),
        sa.Column("diluted_eps", sa.DECIMAL(20, 8), nullable=True, comment="摊薄每股收益"),
        sa.Column("operate_income", sa.DECIMAL(24, 6), nullable=True, comment="营业收入"),
        sa.Column("operate_income_yoy", sa.DECIMAL(20, 8), nullable=True, comment="营业收入同比"),
        sa.Column("gross_profit", sa.DECIMAL(24, 6), nullable=True, comment="毛利"),
        sa.Column("gross_profit_yoy", sa.DECIMAL(20, 8), nullable=True, comment="毛利同比"),
        sa.Column("holder_profit", sa.DECIMAL(24, 6), nullable=True, comment="股东应占利润"),
        sa.Column("holder_profit_yoy", sa.DECIMAL(20, 8), nullable=True, comment="股东应占利润同比"),
        sa.Column("gross_profit_ratio", sa.DECIMAL(20, 8), nullable=True, comment="毛利率"),
        sa.Column("eps_ttm", sa.DECIMAL(20, 8), nullable=True, comment="TTM 每股收益"),
        sa.Column("operate_income_qoq", sa.DECIMAL(20, 8), nullable=True, comment="营业收入环比"),
        sa.Column("net_profit_ratio", sa.DECIMAL(20, 8), nullable=True, comment="净利率"),
        sa.Column("roe_avg", sa.DECIMAL(20, 8), nullable=True, comment="平均 ROE"),
        sa.Column("gross_profit_qoq", sa.DECIMAL(20, 8), nullable=True, comment="毛利环比"),
        sa.Column("roa", sa.DECIMAL(20, 8), nullable=True, comment="ROA"),
        sa.Column("holder_profit_qoq", sa.DECIMAL(20, 8), nullable=True, comment="股东应占利润环比"),
        sa.Column("roe_yearly", sa.DECIMAL(20, 8), nullable=True, comment="年度 ROE"),
        sa.Column("roic_yearly", sa.DECIMAL(20, 8), nullable=True, comment="年度 ROIC"),
        sa.Column("total_assets", sa.DECIMAL(24, 6), nullable=True, comment="资产总计"),
        sa.Column("total_liabilities", sa.DECIMAL(24, 6), nullable=True, comment="负债合计"),
        sa.Column("tax_ebt", sa.DECIMAL(20, 8), nullable=True, comment="税前利润税率"),
        sa.Column("ocf_sales", sa.DECIMAL(20, 8), nullable=True, comment="经营现金流与收入比"),
        sa.Column("total_parent_equity", sa.DECIMAL(24, 6), nullable=True, comment="母公司股东权益"),
        sa.Column("debt_asset_ratio", sa.DECIMAL(20, 8), nullable=True, comment="资产负债率"),
        sa.Column("operate_profit", sa.DECIMAL(24, 6), nullable=True, comment="营业利润"),
        sa.Column("pretax_profit", sa.DECIMAL(24, 6), nullable=True, comment="税前利润"),
        sa.Column("netcash_operate", sa.DECIMAL(24, 6), nullable=True, comment="经营现金流净额"),
        sa.Column("netcash_invest", sa.DECIMAL(24, 6), nullable=True, comment="投资现金流净额"),
        sa.Column("netcash_finance", sa.DECIMAL(24, 6), nullable=True, comment="筹资现金流净额"),
        sa.Column("end_cash", sa.DECIMAL(24, 6), nullable=True, comment="期末现金"),
        sa.Column("divi_ratio", sa.DECIMAL(20, 8), nullable=True, comment="派息比例"),
        sa.Column("dividend_rate", sa.DECIMAL(20, 8), nullable=True, comment="股息率"),
        sa.Column("current_ratio", sa.DECIMAL(20, 8), nullable=True, comment="流动比率"),
        sa.Column("currentdebt_debt", sa.DECIMAL(20, 8), nullable=True, comment="流动负债占负债比"),
        sa.Column("total_market_cap", sa.DECIMAL(24, 6), nullable=True, comment="总市值"),
        sa.Column("hksk_market_cap", sa.DECIMAL(24, 6), nullable=True, comment="港股市值"),
        sa.Column("pe_ttm", sa.DECIMAL(20, 8), nullable=True, comment="PE TTM"),
        sa.Column("pb_ttm", sa.DECIMAL(20, 8), nullable=True, comment="PB TTM"),
        sa.Column("dps_hkd", sa.DECIMAL(20, 8), nullable=True, comment="每股股息 HKD"),
        sa.Column("dps_hkd_ly", sa.DECIMAL(20, 8), nullable=True, comment="上年每股股息 HKD"),
        sa.Column("equity_multiplier", sa.DECIMAL(20, 8), nullable=True, comment="权益乘数"),
        sa.Column("equity_ratio", sa.DECIMAL(20, 8), nullable=True, comment="权益比率"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "report_type", name="uk_hk_financial_indicator"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="港股财务指标摘要表",
    )
    op.create_index("idx_hk_fin_indicator_code_period", "hk_financial_indicator", ["ts_code", "end_date"])
    op.create_table(
        "hk_financial_statement_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="港股 Tushare 代码"),
        sa.Column("name", sa.String(length=128), nullable=True, comment="港股名称"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("statement_type", sa.String(length=16), nullable=False, comment="报表类型：INCOME/BALANCE/CASHFLOW"),
        sa.Column("ind_name", sa.String(length=128), nullable=False, comment="指标名称"),
        sa.Column("ind_value", sa.DECIMAL(24, 6), nullable=True, comment="指标值"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "statement_type", "ind_name", name="uk_hk_fin_statement_item"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="港股三大财务报表项目明细表",
    )
    op.create_index("idx_hk_fin_statement_code_period", "hk_financial_statement_item", ["ts_code", "end_date"])
    op.create_index("idx_hk_fin_statement_type", "hk_financial_statement_item", ["statement_type", "ind_name"])
    _create_hk_context_views()


def downgrade() -> None:
    # 先删除港股摘要视图，再删除底表，避免回滚时视图悬挂。
    op.execute("DROP VIEW IF EXISTS v_hk_stock_research_context_latest")
    op.execute("DROP VIEW IF EXISTS v_hk_financial_statement_item_summary")
    op.execute("DROP VIEW IF EXISTS v_hk_financial_period_summary")
    op.drop_table("hk_financial_statement_item")
    op.drop_table("hk_financial_indicator")
