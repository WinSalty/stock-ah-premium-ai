-- 当前完整表结构参考 SQL。
-- 说明：
-- 1. 本文件用于文档、审阅和新环境核对，实际迁移仍以 backend/alembic/versions 为准。
-- 2. 建库请先执行 resources/sql/00_create_database.sql。
-- 3. 视图请执行 resources/sql/01_readonly_views.sql。

USE stock_ah_ai;

CREATE TABLE IF NOT EXISTS `a_stock_basic` (
  `ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码，主键，例如 600000.SH',
  `symbol` VARCHAR(16) DEFAULT NULL COMMENT '股票交易代码，不含交易所后缀',
  `name` VARCHAR(64) NOT NULL COMMENT '股票简称',
  `area` VARCHAR(64) DEFAULT NULL COMMENT '所属地域',
  `industry` VARCHAR(128) DEFAULT NULL COMMENT '所属行业',
  `fullname` VARCHAR(255) DEFAULT NULL COMMENT '股票全称',
  `market` VARCHAR(64) DEFAULT NULL COMMENT '市场类型，例如主板、创业板、科创板',
  `exchange` VARCHAR(16) DEFAULT NULL COMMENT '交易所代码，例如 SSE、SZSE',
  `curr_type` VARCHAR(16) DEFAULT NULL COMMENT '交易币种',
  `list_status` VARCHAR(8) DEFAULT NULL COMMENT '上市状态，L 表示上市',
  `list_date` DATE DEFAULT NULL COMMENT '上市日期',
  `delist_date` DATE DEFAULT NULL COMMENT '退市日期',
  `is_hs` VARCHAR(8) DEFAULT NULL COMMENT '是否沪深港通标的',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='A 股基础信息表';

CREATE TABLE IF NOT EXISTS `hk_stock_basic` (
  `ts_code` VARCHAR(16) NOT NULL COMMENT '港股 Tushare 代码，主键，例如 00700.HK',
  `name` VARCHAR(128) NOT NULL COMMENT '港股中文简称',
  `fullname` VARCHAR(255) DEFAULT NULL COMMENT '港股中文全称',
  `enname` VARCHAR(255) DEFAULT NULL COMMENT '港股英文名称',
  `cn_spell` VARCHAR(64) DEFAULT NULL COMMENT '中文拼音缩写',
  `market` VARCHAR(64) DEFAULT NULL COMMENT '市场类型',
  `list_status` VARCHAR(8) DEFAULT NULL COMMENT '上市状态，L 表示上市',
  `list_date` DATE DEFAULT NULL COMMENT '上市日期',
  `delist_date` DATE DEFAULT NULL COMMENT '退市日期',
  `trade_unit` DECIMAL(18,4) DEFAULT NULL COMMENT '每手股数',
  `isin` VARCHAR(32) DEFAULT NULL COMMENT 'ISIN 代码',
  `curr_type` VARCHAR(16) DEFAULT NULL COMMENT '交易币种',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='港股基础信息表';

CREATE TABLE IF NOT EXISTS `a_trade_calendar` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `exchange` VARCHAR(16) NOT NULL COMMENT '交易所代码，默认 SSE',
  `cal_date` DATE NOT NULL COMMENT '日历日期',
  `is_open` INT NOT NULL COMMENT '是否开市，1 开市，0 休市',
  `pretrade_date` DATE DEFAULT NULL COMMENT '上一交易日',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_a_trade_calendar` (`exchange`, `cal_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='A 股交易日历表';

CREATE TABLE IF NOT EXISTS `hk_trade_calendar` (
  `cal_date` DATE NOT NULL COMMENT '港股日历日期，主键',
  `is_open` INT NOT NULL COMMENT '是否开市，1 开市，0 休市',
  `pretrade_date` DATE DEFAULT NULL COMMENT '上一交易日',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`cal_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='港股交易日历表';

CREATE TABLE IF NOT EXISTS `a_daily_quote` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `trade_date` DATE NOT NULL COMMENT '交易日期',
  `open` DECIMAL(20,6) DEFAULT NULL COMMENT '开盘价',
  `high` DECIMAL(20,6) DEFAULT NULL COMMENT '最高价',
  `low` DECIMAL(20,6) DEFAULT NULL COMMENT '最低价',
  `close` DECIMAL(20,6) DEFAULT NULL COMMENT '收盘价',
  `pre_close` DECIMAL(20,6) DEFAULT NULL COMMENT '昨收价',
  `change_amount` DECIMAL(20,6) DEFAULT NULL COMMENT '涨跌额',
  `pct_chg` DECIMAL(12,6) DEFAULT NULL COMMENT '涨跌幅，单位百分比',
  `vol` DECIMAL(24,6) DEFAULT NULL COMMENT '成交量',
  `amount` DECIMAL(24,6) DEFAULT NULL COMMENT '成交额',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_a_daily_quote` (`ts_code`, `trade_date`),
  KEY `idx_a_daily_trade_date` (`trade_date`),
  KEY `idx_a_daily_ts_code` (`ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='A 股日线行情表';

CREATE TABLE IF NOT EXISTS `hk_daily_quote` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `ts_code` VARCHAR(16) NOT NULL COMMENT '港股 Tushare 代码',
  `trade_date` DATE NOT NULL COMMENT '交易日期',
  `open` DECIMAL(20,6) DEFAULT NULL COMMENT '开盘价',
  `high` DECIMAL(20,6) DEFAULT NULL COMMENT '最高价',
  `low` DECIMAL(20,6) DEFAULT NULL COMMENT '最低价',
  `close` DECIMAL(20,6) DEFAULT NULL COMMENT '收盘价',
  `pre_close` DECIMAL(20,6) DEFAULT NULL COMMENT '昨收价',
  `change_amount` DECIMAL(20,6) DEFAULT NULL COMMENT '涨跌额',
  `pct_chg` DECIMAL(12,6) DEFAULT NULL COMMENT '涨跌幅，单位百分比',
  `vol` DECIMAL(24,6) DEFAULT NULL COMMENT '成交量',
  `amount` DECIMAL(24,6) DEFAULT NULL COMMENT '成交额',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_hk_daily_quote` (`ts_code`, `trade_date`),
  KEY `idx_hk_daily_trade_date` (`trade_date`),
  KEY `idx_hk_daily_ts_code` (`ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='港股日线行情表，当前 token 无权限时仅保留结构';

CREATE TABLE IF NOT EXISTS `hsgt_constituent` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `ts_code` VARCHAR(16) NOT NULL COMMENT '标的股票代码',
  `trade_date` DATE NOT NULL COMMENT '名单生效交易日',
  `connect_type` VARCHAR(16) NOT NULL COMMENT '沪深港通类型，例如 SH_HK、SZ_HK、HK_SH、HK_SZ',
  `name` VARCHAR(128) DEFAULT NULL COMMENT '股票名称',
  `type_name` VARCHAR(128) DEFAULT NULL COMMENT '类型名称',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_hsgt_constituent` (`trade_date`, `ts_code`, `connect_type`),
  KEY `idx_hsgt_date_type` (`trade_date`, `connect_type`),
  KEY `idx_hsgt_ts_code` (`ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='沪深港通标的名单表';

CREATE TABLE IF NOT EXISTS `fx_rate_daily` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `rate_pair` VARCHAR(32) NOT NULL COMMENT '标准化汇率对，例如 HKD_CNY、USD_HKD',
  `rate_date` DATE NOT NULL COMMENT '汇率日期',
  `base_ccy` VARCHAR(8) NOT NULL COMMENT '基础货币',
  `quote_ccy` VARCHAR(8) NOT NULL COMMENT '计价货币',
  `mid_rate` DECIMAL(20,8) DEFAULT NULL COMMENT '中间价或计算用汇率',
  `bid_close` DECIMAL(20,8) DEFAULT NULL COMMENT '收盘买价',
  `ask_close` DECIMAL(20,8) DEFAULT NULL COMMENT '收盘卖价',
  `source` VARCHAR(32) NOT NULL COMMENT '汇率来源，例如 TUSHARE_FXCM、MANUAL',
  `raw_ts_code` VARCHAR(32) DEFAULT NULL COMMENT '原始 Tushare 汇率代码',
  `is_cross_rate` TINYINT(1) NOT NULL COMMENT '是否为交叉汇率计算结果',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_fx_rate_daily` (`rate_pair`, `rate_date`, `source`),
  KEY `idx_fx_pair_date` (`rate_pair`, `rate_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='外汇汇率日线表';

CREATE TABLE IF NOT EXISTS `ah_stock_pair` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `a_ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `hk_ts_code` VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  `a_name` VARCHAR(128) DEFAULT NULL COMMENT 'A 股名称',
  `hk_name` VARCHAR(128) DEFAULT NULL COMMENT 'H 股名称',
  `source` VARCHAR(32) NOT NULL COMMENT '配对来源，例如 TUSHARE_STK_AH、MANUAL',
  `effective_start_date` DATE DEFAULT NULL COMMENT '配对生效开始日期',
  `effective_end_date` DATE DEFAULT NULL COMMENT '配对生效结束日期',
  `is_active` TINYINT(1) NOT NULL COMMENT '是否启用该配对',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ah_stock_pair` (`a_ts_code`, `hk_ts_code`),
  KEY `idx_ah_pair_hk` (`hk_ts_code`),
  KEY `idx_ah_pair_a` (`a_ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AH 股票配对表';

CREATE TABLE IF NOT EXISTS `official_ah_comparison` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `trade_date` DATE NOT NULL COMMENT '交易日期',
  `a_ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `hk_ts_code` VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  `a_name` VARCHAR(128) DEFAULT NULL COMMENT 'A 股名称',
  `hk_name` VARCHAR(128) DEFAULT NULL COMMENT 'H 股名称',
  `a_close` DECIMAL(20,6) DEFAULT NULL COMMENT 'A 股收盘价，人民币',
  `a_pct_chg` DECIMAL(12,6) DEFAULT NULL COMMENT 'A 股涨跌幅，单位百分比',
  `hk_close` DECIMAL(20,6) DEFAULT NULL COMMENT 'H 股收盘价，港币',
  `hk_pct_chg` DECIMAL(12,6) DEFAULT NULL COMMENT 'H 股涨跌幅，单位百分比',
  `ah_comparison` DECIMAL(20,8) DEFAULT NULL COMMENT '官方 A/H 比价',
  `ah_premium` DECIMAL(20,8) DEFAULT NULL COMMENT '官方 A/H 溢价，单位百分比',
  `ha_comparison` DECIMAL(20,8) DEFAULT NULL COMMENT 'H/A 比价，由 A/H 比价反推',
  `ha_premium` DECIMAL(20,8) DEFAULT NULL COMMENT 'H/A 溢价，单位百分比，由 H/A 比价计算',
  `is_realtime` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否实时或手工重算来源',
  `data_source` VARCHAR(32) NOT NULL DEFAULT 'TUSHARE_OFFICIAL' COMMENT '数据来源标记',
  `source_updated_at` DATETIME DEFAULT NULL COMMENT '来源更新时间或派生指标重算时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_official_ah` (`trade_date`, `a_ts_code`, `hk_ts_code`),
  KEY `idx_official_ah_trade_date` (`trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Tushare 官方 AH 比价快照表，当前主展示口径';

CREATE TABLE IF NOT EXISTS `ah_premium_daily` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `trade_date` DATE NOT NULL COMMENT '交易日期',
  `a_ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `hk_ts_code` VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  `a_name` VARCHAR(128) DEFAULT NULL COMMENT 'A 股名称',
  `hk_name` VARCHAR(128) DEFAULT NULL COMMENT 'H 股名称',
  `a_close_cny` DECIMAL(20,6) DEFAULT NULL COMMENT 'A 股人民币收盘价',
  `h_close_hkd` DECIMAL(20,6) DEFAULT NULL COMMENT 'H 股港币收盘价',
  `hkd_cny` DECIMAL(20,8) DEFAULT NULL COMMENT '港币兑人民币汇率',
  `h_close_cny` DECIMAL(20,6) DEFAULT NULL COMMENT 'H 股折算人民币收盘价',
  `ah_ratio` DECIMAL(20,8) DEFAULT NULL COMMENT '自算 A/H 比价',
  `ah_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '自算 A/H 溢价，单位百分比',
  `ha_ratio` DECIMAL(20,8) DEFAULT NULL COMMENT '自算 H/A 比价',
  `ha_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '自算 H/A 溢价，单位百分比',
  `is_hk_connect` TINYINT(1) NOT NULL COMMENT '是否港股通可操作',
  `connect_channels` VARCHAR(64) DEFAULT NULL COMMENT '港股通通道，逗号分隔，例如 SH_HK,SZ_HK',
  `rate_date` DATE DEFAULT NULL COMMENT '采用的汇率日期',
  `rate_source` VARCHAR(64) DEFAULT NULL COMMENT '采用的汇率来源',
  `rate_fallback` TINYINT(1) NOT NULL COMMENT '是否使用非同日汇率兜底',
  `calc_status` VARCHAR(32) NOT NULL COMMENT '计算状态，例如 OK、MISSING_A_QUOTE、MISSING_H_QUOTE、MISSING_RATE',
  `official_ah_ratio` DECIMAL(20,8) DEFAULT NULL COMMENT '官方 A/H 比价快照',
  `official_ah_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '官方 A/H 溢价快照',
  `official_ha_ratio` DECIMAL(20,8) DEFAULT NULL COMMENT '官方 H/A 比价快照',
  `official_ha_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '官方 H/A 溢价快照',
  `diff_from_official_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '自算 A/H 溢价与官方 A/H 溢价差值',
  `diff_from_official_ha_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '自算 H/A 溢价与官方 H/A 溢价差值',
  `error_message` TEXT DEFAULT NULL COMMENT '计算异常说明',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ah_premium_daily` (`trade_date`, `a_ts_code`, `hk_ts_code`),
  KEY `idx_ah_premium_rank` (`trade_date`, `ah_premium_pct`),
  KEY `idx_ah_premium_hk` (`hk_ts_code`, `trade_date`),
  KEY `idx_ah_premium_a` (`a_ts_code`, `trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='自算港股通 AH 溢价结果表，当前仅作扩展和校验口径保留';

CREATE TABLE IF NOT EXISTS `watchlist_stock` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `a_ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `hk_ts_code` VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  `display_name` VARCHAR(128) DEFAULT NULL COMMENT '用户自定义展示名',
  `preferred_direction` VARCHAR(8) NOT NULL DEFAULT 'HA' COMMENT '关注方向，AH 或 HA',
  `target_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '目标溢价或折价阈值，单位百分比',
  `holding_market` VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN' COMMENT '当前持有侧，A、H 或 UNKNOWN',
  `sort_order` INT NOT NULL DEFAULT 1000 COMMENT '自选展示排序',
  `note` TEXT DEFAULT NULL COMMENT '用户备注',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用该自选股',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_watchlist_stock_pair` (`a_ts_code`, `hk_ts_code`),
  KEY `idx_watchlist_active_order` (`is_active`, `sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户自选 AH 股票表';

CREATE TABLE IF NOT EXISTS `sync_run` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `dataset` VARCHAR(64) NOT NULL COMMENT '同步数据集名称',
  `params_json` TEXT DEFAULT NULL COMMENT '同步参数 JSON',
  `status` VARCHAR(32) NOT NULL COMMENT '任务状态，PENDING、RUNNING、SUCCESS、FAILED',
  `started_at` DATETIME DEFAULT NULL COMMENT '任务开始时间',
  `finished_at` DATETIME DEFAULT NULL COMMENT '任务结束时间',
  `row_count` INT NOT NULL COMMENT '本次写入或处理行数',
  `error_message` TEXT DEFAULT NULL COMMENT '失败错误信息',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据同步任务运行记录表';

CREATE TABLE IF NOT EXISTS `sync_checkpoint` (
  `dataset` VARCHAR(64) NOT NULL COMMENT '同步数据集名称',
  `scope_key` VARCHAR(128) NOT NULL COMMENT '同步范围键，例如 default、ts_code 或通道类型',
  `last_success_date` DATE DEFAULT NULL COMMENT '最近成功同步到的日期',
  `last_run_id` INT DEFAULT NULL COMMENT '最近成功同步任务 ID',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`dataset`, `scope_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据同步断点表';

CREATE TABLE IF NOT EXISTS `data_quality_issue` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `issue_date` DATE DEFAULT NULL COMMENT '问题对应日期',
  `issue_type` VARCHAR(64) NOT NULL COMMENT '问题类型',
  `severity` VARCHAR(32) NOT NULL COMMENT '严重级别，例如 INFO、WARN、ERROR',
  `ref_key` VARCHAR(128) DEFAULT NULL COMMENT '关联对象键，例如股票代码或数据集',
  `message` TEXT NOT NULL COMMENT '问题说明',
  `resolved_at` DATETIME DEFAULT NULL COMMENT '解决时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据质量问题记录表';

CREATE TABLE IF NOT EXISTS `llm_chat_session` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `title` VARCHAR(255) NOT NULL COMMENT '会话标题',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LLM 问答会话表';

CREATE TABLE IF NOT EXISTS `llm_chat_message` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `session_id` INT NOT NULL COMMENT '所属会话 ID',
  `role` VARCHAR(32) NOT NULL COMMENT '消息角色，user 或 assistant',
  `content` TEXT NOT NULL COMMENT '消息正文',
  `sql_text` TEXT DEFAULT NULL COMMENT 'LLM 生成并通过校验的 SQL',
  `result_preview_json` TEXT DEFAULT NULL COMMENT '查询结果预览 JSON',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_llm_chat_message_session_id` (`session_id`),
  CONSTRAINT `fk_llm_chat_message_session`
    FOREIGN KEY (`session_id`) REFERENCES `llm_chat_session` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LLM 问答消息表';
