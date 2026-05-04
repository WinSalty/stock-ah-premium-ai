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
      AND h.trade_date >= DATE_SUB(p.trade_date, INTERVAL 120 DAY)
      AND (CASE WHEN w.preferred_direction = 'AH' THEN h.ah_premium ELSE h.ha_premium END) IS NOT NULL
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
