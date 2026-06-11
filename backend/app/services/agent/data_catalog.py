"""问答可用数据字典：白名单视图/表的列清单与业务口径说明。

自 llm_service._schema() 平移（旧链路退役后该方法删除，本模块成为单点定义）。
消费方：
- prompts.build_system_prompt 把字典拼进系统提示词附录；
- query_database 工具描述引用常用查询示例。
白名单的安全校验仍由 SqlGuardService 独立维护，本字典只负责"告诉模型有什么"。

创建日期：2026-06-12
author: claude（内容平移自 sunshengxian 的 llm_service._schema）
"""

from __future__ import annotations


def schema_catalog() -> dict[str, str]:
    """返回 {视图/表名: 列清单与口径说明} 字典。

    创建日期：2026-06-12
    author: claude
    """

    return {
        "v_latest_official_ah_premium": (
            "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
            "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
            "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
        ),
        "v_official_ah_premium_trend": (
            "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
            "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
            "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
        ),
        "v_latest_hk_connect_official_ah_premium": (
            "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
            "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
            "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
        ),
        "v_watchlist_opportunity": (
            "columns: watchlist_id,user_id,a_ts_code,hk_ts_code,display_name,"
            "preferred_direction,"
            "target_premium_pct,holding_market,sort_order,note,trade_date,a_name,hk_name,"
            "ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,metric_premium_pct,"
            "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
            "data_source,source_updated_at,opportunity_status,updated_at"
        ),
        "v_stock_quote_valuation_trend": (
            "columns: ts_code,name,industry,area,trade_date,close,pct_chg,turnover_rate,"
            "pe,pe_ttm,pb,ps_ttm,dividend_yield_ttm,total_mv,circ_mv"
        ),
        "v_stock_financial_period_summary": (
            "columns: ts_code,name,industry,end_date,ann_date,eps,roe,roe_waa,"
            "roe_dt,roa,grossprofit_margin,netprofit_margin,sales_gpr,profit_to_gr,"
            "debt_to_assets,assets_to_eqt,current_ratio,quick_ratio,revenue_yoy,"
            "q_sales_yoy,netprofit_yoy,q_netprofit_yoy,ocf_to_revenue,ocfps,bps,"
            "profit_dedt,total_revenue,revenue,total_cogs,oper_cost,biz_tax_surchg,"
            "sell_exp,admin_exp,fin_exp,rd_exp,assets_impair_loss,credit_impa_loss,"
            "oth_income,asset_disp_income,operate_profit,non_oper_income,non_oper_exp,"
            "total_profit,income_tax,n_income,n_income_attr_p,minority_gain,invest_income,"
            "fv_value_chg_gain,ebit,ebitda,cashflow_net_profit,cashflow_finan_exp,"
            "c_fr_sale_sg,c_paid_goods_s,c_paid_to_for_empl,c_paid_for_taxes,"
            "n_cashflow_act,c_recp_return_invest,n_recp_disp_fiolta,c_pay_acq_const_fiolta,"
            "n_cashflow_inv_act,c_recp_borrow,c_prepay_amt_borr,c_pay_dist_dpcp_int_exp,"
            "n_cash_flows_fnc_act,n_incr_cash_cash_equ,c_cash_equ_end_period,money_cap,"
            "trad_asset,lt_eqt_invest,invest_real_estate,notes_receiv,accounts_receiv,"
            "oth_receiv,inventories,fix_assets,cip,intan_assets,goodwill,total_cur_assets,"
            "total_nca,total_assets,st_borr,notes_payable,acct_payable,contract_liab,"
            "lt_borr,bond_payable,total_cur_liab,total_ncl,total_liab,"
            "total_hldr_eqy_inc_min_int,total_hldr_eqy_exc_min_int,cap_rese,surplus_rese,"
            "undistr_porfit,calculated_debt_to_assets"
        ),
        "v_stock_business_profile_summary": (
            "columns: ts_code,name,industry,end_date,business_type,bz_item,bz_sales,"
            "bz_profit,bz_cost,gross_margin,revenue_share_pct,curr_type,latest_audit_result,"
            "latest_audit_agency,latest_express_revenue,latest_express_n_income,"
            "latest_express_yoy_sales,latest_express_yoy_dedu_np,latest_express_summary"
        ),
        "v_stock_shareholder_governance_summary": (
            "columns: ts_code,name,section_type,sort_date,ranking,holder_scope,holder_name,"
            "hold_amount,hold_ratio,hold_float_ratio,hold_change,holder_type,holder_num,"
            "pledge_count,pledge_ratio,total_pledge"
        ),
        "v_stock_moneyflow_recent": (
            "columns: ts_code,name,trade_date,net_mf_amount,big_order_net_amount,"
            "extra_big_order_net_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,"
            "sell_elg_amount"
        ),
        "v_stock_research_context_latest": (
            "columns: ts_code,symbol,name,industry,area,market,latest_trade_date,close,"
            "pct_chg,pe_ttm,pb,ps_ttm,dividend_yield_ttm,total_mv,circ_mv,"
            "latest_report_period,roe,roe_waa,roe_dt,roa,grossprofit_margin,"
            "netprofit_margin,sales_gpr,profit_to_gr,debt_to_assets,assets_to_eqt,"
            "current_ratio,quick_ratio,revenue_yoy,q_sales_yoy,netprofit_yoy,"
            "q_netprofit_yoy,ocf_to_revenue,ocfps,bps,total_revenue,revenue,total_cogs,"
            "oper_cost,sell_exp,admin_exp,fin_exp,rd_exp,n_income_attr_p,profit_dedt,"
            "invest_income,fv_value_chg_gain,assets_impair_loss,credit_impa_loss,"
            "n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act,money_cap,trad_asset,"
            "lt_eqt_invest,total_assets,total_liab,total_hldr_eqy_exc_min_int,"
            "latest_main_business_item,latest_main_business_revenue_share_pct,"
            "latest_main_business_gross_margin,latest_audit_result,latest_audit_agency,"
            "latest_express_revenue,latest_express_n_income,latest_express_yoy_sales,"
            "latest_express_yoy_dedu_np,latest_dividend_period,latest_cash_div_tax,"
            "latest_dividend_proc,latest_forecast_ann_date,latest_forecast_type,"
            "latest_forecast_summary,latest_holder_num,latest_pledge_ratio,"
            "latest_net_mf_amount,latest_big_order_net_amount"
        ),
        "v_market_data_fetch_health": (
            "columns: id,question_id,intent,market_scope,symbols_json,data_packages_json,"
            "period_policy,status,cache_hit,row_count,error_message,started_at,finished_at,"
            "updated_at"
        ),
        "dividend_reinvestment_backtest_run": (
            "table purpose: 分红再投入回测批次表。默认查询最新完成批次，"
            "生产历史批次可能使用 status='SUCCESS'，新版批次可能使用 status='COMPLETED'，"
            "因此最新完成批次应使用 "
            "status IN ('COMPLETED','SUCCESS') 并按 finished_at DESC,id DESC 取最新一批；"
            "columns: id,run_key,start_date,end_date,"
            "initial_amount,cash_div_field,reinvest_price_policy,share_rounding_policy,status,"
            "stock_count,summary_count,error_message,started_at,finished_at,created_at,updated_at"
        ),
        "dividend_reinvestment_backtest_summary": (
            "table purpose: 分红再投入筛选摘要表，一只股票在一个 run_id 下只有一行；"
            "用于筛选近十年平均年化、最新 PE、最新 ROE、股息率、连续分红年数、累计收益。"
            "columns: id,run_id,ts_code,symbol,name,industry,list_date,"
            "start_trade_date,end_trade_date,"
            "initial_amount,initial_price,initial_shares,final_price,final_shares,"
            "final_market_value,"
            "total_cash_dividend,total_reinvested_amount,total_reinvested_shares,"
            "dividend_event_count,"
            "dividend_year_count,consecutive_dividend_years,total_return_amount,total_return_pct,"
            "annualized_return_pct,ten_year_avg_annualized_return_pct,latest_dividend_yield_ttm,"
            "latest_total_mv,latest_pe,latest_pe_ttm,latest_pb,latest_roe,rank_score,data_quality,"
            "data_issue,created_at,updated_at"
        ),
        "dividend_reinvestment_backtest_yearly": (
            "table purpose: 分红再投入年度明细表，"
            "用于回答某只股票逐年分红、再投和年末收益明细。"
            "常与 summary 按 run_id,ts_code 关联取得 name、industry 和最新因子。"
            "columns: id,run_id,ts_code,year,year_end_trade_date,"
            "year_end_price,cash_div_per_share,"
            "cash_div_amount,stock_div_per_share,stock_div_shares,reinvest_price_avg,"
            "reinvested_shares,"
            "holding_shares,market_value,return_amount,return_pct,annualized_return_pct,"
            "dividend_event_count,note,created_at,updated_at"
        ),
        "limit_up_analysis_cache": (
            "table purpose: 打板推送报告缓存表，用于风险高收益型、短线、连板和晋级观察推荐。"
            "默认查询最新 READY 报告：status='READY' ORDER BY trade_date DESC,id DESC LIMIT 1；"
            "回答时从报告正文提取观察标的、晋级理由、触发条件和风险。"
            "columns: id,trade_date,report_type,title,content_markdown,content_html,"
            "source_payload_json,status,error_message,generated_at,created_at,updated_at"
        ),
        "v_latest_ah_premium": "columns: same as v_latest_official_ah_premium",
        "v_ah_premium_trend": "columns: same as v_official_ah_premium_trend",
        "v_sync_health": (
            "columns: dataset,last_status,last_started_at,last_finished_at,last_message"
        ),
        "v_data_quality_issues": "columns: issue_type,issue_level,issue_message,related_key",
    }


def schema_catalog_text() -> str:
    """数据字典的提示词文本形态：每个对象一行，便于嵌入系统提示词附录。

    创建日期：2026-06-12
    author: claude
    """

    return "\n".join(f"- {name}: {detail}" for name, detail in schema_catalog().items())
