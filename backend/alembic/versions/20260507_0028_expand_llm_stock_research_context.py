from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260507_0028"
down_revision = "20260507_0027"
branch_labels = None
depends_on = None


def _create_context_views() -> None:
    # LLM 只读上下文统一通过摘要视图暴露，隐藏底层 Tushare 接口名和抓取审计表。
    # 本地生产库仍是 MySQL 5.7，视图避免使用窗口函数，确保迁移可在现有环境直接执行。
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_business_profile_summary AS
        SELECT
          mb.ts_code,
          b.name,
          b.industry,
          mb.end_date,
          mb.business_type,
          mb.bz_item,
          mb.bz_sales,
          mb.bz_profit,
          mb.bz_cost,
          CASE
            WHEN mb.bz_sales IS NULL OR mb.bz_sales = 0 THEN NULL
            ELSE ROUND(mb.bz_profit * 100 / mb.bz_sales, 8)
          END AS gross_margin,
          CASE
            WHEN mb_total.total_sales IS NULL OR mb_total.total_sales = 0 THEN NULL
            ELSE ROUND(
              mb.bz_sales * 100
              / mb_total.total_sales,
              8
            )
          END AS revenue_share_pct,
          mb.curr_type,
          fa.audit_result AS latest_audit_result,
          fa.audit_agency AS latest_audit_agency,
          ex.revenue AS latest_express_revenue,
          ex.n_income AS latest_express_n_income,
          ex.yoy_sales AS latest_express_yoy_sales,
          ex.yoy_dedu_np AS latest_express_yoy_dedu_np,
          ex.perf_summary AS latest_express_summary
        FROM a_main_business_composition mb
        LEFT JOIN a_stock_basic b
          ON b.ts_code = mb.ts_code
        LEFT JOIN (
          SELECT
            ts_code,
            end_date,
            business_type,
            SUM(bz_sales) AS total_sales
          FROM a_main_business_composition
          GROUP BY ts_code, end_date, business_type
        ) mb_total
          ON mb_total.ts_code = mb.ts_code
         AND mb_total.end_date = mb.end_date
         AND mb_total.business_type = mb.business_type
        LEFT JOIN a_financial_audit fa
          ON fa.ts_code = mb.ts_code
         AND fa.ann_date = (
           SELECT MAX(fa2.ann_date)
           FROM a_financial_audit fa2
           WHERE fa2.ts_code = mb.ts_code
         )
        LEFT JOIN a_express ex
          ON ex.ts_code = mb.ts_code
         AND ex.ann_date = (
           SELECT MAX(ex2.ann_date)
           FROM a_express ex2
           WHERE ex2.ts_code = mb.ts_code
         )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_shareholder_governance_summary AS
        SELECT
          h.ts_code,
          b.name,
          'TOP10_HOLDER' AS section_type,
          h.end_date AS sort_date,
          (
            SELECT COUNT(*) + 1
            FROM a_top10_holder h2
            WHERE h2.ts_code = h.ts_code
              AND h2.end_date = h.end_date
              AND h2.holder_scope = h.holder_scope
              AND (
                COALESCE(h2.hold_ratio, -999999999) > COALESCE(h.hold_ratio, -999999999)
                OR (
                  COALESCE(h2.hold_ratio, -999999999) = COALESCE(h.hold_ratio, -999999999)
                  AND COALESCE(h2.hold_amount, -999999999) > COALESCE(h.hold_amount, -999999999)
                )
                OR (
                  COALESCE(h2.hold_ratio, -999999999) = COALESCE(h.hold_ratio, -999999999)
                  AND COALESCE(h2.hold_amount, -999999999) = COALESCE(h.hold_amount, -999999999)
                  AND h2.holder_name < h.holder_name
                )
              )
          ) AS ranking,
          h.holder_scope,
          h.holder_name,
          h.hold_amount,
          h.hold_ratio,
          h.hold_float_ratio,
          h.hold_change,
          h.holder_type,
          NULL AS holder_num,
          NULL AS pledge_count,
          NULL AS pledge_ratio,
          NULL AS total_pledge
        FROM a_top10_holder h
        LEFT JOIN a_stock_basic b
          ON b.ts_code = h.ts_code
        UNION ALL
        SELECT
          hn.ts_code,
          b.name,
          'HOLDER_NUMBER' AS section_type,
          hn.end_date AS sort_date,
          1 AS ranking,
          NULL AS holder_scope,
          NULL AS holder_name,
          NULL AS hold_amount,
          NULL AS hold_ratio,
          NULL AS hold_float_ratio,
          NULL AS hold_change,
          NULL AS holder_type,
          hn.holder_num,
          NULL AS pledge_count,
          NULL AS pledge_ratio,
          NULL AS total_pledge
        FROM a_holder_number hn
        LEFT JOIN a_stock_basic b
          ON b.ts_code = hn.ts_code
        UNION ALL
        SELECT
          ps.ts_code,
          b.name,
          'PLEDGE' AS section_type,
          ps.end_date AS sort_date,
          1 AS ranking,
          NULL AS holder_scope,
          NULL AS holder_name,
          NULL AS hold_amount,
          NULL AS hold_ratio,
          NULL AS hold_float_ratio,
          NULL AS hold_change,
          NULL AS holder_type,
          NULL AS holder_num,
          ps.pledge_count,
          ps.pledge_ratio,
          COALESCE(ps.unrest_pledge, 0) + COALESCE(ps.rest_pledge, 0) AS total_pledge
        FROM a_pledge_stat ps
        LEFT JOIN a_stock_basic b
          ON b.ts_code = ps.ts_code
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_moneyflow_recent AS
        SELECT
          mf.ts_code,
          b.name,
          mf.trade_date,
          mf.net_mf_amount,
          COALESCE(mf.buy_lg_amount, 0) + COALESCE(mf.buy_elg_amount, 0)
            - COALESCE(mf.sell_lg_amount, 0) - COALESCE(mf.sell_elg_amount, 0)
            AS big_order_net_amount,
          COALESCE(mf.buy_elg_amount, 0) - COALESCE(mf.sell_elg_amount, 0)
            AS extra_big_order_net_amount,
          mf.buy_lg_amount,
          mf.sell_lg_amount,
          mf.buy_elg_amount,
          mf.sell_elg_amount
        FROM a_moneyflow mf
        LEFT JOIN a_stock_basic b
          ON b.ts_code = mf.ts_code
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_research_context_latest AS
        SELECT
          b.ts_code,
          b.symbol,
          b.name,
          b.industry,
          b.area,
          b.market,
          q.trade_date AS latest_trade_date,
          q.close,
          q.pct_chg,
          q.pe_ttm,
          q.pb,
          q.ps_ttm,
          q.dividend_yield_ttm,
          q.total_mv,
          q.circ_mv,
          f.end_date AS latest_report_period,
          f.roe,
          f.roe_waa,
          f.roe_dt,
          f.roa,
          f.grossprofit_margin,
          f.netprofit_margin,
          f.sales_gpr,
          f.profit_to_gr,
          f.debt_to_assets,
          f.assets_to_eqt,
          f.current_ratio,
          f.quick_ratio,
          f.revenue_yoy,
          f.q_sales_yoy,
          f.netprofit_yoy,
          f.q_netprofit_yoy,
          f.ocf_to_revenue,
          f.ocfps,
          f.bps,
          f.total_revenue,
          f.revenue,
          f.total_cogs,
          f.oper_cost,
          f.sell_exp,
          f.admin_exp,
          f.fin_exp,
          f.rd_exp,
          f.n_income_attr_p,
          f.profit_dedt,
          f.invest_income,
          f.fv_value_chg_gain,
          f.assets_impair_loss,
          f.credit_impa_loss,
          f.n_cashflow_act,
          f.n_cashflow_inv_act,
          f.n_cash_flows_fnc_act,
          f.money_cap,
          f.trad_asset,
          f.lt_eqt_invest,
          f.total_assets,
          f.total_liab,
          f.total_hldr_eqy_exc_min_int,
          bp.bz_item AS latest_main_business_item,
          bp.revenue_share_pct AS latest_main_business_revenue_share_pct,
          bp.gross_margin AS latest_main_business_gross_margin,
          bp.latest_audit_result,
          bp.latest_audit_agency,
          bp.latest_express_revenue,
          bp.latest_express_n_income,
          bp.latest_express_yoy_sales,
          bp.latest_express_yoy_dedu_np,
          d.end_date AS latest_dividend_period,
          d.cash_div_tax AS latest_cash_div_tax,
          d.div_proc AS latest_dividend_proc,
          fc.ann_date AS latest_forecast_ann_date,
          fc.type AS latest_forecast_type,
          fc.summary AS latest_forecast_summary,
          hn.holder_num AS latest_holder_num,
          ps.pledge_ratio AS latest_pledge_ratio,
          mf.net_mf_amount AS latest_net_mf_amount,
          mf.big_order_net_amount AS latest_big_order_net_amount
        FROM a_stock_basic b
        LEFT JOIN v_stock_quote_valuation_trend q
          ON q.ts_code = b.ts_code
         AND q.trade_date = (
           SELECT MAX(q2.trade_date)
           FROM v_stock_quote_valuation_trend q2
           WHERE q2.ts_code = b.ts_code
         )
        LEFT JOIN v_stock_financial_period_summary f
          ON f.ts_code = b.ts_code
         AND f.end_date = (
           SELECT MAX(f2.end_date)
           FROM v_stock_financial_period_summary f2
           WHERE f2.ts_code = b.ts_code
         )
        LEFT JOIN v_stock_business_profile_summary bp
          ON bp.ts_code = b.ts_code
         AND bp.business_type = 'PRODUCT'
         AND bp.end_date = (
           SELECT MAX(bp2.end_date)
           FROM v_stock_business_profile_summary bp2
           WHERE bp2.ts_code = b.ts_code AND bp2.business_type = 'PRODUCT'
         )
         AND bp.revenue_share_pct = (
           SELECT MAX(bp3.revenue_share_pct)
           FROM v_stock_business_profile_summary bp3
           WHERE bp3.ts_code = b.ts_code
             AND bp3.business_type = 'PRODUCT'
             AND bp3.end_date = bp.end_date
         )
        LEFT JOIN a_dividend d
          ON d.ts_code = b.ts_code
         AND d.ann_date = (
           SELECT MAX(d2.ann_date)
           FROM a_dividend d2
           WHERE d2.ts_code = b.ts_code
         )
        LEFT JOIN a_forecast fc
          ON fc.ts_code = b.ts_code
         AND fc.ann_date = (
           SELECT MAX(fc2.ann_date)
           FROM a_forecast fc2
           WHERE fc2.ts_code = b.ts_code
         )
        LEFT JOIN a_holder_number hn
          ON hn.ts_code = b.ts_code
         AND hn.end_date = (
           SELECT MAX(hn2.end_date)
           FROM a_holder_number hn2
           WHERE hn2.ts_code = b.ts_code
         )
        LEFT JOIN a_pledge_stat ps
          ON ps.ts_code = b.ts_code
         AND ps.end_date = (
           SELECT MAX(ps2.end_date)
           FROM a_pledge_stat ps2
           WHERE ps2.ts_code = b.ts_code
         )
        LEFT JOIN v_stock_moneyflow_recent mf
          ON mf.ts_code = b.ts_code
         AND mf.trade_date = (
           SELECT MAX(mf2.trade_date)
           FROM v_stock_moneyflow_recent mf2
           WHERE mf2.ts_code = b.ts_code
         )
        """
    )


def upgrade() -> None:
    # 这些表只接入 15000 积分门槛内可用接口，仍限定单股短/中周期补数，避免 LLM 自动触发全市场扫描。
    op.create_table(
        "a_main_business_composition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("business_type", sa.String(length=8), nullable=False, server_default="", comment="主营构成口径：PRODUCT/REGION"),
        sa.Column("bz_item", sa.String(length=255), nullable=False, server_default="", comment="主营业务项目"),
        sa.Column("bz_sales", sa.DECIMAL(24, 6), nullable=True, comment="主营业务收入"),
        sa.Column("bz_profit", sa.DECIMAL(24, 6), nullable=True, comment="主营业务利润"),
        sa.Column("bz_cost", sa.DECIMAL(24, 6), nullable=True, comment="主营业务成本"),
        sa.Column("curr_type", sa.String(length=16), nullable=True, comment="货币代码"),
        sa.Column("update_flag", sa.String(length=8), nullable=True, comment="更新标识"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "business_type", "bz_item", name="uk_a_main_business_composition"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股主营业务构成表",
    )
    op.create_index("idx_a_main_business_code_period", "a_main_business_composition", ["ts_code", "end_date"])
    op.create_table(
        "a_financial_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=False, comment="公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("audit_result", sa.String(length=128), nullable=True, comment="审计结果"),
        sa.Column("audit_fees", sa.DECIMAL(24, 6), nullable=True, comment="审计费用"),
        sa.Column("audit_agency", sa.String(length=255), nullable=True, comment="会计师事务所"),
        sa.Column("audit_sign", sa.String(length=255), nullable=True, comment="签字会计师"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "ann_date", "end_date", name="uk_a_financial_audit"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股财务审计意见表",
    )
    op.create_index("idx_a_financial_audit_code_period", "a_financial_audit", ["ts_code", "end_date"])
    op.create_table(
        "a_express",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=False, comment="公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("revenue", sa.DECIMAL(24, 6), nullable=True, comment="营业收入"),
        sa.Column("operate_profit", sa.DECIMAL(24, 6), nullable=True, comment="营业利润"),
        sa.Column("total_profit", sa.DECIMAL(24, 6), nullable=True, comment="利润总额"),
        sa.Column("n_income", sa.DECIMAL(24, 6), nullable=True, comment="净利润"),
        sa.Column("total_assets", sa.DECIMAL(24, 6), nullable=True, comment="总资产"),
        sa.Column("total_hldr_eqy_exc_min_int", sa.DECIMAL(24, 6), nullable=True, comment="归母股东权益"),
        sa.Column("diluted_eps", sa.DECIMAL(20, 8), nullable=True, comment="摊薄每股收益"),
        sa.Column("diluted_roe", sa.DECIMAL(20, 8), nullable=True, comment="摊薄净资产收益率"),
        sa.Column("yoy_net_profit", sa.DECIMAL(24, 6), nullable=True, comment="去年同期净利润"),
        sa.Column("bps", sa.DECIMAL(20, 8), nullable=True, comment="每股净资产"),
        sa.Column("yoy_sales", sa.DECIMAL(20, 8), nullable=True, comment="营业收入同比"),
        sa.Column("yoy_op", sa.DECIMAL(20, 8), nullable=True, comment="营业利润同比"),
        sa.Column("yoy_tp", sa.DECIMAL(20, 8), nullable=True, comment="利润总额同比"),
        sa.Column("yoy_dedu_np", sa.DECIMAL(20, 8), nullable=True, comment="归母净利润同比"),
        sa.Column("yoy_eps", sa.DECIMAL(20, 8), nullable=True, comment="每股收益同比"),
        sa.Column("yoy_roe", sa.DECIMAL(20, 8), nullable=True, comment="加权 ROE 同比"),
        sa.Column("growth_assets", sa.DECIMAL(20, 8), nullable=True, comment="总资产较年初增长率"),
        sa.Column("yoy_equity", sa.DECIMAL(20, 8), nullable=True, comment="归母权益较年初增长率"),
        sa.Column("growth_bps", sa.DECIMAL(20, 8), nullable=True, comment="每股净资产较年初增长率"),
        sa.Column("perf_summary", sa.Text(), nullable=True, comment="业绩简要说明"),
        sa.Column("is_audit", sa.Integer(), nullable=True, comment="是否审计"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "ann_date", "end_date", name="uk_a_express"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股业绩快报表",
    )
    op.create_index("idx_a_express_code_period", "a_express", ["ts_code", "end_date"])
    op.create_table(
        "a_top10_holder",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=True, comment="公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("holder_scope", sa.String(length=16), nullable=False, server_default="", comment="股东范围：TOTAL/FLOAT"),
        sa.Column("holder_name", sa.String(length=255), nullable=False, server_default="", comment="股东名称"),
        sa.Column("hold_amount", sa.DECIMAL(24, 6), nullable=True, comment="持股数量"),
        sa.Column("hold_ratio", sa.DECIMAL(20, 8), nullable=True, comment="持股比例"),
        sa.Column("hold_float_ratio", sa.DECIMAL(20, 8), nullable=True, comment="流通股持股比例"),
        sa.Column("hold_change", sa.DECIMAL(24, 6), nullable=True, comment="持股变动"),
        sa.Column("holder_type", sa.String(length=128), nullable=True, comment="股东类型"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "holder_scope", "holder_name", name="uk_a_top10_holder"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股前十大股东和前十大流通股东表",
    )
    op.create_index("idx_a_top10_holder_code_period", "a_top10_holder", ["ts_code", "end_date"])
    op.create_table(
        "a_holder_number",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=False, comment="公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="截止日期"),
        sa.Column("holder_num", sa.Integer(), nullable=True, comment="股东户数"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "ann_date", name="uk_a_holder_number"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股股东户数表",
    )
    op.create_index("idx_a_holder_number_code_period", "a_holder_number", ["ts_code", "end_date"])
    op.create_table(
        "a_pledge_stat",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="截止日期"),
        sa.Column("pledge_count", sa.Integer(), nullable=True, comment="质押次数"),
        sa.Column("unrest_pledge", sa.DECIMAL(24, 6), nullable=True, comment="无限售股质押数量"),
        sa.Column("rest_pledge", sa.DECIMAL(24, 6), nullable=True, comment="限售股质押数量"),
        sa.Column("total_share", sa.DECIMAL(24, 6), nullable=True, comment="总股本"),
        sa.Column("pledge_ratio", sa.DECIMAL(20, 8), nullable=True, comment="质押比例"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", name="uk_a_pledge_stat"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股股权质押统计表",
    )
    op.create_index("idx_a_pledge_stat_code_date", "a_pledge_stat", ["ts_code", "end_date"])
    op.create_table(
        "a_moneyflow",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="交易日期"),
        sa.Column("buy_sm_vol", sa.DECIMAL(24, 6), nullable=True, comment="小单买入量"),
        sa.Column("buy_sm_amount", sa.DECIMAL(24, 6), nullable=True, comment="小单买入金额"),
        sa.Column("sell_sm_vol", sa.DECIMAL(24, 6), nullable=True, comment="小单卖出量"),
        sa.Column("sell_sm_amount", sa.DECIMAL(24, 6), nullable=True, comment="小单卖出金额"),
        sa.Column("buy_md_vol", sa.DECIMAL(24, 6), nullable=True, comment="中单买入量"),
        sa.Column("buy_md_amount", sa.DECIMAL(24, 6), nullable=True, comment="中单买入金额"),
        sa.Column("sell_md_vol", sa.DECIMAL(24, 6), nullable=True, comment="中单卖出量"),
        sa.Column("sell_md_amount", sa.DECIMAL(24, 6), nullable=True, comment="中单卖出金额"),
        sa.Column("buy_lg_vol", sa.DECIMAL(24, 6), nullable=True, comment="大单买入量"),
        sa.Column("buy_lg_amount", sa.DECIMAL(24, 6), nullable=True, comment="大单买入金额"),
        sa.Column("sell_lg_vol", sa.DECIMAL(24, 6), nullable=True, comment="大单卖出量"),
        sa.Column("sell_lg_amount", sa.DECIMAL(24, 6), nullable=True, comment="大单卖出金额"),
        sa.Column("buy_elg_vol", sa.DECIMAL(24, 6), nullable=True, comment="特大单买入量"),
        sa.Column("buy_elg_amount", sa.DECIMAL(24, 6), nullable=True, comment="特大单买入金额"),
        sa.Column("sell_elg_vol", sa.DECIMAL(24, 6), nullable=True, comment="特大单卖出量"),
        sa.Column("sell_elg_amount", sa.DECIMAL(24, 6), nullable=True, comment="特大单卖出金额"),
        sa.Column("net_mf_vol", sa.DECIMAL(24, 6), nullable=True, comment="净流入量"),
        sa.Column("net_mf_amount", sa.DECIMAL(24, 6), nullable=True, comment="净流入金额"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "trade_date", name="uk_a_moneyflow"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股个股资金流向表",
    )
    op.create_index("idx_a_moneyflow_code_date", "a_moneyflow", ["ts_code", "trade_date"])
    _create_context_views()


def downgrade() -> None:
    # 回滚时先恢复 0027 的摘要视图口径，再删除本次新增表，避免视图引用不存在的表。
    op.execute("DROP VIEW IF EXISTS v_stock_moneyflow_recent")
    op.execute("DROP VIEW IF EXISTS v_stock_shareholder_governance_summary")
    op.execute("DROP VIEW IF EXISTS v_stock_business_profile_summary")
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_research_context_latest AS
        SELECT
          b.ts_code,
          b.symbol,
          b.name,
          b.industry,
          b.area,
          b.market,
          q.trade_date AS latest_trade_date,
          q.close,
          q.pct_chg,
          q.pe_ttm,
          q.pb,
          q.ps_ttm,
          q.dividend_yield_ttm,
          q.total_mv,
          q.circ_mv,
          f.end_date AS latest_report_period,
          f.roe,
          f.roe_waa,
          f.roe_dt,
          f.roa,
          f.grossprofit_margin,
          f.netprofit_margin,
          f.sales_gpr,
          f.profit_to_gr,
          f.debt_to_assets,
          f.assets_to_eqt,
          f.current_ratio,
          f.quick_ratio,
          f.revenue_yoy,
          f.q_sales_yoy,
          f.netprofit_yoy,
          f.q_netprofit_yoy,
          f.ocf_to_revenue,
          f.ocfps,
          f.bps,
          f.total_revenue,
          f.revenue,
          f.total_cogs,
          f.oper_cost,
          f.sell_exp,
          f.admin_exp,
          f.fin_exp,
          f.rd_exp,
          f.n_income_attr_p,
          f.profit_dedt,
          f.invest_income,
          f.fv_value_chg_gain,
          f.assets_impair_loss,
          f.credit_impa_loss,
          f.n_cashflow_act,
          f.n_cashflow_inv_act,
          f.n_cash_flows_fnc_act,
          f.money_cap,
          f.trad_asset,
          f.lt_eqt_invest,
          f.total_assets,
          f.total_liab,
          f.total_hldr_eqy_exc_min_int,
          d.end_date AS latest_dividend_period,
          d.cash_div_tax AS latest_cash_div_tax,
          d.div_proc AS latest_dividend_proc,
          fc.ann_date AS latest_forecast_ann_date,
          fc.type AS latest_forecast_type,
          fc.summary AS latest_forecast_summary
        FROM a_stock_basic b
        LEFT JOIN v_stock_quote_valuation_trend q
          ON q.ts_code = b.ts_code
         AND q.trade_date = (
           SELECT MAX(q2.trade_date)
           FROM v_stock_quote_valuation_trend q2
           WHERE q2.ts_code = b.ts_code
         )
        LEFT JOIN v_stock_financial_period_summary f
          ON f.ts_code = b.ts_code
         AND f.end_date = (
           SELECT MAX(f2.end_date)
           FROM v_stock_financial_period_summary f2
           WHERE f2.ts_code = b.ts_code
         )
        LEFT JOIN a_dividend d
          ON d.ts_code = b.ts_code
         AND d.ann_date = (
           SELECT MAX(d2.ann_date)
           FROM a_dividend d2
           WHERE d2.ts_code = b.ts_code
         )
        LEFT JOIN a_forecast fc
          ON fc.ts_code = b.ts_code
         AND fc.ann_date = (
           SELECT MAX(fc2.ann_date)
           FROM a_forecast fc2
           WHERE fc2.ts_code = b.ts_code
         )
        """
    )
    op.drop_table("a_moneyflow")
    op.drop_table("a_pledge_stat")
    op.drop_table("a_holder_number")
    op.drop_table("a_top10_holder")
    op.drop_table("a_express")
    op.drop_table("a_financial_audit")
    op.drop_table("a_main_business_composition")
