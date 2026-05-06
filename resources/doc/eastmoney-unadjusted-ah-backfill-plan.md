# 东方财富不复权历史 AH 比价补数实施方案

更新日期：2026-05-06

## 目标

用东方财富历史 K 线公开 JSON 接口补齐 2025-08-12 之前的 A/H 不复权收盘价，结合 `water-stock` 拉取的 HKD/CNY 历史汇率，在 `stock-ah-premium-ai` 自己的数据库内追跑历史 AH 比价。新链路不覆盖现有 Tushare 官方数据和 Baidu 前复权补数，使用独立表和独立 `data_source` 标记，便于查询、核验和回滚。

## 设计原则

- `stock-ah-premium-ai` 负责主业务数据、表结构、历史 AH 比价追算、查询页展示和后端接口。
- `water-stock` 只负责拉取 HKD/CNY 历史汇率并写入 `stock-ah-premium-ai` 数据库的独立汇率表，不再承担不复权 AH 比价计算。
- 现有 `water-stock` Baidu 前复权补数逻辑先保留，不删除、不改默认行为，避免影响已补数据和已验证的幂等记录。
- 东方财富 K 线接口只用于不复权历史股价补数，使用低频批量拉取，不绕过登录、验证码或权限控制。
- 不复权补数结果使用新的 `data_source='EASTMONEY_UNADJUSTED_BACKFILL'`，与 `TUSHARE_OFFICIAL`、`BAIDU_HISTORY_BACKFILL` 明确区分。
- 所有写入逻辑必须幂等：同一日期、同一股票、同一来源重复执行不重复插入；追跑 AH 比价时不覆盖官方 Tushare 行。

## 数据来源

### 东方财富历史 K 线

接口地址：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get
```

核心参数：

```text
secid=1.600036      # 沪市 A 股
secid=0.000001      # 深市 A 股
secid=116.03968     # 港股
klt=101             # 日 K
fqt=0               # 不复权
beg=20180101
end=20250811
fields1=f1,f2,f3,f4,f5,f6
fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
```

`klines` 字段格式：

```text
日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
```

本链路只使用不复权 `收盘` 计算 AH 比价，同时保留开高低、成交量、成交额等字段，便于后续排查。

### HKD/CNY 历史汇率

`water-stock` 新增单独方法拉取 HKD/CNY 历史日线，写入 `stock-ah-premium-ai` 数据库独立表。初版可以继续复用现有 Baidu HKDCNY 请求能力，但必须写到新表，不混入 `fx_rate_daily` 或其他 Tushare 同步表。

## 新增表

### `eastmoney_unadjusted_daily_quote`

用途：存储东方财富 A 股与港股不复权历史日 K。

建议字段：

```sql
CREATE TABLE IF NOT EXISTS eastmoney_unadjusted_daily_quote (
  id INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  market VARCHAR(8) NOT NULL COMMENT '市场: A、HK',
  ts_code VARCHAR(16) NOT NULL COMMENT '项目标准代码，如 600036.SH、03968.HK',
  eastmoney_secid VARCHAR(32) NOT NULL COMMENT '东方财富 secid，如 1.600036、116.03968',
  trade_date DATE NOT NULL COMMENT '交易日期',
  open DECIMAL(20,6) DEFAULT NULL COMMENT '不复权开盘价',
  close DECIMAL(20,6) NOT NULL COMMENT '不复权收盘价',
  high DECIMAL(20,6) DEFAULT NULL COMMENT '不复权最高价',
  low DECIMAL(20,6) DEFAULT NULL COMMENT '不复权最低价',
  volume DECIMAL(24,4) DEFAULT NULL COMMENT '成交量，按东方财富原始单位保存',
  amount DECIMAL(24,4) DEFAULT NULL COMMENT '成交额，按东方财富原始单位保存',
  amplitude DECIMAL(20,6) DEFAULT NULL COMMENT '振幅',
  pct_chg DECIMAL(20,6) DEFAULT NULL COMMENT '涨跌幅',
  change_amount DECIMAL(20,6) DEFAULT NULL COMMENT '涨跌额',
  turnover_rate DECIMAL(20,6) DEFAULT NULL COMMENT '换手率',
  adjust_type VARCHAR(16) NOT NULL DEFAULT 'NONE' COMMENT '复权类型: NONE 不复权',
  data_source VARCHAR(32) NOT NULL DEFAULT 'EASTMONEY_KLINE' COMMENT '数据来源',
  raw_payload_json TEXT DEFAULT NULL COMMENT '原始单行数据或摘要 JSON',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_em_unadj_quote (market, ts_code, trade_date, adjust_type),
  KEY idx_em_unadj_quote_date (trade_date),
  KEY idx_em_unadj_quote_code_date (ts_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='东方财富不复权历史日线表';
```

### `waterstock_fx_rate_daily`

用途：存储 `water-stock` 拉取的 HKD/CNY 历史汇率，供 `stock-ah-premium-ai` 追跑历史 AH 比价使用。

建议字段：

```sql
CREATE TABLE IF NOT EXISTS waterstock_fx_rate_daily (
  id INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  currency_pair VARCHAR(16) NOT NULL COMMENT '汇率对，如 HKDCNY',
  rate_date DATE NOT NULL COMMENT '汇率日期',
  open DECIMAL(20,8) DEFAULT NULL COMMENT '开盘汇率',
  close DECIMAL(20,8) NOT NULL COMMENT '收盘汇率',
  high DECIMAL(20,8) DEFAULT NULL COMMENT '最高汇率',
  low DECIMAL(20,8) DEFAULT NULL COMMENT '最低汇率',
  data_source VARCHAR(32) NOT NULL DEFAULT 'WATER_STOCK_BAIDU_FX' COMMENT '汇率来源',
  raw_payload_json TEXT DEFAULT NULL COMMENT '原始响应摘要 JSON',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_waterstock_fx_rate (currency_pair, rate_date, data_source),
  KEY idx_waterstock_fx_rate_date (rate_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='water-stock 历史汇率日线表';
```

### `historical_ah_unadjusted_backfill_run`

用途：记录每个 A/H 股票对基于不复权股价和汇率追跑 AH 比价的执行状态，避免重复追跑。

建议字段：

```sql
CREATE TABLE IF NOT EXISTS historical_ah_unadjusted_backfill_run (
  id INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  a_ts_code VARCHAR(16) NOT NULL COMMENT 'A 股 Tushare 代码',
  hk_ts_code VARCHAR(16) NOT NULL COMMENT 'H 股 Tushare 代码',
  data_source VARCHAR(32) NOT NULL COMMENT '补数来源标记',
  status VARCHAR(16) NOT NULL COMMENT '状态: RUNNING、COMPLETED、FAILED',
  candidate_rows INT NOT NULL DEFAULT 0 COMMENT 'A/H/汇率三方日期交集行数',
  inserted_rows INT NOT NULL DEFAULT 0 COMMENT '写入官方 AH 主表行数',
  skipped_existing_rows INT NOT NULL DEFAULT 0 COMMENT '主表唯一键已存在跳过行数',
  skipped_invalid_rows INT NOT NULL DEFAULT 0 COMMENT '价格或汇率无效跳过行数',
  first_trade_date DATE DEFAULT NULL COMMENT '本轮最早日期',
  last_trade_date DATE DEFAULT NULL COMMENT '本轮最晚日期',
  last_error VARCHAR(512) DEFAULT NULL COMMENT '失败原因摘要',
  started_at DATETIME DEFAULT NULL COMMENT '最近开始时间',
  completed_at DATETIME DEFAULT NULL COMMENT '最近完成时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_unadj_backfill_pair (a_ts_code, hk_ts_code, data_source),
  KEY idx_unadj_backfill_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='不复权历史 AH 比价补数执行记录表';
```

## `stock-ah-premium-ai` 实施内容

### 数据库迁移

新增 Alembic 迁移，创建上述三张表，并在 `backend/app/db/models/market.py` 增加对应 SQLAlchemy 模型。迁移和模型字段必须带中文注释，说明数据来源、复权口径和幂等唯一键。

同时更新：

- `resources/sql/03_full_schema_with_comments.sql`
- `resources/doc/database-schema.md`
- `resources/doc/development-progress.md`

### 东方财富 K 线客户端

新增 `backend/app/services/eastmoney_kline_service.py`：

- 将 `600036.SH` 转为 `1.600036`。
- 将 `000001.SZ` 转为 `0.000001`。
- 将 `03968.HK` 转为 `116.03968`。
- 请求 `fqt=0`，只拉不复权数据。
- 解析 `klines` 为结构化对象。
- 设置合理超时、低频请求间隔和错误日志。
- 原始单行数据保存到 `raw_payload_json`，避免后续字段口径争议时无法追溯。

### 不复权日线同步服务

新增 `UnadjustedQuoteSyncService`：

- 输入 A/H 股票对和日期范围。
- 分别拉取 A 股、H 股不复权日线。
- Upsert 到 `eastmoney_unadjusted_daily_quote`。
- 默认只同步用户自选股，也支持指定单个股票对调试。
- 不与 Tushare 的 `a_daily_quote`、`hk_daily_quote` 混表。

### 历史 AH 比价追跑服务

新增 `UnadjustedAhBackfillService`：

1. 读取用户关注 A/H 股票对或指定股票对。
2. 查询 `eastmoney_unadjusted_daily_quote` 中 A 股不复权收盘价。
3. 查询 `eastmoney_unadjusted_daily_quote` 中 H 股不复权收盘价。
4. 查询 `waterstock_fx_rate_daily` 中同日 HKD/CNY 收盘汇率。
5. 取三方日期交集，不依赖交易日历。
6. 计算：

```text
ah_comparison = a_close / (hk_close * hkd_cny_close)
ah_premium = (ah_comparison - 1) * 100
official_ah_comparison = round(ah_comparison, 2)
ha_comparison = 1 / official_ah_comparison
ha_premium = (ha_comparison - 1) * 100
```

7. 写入 `official_ah_comparison`：

```text
data_source = EASTMONEY_UNADJUSTED_BACKFILL
is_realtime = 0
```

8. 对同日同 A/H 股票对先删除 `BAIDU_HISTORY_BACKFILL` 行，再使用 `INSERT IGNORE` 或等价 upsert 写入不复权结果；不覆盖 `TUSHARE_OFFICIAL`、实时计算或人工来源。
9. 记录 `historical_ah_unadjusted_backfill_run`，已 `COMPLETED` 的股票对默认跳过。

说明：Baidu 前复权补数是本次替换对象，追跑时允许按 `data_source='BAIDU_HISTORY_BACKFILL'` 有条件删除重建；官方 Tushare 行仍保持最高优先级，不被不复权补数覆盖。

### 查询页面接入

后端 `DataQueryService.DATA_QUERY_SPECS` 新增数据集：

- `eastmoney_unadjusted_daily_quote`：东方财富不复权日线
- `waterstock_fx_rate_daily`：water-stock 历史汇率
- `historical_ah_unadjusted_backfill_run`：不复权 AH 补数记录

查询页无需大改，当前 `DataQueryPage` 已经按后端数据集白名单动态渲染列。需要补充：

- 数据集中文名称和说明。
- `keyword_fields` 支持股票代码、市场、数据来源、汇率对。
- `date_field` 分别设置为 `trade_date`、`rate_date`、`started_at` 或 `completed_at` 中适合查询的字段。

### 运维入口

新增同步页调用的一键管理入口：

- `POST /api/sync/batches/eastmoney-unadjusted`

该入口内部先同步 `watchlist_stock` 中启用且尚未完成追跑的 A/H 股票对东方财富不复权日线，再基于 A 股日线、H 股日线和 `waterstock_fx_rate_daily` 中同日 HKD/CNY 汇率三方交集追跑 AH 比价；日期默认从 2018-01-01 到当天。

## `water-stock` 实施内容

### 新增汇率写入方法

在 `water-stock` 新增单独方法，例如：

```java
syncHkdCnyHistoryToStockAhDatabase(String startDate, String endDate)
```

职责：

- 调用现有 Baidu HKDCNY 历史接口。
- 解析日期、开盘、收盘、最高、最低。
- 写入 `stock-ah-premium-ai` 数据库的 `waterstock_fx_rate_daily`。
- 使用 `insert ... on duplicate key update` 幂等更新。
- 不写入 `official_ah_comparison`，不参与 AH 比价计算。

### 调度建议

- 先提供手动方法或低频调度，避免与现有 Baidu AH 前复权补数调度混淆。
- 现有 `StockAhHistoricalPremiumBackfillSchedule` 保留。
- 新汇率同步可配置独立开关：

```yaml
stock-ah:
  fx-history:
    enabled: false
    cron: "0 10 * * * ?"
```

## 执行顺序

1. 在 `stock-ah-premium-ai` 增加三张表迁移、模型和完整建表 SQL。
2. 在 `stock-ah-premium-ai` 查询数据集白名单中加入三张表。
3. 在 `water-stock` 增加 HKD/CNY 历史汇率同步方法，写入 `waterstock_fx_rate_daily`。
4. 在 `stock-ah-premium-ai` 增加东方财富不复权日线客户端和同步服务。
5. 先用招商银行单票同步 A/H 不复权日线和 HKD/CNY 汇率。
6. 运行不复权 AH 比价追跑，写入 `official_ah_comparison` 缺失日期。
7. 在查询页核验三类数据：
   - 东方财富不复权日线
   - water-stock 汇率
   - 不复权 AH 补数记录
8. 抽样和 Tushare 官方 2025-08-12 之后数据对比，确认不复权口径与官方 AH 比价更接近后，再扩展到其他自选股。

## 验收标准

- 招商银行 A 股和 H 股不复权日线可从东方财富同步到独立表。
- HKD/CNY 历史汇率可由 `water-stock` 写入独立表。
- 三方日期交集追跑的 AH 比价可写入 `official_ah_comparison`，且不覆盖已有官方行。
- 查询页面可以选择并查看三张新增表。
- 重跑同步和追跑任务不产生重复数据。
- 2025-08-12 之后抽样对比 Tushare 官方 AH 比价，差异应显著小于 Baidu 前复权口径。

## 风险与边界

- 东方财富公开端点不是正式 SLA 数据服务，需保留 `raw_payload_json` 和 `data_source` 方便追溯。
- 不复权历史补数与 Baidu 前复权补数不能混称为同一口径。
- 主表当前唯一键不允许同一日期同一 A/H 股票对保留多种历史口径；是否替换 Baidu 前复权数据需要单独决策。
- 港股和 A 股休市差异不再依赖交易日历判断，追跑只使用 A 股价、H 股价、汇率三方日期交集。
