from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260507_0027"
down_revision = "20260507_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 个股报告需要识别利润质量，新增字段只承接 Tushare 白名单接口返回值；
    # 旧数据保持 NULL，后续按需补数重跑同一股票时由 upsert 覆盖最新字段。
    op.add_column(
        "a_income_statement",
        sa.Column("invest_income", sa.DECIMAL(24, 6), nullable=True, comment="投资收益"),
    )
    op.add_column(
        "a_income_statement",
        sa.Column(
            "fv_value_chg_gain",
            sa.DECIMAL(24, 6),
            nullable=True,
            comment="公允价值变动收益",
        ),
    )
    op.add_column(
        "a_financial_indicator",
        sa.Column("profit_dedt", sa.DECIMAL(24, 6), nullable=True, comment="扣非净利润"),
    )

    income_extra_columns = (
        ("total_cogs", "营业总成本"),
        ("biz_tax_surchg", "营业税金及附加"),
        ("rd_exp", "研发费用"),
        ("assets_impair_loss", "资产减值损失"),
        ("credit_impa_loss", "信用减值损失"),
        ("oth_income", "其他收益"),
        ("asset_disp_income", "资产处置收益"),
        ("non_oper_income", "营业外收入"),
        ("non_oper_exp", "营业外支出"),
        ("minority_gain", "少数股东损益"),
        ("ebit", "息税前利润"),
        ("ebitda", "息税折旧摊销前利润"),
    )
    for column_name, comment in income_extra_columns:
        op.add_column(
            "a_income_statement",
            sa.Column(column_name, sa.DECIMAL(24, 6), nullable=True, comment=comment),
        )

    balance_extra_columns = (
        ("lt_eqt_invest", "长期股权投资"),
        ("invest_real_estate", "投资性房地产"),
        ("oth_receiv", "其他应收款"),
        ("fix_assets", "固定资产"),
        ("cip", "在建工程"),
        ("intan_assets", "无形资产"),
        ("goodwill", "商誉"),
        ("total_nca", "非流动资产合计"),
        ("notes_payable", "应付票据"),
        ("acct_payable", "应付账款"),
        ("contract_liab", "合同负债"),
        ("total_ncl", "非流动负债合计"),
        ("cap_rese", "资本公积"),
        ("surplus_rese", "盈余公积"),
        ("undistr_porfit", "未分配利润"),
    )
    for column_name, comment in balance_extra_columns:
        op.add_column(
            "a_balance_sheet",
            sa.Column(column_name, sa.DECIMAL(24, 6), nullable=True, comment=comment),
        )

    cashflow_extra_columns = (
        ("c_paid_goods_s", "购买商品接受劳务支付的现金"),
        ("c_paid_to_for_empl", "支付给职工以及为职工支付的现金"),
        ("c_paid_for_taxes", "支付的各项税费"),
        ("c_recp_return_invest", "取得投资收益收到的现金"),
        ("n_recp_disp_fiolta", "处置固定资产等收回现金净额"),
        ("c_pay_acq_const_fiolta", "购建固定资产等支付的现金"),
        ("c_recp_borrow", "取得借款收到的现金"),
        ("c_prepay_amt_borr", "偿还债务支付的现金"),
        ("c_pay_dist_dpcp_int_exp", "分配股利利润或偿付利息支付的现金"),
    )
    for column_name, comment in cashflow_extra_columns:
        op.add_column(
            "a_cashflow_statement",
            sa.Column(column_name, sa.DECIMAL(24, 6), nullable=True, comment=comment),
        )

    fina_extra_columns = (
        ("roe_dt", "扣非摊薄 ROE"),
        ("roa", "总资产报酬率"),
        ("sales_gpr", "销售毛利率"),
        ("profit_to_gr", "净利润与营业总收入比"),
        ("assets_to_eqt", "权益乘数"),
        ("q_sales_yoy", "单季度营业收入同比"),
        ("q_netprofit_yoy", "单季度净利润同比"),
        ("ocfps", "每股经营现金流"),
    )
    for column_name, comment in fina_extra_columns:
        op.add_column(
            "a_financial_indicator",
            sa.Column(column_name, sa.DECIMAL(20, 8), nullable=True, comment=comment),
        )
    # 摘要视图是 LLM 唯一可读的个股研究入口；字段扩展后同步重建视图，保证迁移完成即可被问答链路使用。
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_financial_period_summary AS
        SELECT
          fi.ts_code,
          b.name,
          b.industry,
          fi.end_date,
          fi.ann_date,
          fi.eps,
          fi.roe,
          fi.roe_waa,
          fi.roe_dt,
          fi.roa,
          fi.grossprofit_margin,
          fi.netprofit_margin,
          fi.sales_gpr,
          fi.profit_to_gr,
          fi.debt_to_assets,
          fi.assets_to_eqt,
          fi.current_ratio,
          fi.quick_ratio,
          fi.or_yoy AS revenue_yoy,
          fi.q_sales_yoy,
          fi.netprofit_yoy,
          fi.q_netprofit_yoy,
          fi.ocf_to_revenue,
          fi.ocfps,
          fi.bps,
          fi.profit_dedt,
          i.total_revenue,
          i.revenue,
          i.total_cogs,
          i.oper_cost,
          i.biz_tax_surchg,
          i.sell_exp,
          i.admin_exp,
          i.fin_exp,
          i.rd_exp,
          i.assets_impair_loss,
          i.credit_impa_loss,
          i.oth_income,
          i.asset_disp_income,
          i.operate_profit,
          i.non_oper_income,
          i.non_oper_exp,
          i.total_profit,
          i.income_tax,
          i.n_income,
          i.n_income_attr_p,
          i.minority_gain,
          i.invest_income,
          i.fv_value_chg_gain,
          i.ebit,
          i.ebitda,
          c.net_profit AS cashflow_net_profit,
          c.finan_exp AS cashflow_finan_exp,
          c.c_fr_sale_sg,
          c.c_paid_goods_s,
          c.c_paid_to_for_empl,
          c.c_paid_for_taxes,
          c.n_cashflow_act,
          c.c_recp_return_invest,
          c.n_recp_disp_fiolta,
          c.c_pay_acq_const_fiolta,
          c.n_cashflow_inv_act,
          c.c_recp_borrow,
          c.c_prepay_amt_borr,
          c.c_pay_dist_dpcp_int_exp,
          c.n_cash_flows_fnc_act,
          c.n_incr_cash_cash_equ,
          c.c_cash_equ_end_period,
          bs.money_cap,
          bs.trad_asset,
          bs.lt_eqt_invest,
          bs.invest_real_estate,
          bs.notes_receiv,
          bs.accounts_receiv,
          bs.oth_receiv,
          bs.inventories,
          bs.fix_assets,
          bs.cip,
          bs.intan_assets,
          bs.goodwill,
          bs.total_cur_assets,
          bs.total_nca,
          bs.total_assets,
          bs.st_borr,
          bs.notes_payable,
          bs.acct_payable,
          bs.contract_liab,
          bs.lt_borr,
          bs.bond_payable,
          bs.total_cur_liab,
          bs.total_ncl,
          bs.total_liab,
          bs.total_hldr_eqy_inc_min_int,
          bs.total_hldr_eqy_exc_min_int,
          bs.cap_rese,
          bs.surplus_rese,
          bs.undistr_porfit,
          CASE
            WHEN bs.total_assets IS NULL OR bs.total_assets = 0 THEN NULL
            ELSE ROUND(bs.total_liab * 100 / bs.total_assets, 8)
          END AS calculated_debt_to_assets
        FROM a_financial_indicator fi
        LEFT JOIN a_stock_basic b
          ON b.ts_code = fi.ts_code
        LEFT JOIN a_income_statement i
          ON i.ts_code = fi.ts_code
         AND i.end_date = fi.end_date
         AND i.update_flag = (
           SELECT MAX(i2.update_flag)
           FROM a_income_statement i2
           WHERE i2.ts_code = fi.ts_code AND i2.end_date = fi.end_date
         )
        LEFT JOIN a_cashflow_statement c
          ON c.ts_code = fi.ts_code
         AND c.end_date = fi.end_date
         AND c.update_flag = (
           SELECT MAX(c2.update_flag)
           FROM a_cashflow_statement c2
           WHERE c2.ts_code = fi.ts_code AND c2.end_date = fi.end_date
         )
        LEFT JOIN a_balance_sheet bs
          ON bs.ts_code = fi.ts_code
         AND bs.end_date = fi.end_date
         AND bs.update_flag = (
           SELECT MAX(bs2.update_flag)
           FROM a_balance_sheet bs2
           WHERE bs2.ts_code = fi.ts_code AND bs2.end_date = fi.end_date
         )
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


def downgrade() -> None:
    # 回滚时先恢复旧视图口径，再移除本次扩展字段，避免视图引用不存在列。
    op.execute(
        """
        CREATE OR REPLACE VIEW v_stock_financial_period_summary AS
        SELECT
          fi.ts_code,
          b.name,
          b.industry,
          fi.end_date,
          fi.ann_date,
          fi.eps,
          fi.roe,
          fi.roe_waa,
          fi.grossprofit_margin,
          fi.netprofit_margin,
          fi.debt_to_assets,
          fi.current_ratio,
          fi.quick_ratio,
          fi.or_yoy AS revenue_yoy,
          fi.netprofit_yoy,
          fi.ocf_to_revenue,
          fi.bps,
          i.total_revenue,
          i.revenue,
          i.n_income_attr_p,
          c.n_cashflow_act,
          bs.total_assets,
          bs.total_liab,
          CASE
            WHEN bs.total_assets IS NULL OR bs.total_assets = 0 THEN NULL
            ELSE ROUND(bs.total_liab * 100 / bs.total_assets, 8)
          END AS calculated_debt_to_assets
        FROM a_financial_indicator fi
        LEFT JOIN a_stock_basic b
          ON b.ts_code = fi.ts_code
        LEFT JOIN a_income_statement i
          ON i.ts_code = fi.ts_code
         AND i.end_date = fi.end_date
         AND i.update_flag = (
           SELECT MAX(i2.update_flag)
           FROM a_income_statement i2
           WHERE i2.ts_code = fi.ts_code AND i2.end_date = fi.end_date
         )
        LEFT JOIN a_cashflow_statement c
          ON c.ts_code = fi.ts_code
         AND c.end_date = fi.end_date
         AND c.update_flag = (
           SELECT MAX(c2.update_flag)
           FROM a_cashflow_statement c2
           WHERE c2.ts_code = fi.ts_code AND c2.end_date = fi.end_date
         )
        LEFT JOIN a_balance_sheet bs
          ON bs.ts_code = fi.ts_code
         AND bs.end_date = fi.end_date
         AND bs.update_flag = (
           SELECT MAX(bs2.update_flag)
           FROM a_balance_sheet bs2
           WHERE bs2.ts_code = fi.ts_code AND bs2.end_date = fi.end_date
         )
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
          f.grossprofit_margin,
          f.netprofit_margin,
          f.debt_to_assets,
          f.revenue_yoy,
          f.netprofit_yoy,
          f.ocf_to_revenue,
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
    for column_name in (
        "ocfps",
        "q_netprofit_yoy",
        "q_sales_yoy",
        "assets_to_eqt",
        "profit_to_gr",
        "sales_gpr",
        "roa",
        "roe_dt",
    ):
        op.drop_column("a_financial_indicator", column_name)
    for column_name in (
        "c_pay_dist_dpcp_int_exp",
        "c_prepay_amt_borr",
        "c_recp_borrow",
        "c_pay_acq_const_fiolta",
        "n_recp_disp_fiolta",
        "c_recp_return_invest",
        "c_paid_for_taxes",
        "c_paid_to_for_empl",
        "c_paid_goods_s",
    ):
        op.drop_column("a_cashflow_statement", column_name)
    for column_name in (
        "undistr_porfit",
        "surplus_rese",
        "cap_rese",
        "total_ncl",
        "contract_liab",
        "acct_payable",
        "notes_payable",
        "total_nca",
        "goodwill",
        "intan_assets",
        "cip",
        "fix_assets",
        "oth_receiv",
        "invest_real_estate",
        "lt_eqt_invest",
    ):
        op.drop_column("a_balance_sheet", column_name)
    for column_name in (
        "ebitda",
        "ebit",
        "minority_gain",
        "non_oper_exp",
        "non_oper_income",
        "asset_disp_income",
        "oth_income",
        "credit_impa_loss",
        "assets_impair_loss",
        "rd_exp",
        "biz_tax_surchg",
        "total_cogs",
    ):
        op.drop_column("a_income_statement", column_name)
    op.drop_column("a_financial_indicator", "profit_dedt")
    op.drop_column("a_income_statement", "fv_value_chg_gain")
    op.drop_column("a_income_statement", "invest_income")
