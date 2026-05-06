-- 用招商银行 A/H 已补齐的行情日期补齐 AH 联合交易日历。
-- 背景：Baidu 历史补数已经按 A 股价、H 股价、HKD/CNY 汇率三方日期交集生成，
--      因此这些日期可以作为 AH 联合交易日的兜底基准，避免总览趋势接口被缺失交易日历过滤掉早期数据。
-- 幂等口径：重复执行不会产生重复日期；若同日已存在但被标记为休市，则按招商银行交集基准修正为开市。

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_cmb_ah_trade_dates (
  cal_date DATE NOT NULL PRIMARY KEY
) ENGINE=Memory;

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_cmb_ah_trade_dates_with_prev (
  cal_date DATE NOT NULL PRIMARY KEY,
  pretrade_date DATE DEFAULT NULL
) ENGINE=Memory;

TRUNCATE TABLE tmp_cmb_ah_trade_dates;
TRUNCATE TABLE tmp_cmb_ah_trade_dates_with_prev;

-- 只使用招商银行这组 A/H 主表日期作为兜底基准，避免把其他标的的零散异常日期扩散到全局交易日历。
INSERT INTO tmp_cmb_ah_trade_dates (cal_date)
SELECT DISTINCT trade_date
FROM official_ah_comparison
WHERE a_ts_code = '600036.SH'
  AND hk_ts_code = '03968.HK';

-- 为新增的早期日历补上上一交易日，便于后续同步或展示逻辑沿用交易日历字段。
INSERT INTO tmp_cmb_ah_trade_dates_with_prev (cal_date, pretrade_date)
SELECT ordered_dates.cal_date, ordered_dates.pretrade_date
FROM (
  SELECT
    sorted_dates.cal_date,
    @previous_trade_date AS pretrade_date,
    @previous_trade_date := sorted_dates.cal_date AS ignored_current_date
  FROM (
    SELECT cal_date
    FROM tmp_cmb_ah_trade_dates
    ORDER BY cal_date
  ) sorted_dates
  CROSS JOIN (SELECT @previous_trade_date := NULL) vars
) ordered_dates;

-- A 股交易日历缺失时插入 SSE 开市日；已存在但为休市时按招商银行三方交集修正为开市。
INSERT INTO a_trade_calendar (exchange, cal_date, is_open, pretrade_date, created_at, updated_at)
SELECT 'SSE', cal_date, 1, pretrade_date, NOW(), NOW()
FROM tmp_cmb_ah_trade_dates_with_prev
ON DUPLICATE KEY UPDATE
  is_open = 1,
  pretrade_date = COALESCE(a_trade_calendar.pretrade_date, VALUES(pretrade_date)),
  updated_at = NOW();

-- 港股交易日历缺失时插入开市日；已存在但为休市时按招商银行三方交集修正为开市。
INSERT INTO hk_trade_calendar (cal_date, is_open, pretrade_date, created_at, updated_at)
SELECT cal_date, 1, pretrade_date, NOW(), NOW()
FROM tmp_cmb_ah_trade_dates_with_prev
ON DUPLICATE KEY UPDATE
  is_open = 1,
  pretrade_date = COALESCE(hk_trade_calendar.pretrade_date, VALUES(pretrade_date)),
  updated_at = NOW();

DROP TEMPORARY TABLE IF EXISTS tmp_cmb_ah_trade_dates_with_prev;
DROP TEMPORARY TABLE IF EXISTS tmp_cmb_ah_trade_dates;
