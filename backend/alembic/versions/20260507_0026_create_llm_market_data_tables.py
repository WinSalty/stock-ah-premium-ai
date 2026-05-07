from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260507_0026"
down_revision = "20260507_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # LLM 个股研究只允许按单只股票、短窗口、白名单字段补数；这些表保存能被只读视图消费的
    # 核心事实数据，唯一键按 Tushare 业务主键设计，重跑同一股票同一区间时通过 upsert 覆盖最新修订。
    op.create_table(
        "a_daily_basic",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="交易日期"),
        sa.Column("close", sa.DECIMAL(20, 6), nullable=True, comment="收盘价"),
        sa.Column("turnover_rate", sa.DECIMAL(20, 8), nullable=True, comment="换手率"),
        sa.Column("volume_ratio", sa.DECIMAL(20, 8), nullable=True, comment="量比"),
        sa.Column("pe", sa.DECIMAL(20, 8), nullable=True, comment="市盈率"),
        sa.Column("pe_ttm", sa.DECIMAL(20, 8), nullable=True, comment="滚动市盈率"),
        sa.Column("pb", sa.DECIMAL(20, 8), nullable=True, comment="市净率"),
        sa.Column("ps", sa.DECIMAL(20, 8), nullable=True, comment="市销率"),
        sa.Column("ps_ttm", sa.DECIMAL(20, 8), nullable=True, comment="滚动市销率"),
        sa.Column("dv_ratio", sa.DECIMAL(20, 8), nullable=True, comment="股息率"),
        sa.Column("dv_ttm", sa.DECIMAL(20, 8), nullable=True, comment="滚动股息率"),
        sa.Column("total_share", sa.DECIMAL(24, 6), nullable=True, comment="总股本"),
        sa.Column("float_share", sa.DECIMAL(24, 6), nullable=True, comment="流通股本"),
        sa.Column("free_share", sa.DECIMAL(24, 6), nullable=True, comment="自由流通股本"),
        sa.Column("total_mv", sa.DECIMAL(24, 6), nullable=True, comment="总市值"),
        sa.Column("circ_mv", sa.DECIMAL(24, 6), nullable=True, comment="流通市值"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON，便于审计字段缺口"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "trade_date", name="uk_a_daily_basic"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股每日估值指标表",
    )
    op.create_index("idx_a_daily_basic_date", "a_daily_basic", ["trade_date"])
    op.create_index("idx_a_daily_basic_code_date", "a_daily_basic", ["ts_code", "trade_date"])

    # 三张财务报表只落分析报告第一阶段真正需要的核心字段，保留 raw_payload_json 用于后续扩字段。
    # report_type/update_flag 进入唯一键，避免 Tushare 后续修订报表时覆盖不同口径数据。
    op.create_table(
        "a_income_statement",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=True, comment="公告日期"),
        sa.Column("f_ann_date", sa.Date(), nullable=True, comment="实际公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("report_type", sa.String(length=16), nullable=False, server_default="", comment="报告类型"),
        sa.Column("comp_type", sa.String(length=16), nullable=True, comment="公司类型"),
        sa.Column("end_type", sa.String(length=16), nullable=True, comment="报告期类型"),
        sa.Column("basic_eps", sa.DECIMAL(20, 8), nullable=True, comment="基本每股收益"),
        sa.Column("diluted_eps", sa.DECIMAL(20, 8), nullable=True, comment="稀释每股收益"),
        sa.Column("total_revenue", sa.DECIMAL(24, 6), nullable=True, comment="营业总收入"),
        sa.Column("revenue", sa.DECIMAL(24, 6), nullable=True, comment="营业收入"),
        sa.Column("oper_cost", sa.DECIMAL(24, 6), nullable=True, comment="营业成本"),
        sa.Column("sell_exp", sa.DECIMAL(24, 6), nullable=True, comment="销售费用"),
        sa.Column("admin_exp", sa.DECIMAL(24, 6), nullable=True, comment="管理费用"),
        sa.Column("fin_exp", sa.DECIMAL(24, 6), nullable=True, comment="财务费用"),
        sa.Column("operate_profit", sa.DECIMAL(24, 6), nullable=True, comment="营业利润"),
        sa.Column("total_profit", sa.DECIMAL(24, 6), nullable=True, comment="利润总额"),
        sa.Column("income_tax", sa.DECIMAL(24, 6), nullable=True, comment="所得税"),
        sa.Column("n_income", sa.DECIMAL(24, 6), nullable=True, comment="净利润"),
        sa.Column("n_income_attr_p", sa.DECIMAL(24, 6), nullable=True, comment="归母净利润"),
        sa.Column("update_flag", sa.String(length=8), nullable=False, server_default="", comment="更新标识"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "report_type", "update_flag", name="uk_a_income_statement"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股利润表核心字段表",
    )
    op.create_index("idx_a_income_code_period", "a_income_statement", ["ts_code", "end_date"])

    op.create_table(
        "a_balance_sheet",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=True, comment="公告日期"),
        sa.Column("f_ann_date", sa.Date(), nullable=True, comment="实际公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("report_type", sa.String(length=16), nullable=False, server_default="", comment="报告类型"),
        sa.Column("comp_type", sa.String(length=16), nullable=True, comment="公司类型"),
        sa.Column("total_assets", sa.DECIMAL(24, 6), nullable=True, comment="资产总计"),
        sa.Column("total_liab", sa.DECIMAL(24, 6), nullable=True, comment="负债合计"),
        sa.Column("total_hldr_eqy_inc_min_int", sa.DECIMAL(24, 6), nullable=True, comment="股东权益合计含少数股东"),
        sa.Column("total_hldr_eqy_exc_min_int", sa.DECIMAL(24, 6), nullable=True, comment="归母股东权益"),
        sa.Column("money_cap", sa.DECIMAL(24, 6), nullable=True, comment="货币资金"),
        sa.Column("trad_asset", sa.DECIMAL(24, 6), nullable=True, comment="交易性金融资产"),
        sa.Column("notes_receiv", sa.DECIMAL(24, 6), nullable=True, comment="应收票据"),
        sa.Column("accounts_receiv", sa.DECIMAL(24, 6), nullable=True, comment="应收账款"),
        sa.Column("inventories", sa.DECIMAL(24, 6), nullable=True, comment="存货"),
        sa.Column("total_cur_assets", sa.DECIMAL(24, 6), nullable=True, comment="流动资产合计"),
        sa.Column("st_borr", sa.DECIMAL(24, 6), nullable=True, comment="短期借款"),
        sa.Column("lt_borr", sa.DECIMAL(24, 6), nullable=True, comment="长期借款"),
        sa.Column("bond_payable", sa.DECIMAL(24, 6), nullable=True, comment="应付债券"),
        sa.Column("total_cur_liab", sa.DECIMAL(24, 6), nullable=True, comment="流动负债合计"),
        sa.Column("update_flag", sa.String(length=8), nullable=False, server_default="", comment="更新标识"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "report_type", "update_flag", name="uk_a_balance_sheet"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股资产负债表核心字段表",
    )
    op.create_index("idx_a_balance_code_period", "a_balance_sheet", ["ts_code", "end_date"])

    op.create_table(
        "a_cashflow_statement",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=True, comment="公告日期"),
        sa.Column("f_ann_date", sa.Date(), nullable=True, comment="实际公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("report_type", sa.String(length=16), nullable=False, server_default="", comment="报告类型"),
        sa.Column("comp_type", sa.String(length=16), nullable=True, comment="公司类型"),
        sa.Column("net_profit", sa.DECIMAL(24, 6), nullable=True, comment="净利润"),
        sa.Column("finan_exp", sa.DECIMAL(24, 6), nullable=True, comment="财务费用"),
        sa.Column("c_fr_sale_sg", sa.DECIMAL(24, 6), nullable=True, comment="销售商品提供劳务收到的现金"),
        sa.Column("n_cashflow_act", sa.DECIMAL(24, 6), nullable=True, comment="经营活动现金流净额"),
        sa.Column("n_cashflow_inv_act", sa.DECIMAL(24, 6), nullable=True, comment="投资活动现金流净额"),
        sa.Column("n_cash_flows_fnc_act", sa.DECIMAL(24, 6), nullable=True, comment="筹资活动现金流净额"),
        sa.Column("n_incr_cash_cash_equ", sa.DECIMAL(24, 6), nullable=True, comment="现金及等价物净增加额"),
        sa.Column("c_cash_equ_end_period", sa.DECIMAL(24, 6), nullable=True, comment="期末现金及等价物余额"),
        sa.Column("update_flag", sa.String(length=8), nullable=False, server_default="", comment="更新标识"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "report_type", "update_flag", name="uk_a_cashflow_statement"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股现金流量表核心字段表",
    )
    op.create_index("idx_a_cashflow_code_period", "a_cashflow_statement", ["ts_code", "end_date"])

    op.create_table(
        "a_financial_indicator",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=True, comment="公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("eps", sa.DECIMAL(20, 8), nullable=True, comment="每股收益"),
        sa.Column("dt_eps", sa.DECIMAL(20, 8), nullable=True, comment="稀释每股收益"),
        sa.Column("roe", sa.DECIMAL(20, 8), nullable=True, comment="净资产收益率"),
        sa.Column("roe_waa", sa.DECIMAL(20, 8), nullable=True, comment="加权平均净资产收益率"),
        sa.Column("grossprofit_margin", sa.DECIMAL(20, 8), nullable=True, comment="毛利率"),
        sa.Column("netprofit_margin", sa.DECIMAL(20, 8), nullable=True, comment="净利率"),
        sa.Column("debt_to_assets", sa.DECIMAL(20, 8), nullable=True, comment="资产负债率"),
        sa.Column("current_ratio", sa.DECIMAL(20, 8), nullable=True, comment="流动比率"),
        sa.Column("quick_ratio", sa.DECIMAL(20, 8), nullable=True, comment="速动比率"),
        sa.Column("or_yoy", sa.DECIMAL(20, 8), nullable=True, comment="营业收入同比"),
        sa.Column("netprofit_yoy", sa.DECIMAL(20, 8), nullable=True, comment="净利润同比"),
        sa.Column("ocf_to_revenue", sa.DECIMAL(20, 8), nullable=True, comment="经营现金流与营收比"),
        sa.Column("roe_yoy", sa.DECIMAL(20, 8), nullable=True, comment="ROE 同比"),
        sa.Column("bps", sa.DECIMAL(20, 8), nullable=True, comment="每股净资产"),
        sa.Column("update_flag", sa.String(length=8), nullable=True, comment="更新标识"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", name="uk_a_financial_indicator"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股财务指标核心字段表",
    )
    op.create_index("idx_a_fin_indicator_code_period", "a_financial_indicator", ["ts_code", "end_date"])

    # 分红和业绩预告属于报告增强包，只有用户要求个股报告或股息/业绩前瞻时才按单股补取。
    op.create_table(
        "a_dividend",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="分红年度或报告期"),
        sa.Column("ann_date", sa.Date(), nullable=False, comment="公告日期"),
        sa.Column("div_proc", sa.String(length=64), nullable=False, server_default="", comment="分红进度"),
        sa.Column("stk_div", sa.DECIMAL(20, 8), nullable=True, comment="送转股比例"),
        sa.Column("cash_div", sa.DECIMAL(20, 8), nullable=True, comment="每股分红税前"),
        sa.Column("cash_div_tax", sa.DECIMAL(20, 8), nullable=True, comment="每股分红税后"),
        sa.Column("record_date", sa.Date(), nullable=True, comment="股权登记日"),
        sa.Column("ex_date", sa.Date(), nullable=True, comment="除权除息日"),
        sa.Column("pay_date", sa.Date(), nullable=True, comment="派息日"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "end_date", "ann_date", "div_proc", name="uk_a_dividend"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股分红送股表",
    )
    op.create_index("idx_a_dividend_code_period", "a_dividend", ["ts_code", "end_date"])

    op.create_table(
        "a_forecast",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("ann_date", sa.Date(), nullable=False, comment="公告日期"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="报告期"),
        sa.Column("type", sa.String(length=64), nullable=False, server_default="", comment="预告类型"),
        sa.Column("p_change_min", sa.DECIMAL(20, 8), nullable=True, comment="业绩变动下限百分比"),
        sa.Column("p_change_max", sa.DECIMAL(20, 8), nullable=True, comment="业绩变动上限百分比"),
        sa.Column("net_profit_min", sa.DECIMAL(24, 6), nullable=True, comment="预告净利润下限"),
        sa.Column("net_profit_max", sa.DECIMAL(24, 6), nullable=True, comment="预告净利润上限"),
        sa.Column("last_parent_net", sa.DECIMAL(24, 6), nullable=True, comment="上年同期归母净利润"),
        sa.Column("first_ann_date", sa.Date(), nullable=True, comment="首次公告日"),
        sa.Column("summary", sa.Text(), nullable=True, comment="预告摘要"),
        sa.Column("change_reason", sa.Text(), nullable=True, comment="业绩变动原因"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="Tushare 原始行 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "ann_date", "end_date", "type", name="uk_a_forecast"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="A 股业绩预告表",
    )
    op.create_index("idx_a_forecast_code_period", "a_forecast", ["ts_code", "end_date"])

    # 审计表记录 LLM 因用户问题触发的按需补数批次与每个 Tushare 接口调用，
    # 用于排查积分消耗、缓存命中和失败降级；不保存 token，也不让 LLM 直接访问这些底表。
    op.create_table(
        "llm_market_data_fetch_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("question_id", sa.String(length=64), nullable=True, comment="LLM 单轮问题追踪 ID"),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="用户 ID"),
        sa.Column("session_id", sa.Integer(), nullable=True, comment="会话 ID"),
        sa.Column("intent", sa.String(length=64), nullable=False, server_default="stock_research", comment="补数意图"),
        sa.Column("market_scope", sa.String(length=32), nullable=False, server_default="A_STOCK_SINGLE", comment="市场范围，当前仅允许单只 A 股"),
        sa.Column("symbols_json", sa.Text(), nullable=True, comment="本轮涉及股票代码 JSON"),
        sa.Column("data_packages_json", sa.Text(), nullable=True, comment="白名单数据包 JSON"),
        sa.Column("period_policy", sa.String(length=64), nullable=False, server_default="RECENT_LIMITED", comment="保守取数周期策略"),
        sa.Column("start_date", sa.Date(), nullable=True, comment="本轮开始日期"),
        sa.Column("end_date", sa.Date(), nullable=True, comment="本轮结束日期"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="RUNNING", comment="状态: RUNNING、COMPLETED、FAILED、SKIPPED"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否完全命中缓存"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0", comment="本轮写入或命中的上下文行数"),
        sa.Column("error_message", sa.String(length=512), nullable=True, comment="失败原因摘要"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="完成时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="LLM 按需市场数据抓取批次表",
    )
    op.create_index("idx_llm_market_fetch_question", "llm_market_data_fetch_run", ["question_id"])
    op.create_index("idx_llm_market_fetch_status", "llm_market_data_fetch_run", ["status", "started_at"])

    op.create_table(
        "llm_market_data_fetch_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("run_id", sa.Integer(), nullable=True, comment="抓取批次 ID"),
        sa.Column("package_name", sa.String(length=64), nullable=False, comment="数据包名称"),
        sa.Column("api_name", sa.String(length=64), nullable=False, comment="Tushare 接口名"),
        sa.Column("params_json", sa.Text(), nullable=True, comment="已脱敏请求参数 JSON"),
        sa.Column("fields_json", sa.Text(), nullable=True, comment="字段白名单 JSON"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="RUNNING", comment="状态"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0", comment="返回或写入行数"),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True, comment="调用耗时毫秒"),
        sa.Column("error_message", sa.String(length=512), nullable=True, comment="失败原因摘要"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="LLM 按需市场数据抓取明细表",
    )
    op.create_index("idx_llm_market_fetch_item_run", "llm_market_data_fetch_item", ["run_id"])
    op.create_index("idx_llm_market_fetch_item_api", "llm_market_data_fetch_item", ["api_name", "status"])


def downgrade() -> None:
    op.drop_index("idx_llm_market_fetch_item_api", table_name="llm_market_data_fetch_item")
    op.drop_index("idx_llm_market_fetch_item_run", table_name="llm_market_data_fetch_item")
    op.drop_table("llm_market_data_fetch_item")
    op.drop_index("idx_llm_market_fetch_status", table_name="llm_market_data_fetch_run")
    op.drop_index("idx_llm_market_fetch_question", table_name="llm_market_data_fetch_run")
    op.drop_table("llm_market_data_fetch_run")
    op.drop_index("idx_a_forecast_code_period", table_name="a_forecast")
    op.drop_table("a_forecast")
    op.drop_index("idx_a_dividend_code_period", table_name="a_dividend")
    op.drop_table("a_dividend")
    op.drop_index("idx_a_fin_indicator_code_period", table_name="a_financial_indicator")
    op.drop_table("a_financial_indicator")
    op.drop_index("idx_a_cashflow_code_period", table_name="a_cashflow_statement")
    op.drop_table("a_cashflow_statement")
    op.drop_index("idx_a_balance_code_period", table_name="a_balance_sheet")
    op.drop_table("a_balance_sheet")
    op.drop_index("idx_a_income_code_period", table_name="a_income_statement")
    op.drop_table("a_income_statement")
    op.drop_index("idx_a_daily_basic_code_date", table_name="a_daily_basic")
    op.drop_index("idx_a_daily_basic_date", table_name="a_daily_basic")
    op.drop_table("a_daily_basic")
