# QMT 交易数据回流与量化复盘设计

文档日期：2026-06-13

## 0. 背景与边界

本文档新增两部分内容，二者强相关、分阶段交付：

1. 【QMT 交易数据回流】：Windows VPS 上的 QMT（`xttrader`）把账户/持仓/委托/成交数据落到 Linux 侧 MySQL（`stock_ah_ai`），供服务侧只读复盘。
2. 【量化复盘页面】：服务侧（现有 `stock-ah-premium-ai`）新增页面，读取回流数据，对「当日交易情况」和「历史交易情况」做统计与复盘，并与信号侧 `limit_up_selected_stock` 通过 `ts_code + 交易日` 关联，验证「信号 → 执行 → 收益」链路。

不可推翻的既定前提：

- 解耦架构：信号侧 Linux（FastAPI + React + MySQL），执行侧 Windows VPS（`xtdata` 行情 + `xttrader` 下单）；两侧只通过 MySQL / 只读接口通信。QMT 只写、信号侧只读。
- 信号侧已规划 `limit_up_selected_stock`（一股一行，`trade_date=T` 信号日、`target_trade_date=T+1` 买入日；含龙头强度分 / 角色 / 战法 / 情绪周期 `market_state` / 可成交性 `tradable_flag` / 连板先验等）。
- A 股 T+1：当日买入当日不可卖，最早 T+2 卖；主板 ±10%、创业板 ±20%；只做主板 + 创业板、避开 ST。
- 回测口径：`trade_date=T` 买入在 T+1 须经 `a_trade_calendar` 映射；不复权；一字 / 秒封买不进不计收益。

QMT API 关键事实（落地强约束，已据官方文档 + GitHub 镜像核实）：

- `query_stock_asset` / `query_stock_positions` / `query_stock_orders` / `query_stock_trades` **全部只返回「当日」数据**，没有任何按日期范围查询历史的接口。隔日后当日数据被清空，前一日无法再从 API 取回。
- 因此历史成交明细、历史每日资产（净值曲线）、历史每日持仓，**必须由执行侧每个交易日主动落快照**，不落则历史不可还原。
- 原生 `XtAsset` 只有 6 个字段（`cash` / `frozen_cash` / `market_value` / `total_asset` / `account_type` / `account_id`），**不给净值、当日盈亏、累计收益率**；这些必须用快照差分 + 出入金台账自己算。
- 原生 `XtPosition` 只给 `volume` / `can_use_volume` / `open_price`（成本）/ `market_value`，**不含浮动盈亏 / 持仓盈亏 / 当前价**；浮动盈亏需用 `realtime_quote_snapshot.last_price × volume - 成本` 自己算。社区文章里的 `float_profit` / `profit_rate` / `last_price` 属于 KhQuant 等第三方封装层补充字段，原生 API 不返回，设计与代码不得假定其存在。
- `XtTrade`（成交回报）字段齐全：`traded_id`（成交编号，最小去重单位）/ `traded_time`（时间戳）/ `traded_price` / `traded_volume` / `traded_amount` / `order_id`（关联委托）/ `offset_flag` / `strategy_name` / `order_remark`。
- 回调：`on_stock_trade(XtTrade)`、`on_stock_order(XtOrder)`、`on_stock_asset(XtAsset)`、`on_stock_position(XtPosition)`、`on_order_error(XtOrderError)`、`on_cancel_error(XtCancelError)`、`on_disconnected()`。**`on_connected` 不存在**，连接成功靠 `connect()` 返回 0 判断。
- 连接为一次性，**断开后不会自动重连**，需主动重新 `connect` + `subscribe`；进程需 `run_forever()` 常驻，进程退出即丢失当日推送与订阅。
- 字段集存在版本差异（官方基础表 vs GitHub 镜像 vs 较新 `xtquant`）。落地前必须在目标 Windows 机器上对实际安装版本用 `vars(obj)` / `dir(obj)` 实测确认字段是否存在，避免 `AttributeError`。

---

## 1. 采集方式：实时回调 + 定时快照（两条腿，职责互补）

回流采用「实时回调落明细」+「定时拉 `query_*` 落快照」双通道，二者**职责不重叠、互为补全**：

### 1.1 实时回调（事件驱动增量，写明细）

盘中 `xttrader` 订阅推送，落「会变化的明细」：

| 回调 | 推送对象 | 写入目标表 | 职责 |
| --- | --- | --- | --- |
| `on_stock_trade` | `XtTrade` | `qmt_trade` | 每笔成交回报落明细，是已实现盈亏与成交统计的唯一事实源 |
| `on_stock_order` | `XtOrder` | `qmt_order` | 委托状态变化（已报/部成/已成/已撤/废单）落明细，是成交率/撤单率/买不进的事实源 |
| `on_order_error` | `XtOrderError` | `qmt_order`（`order_status=ERROR` + `error_msg`） | 下单失败落账，避免计划单「凭空消失」 |
| `on_cancel_error` | `XtCancelError` | `qmt_order`（追加撤单失败标记） | 撤单失败留痕 |
| `on_stock_asset` | `XtAsset` | （盘中可选）`qmt_account_daily` 当日行的盘中覆盖 | 资金实时变动，仅刷新当日快照，不单独留流水 |
| `on_stock_position` | `XtPosition` | （盘中可选）`qmt_position_snapshot` 当日行盘中覆盖 | 持仓实时变动，仅刷新当日快照 |
| `on_disconnected` | 无 | 写执行侧本地日志 + 触发重连 | 断线检测，驱动补采 |

实时回调职责：**保证「明细级、不可重建」的数据（成交回报、委托状态轨迹、下单/撤单失败）不丢**。成交回报一旦错过、隔日 API 取不回，故 `qmt_trade` / `qmt_order` 以回调为主力写入路径。

### 1.2 定时快照（轮询拉全量，写快照 + 兜底对账）

按调度拉 `query_*` 全量，落「按时点的状态快照」并兜底补全回调可能漏掉的明细：

| 时机 | 调用 | 写入目标表 | 职责 |
| --- | --- | --- | --- |
| 收盘后（如 15:05） | `query_stock_trades` | `qmt_trade`（按 `account_id + traded_id` upsert 补全） | **当日成交全量兜底**：把盘中回调可能漏的成交补齐，对齐为「当日权威成交全集」 |
| 收盘后 | `query_stock_orders` | `qmt_order`（按 `account_id + order_id` upsert 补全） | 当日委托终态全量兜底 |
| 收盘后（如 15:30） | `query_stock_asset` | `qmt_account_daily`（当日一行，`snapshot_type=CLOSE`） | **每日收盘资产快照**：净值曲线唯一来源 |
| 收盘后 | `query_stock_positions` | `qmt_position_snapshot`（当日 N 行，`snapshot_type=CLOSE`） | 每日收盘持仓快照：持仓盈亏、可卖市值复盘来源 |
| 盘中分钟级（可选，如每 5 min） | `query_stock_asset` / `query_stock_positions` | 当日行盘中覆盖（`snapshot_type=INTRADAY`） | 给「当日交易情况」页提供准实时持仓/资产，不进历史净值 |
| 开盘前（如 9:10） | `query_stock_positions` | `qmt_position_snapshot`（`snapshot_type=OPEN`，可选） | 昨夜拥股基线，便于核对 T+1 可卖量 |

定时快照职责：**还原「无法事件化」的状态（每日净值、每日持仓）+ 给当日明细做全量对账兜底**。`query_*` 只返回当日，故收盘快照是历史还原的唯一机会，必须保证当日至少成功落一次 `CLOSE` 快照。

### 1.3 两条腿的边界总结

- **明细（成交/委托）**：回调为主、收盘 `query_*` 兜底补全，幂等 upsert 去重，谁先到谁先写、后到的覆盖为终态。
- **快照（资产/持仓）**：以定时拉取为权威，回调推送仅刷新「当日快照」给准实时页用，**不写历史净值/历史持仓**（避免回调高频抖动污染日终口径）。
- 历史净值曲线、历史每日持仓只认 `CLOSE` 快照；当日实时展示用 `INTRADAY` 覆盖。

---

## 2. 新增 MySQL 表 DDL 草案

落库目标库 `stock_ah_ai`，与现有表同库；建表风格对齐 `03_full_schema_with_comments.sql`（InnoDB / utf8mb4_unicode_ci / 每字段中文 COMMENT / `DATETIME` + `CURRENT_TIMESTAMP` / `DECIMAL(20,8)` 金额）。

时间字段强约定（见第 4 节）：所有「QMT 源时间」字段（`traded_time`、`order_time`）以 **UTC naive** 入库（执行侧把东八区时间戳转 UTC 后写入），前端用 `formatEast8DateTime(value)` 展示；`created_at` / `updated_at` 为 DB 生成、按东八区本地理解，前端用 `formatEast8DateTime(value, { naiveAsEast8: true })`。同时保留 `traded_time_east8` / `order_time_east8`（DATETIME，东八区 naive，原样落 QMT 时间）用于人工核对与对账，避免「±8h」误判。

### 2.1 `qmt_trade`：交易成交明细表

```sql
-- QMT 成交明细表：每笔成交回报一行，是已实现盈亏与成交统计的唯一事实源。
-- 写入路径：盘中 on_stock_trade 回调为主，收盘 query_stock_trades 全量兜底补全；
-- 幂等口径：按 (account_id, traded_id) 唯一去重，重复回报或重跑补采均 upsert 覆盖为终态，不产生重复行。
CREATE TABLE IF NOT EXISTS `qmt_trade` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `account_id` VARCHAR(32) NOT NULL COMMENT 'QMT 资金账号',
  `account_type` INT DEFAULT NULL COMMENT 'QMT 账号类型枚举（原样落 XtTrade.account_type）',
  `trade_date` DATE NOT NULL COMMENT '成交所属交易日（东八区自然交易日，与 a_trade_calendar.cal_date 对齐）',
  `ts_code` VARCHAR(16) NOT NULL COMMENT '标准证券代码，如 600036.SH、300750.SZ；由 QMT stock_code 经 stock_identity_resolver 规整',
  `qmt_stock_code` VARCHAR(16) NOT NULL COMMENT 'QMT 原始证券代码（保留原值便于排查代码格式差异）',
  `traded_id` VARCHAR(64) NOT NULL COMMENT 'QMT 成交编号，成交去重最小单位',
  `order_id` BIGINT DEFAULT NULL COMMENT '关联委托订单编号（XtTrade.order_id），用于回溯委托与 FIFO 撮合',
  `order_sysid` VARCHAR(64) DEFAULT NULL COMMENT '柜台合同编号',
  `trade_side` VARCHAR(8) NOT NULL COMMENT '买卖方向：BUY、SELL（由 XtTrade.order_type/offset_flag 规整，落库前在执行侧统一映射）',
  `offset_flag` INT DEFAULT NULL COMMENT 'QMT 交易操作原值（开/平等），保留供核对',
  `traded_price` DECIMAL(20,8) NOT NULL COMMENT '成交均价',
  `traded_volume` BIGINT NOT NULL COMMENT '成交数量（股）',
  `traded_amount` DECIMAL(20,8) DEFAULT NULL COMMENT '成交金额（QMT 原值，未必含费用）',
  `traded_time` DATETIME NOT NULL COMMENT '成交时间（UTC naive：执行侧将 QMT 东八区时间戳转 UTC 后入库，前端 formatEast8DateTime 展示）',
  `traded_time_east8` DATETIME DEFAULT NULL COMMENT '成交时间（东八区 naive，原样落 QMT 时间，仅供人工核对与对账）',
  `strategy_name` VARCHAR(64) DEFAULT NULL COMMENT 'QMT 策略名称（如下单时透传）',
  `order_remark` VARCHAR(255) DEFAULT NULL COMMENT '委托备注（下单时可写入信号侧来源标识，便于对账）',
  `signal_trade_date` DATE DEFAULT NULL COMMENT '关联信号日 T（执行侧或对账阶段回填，用于 join limit_up_selected_stock.trade_date）',
  `data_source` VARCHAR(24) NOT NULL DEFAULT 'CALLBACK' COMMENT '数据来源：CALLBACK 回调、QUERY_BACKFILL 收盘兜底补采',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间（DB 生成，东八区理解）',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_qmt_trade_account_traded` (`account_id`, `traded_id`),
  KEY `idx_qmt_trade_date_code` (`trade_date`, `ts_code`),
  KEY `idx_qmt_trade_order` (`account_id`, `order_id`),
  KEY `idx_qmt_trade_signal` (`signal_trade_date`, `ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='QMT 成交明细表（成交回报，已实现盈亏与成交统计事实源）';
```

### 2.2 `qmt_order`：委托表

```sql
-- QMT 委托明细表：每个委托一行，记录终态与成交进度，是成交率/撤单率/买不进统计的事实源。
-- 写入路径：盘中 on_stock_order / on_order_error / on_cancel_error 回调为主，收盘 query_stock_orders 全量兜底；
-- 幂等口径：按 (account_id, order_id) 唯一去重；同一委托多次状态推送 upsert 覆盖为最新状态（已成/已撤/废单为终态）。
CREATE TABLE IF NOT EXISTS `qmt_order` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `account_id` VARCHAR(32) NOT NULL COMMENT 'QMT 资金账号',
  `account_type` INT DEFAULT NULL COMMENT 'QMT 账号类型枚举',
  `trade_date` DATE NOT NULL COMMENT '委托所属交易日（东八区，与 a_trade_calendar.cal_date 对齐）',
  `ts_code` VARCHAR(16) NOT NULL COMMENT '标准证券代码（由 QMT stock_code 规整）',
  `qmt_stock_code` VARCHAR(16) NOT NULL COMMENT 'QMT 原始证券代码',
  `order_id` BIGINT NOT NULL COMMENT 'QMT 订单编号',
  `order_sysid` VARCHAR(64) DEFAULT NULL COMMENT '柜台合同编号',
  `trade_side` VARCHAR(8) NOT NULL COMMENT '买卖方向：BUY、SELL（由 order_type/offset_flag 规整）',
  `offset_flag` INT DEFAULT NULL COMMENT 'QMT 交易操作原值',
  `price_type` INT DEFAULT NULL COMMENT 'QMT 报价类型枚举（限价/市价等）',
  `order_price` DECIMAL(20,8) DEFAULT NULL COMMENT '委托价格',
  `order_volume` BIGINT NOT NULL COMMENT '委托数量（股）',
  `traded_volume` BIGINT NOT NULL DEFAULT 0 COMMENT '已成交数量（用于算成交率/部成）',
  `traded_price` DECIMAL(20,8) DEFAULT NULL COMMENT '成交均价',
  `order_status` VARCHAR(16) NOT NULL COMMENT '委托状态：REPORTED 已报、PART_TRADED 部成、TRADED 已成、CANCELLED 已撤、REJECTED 废单、ERROR 下单失败（由 QMT order_status 枚举规整）',
  `status_msg` VARCHAR(255) DEFAULT NULL COMMENT '状态描述（QMT status_msg）',
  `error_id` INT DEFAULT NULL COMMENT '下单/撤单失败错误码（来自 on_order_error / on_cancel_error）',
  `error_msg` VARCHAR(255) DEFAULT NULL COMMENT '下单/撤单失败错误描述',
  `cancel_failed` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否发生撤单失败（on_cancel_error 标记）',
  `order_time` DATETIME DEFAULT NULL COMMENT '报单时间（UTC naive：东八区时间戳转 UTC 入库，前端 formatEast8DateTime 展示）',
  `order_time_east8` DATETIME DEFAULT NULL COMMENT '报单时间（东八区 naive 原值，供核对）',
  `strategy_name` VARCHAR(64) DEFAULT NULL COMMENT 'QMT 策略名称',
  `order_remark` VARCHAR(255) DEFAULT NULL COMMENT '委托备注（透传信号侧来源标识，便于对账）',
  `signal_trade_date` DATE DEFAULT NULL COMMENT '关联信号日 T（对账阶段回填）',
  `data_source` VARCHAR(24) NOT NULL DEFAULT 'CALLBACK' COMMENT '数据来源：CALLBACK、QUERY_BACKFILL',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_qmt_order_account_order` (`account_id`, `order_id`),
  KEY `idx_qmt_order_date_code` (`trade_date`, `ts_code`),
  KEY `idx_qmt_order_status` (`trade_date`, `order_status`),
  KEY `idx_qmt_order_signal` (`signal_trade_date`, `ts_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='QMT 委托明细表（委托终态与成交进度，成交率/撤单率事实源）';
```

### 2.3 `qmt_position_snapshot`：持仓快照表（按日）

```sql
-- QMT 持仓快照表（按日）：每个交易日按账户+证券落一行持仓快照，是持仓盈亏与可卖市值复盘来源。
-- 写入路径：收盘 query_stock_positions 落 CLOSE 快照（权威）；盘中分钟级落 INTRADAY 覆盖当日行（准实时）；开盘前可选 OPEN。
-- 幂等口径：按 (account_id, trade_date, ts_code, snapshot_type) 唯一；同类型同日重复采集 upsert 覆盖。
-- 盈亏口径：原生 API 不给浮动盈亏，float_profit/market_value_calc 由执行侧或服务侧结合行情现价计算后回填（见第 1 节与复盘指标）。
CREATE TABLE IF NOT EXISTS `qmt_position_snapshot` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `account_id` VARCHAR(32) NOT NULL COMMENT 'QMT 资金账号',
  `account_type` INT DEFAULT NULL COMMENT 'QMT 账号类型枚举',
  `trade_date` DATE NOT NULL COMMENT '快照所属交易日（东八区，与 a_trade_calendar.cal_date 对齐）',
  `snapshot_type` VARCHAR(12) NOT NULL DEFAULT 'CLOSE' COMMENT '快照类型：OPEN 开盘前、INTRADAY 盘中、CLOSE 收盘（历史净值/持仓复盘只认 CLOSE）',
  `ts_code` VARCHAR(16) NOT NULL COMMENT '标准证券代码',
  `qmt_stock_code` VARCHAR(16) NOT NULL COMMENT 'QMT 原始证券代码',
  `volume` BIGINT NOT NULL DEFAULT 0 COMMENT '持仓数量（总持仓，含当日买入；T+1 当日买入计入但不可卖）',
  `can_use_volume` BIGINT NOT NULL DEFAULT 0 COMMENT '可用数量（可卖部分，T+1 不含当日买入）',
  `frozen_volume` BIGINT DEFAULT NULL COMMENT '冻结数量（版本若不提供则为空）',
  `on_road_volume` BIGINT DEFAULT NULL COMMENT '在途数量（版本若不提供则为空）',
  `yesterday_volume` BIGINT DEFAULT NULL COMMENT '昨夜拥股（版本若不提供则为空）',
  `open_price` DECIMAL(20,8) DEFAULT NULL COMMENT '开仓/持仓成本价（XtPosition.open_price）',
  `avg_price` DECIMAL(20,8) DEFAULT NULL COMMENT '成本均价（部分版本提供 avg_price，否则空）',
  `market_value` DECIMAL(20,8) DEFAULT NULL COMMENT '持仓市值（XtPosition.market_value，QMT 原值）',
  `last_price` DECIMAL(20,8) DEFAULT NULL COMMENT '盯市现价（原生 API 不给，由 realtime_quote_snapshot/收盘价回填，用于算浮动盈亏）',
  `float_profit` DECIMAL(20,8) DEFAULT NULL COMMENT '浮动盈亏=(last_price-成本)×volume（计算字段，原生 API 不返回，回填）',
  `profit_rate` DECIMAL(20,8) DEFAULT NULL COMMENT '浮动盈亏比例=(last_price-成本)/成本（计算字段，回填）',
  `data_source` VARCHAR(24) NOT NULL DEFAULT 'QUERY' COMMENT '数据来源：QUERY 定时拉取、CALLBACK 回调刷新',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_qmt_position_snap` (`account_id`, `trade_date`, `ts_code`, `snapshot_type`),
  KEY `idx_qmt_position_date_type` (`trade_date`, `snapshot_type`),
  KEY `idx_qmt_position_code` (`ts_code`, `trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='QMT 持仓快照表（按日，持仓盈亏与可卖市值复盘来源）';
```

### 2.4 `qmt_account_daily`：账户资产日快照表

```sql
-- QMT 账户资产日快照表：每个交易日按账户落一行收盘资产快照，是净值曲线与账户级收益的唯一来源。
-- 写入路径：收盘 query_stock_asset 落 CLOSE（权威，进历史净值）；盘中可选 INTRADAY 覆盖给当日页用（不进历史净值）。
-- 幂等口径：按 (account_id, trade_date, snapshot_type) 唯一；同日同类型重复采集 upsert 覆盖。
-- 收益口径：total_asset 含当日浮动盈亏，做净值曲线必须扣当日净出入金（net_cash_flow，来自出入金台账），否则收益被资金进出污染（见第 4 节与复盘指标）。
CREATE TABLE IF NOT EXISTS `qmt_account_daily` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `account_id` VARCHAR(32) NOT NULL COMMENT 'QMT 资金账号',
  `account_type` INT DEFAULT NULL COMMENT 'QMT 账号类型枚举',
  `trade_date` DATE NOT NULL COMMENT '快照所属交易日（东八区，与 a_trade_calendar.cal_date 对齐）',
  `snapshot_type` VARCHAR(12) NOT NULL DEFAULT 'CLOSE' COMMENT '快照类型：INTRADAY 盘中、CLOSE 收盘（历史净值曲线只认 CLOSE）',
  `total_asset` DECIMAL(20,8) NOT NULL COMMENT '总资产（XtAsset.total_asset，含当日浮动盈亏的实时口径）',
  `cash` DECIMAL(20,8) NOT NULL COMMENT '可用资金',
  `frozen_cash` DECIMAL(20,8) NOT NULL DEFAULT 0 COMMENT '冻结资金',
  `market_value` DECIMAL(20,8) NOT NULL DEFAULT 0 COMMENT '持仓市值',
  `net_cash_flow` DECIMAL(20,8) NOT NULL DEFAULT 0 COMMENT '当日净出入金（入金为正、出金为负；来自出入金台账，API 不提供，人工/外部录入）',
  `prev_total_asset` DECIMAL(20,8) DEFAULT NULL COMMENT '上一交易日收盘总资产（计算字段，回填，便于算当日盈亏）',
  `daily_pnl` DECIMAL(20,8) DEFAULT NULL COMMENT '当日盈亏=total_asset-prev_total_asset-net_cash_flow（计算字段，已剔除出入金）',
  `daily_return` DECIMAL(20,8) DEFAULT NULL COMMENT '当日收益率（单日 Modified Dietz，分母含现金流时长加权部分；计算字段）',
  `cash_flow_note` VARCHAR(255) DEFAULT NULL COMMENT '出入金备注（如大额出入金当日需真实估值切段说明）',
  `data_source` VARCHAR(24) NOT NULL DEFAULT 'QUERY' COMMENT '数据来源：QUERY 定时拉取、CALLBACK 回调刷新',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_qmt_account_daily` (`account_id`, `trade_date`, `snapshot_type`),
  KEY `idx_qmt_account_date` (`trade_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='QMT 账户资产日快照表（净值曲线与账户级收益来源）';
```

### 2.5 与 `limit_up_selected_stock` 的关联口径

QMT 表用 `ts_code` + 交易日与信号侧关联，验证「信号 → 执行 → 收益」链路：

- 信号侧一行：`limit_up_selected_stock(ts_code, trade_date=T 信号日, target_trade_date=T+1 买入日, market_state, role, strategy, tradable_flag, 龙头强度分, 连板先验...)`。
- 关联键：`qmt_trade.ts_code = limit_up_selected_stock.ts_code` **且** `qmt_trade.trade_date = limit_up_selected_stock.target_trade_date`（买入成交发生在 T+1），即「QMT 在 T+1 实际成交了哪些 T 信号股」。
- 为减少 join 时再算 T+1 映射，`qmt_trade` / `qmt_order` 设 `signal_trade_date`（= T），由执行侧下单时透传或对账阶段经 `a_trade_calendar` 反推 `pretrade_date` 回填；之后可直接 `qmt_trade.signal_trade_date = limit_up_selected_stock.trade_date AND ts_code 相同` 关联。
- 漏斗对账：`limit_up_selected_stock`（计划目标）→ `qmt_order`（实际挂单）→ `qmt_trade`（实际成交），按 `tradable_flag` / 连板先验 / `market_state` 分组看「计划 vs 挂单 vs 成交」流失率与「买不进比例」。

---

## 3. 写入路径

### 3.1 直连 MySQL vs 经 Linux 内网写接口

两种路径对比：

| 维度 | A. Windows 直连 MySQL | B. 经 Linux 内网写接口（FastAPI 写端点） |
| --- | --- | --- |
| 侵入性 | 最小：执行侧只依赖一个 MySQL 连接 | 需在信号侧暴露写接口，增加后端面 |
| 与解耦架构一致性 | 一致（两侧只通过 MySQL 通信，正是既定口径） | 偏离「只通过 MySQL / 只读接口」的只读约定，引入写接口 |
| 校验与去重 | 幂等由唯一键 + upsert 保证，校验在执行侧 | 可在接口层集中做校验/规整/鉴权 |
| 网络面 | 需放通 MySQL 端口给执行侧（内网/白名单/独立写账号） | 只放通 HTTPS，DB 不对外 |
| 故障耦合 | DB 抖动直接影响执行侧写入 | 接口层可做缓冲/重试，隔离 DB |

**推荐：A. Windows 直连 MySQL**，理由与既定架构一致——「两侧只通过 MySQL / 只读接口通信，QMT 只写、信号侧只读」。即 QMT 侧持有一个**只对 `qmt_*` 表有写权限**的独立 MySQL 账号（最小权限，仅 INSERT/UPDATE/SELECT on `qmt_*`），信号侧仍只读。落地约束：

- 为执行侧建独立写账号，授权范围仅限 4 张 `qmt_*` 表，不授予其他业务表写权限。
- 数据库连接信息按 `/Users/salty/codeProject/ai/doc/mysqluse.md` 口径，不硬编码、不入库敏感信息、不写入日志。
- 网络层用内网 / VPN / IP 白名单限制 MySQL 端口暴露面。
- 所有写入走唯一键 upsert，保证回调与定时兜底、断线重连补采均幂等。

（若后续 MySQL 端口暴露不可接受，再退化为 B 方案，在信号侧加一个鉴权写接口，但当前不引入。）

### 3.2 断线重连后的补采

`xttrader` 断开不自动重连，且断开期间的推送丢失。补采机制：

1. `on_disconnected` 触发后，执行侧守护逻辑重建 session（新 `session_id`）→ `connect()`（返回 0）→ `subscribe(acc)`。
2. 重连成功后**立即用 `query_*` 全量补采当日**：`query_stock_trades` / `query_stock_orders` 全量 upsert 到 `qmt_trade` / `qmt_order`（按唯一键去重，断线期间漏掉的成交/委托被补回，`data_source=QUERY_BACKFILL`）；`query_stock_asset` / `query_stock_positions` 刷新当日快照。
3. 配合 Windows 任务计划 / 守护进程保证进程常驻；建议每日开盘前主动重建 session 重连一次，规避隔夜连接失效。
4. 收盘后兜底批次再做一次当日全量 `query_*`，作为「当日权威全集」最终对齐。

补采能成立的前提：`query_*` 返回的是「当日全量」，故任何时刻重连后拉一次即可把当日缺失补齐——但**必须当日内完成**，隔日后当日数据被清空不可补。

### 3.3 对账：本地下单台账 vs xttrader 回报

执行侧自己维护「本地下单台账」（每次调 `order_stock` 的计划单：`ts_code` / 方向 / 计划量 / 计划价 / 信号来源 / 下单时刻），与 xttrader 回报对账：

- **委托对账**：本地台账每条计划单应在 `qmt_order` 找到对应回报（通过 `order_remark` 透传的本地单号或 `order_id` 关联）。台账有、回报无 → 漏单/下单失败（查 `on_order_error`）；回报有、台账无 → 非本系统下单（手工单），单独标记。
- **成交对账**：`qmt_order.traded_volume` 与该委托下 `qmt_trade` 成交量之和应一致；不一致说明有成交回报漏采，触发 `query_stock_trades` 补采。
- **资产对账**：当日 `Σ成交净额 ± 费用` 应与 `qmt_account_daily` 资产变动方向一致（粗校验）；偏差超阈值告警。
- **滑点对账**：本地台账「下单时刻价 / 信号决策价」对比 `qmt_trade.traded_price`，落为执行质量指标（见第 5 节）。
- 对账结果建议落执行侧本地日志 + 可选写一张对账记录（本设计先不强制建表，纳入后续阶段）。

---

## 4. 时间口径（必须与项目 AGENTS.md 一致，避免 ±8h）

QMT 的 `traded_time` / `order_time` 是**东八区**时间戳（QMT 运行在东八区）。项目 AGENTS.md 既定口径：

- 后端用 `datetime.now(UTC).replace(tzinfo=None)` 写入的字段按 **UTC naive** 入库，前端 `formatEast8DateTime(value)` 展示。
- DB 生成字段（`server_default=func.now()` / `CURRENT_TIMESTAMP` / `created_at` / `updated_at`）按**东八区本地时间**理解，前端 `formatEast8DateTime(value, { naiveAsEast8: true })`。

据此固化 QMT 字段入库口径：

| 字段 | 来源 | 入库口径 | 前端展示 |
| --- | --- | --- | --- |
| `traded_time` / `order_time` | QMT 东八区时间戳 | 执行侧把东八区时间**转 UTC** 后以 UTC naive 入库（与后端 UTC naive 字段同口径） | `formatEast8DateTime(value)` |
| `traded_time_east8` / `order_time_east8` | QMT 东八区时间戳 | 原样落**东八区 naive**（不加减），仅供人工核对/对账 | `formatEast8DateTime(value, { naiveAsEast8: true })` |
| `trade_date`（DATE） | QMT 东八区自然交易日 | 直接落东八区交易日（DATE 无时区问题），与 `a_trade_calendar.cal_date` 对齐 | 按日期直接展示 |
| `created_at` / `updated_at` | DB 生成 | `CURRENT_TIMESTAMP`，东八区理解 | `formatEast8DateTime(value, { naiveAsEast8: true })` |

执行侧转换实现约定（关键，杜绝盲目 ±8h）：

- QMT 时间戳（int 秒）先按**东八区**解释为本地 `datetime`（`datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Shanghai"))`），再 `.astimezone(UTC).replace(tzinfo=None)` 得 UTC naive 写 `traded_time`；东八区原值 `.replace(tzinfo=None)` 写 `traded_time_east8`。
- 不在前端、不在 SQL 里手工 `+8h`/`-8h`；展示一律靠 `formatEast8DateTime` 的两种参数区分来源。
- 该口径写入本文档与（落地时）`qmt_*` 模型注释，作为固化标准；发现展示快/慢 8 小时先查字段来源与格式化参数，不得临时拼接偏移。

---

## 5. 量化复盘页面（服务侧只读）

页面读取 `qmt_*` 表 + `limit_up_selected_stock` + `realtime_quote_snapshot` + `a_trade_calendar` + `tencent_unadjusted_daily_quote`，分「当日交易情况」与「历史交易情况」两屏，指标口径采用业界标准。

### 5.1 当日交易情况

- 今日成交流水（`qmt_trade` 当日）、今日委托与终态（`qmt_order` 当日，含撤单/废单/下单失败）。
- 当日持仓（`qmt_position_snapshot` 当日 `INTRADAY`/`CLOSE`）：总持仓 `volume`、可卖 `can_use_volume`（T+1 当日买入不可卖，单列）、浮动盈亏（`last_price` 盯市，原生不给需算）。
- 当日盈亏卡片：`daily_pnl = total_asset - prev_total_asset - net_cash_flow`（明确标注已剔除出入金，入金不算「赚的钱」）。
- 信号→执行漏斗：当日 `limit_up_selected_stock`（target_trade_date=今日）→ `qmt_order` 挂单 → `qmt_trade` 成交，逐级流失率 + 买不进比例，按 `tradable_flag` / `market_state` / 连板先验分组。
- 当日滑点：信号决策价 / 下单时刻价 vs `traded_price`（两种基准分开展示，见下）。

### 5.2 历史交易情况

- 净值曲线 / 累计收益率：`qmt_account_daily`（`CLOSE`）逐日序列，**用 TWR（子区间法）或日频 Modified Dietz 近似**扣出入金链式计算（`net_cash_flow` 来自出入金台账）；大额出入金当日须真实估值切段，小额可用 Modified Dietz。
- 风险指标：最大回撤 MDD = max((峰值-谷值)/峰值)，另列回撤时长与恢复时间；夏普 / 索提诺 / 卡玛（日频年化乘 √252，无风险利率短线可设 0 并注明口径）。
- 交易质量：胜率 + 盈亏比 + 盈利因子（成对展示，单看其一会误判）、日胜率、换手率、持仓集中度（HHI + Top1/Top3）。
- 已实现盈亏：对 `qmt_trade` 买卖按 **FIFO**（与 QMT/券商对账单口径对齐）撮合，单票/累计已实现盈亏；浮动盈亏（未平仓盯市）与已实现盈亏**分列**。
- 持有天数：卖出日 - 买入日，按 `a_trade_calendar` 交易日计（打板隔日卖典型 1 个交易日）。
- 滑点（实现差额 / Implementation Shortfall）：①信号决策价基准（信号→执行全链路损耗，含延迟成本）；②下单到达价基准（QMT 纯执行质量）。一字/秒封买不进的计划单按「未成交机会成本」单列（呼应回测「买不进不计收益」）。
- 打板专属维度：封板率/打板成功率、隔日卖出收益率分布（封住 vs 炸板两组对比）；按 `market_state` 情绪周期分组、按 `strategy` 战法分组做实盘表现归因（验证「在对的周期做对的票」）。

### 5.3 计算口径归属

- 原生 API 直接给：成交价/量/额、当日委托与成交全集、持仓 `volume`/`can_use_volume`/成本、`total_asset`/`cash`/`market_value`。
- 需自己算：浮动盈亏（行情现价）、已实现盈亏（FIFO 撮合）、当日盈亏（快照差分扣出入金）、累计收益率（净值序列扣出入金链式）、所有风险/风险调整指标。
- 计算可在执行侧回填（`float_profit`/`daily_pnl` 等列）或服务侧读时计算；建议「重且稳定」的回填入库（净值、当日盈亏），「随行情变」的服务侧实时算（浮动盈亏用 `realtime_quote_snapshot`）。

---

## 6. 实施阶段与依赖顺序

> 按阶段 + 任务划分，给验收标准与依赖顺序；不含工期预估。

### P0 口径与 schema 固化（依赖：无）

1. 评审并确认本设计的表结构、唯一键、时间口径、写入路径（直连 MySQL + 独立写账号）。
2. 落 `qmt_*` 四张表的 Alembic 迁移 + SQLAlchemy 模型 + `03_full_schema_with_comments.sql` + `database-schema.md` 表清单（每字段中文注释）。
3. 建执行侧只读/只写账号模板（仅 `qmt_*` 写权限）。

验收：四表建成、唯一键与索引齐全、字段注释完整、文档与迁移同步；执行侧账号最小权限可用。

### P1 执行侧回流（依赖：P0）

1. 执行侧 `xttrader` 连接 + 回调注册（`on_stock_trade`/`on_stock_order`/`on_order_error`/`on_cancel_error`/`on_stock_asset`/`on_stock_position`/`on_disconnected`），明细 upsert 入 `qmt_trade`/`qmt_order`。
2. 字段实测：在目标 Windows 机用 `vars(obj)` 确认实际 `xtquant` 版本字段，规整代码/方向/状态枚举与时间转换（东八区→UTC naive + east8 原值）。
3. 定时快照：收盘 `query_*` 落 `CLOSE`（含全量兜底补全明细）、可选盘中 `INTRADAY`。
4. 断线重连 + 当日 `query_*` 补采；Windows 守护进程/任务计划常驻、每日开盘前重连。

验收：盘中回调实时落明细；收盘四表均有当日权威数据；断线重连后当日缺失被补齐；时间字段无 ±8h；唯一键幂等（重跑不产生重复行）。

### P2 对账与回填（依赖：P1）

1. 本地下单台账 vs `qmt_order`/`qmt_trade` 委托/成交/资产对账，偏差告警。
2. `signal_trade_date` 回填（透传或经 `a_trade_calendar` 反推）；`prev_total_asset`/`daily_pnl`/净值相关回填。
3. 出入金台账录入机制（`net_cash_flow`）。

验收：每条本地计划单可对到回报或定位为漏单/失败；成交量勾稽一致；当日盈亏剔除出入金正确；信号关联键可用。

### P3 复盘页只读 API + 前端（依赖：P1，对账/归因依赖 P2）

1. 后端只读视图/接口：当日成交/委托/持仓、当日盈亏、信号→执行漏斗、历史净值曲线、风险与交易质量指标、滑点、打板归因。
2. 前端「当日交易情况」「历史交易情况」两屏；时间一律走 `formatEast8DateTime`（按字段来源选参数）。
3. 指标口径（TWR/Modified Dietz、MDD、夏普/索提诺/卡玛、FIFO、滑点双基准）在接口/页面注明。

验收：能看到 QMT 实际交易了什么与收益率；当日/历史两屏指标口径正确并标注；与 `limit_up_selected_stock` 关联的漏斗与归因可用；浮动盈亏与已实现盈亏分列；展示时间无 ±8h。

---

## 7. 风险与注意事项

- 字段版本差异：`avg_price`/`frozen_volume`/`on_road_volume`/`yesterday_volume`/`direction`/`offset_flag` 等在不同 `xtquant` 版本有无不一，DDL 已设为可空，落地前必须实测。
- 第三方封装字段误用：`float_profit`/`profit_rate`/`last_price` 是 KhQuant 等补充字段，原生不返回，必须自己用行情算，不得假定 API 给。
- `total_asset` 含当日浮动盈亏且不含出入金，净值曲线必须扣 `net_cash_flow`，否则收益被资金进出污染；出入金 API 不提供，需另维护台账。
- 当日数据 API 仅当日有效，断线补采与收盘快照必须当日内完成；隔日不可补。
- 成本法两套（FIFO / 移动加权）部分平仓中间值不同、清仓后累计相等；必须固定 FIFO 并与对账单口径一致，否则无法对账。
- 除权除息会改持仓成本，原生成交流水不含除权调整；历史成本还原需结合 `tencent_unadjusted_daily_quote` / 除权信息单独处理。
- 滑点「决策价」二选一含义不同（信号→执行全链路 vs 纯执行质量），两者分开展示，勿合并成单一数字。
