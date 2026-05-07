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
 );

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
