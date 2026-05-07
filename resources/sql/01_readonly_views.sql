CREATE OR REPLACE VIEW v_official_ah_premium_trend AS
SELECT
  o.trade_date,
  o.a_ts_code,
  o.hk_ts_code,
  o.a_name,
  o.hk_name,
  o.a_close,
  o.a_pct_chg,
  o.hk_close,
  o.hk_pct_chg,
  o.ah_comparison AS ah_ratio,
  o.ah_premium AS ah_premium_pct,
  o.ha_comparison AS ha_ratio,
  o.ha_premium AS ha_premium_pct,
  CASE WHEN c.connect_channels IS NULL THEN 0 ELSE 1 END AS is_hk_connect,
  c.connect_channels,
  o.is_realtime,
  o.data_source,
  o.source_updated_at,
  o.updated_at
FROM official_ah_comparison o
LEFT JOIN (
  SELECT
    trade_date,
    ts_code AS hk_ts_code,
    GROUP_CONCAT(DISTINCT connect_type ORDER BY connect_type SEPARATOR ',') AS connect_channels
  FROM hsgt_constituent
  WHERE connect_type IN ('SH_HK', 'SZ_HK')
  GROUP BY trade_date, ts_code
) c ON c.trade_date = o.trade_date AND c.hk_ts_code = o.hk_ts_code;

CREATE OR REPLACE VIEW v_latest_official_ah_premium AS
SELECT p.*
FROM v_official_ah_premium_trend p
JOIN (
  SELECT MAX(trade_date) AS latest_trade_date
  FROM official_ah_comparison
) d ON p.trade_date = d.latest_trade_date;

CREATE OR REPLACE VIEW v_latest_hk_connect_official_ah_premium AS
SELECT *
FROM v_latest_official_ah_premium
WHERE is_hk_connect = 1;

CREATE OR REPLACE VIEW v_watchlist_opportunity AS
SELECT
  w.id AS watchlist_id,
  w.user_id,
  w.a_ts_code,
  w.hk_ts_code,
  COALESCE(w.display_name, p.a_name, w.a_ts_code) AS display_name,
  w.preferred_direction,
  w.target_premium_pct,
  w.holding_market,
  w.sort_order,
  w.note,
  p.trade_date,
  p.a_name,
  p.hk_name,
  p.ah_ratio,
  p.ah_premium_pct,
  p.ha_ratio,
  p.ha_premium_pct,
  CASE
    WHEN w.preferred_direction = 'AH' THEN p.ah_premium_pct
    ELSE p.ha_premium_pct
  END AS metric_premium_pct,
  CASE
    WHEN w.target_premium_pct IS NULL THEN NULL
    WHEN w.preferred_direction = 'AH' THEN w.target_premium_pct - p.ah_premium_pct
    ELSE w.target_premium_pct - p.ha_premium_pct
  END AS distance_to_target_pct,
  (
    SELECT ROUND(
      SUM(
        CASE
          WHEN (
            CASE WHEN w.preferred_direction = 'AH' THEN h.ah_premium ELSE h.ha_premium END
          ) <= (
            CASE WHEN w.preferred_direction = 'AH' THEN p.ah_premium_pct ELSE p.ha_premium_pct END
          )
          THEN 1 ELSE 0
        END
      ) * 100 / COUNT(*),
      8
    )
    FROM official_ah_comparison h
    WHERE h.a_ts_code = w.a_ts_code
      AND h.hk_ts_code = w.hk_ts_code
      AND h.trade_date <= p.trade_date
      AND (CASE WHEN w.preferred_direction = 'AH' THEN h.ah_premium ELSE h.ha_premium END) IS NOT NULL
      AND (
        SELECT COUNT(*)
        FROM official_ah_comparison h2
        WHERE h2.a_ts_code = w.a_ts_code
          AND h2.hk_ts_code = w.hk_ts_code
          AND h2.trade_date <= p.trade_date
          AND h2.trade_date >= h.trade_date
          AND (CASE WHEN w.preferred_direction = 'AH' THEN h2.ah_premium ELSE h2.ha_premium END) IS NOT NULL
      ) <= 60
  ) AS premium_percentile_60,
  p.is_hk_connect,
  p.connect_channels,
  p.data_source,
  p.source_updated_at,
  CASE
    WHEN p.trade_date IS NULL THEN 'DATA_ISSUE'
    WHEN p.is_hk_connect = 0 THEN 'NOT_CONNECT'
    WHEN w.target_premium_pct IS NULL THEN 'WATCH'
    WHEN (
      CASE
        WHEN w.preferred_direction = 'AH' THEN w.target_premium_pct - p.ah_premium_pct
        ELSE w.target_premium_pct - p.ha_premium_pct
      END
    ) <= 0 THEN 'REACHED'
    WHEN (
      CASE
        WHEN w.preferred_direction = 'AH' THEN w.target_premium_pct - p.ah_premium_pct
        ELSE w.target_premium_pct - p.ha_premium_pct
      END
    ) <= 3 THEN 'NEAR'
    ELSE 'WATCH'
  END AS opportunity_status,
  w.updated_at
FROM watchlist_stock w
LEFT JOIN v_latest_official_ah_premium p
  ON p.a_ts_code = w.a_ts_code AND p.hk_ts_code = w.hk_ts_code
WHERE w.is_active = 1;

-- 兼容旧 LLM 白名单名称，但口径已切换为官方 AH 比价表。
CREATE OR REPLACE VIEW v_latest_ah_premium AS
SELECT *
FROM v_latest_official_ah_premium;

CREATE OR REPLACE VIEW v_ah_premium_trend AS
SELECT *
FROM v_official_ah_premium_trend;

CREATE OR REPLACE VIEW v_sync_health AS
SELECT
  dataset,
  status,
  started_at,
  finished_at,
  row_count,
  error_message,
  updated_at
FROM sync_run;

CREATE OR REPLACE VIEW v_data_quality_issues AS
SELECT
  issue_date,
  issue_type,
  severity,
  ref_key,
  message,
  resolved_at,
  updated_at
FROM data_quality_issue;

CREATE OR REPLACE VIEW v_stock_selection_latest AS
SELECT *
FROM stock_selection_factor_snapshot
WHERE factor_date = (
  SELECT MAX(factor_date)
  FROM stock_selection_factor_snapshot
);

CREATE OR REPLACE VIEW v_stock_selection_history AS
SELECT *
FROM stock_selection_factor_snapshot;

CREATE OR REPLACE VIEW v_stock_factor_dictionary AS
SELECT 'selection_tags' AS field_name, 'BLUE_CHIP/LOW_VALUATION/DIVIDEND/QUALITY 等筛选标签' AS description
UNION ALL SELECT 'selection_score', '综合筛选分，结合蓝筹指数、估值、红利和质量指标'
UNION ALL SELECT 'pe_ttm', '滚动市盈率，越低通常估值越便宜，但需结合行业和盈利稳定性'
UNION ALL SELECT 'pb', '市净率，金融、周期和资产型公司常用估值指标'
UNION ALL SELECT 'dividend_yield_ttm', '滚动股息率，衡量红利属性'
UNION ALL SELECT 'roe', '最近报告期净资产收益率，衡量盈利能力'
UNION ALL SELECT 'debt_to_assets', '资产负债率，衡量杠杆和财务风险'
UNION ALL SELECT 'return_20d/60d/120d', '近 20/60/120 个交易日涨跌幅，用于识别趋势和拥挤度'
UNION ALL SELECT 'is_hs300/is_sse50', '蓝筹代表性指数成分标记'
UNION ALL SELECT 'is_csi_dividend/is_sse_dividend/is_sz_dividend', '红利指数成分标记'
UNION ALL SELECT 'is_csi300_value', '沪深300价值指数成分标记';

-- LLM 个股报告使用的只读视图：仅聚合单股短窗口数据，不暴露抓取审计表和 Tushare 底层接口。
CREATE OR REPLACE VIEW v_stock_quote_valuation_trend AS
SELECT
  q.ts_code,
  b.name,
  b.industry,
  b.area,
  q.trade_date,
  q.close,
  q.pct_chg,
  db.turnover_rate,
  db.pe,
  db.pe_ttm,
  db.pb,
  db.ps_ttm,
  db.dv_ttm AS dividend_yield_ttm,
  db.total_mv,
  db.circ_mv
FROM a_daily_quote q
LEFT JOIN a_daily_basic db
  ON db.ts_code = q.ts_code AND db.trade_date = q.trade_date
LEFT JOIN a_stock_basic b
  ON b.ts_code = q.ts_code;

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
 );

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
 );

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
  ON b.ts_code = ps.ts_code;

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
  ON b.ts_code = mf.ts_code;

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
 );

CREATE OR REPLACE VIEW v_market_data_fetch_health AS
SELECT
  r.id,
  r.question_id,
  r.intent,
  r.market_scope,
  r.symbols_json,
  r.data_packages_json,
  r.period_policy,
  r.status,
  r.cache_hit,
  r.row_count,
  r.error_message,
  r.started_at,
  r.finished_at,
  r.updated_at
FROM llm_market_data_fetch_run r;
