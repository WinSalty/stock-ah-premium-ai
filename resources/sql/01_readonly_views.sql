CREATE OR REPLACE VIEW v_latest_ah_premium AS
SELECT p.*
FROM ah_premium_daily p
JOIN (
  SELECT MAX(trade_date) AS latest_trade_date
  FROM ah_premium_daily
  WHERE calc_status = 'OK'
) d ON p.trade_date = d.latest_trade_date;

CREATE OR REPLACE VIEW v_ah_premium_trend AS
SELECT
  trade_date,
  a_ts_code,
  hk_ts_code,
  a_name,
  hk_name,
  ah_ratio,
  ah_premium_pct,
  connect_channels,
  calc_status
FROM ah_premium_daily;

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
