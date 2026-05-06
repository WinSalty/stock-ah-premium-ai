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

CREATE TABLE IF NOT EXISTS `historical_premium_backfill_record` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `a_ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `hk_ts_code` VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  `data_source` VARCHAR(32) NOT NULL COMMENT '补数来源标记',
  `status` VARCHAR(16) NOT NULL COMMENT '补数状态: RUNNING、COMPLETED、FAILED',
  `candidate_rows` INT NOT NULL DEFAULT 0 COMMENT '三方数据交集候选行数',
  `inserted_rows` INT NOT NULL DEFAULT 0 COMMENT '实际新增行数',
  `skipped_existing_rows` INT NOT NULL DEFAULT 0 COMMENT '唯一键已存在跳过行数',
  `skipped_invalid_rows` INT NOT NULL DEFAULT 0 COMMENT '价格或汇率无效跳过行数',
  `first_trade_date` DATE DEFAULT NULL COMMENT '本轮候选最早交易日期',
  `last_trade_date` DATE DEFAULT NULL COMMENT '本轮候选最晚交易日期',
  `last_error` VARCHAR(512) DEFAULT NULL COMMENT '失败原因摘要',
  `started_at` DATETIME DEFAULT NULL COMMENT '最近一次开始时间',
  `completed_at` DATETIME DEFAULT NULL COMMENT '最近一次成功完成时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_hist_premium_backfill_pair` (`a_ts_code`, `hk_ts_code`, `data_source`),
  KEY `idx_hist_premium_backfill_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Baidu 历史 AH 比价补数执行记录表';

CREATE TABLE IF NOT EXISTS `realtime_quote_snapshot` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `market` VARCHAR(8) NOT NULL COMMENT '报价市场：A、HK、FX',
  `symbol` VARCHAR(32) NOT NULL COMMENT '标准代码，如 600036.SH、03968.HK、HKD/CNY',
  `last_price` DECIMAL(20,8) DEFAULT NULL COMMENT '最新价或汇率',
  `currency` VARCHAR(8) NOT NULL COMMENT '价格币种，如 CNY、HKD',
  `quote_time` DATETIME DEFAULT NULL COMMENT '行情源报价时间',
  `source` VARCHAR(64) NOT NULL COMMENT '行情来源，如 MANUAL、QOS、FUTU_OPENAPI、FXAPI',
  `quality` VARCHAR(32) NOT NULL DEFAULT 'UNAVAILABLE' COMMENT '报价质量：REALTIME、DELAYED、STALE、ERROR、UNAVAILABLE',
  `raw_payload_json` TEXT DEFAULT NULL COMMENT '原始响应摘要 JSON，不存敏感字段',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否作为有效快照参与读取',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_realtime_quote_symbol_time` (`market`, `symbol`, `quote_time`),
  KEY `idx_realtime_quote_source_time` (`source`, `quote_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='实时行情快照表';

CREATE TABLE IF NOT EXISTS `app_user` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `username` VARCHAR(64) NOT NULL COMMENT '登录用户名',
  `password_hash` VARCHAR(255) NOT NULL COMMENT 'PBKDF2 密码哈希',
  `role` VARCHAR(32) NOT NULL DEFAULT 'USER' COMMENT '用户角色，ADMIN 或 USER',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `display_name` VARCHAR(64) DEFAULT NULL COMMENT '展示名称',
  `email` VARCHAR(128) DEFAULT NULL COMMENT '邮箱',
  `phone` VARCHAR(32) DEFAULT NULL COMMENT '电话',
  `bio` TEXT DEFAULT NULL COMMENT '个人简介或备注',
  `menu_permissions_json` TEXT DEFAULT NULL COMMENT '用户粒度菜单权限 JSON',
  `overview_chart_settings_json` TEXT DEFAULT NULL COMMENT '总览趋势图用户粒度指标显示配置 JSON',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_app_user_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='应用用户表';

CREATE TABLE IF NOT EXISTS `invitation_code` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `code` VARCHAR(64) NOT NULL COMMENT '邀请码',
  `created_by_user_id` INT DEFAULT NULL COMMENT '创建管理员用户 ID',
  `used_by_user_id` INT DEFAULT NULL COMMENT '使用该邀请码注册的用户 ID',
  `used_at` DATETIME DEFAULT NULL COMMENT '使用时间',
  `note` TEXT DEFAULT NULL COMMENT '备注',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_invitation_code` (`code`),
  KEY `idx_invitation_created_by` (`created_by_user_id`),
  KEY `idx_invitation_used_by` (`used_by_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='注册邀请码表';

CREATE TABLE IF NOT EXISTS `watchlist_stock` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` INT NOT NULL DEFAULT 1 COMMENT '所属用户 ID',
  `a_ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `hk_ts_code` VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  `display_name` VARCHAR(128) DEFAULT NULL COMMENT '用户自定义展示名',
  `preferred_direction` VARCHAR(8) NOT NULL DEFAULT 'HA' COMMENT '关注方向，AH 或 HA',
  `target_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '目标溢价或折价阈值，单位百分比',
  `push_enabled` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用消息推送，默认开启',
  `a_price_alert_enabled` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用 A 股股价提醒',
  `a_price_alert_operator` VARCHAR(8) NOT NULL DEFAULT 'GTE' COMMENT 'A 股股价提醒触发方向，GTE 大于等于，LTE 小于等于',
  `a_price_alert_target_price` DECIMAL(20,6) DEFAULT NULL COMMENT 'A 股股价提醒目标价格，人民币',
  `h_price_alert_enabled` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用 H 股股价提醒',
  `h_price_alert_operator` VARCHAR(8) NOT NULL DEFAULT 'GTE' COMMENT 'H 股股价提醒触发方向，GTE 大于等于，LTE 小于等于',
  `h_price_alert_target_price` DECIMAL(20,6) DEFAULT NULL COMMENT 'H 股股价提醒目标价格，港币',
  `holding_market` VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN' COMMENT '当前持有侧，A、H 或 UNKNOWN',
  `sort_order` INT NOT NULL DEFAULT 1000 COMMENT '自选展示排序',
  `note` TEXT DEFAULT NULL COMMENT '用户备注',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用该自选股',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_watchlist_user_pair` (`user_id`, `a_ts_code`, `hk_ts_code`),
  KEY `idx_watchlist_active_order` (`is_active`, `sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户自选 AH 股票表';

CREATE TABLE IF NOT EXISTS `pushplus_binding` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` INT NOT NULL COMMENT '所属用户 ID',
  `friend_id` INT NOT NULL COMMENT 'PushPlus 好友 ID',
  `friend_token` VARCHAR(128) NOT NULL COMMENT 'PushPlus 好友令牌，仅后端发送使用',
  `friend_nick_name` VARCHAR(128) DEFAULT NULL COMMENT 'PushPlus 好友昵称',
  `friend_remark` VARCHAR(128) DEFAULT NULL COMMENT 'PushPlus 好友备注',
  `is_follow` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否关注 PushPlus 微信公众号',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '绑定是否启用',
  `bound_at` DATETIME NOT NULL COMMENT '绑定时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pushplus_binding_user` (`user_id`),
  KEY `idx_pushplus_binding_active` (`is_active`),
  CONSTRAINT `fk_pushplus_binding_user`
    FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PushPlus 好友绑定表';

CREATE TABLE IF NOT EXISTS `alert_event` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` INT NOT NULL COMMENT '所属用户 ID',
  `watchlist_id` INT DEFAULT NULL COMMENT '触发提醒的自选股 ID',
  `event_type` VARCHAR(32) NOT NULL COMMENT '提醒类型，如 THRESHOLD_REACHED、PRICE_REACHED',
  `trading_day` DATE NOT NULL COMMENT '提醒所属交易日',
  `metric_direction` VARCHAR(8) DEFAULT NULL COMMENT '溢价提醒方向，AH 或 HA',
  `metric_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '触发时溢价指标',
  `target_premium_pct` DECIMAL(20,8) DEFAULT NULL COMMENT '用户设置的溢价目标阈值',
  `price_alert_market` VARCHAR(8) DEFAULT NULL COMMENT '股价提醒市场，A 或 H',
  `price_alert_operator` VARCHAR(8) DEFAULT NULL COMMENT '股价提醒触发方向，GTE 或 LTE',
  `price_alert_ts_code` VARCHAR(16) DEFAULT NULL COMMENT '股价提醒证券代码',
  `last_price` DECIMAL(20,6) DEFAULT NULL COMMENT '触发时价格',
  `target_price` DECIMAL(20,6) DEFAULT NULL COMMENT '用户设置的目标价格',
  `message_title` VARCHAR(128) NOT NULL COMMENT '推送标题',
  `message_content` TEXT NOT NULL COMMENT '推送内容',
  `push_channel` VARCHAR(32) NOT NULL DEFAULT 'PUSHPLUS' COMMENT '推送渠道',
  `push_status` VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '推送状态',
  `push_message_id` VARCHAR(128) DEFAULT NULL COMMENT 'PushPlus 消息流水号',
  `error_message` TEXT DEFAULT NULL COMMENT '失败错误信息',
  `dedupe_key` VARCHAR(255) NOT NULL COMMENT '同一交易日提醒去重键',
  `sent_at` DATETIME DEFAULT NULL COMMENT '发送时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_alert_event_dedupe` (`dedupe_key`),
  KEY `idx_alert_event_user_day` (`user_id`, `trading_day`),
  KEY `idx_alert_event_watchlist` (`watchlist_id`),
  CONSTRAINT `fk_alert_event_user`
    FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`),
  CONSTRAINT `fk_alert_event_watchlist`
    FOREIGN KEY (`watchlist_id`) REFERENCES `watchlist_stock` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='提醒事件与推送记录表';

CREATE TABLE IF NOT EXISTS `pushplus_message_log` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `user_id` INT NOT NULL COMMENT '接收系统用户 ID',
  `alert_event_id` INT DEFAULT NULL COMMENT '关联提醒事件 ID，测试推送为空',
  `recipient_type` VARCHAR(16) NOT NULL COMMENT '接收类型，FRIEND 好友消息或 PERSONAL 一对一消息',
  `recipient_friend_id` INT DEFAULT NULL COMMENT 'PushPlus 好友 ID，一对一消息为空',
  `recipient_name` VARCHAR(128) DEFAULT NULL COMMENT '接收对象展示名称',
  `message_title` VARCHAR(128) NOT NULL COMMENT '推送标题',
  `message_content` TEXT NOT NULL COMMENT '推送内容',
  `push_channel` VARCHAR(32) NOT NULL DEFAULT 'PUSHPLUS' COMMENT '推送渠道',
  `push_status` VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '推送状态',
  `push_message_id` VARCHAR(128) DEFAULT NULL COMMENT 'PushPlus 消息流水号',
  `error_message` TEXT DEFAULT NULL COMMENT '失败错误信息',
  `sent_at` DATETIME DEFAULT NULL COMMENT '发送成功时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_pushplus_message_log_user_created` (`user_id`, `created_at`),
  KEY `idx_pushplus_message_log_status_created` (`push_status`, `created_at`),
  CONSTRAINT `fk_pushplus_message_log_user`
    FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`),
  CONSTRAINT `fk_pushplus_message_log_alert_event`
    FOREIGN KEY (`alert_event_id`) REFERENCES `alert_event` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PushPlus 推送消息流水表';

CREATE TABLE IF NOT EXISTS `stock_selection_factor_snapshot` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `factor_date` DATE NOT NULL COMMENT '因子快照日期',
  `ts_code` VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  `symbol` VARCHAR(16) DEFAULT NULL COMMENT '股票交易代码',
  `name` VARCHAR(64) NOT NULL COMMENT '股票简称',
  `industry` VARCHAR(128) DEFAULT NULL COMMENT '所属行业',
  `area` VARCHAR(64) DEFAULT NULL COMMENT '所属地域',
  `market` VARCHAR(64) DEFAULT NULL COMMENT '市场板块',
  `selection_tags` VARCHAR(128) NOT NULL COMMENT '筛选标签，逗号分隔',
  `selection_score` DECIMAL(20,8) DEFAULT NULL COMMENT '综合筛选分',
  `selection_reason` TEXT DEFAULT NULL COMMENT '入选原因说明',
  `is_hs300` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否沪深300成分',
  `is_sse50` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否上证50成分',
  `is_csi300_value` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否沪深300价值指数成分',
  `is_csi_dividend` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否中证红利指数成分',
  `is_sse_dividend` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否上证红利指数成分',
  `is_sz_dividend` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否深证红利指数成分',
  `close` DECIMAL(20,6) DEFAULT NULL COMMENT '最新收盘价',
  `pct_chg` DECIMAL(12,6) DEFAULT NULL COMMENT '最新涨跌幅',
  `turnover_rate` DECIMAL(20,8) DEFAULT NULL COMMENT '换手率',
  `pe_ttm` DECIMAL(20,8) DEFAULT NULL COMMENT '滚动市盈率',
  `pb` DECIMAL(20,8) DEFAULT NULL COMMENT '市净率',
  `ps_ttm` DECIMAL(20,8) DEFAULT NULL COMMENT '滚动市销率',
  `dividend_yield_ttm` DECIMAL(20,8) DEFAULT NULL COMMENT '滚动股息率',
  `total_mv` DECIMAL(24,6) DEFAULT NULL COMMENT '总市值，单位万元',
  `circ_mv` DECIMAL(24,6) DEFAULT NULL COMMENT '流通市值，单位万元',
  `roe` DECIMAL(20,8) DEFAULT NULL COMMENT '最近报告期 ROE',
  `grossprofit_margin` DECIMAL(20,8) DEFAULT NULL COMMENT '毛利率',
  `netprofit_margin` DECIMAL(20,8) DEFAULT NULL COMMENT '净利率',
  `debt_to_assets` DECIMAL(20,8) DEFAULT NULL COMMENT '资产负债率',
  `revenue_yoy` DECIMAL(20,8) DEFAULT NULL COMMENT '营业收入同比',
  `latest_report_period` DATE DEFAULT NULL COMMENT '最近财报报告期',
  `return_20d` DECIMAL(20,8) DEFAULT NULL COMMENT '近 20 个交易日涨跌幅',
  `return_60d` DECIMAL(20,8) DEFAULT NULL COMMENT '近 60 个交易日涨跌幅',
  `return_120d` DECIMAL(20,8) DEFAULT NULL COMMENT '近 120 个交易日涨跌幅',
  `latest_dividend_year` VARCHAR(16) DEFAULT NULL COMMENT '最近分红年度',
  `latest_cash_div_tax` DECIMAL(20,8) DEFAULT NULL COMMENT '最近税后现金分红',
  `latest_dividend_proc` VARCHAR(64) DEFAULT NULL COMMENT '最近分红进度',
  `forecast_type` VARCHAR(64) DEFAULT NULL COMMENT '最近业绩预告类型',
  `forecast_summary` TEXT DEFAULT NULL COMMENT '最近业绩预告摘要',
  `data_source` VARCHAR(32) NOT NULL DEFAULT 'TUSHARE' COMMENT '数据来源',
  `source_trade_date` DATE DEFAULT NULL COMMENT '行情来源交易日',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_stock_selection_factor` (`factor_date`, `ts_code`),
  KEY `idx_selection_factor_date_score` (`factor_date`, `selection_score`),
  KEY `idx_selection_factor_tags` (`selection_tags`),
  KEY `idx_selection_factor_industry` (`industry`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='A 股选股因子快照宽表';

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
  `user_id` INT NOT NULL DEFAULT 1 COMMENT '所属用户 ID',
  `title` VARCHAR(255) NOT NULL COMMENT '会话标题',
  `deleted_at` DATETIME DEFAULT NULL COMMENT '逻辑删除时间，非空表示会话已删除',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_llm_chat_session_deleted_at` (`deleted_at`),
  KEY `idx_llm_chat_session_user` (`user_id`)
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

CREATE TABLE IF NOT EXISTS `llm_call_metric` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `question_id` VARCHAR(32) NOT NULL COMMENT '单轮问题追踪 ID，不包含问题原文',
  `conversation_title` VARCHAR(128) DEFAULT NULL COMMENT '对话标题，由用户提问清洗截取生成',
  `user_id` INT DEFAULT NULL COMMENT '所属用户 ID',
  `user_name` VARCHAR(64) DEFAULT NULL COMMENT '用户展示名称，优先展示名称否则登录名',
  `session_id` INT DEFAULT NULL COMMENT '所属会话 ID',
  `phase` VARCHAR(64) NOT NULL COMMENT '调用阶段，如 question_router、generate_sql、answer_stream',
  `phase_label` VARCHAR(64) DEFAULT NULL COMMENT '调用阶段中文名称',
  `phase_description` TEXT DEFAULT NULL COMMENT '调用阶段中文含义说明',
  `provider` VARCHAR(32) DEFAULT NULL COMMENT '调用提供方，如 Qwen、DeepSeek、Database、Internal',
  `model` VARCHAR(64) DEFAULT NULL COMMENT '模型名称',
  `success` INT NOT NULL DEFAULT 1 COMMENT '是否成功，1 成功，0 失败',
  `elapsed_ms` DOUBLE DEFAULT NULL COMMENT '阶段耗时毫秒',
  `first_chunk_ms` DOUBLE DEFAULT NULL COMMENT '流式首包耗时毫秒',
  `output_chars` INT NOT NULL DEFAULT 0 COMMENT '输出字符数',
  `chunk_count` INT NOT NULL DEFAULT 0 COMMENT '流式 chunk 数',
  `row_count` INT NOT NULL DEFAULT 0 COMMENT '关联数据行数',
  `request_payload_json` LONGTEXT DEFAULT NULL COMMENT '调用 LLM 时的请求参数 JSON，包含上下文 messages，不包含鉴权头和 API Key',
  `response_content` LONGTEXT DEFAULT NULL COMMENT '大模型返回的原始响应内容，流式回答保存拼接后的完整内容',
  `error_message` VARCHAR(512) DEFAULT NULL COMMENT '错误摘要，不包含密钥和问题全文',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_llm_call_metric_question` (`question_id`),
  KEY `idx_llm_call_metric_user_created` (`user_id`, `created_at`),
  KEY `idx_llm_call_metric_session_created` (`session_id`, `created_at`),
  KEY `idx_llm_call_metric_phase_model` (`phase`, `model`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LLM 调用耗时指标表';
