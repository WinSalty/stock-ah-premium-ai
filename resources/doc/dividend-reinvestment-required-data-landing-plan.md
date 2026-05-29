# 分红再投入所需数据落地清单

文档日期：2026-05-29

## 1. 文档定位

本文档只描述“分红再投入筛选”所需数据如何落地，重点回答以下问题：

- 需要从 Tushare 拉哪些接口。
- 每个接口需要哪些字段。
- 数据落到哪些本地表。
- 首次全量和日常增量如何控制请求量。
- 如何校验数据是否足够支撑回测计算。

完整功能设计、结果表、API 和页面方案见：[分红再投入筛选数据落地方案](./dividend-reinvestment-data-landing-plan.md)。

## 2. 数据落地总览

第一版只做 A 股日线级分红再投入筛选，不接港股、ETF、基金、分钟线或 Tick 数据。

当前代码已按本文档第一版口径接入统一同步入口：

- 后端批量接口：`POST /api/sync/batches/dividend-reinvestment-data`。
- 同步数据集名：`dividend_reinvestment_data_landing`。
- 前端入口：数据同步页“同步分红再投数据”按钮。
- 结果查询：数据查询页可查看 `dividend_reinvestment_backtest_run`、`dividend_reinvestment_backtest_summary`、`dividend_reinvestment_backtest_yearly`。

| 数据域 | Tushare 接口 | 本地表 | 是否必须 | 落地粒度 | 用途 |
| --- | --- | --- | --- | --- | --- |
| A 股基础信息 | `stock_basic` | `a_stock_basic` | 必须 | 全量股票 | 股票池、上市日期、行业、上市状态和 ST 过滤。 |
| A 股交易日历 | `trade_cal` | `a_trade_calendar` | 必须 | 日期范围 | 除息日后可买入日、年末交易日、当前最新交易日定位。 |
| A 股日线行情 | `daily` | `a_daily_quote` | 必须 | 按交易日全市场 | 初始买入价、除息日再投入价、年末市值和最终市值。 |
| A 股分红送股 | `dividend` | `a_dividend` | 必须 | 按除权除息日全市场 | 现金分红、送转股、除权除息日和派息日。 |
| A 股每日指标 | `daily_basic` | `a_daily_basic` | 必须但只需最新 | 最新交易日全市场 | 最新市值、股息率、PE、PB 和股本筛选。 |
| 复权因子 | `adj_factor` | 暂不落库 | 可选 | 单股抽样 | 用于抽样校验分红再投入收益与复权收益方向是否一致。 |

第一版不落全历史 `daily_basic`，也不把 `adj_factor` 作为生产计算依赖。核心回测只依赖 `daily`、`dividend`、`trade_cal` 和 `stock_basic`。

## 3. 接口字段清单

### 3.1 `stock_basic`

本地表：`a_stock_basic`。

建议参数：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `exchange` | 空字符串 | 拉取全市场。 |
| `list_status` | `L` | 第一版只处理正常上市股票。 |

建议字段：

| 字段 | 本地字段 | 用途 |
| --- | --- | --- |
| `ts_code` | `ts_code` | 股票唯一代码。 |
| `symbol` | `symbol` | 纯数字代码。 |
| `name` | `name` | 股票名称，用于展示和 ST 过滤。 |
| `area` | `area` | 地域筛选。 |
| `industry` | `industry` | 行业筛选和行业内排名。 |
| `market` | `market` | 主板、创业板等市场信息。 |
| `exchange` | `exchange` | 交易所。 |
| `list_status` | `list_status` | 上市状态。 |
| `list_date` | `list_date` | 上市日期，用于判断是否覆盖完整回测期。 |
| `delist_date` | `delist_date` | 退市日期，第一版正常上市时通常为空。 |
| `is_hs` | `is_hs` | 是否沪深港通标的，作为补充展示字段。 |

落地规则：

- 按 `ts_code` upsert。
- 初始股票池只保留 `list_status=L`。
- 回测计算阶段再按 `list_date <= start_date` 或上市年限阈值过滤。

## 3.2 `trade_cal`

本地表：`a_trade_calendar`。

建议参数：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `exchange` | `SSE` | A 股交易日历用上交所即可覆盖共同交易日口径。 |
| `start_date` | `20160101` | 第一版默认历史起点。 |
| `end_date` | 当前日期后 30 到 370 天 | 留出未来日历窗口，方便增量任务。 |

建议字段：

| 字段 | 本地字段 | 用途 |
| --- | --- | --- |
| `exchange` | `exchange` | 交易所。 |
| `cal_date` | `cal_date` | 日历日期。 |
| `is_open` | `is_open` | 是否开市。 |
| `pretrade_date` | `pretrade_date` | 上一交易日。 |

落地规则：

- 按 `exchange + cal_date` upsert。
- 回测只使用 `is_open=1` 的日期。
- 需要在本地构建两个辅助能力：查某日之后第一个交易日、查某年最后一个交易日。

## 3.3 `daily`

本地表：`a_daily_quote`。

建议参数：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `trade_date` | 单个交易日 | 按交易日拉全市场，避免按股票逐只拉导致请求量过高。 |

不建议第一版按 `ts_code + start_date + end_date` 对全市场逐股拉取，因为 5500 只股票会产生数千到上万次额外请求，且不利于断点按日期续跑。

建议字段：

| 字段 | 本地字段 | 用途 |
| --- | --- | --- |
| `ts_code` | `ts_code` | 股票代码。 |
| `trade_date` | `trade_date` | 交易日。 |
| `open` | `open` | 备用展示。 |
| `high` | `high` | 备用展示。 |
| `low` | `low` | 备用展示。 |
| `close` | `close` | 核心价格字段。 |
| `pre_close` | `pre_close` | 备用校验。 |
| `change` | `change_amount` | 涨跌额。 |
| `pct_chg` | `pct_chg` | 涨跌幅。 |
| `vol` | `vol` | 成交量，可用于后续流动性过滤。 |
| `amount` | `amount` | 成交额，可用于后续流动性过滤。 |

落地规则：

- 按 `ts_code + trade_date` upsert。
- 仅在 `a_trade_calendar.is_open=1` 的日期请求。
- 每个交易日请求成功后更新 checkpoint。
- 如果某交易日返回 0 行，应记录为异常，不直接视为成功，除非交易日历确认该日非开市。
- 回测计算只依赖 `close`，若某股票某日 `close` 缺失，则按最近可用价或跳过该再投入事件处理。

## 3.4 `dividend`

本地表：`a_dividend`。

建议参数：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `ex_date` | 单个自然日 | 按除权除息日拉全市场，适合分红再投入计算。 |

备选参数：

| 参数 | 使用场景 |
| --- | --- |
| `ts_code` | 单股补洞或人工复核。 |
| `ann_date` | 后续如果需要按公告日追踪预案变化再启用。 |
| `record_date` | 后续如果需要股权登记日维度复核再启用。 |

建议字段：

| 字段 | 本地字段 | 用途 |
| --- | --- | --- |
| `ts_code` | `ts_code` | 股票代码。 |
| `end_date` | `end_date` | 分红年度或报告期。 |
| `ann_date` | `ann_date` | 公告日期。 |
| `div_proc` | `div_proc` | 分红进度，用于只取实施类分红。 |
| `stk_div` | `stk_div` | 每股送转股，影响持股数。 |
| `cash_div` | `cash_div` | 税后现金分红口径。 |
| `cash_div_tax` | `cash_div_tax` | 税前现金分红口径，第一版默认使用。 |
| `record_date` | `record_date` | 股权登记日，备用复核。 |
| `ex_date` | `ex_date` | 除权除息日，再投入价格定位核心日期。 |
| `pay_date` | `pay_date` | 派息日，备用口径。 |

落地规则：

- 按 `ts_code + end_date + ann_date + div_proc` upsert，沿用现有模型唯一键。
- 第一版请求时按 `ex_date` 循环；返回数据必须保存 `ex_date`。
- `ex_date` 为空的数据不参与回测，可不写入或写入后计算阶段过滤。
- `cash_div_tax`、`cash_div`、`stk_div` 全为空或全为 0 的记录不参与回测。
- 计算阶段只取实施类状态，状态枚举以真实返回值抽样后固化；初版可以先支持 `实施`，其他状态进入待确认列表。

## 3.5 `daily_basic`

本地表：`a_daily_basic`。

建议参数：

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `trade_date` | 最新可用交易日 | 从当前日期向前最多尝试 20 个自然日，找到有数据的最近交易日。 |

建议字段：

| 字段 | 本地字段 | 用途 |
| --- | --- | --- |
| `ts_code` | `ts_code` | 股票代码。 |
| `trade_date` | `trade_date` | 指标日期。 |
| `close` | `close` | 最新收盘价，和 `daily` 做交叉校验。 |
| `turnover_rate` | `turnover_rate` | 换手率，后续流动性筛选。 |
| `pe` | `pe` | 静态 PE。 |
| `pe_ttm` | `pe_ttm` | TTM PE。 |
| `pb` | `pb` | PB。 |
| `ps` | `ps` | PS。 |
| `ps_ttm` | `ps_ttm` | TTM PS。 |
| `dv_ratio` | `dv_ratio` | 股息率。 |
| `dv_ttm` | `dv_ttm` | TTM 股息率。 |
| `total_share` | `total_share` | 总股本。 |
| `float_share` | `float_share` | 流通股本。 |
| `free_share` | `free_share` | 自由流通股本。 |
| `total_mv` | `total_mv` | 总市值。 |
| `circ_mv` | `circ_mv` | 流通市值。 |

落地规则：

- 按 `ts_code + trade_date` upsert。
- 第一版只保证最新快照可用。
- 页面和筛选默认取 `max(trade_date)` 的快照。
- 若未来要做历史估值分位，再新增历史每日指标回补阶段，不混入第一版。

## 3.6 `adj_factor` 可选校验

第一版不落生产表。

使用场景：

- 抽样 10 到 30 只股票，对比手工分红再投入收益与前复权价格收益方向。
- 排查送转股和现金分红处理是否明显偏离。

建议只在开发或管理员校验脚本中按单股短列表调用，不进入常规全量回补。

## 4. 请求节奏设计

### 4.1 首次全量回补顺序

1. 同步 `stock_basic`。
2. 同步 `trade_cal`。
3. 按交易日同步 `daily`。
4. 按自然日同步 `dividend(ex_date=...)`。
5. 同步最新 `daily_basic`。
6. 执行本地回测计算。

这个顺序的好处：

- 先有交易日历，再避免对非交易日请求 `daily`。
- `dividend` 按自然日推进，即使当天无分红也可以稳定记录进度。
- 计算阶段完全本地化，失败后不需要重新消耗 Tushare 请求。

### 4.2 请求量估算

按 2016-01-01 至 2026-05-29 估算：

| 阶段 | 估算请求数 | 说明 |
| --- | --- | --- |
| `stock_basic` | 1 | 全市场一次。 |
| `trade_cal` | 1 到 3 | 覆盖 2016 至当前和未来窗口。 |
| `daily` | 约 2500 | 按 A 股交易日。 |
| `dividend` | 约 3800 | 按自然日 `ex_date`。 |
| `daily_basic` | 20 以内 | 找最新可用交易日，成功后停止。 |

总请求约 6300 到 6500 次。按 0.6 秒间隔估算约 65 分钟。

### 4.3 日常增量

日常增量任务按交易日收盘后执行：

1. 当天 `daily`：1 次。
2. 当天 `daily_basic`：1 次。
3. 当天 `dividend(ex_date=当天)`：1 次。
4. 每周刷新 `stock_basic`：1 次。
5. 每月刷新 `trade_cal` 未来窗口：1 次。

常规交易日请求量约 3 次，远低于 120 次/分钟限制。

## 5. 断点和状态记录

建议为所需数据落地维护独立阶段状态，即使最终复用 `sync_checkpoint`，也应使用明确的 checkpoint key。

| checkpoint key | 含义 |
| --- | --- |
| `dividend_reinvestment.stock_basic.synced_at` | 最近一次股票基础信息完成时间。 |
| `dividend_reinvestment.trade_cal.end_date` | 交易日历已覆盖到的日期。 |
| `dividend_reinvestment.daily.last_trade_date` | 日线已成功同步到的交易日。 |
| `dividend_reinvestment.dividend.last_ex_date` | 分红已成功同步到的除息自然日。 |
| `dividend_reinvestment.daily_basic.latest_trade_date` | 最新每日指标快照日期。 |

当前实现复用 `sync_checkpoint`，其中 `dataset` 固定为 `dividend_reinvestment_data_landing`，
`scope_key` 分别使用 `stock_basic`、`trade_cal`、`daily`、`dividend`、`daily_basic`，
表示各阶段最近成功日期。这个结构比长 key 更贴近现有同步框架，查询和重跑也更直接。

状态记录要求：

- 每个阶段开始、成功、失败都写入任务日志。
- 每次 Tushare 请求记录接口名、参数、字段、返回行数和耗时。
- 单日失败不应吞掉错误；任务应标记失败并保留最后成功 checkpoint。
- 重跑从 checkpoint 下一天继续。
- 强制重跑只能清理本功能结果表或指定原始数据日期范围，不允许无提示删除其他业务表。

## 6. 数据质量校验

### 6.1 落地完成校验

全量回补完成后至少检查：

| 校验项 | 通过标准 |
| --- | --- |
| `a_trade_calendar` 覆盖范围 | 覆盖 `start_date` 到 `end_date`，且开市日数量与常识相符。 |
| `a_daily_quote` 覆盖范围 | 最小交易日不晚于 `start_date` 后首个开市日，最大交易日接近 `end_date`。 |
| `a_daily_quote` 行数 | 十年全市场约千万级，明显低于预期时必须提示。 |
| `a_dividend` 行数 | 至少覆盖多个年度和大量股票；若为 0 必须阻断回测。 |
| `a_daily_basic` 最新日期 | 应接近当前最新交易日。 |

### 6.2 单股计算前校验

每只股票计算前检查：

- 上市日期是否早于回测开始日。
- 起始交易日是否有可用收盘价。
- 结束交易日是否有可用收盘价。
- 回测期内是否有分红记录。
- 分红记录是否有可用 `ex_date`。
- 每次 `ex_date` 或之后是否能找到再投入价格。

数据质量标记建议：

| 标记 | 含义 |
| --- | --- |
| `COMPLETE` | 价格、分红和年度估值完整。 |
| `NO_DIVIDEND` | 回测期内无有效分红。 |
| `PARTIAL_PRICE` | 部分除息日或年末价格缺失，已使用兜底或跳过。 |
| `SHORT_HISTORY` | 上市时间不足以覆盖完整回测期。 |
| `SUSPENDED_OR_DELISTED` | 长期缺价格，疑似停牌或退市，不参与主榜单。 |

## 7. 本地查询视图建议

为后续页面和 LLM 只读查询准备以下视图：

| 视图 | 用途 |
| --- | --- |
| `v_dividend_reinvestment_latest_summary` | 最新成功批次的回测摘要榜单。 |
| `v_dividend_reinvestment_latest_yearly` | 最新成功批次的年度明细。 |
| `v_dividend_reinvestment_data_health` | 原始数据覆盖范围、行数、最新日期和异常提示。 |

LLM 默认只读最新成功批次视图，不直接扫原始千万级日线表。

## 8. 第一版不做的事

以下能力先不纳入第一版，避免数据落地范围膨胀：

- 全历史 `daily_basic` 每日估值回补。
- 分钟线、Tick 或盘口数据。
- 港股分红和港股日线。
- ETF、基金、可转债分红再投入。
- 交易税费、滑点和真实整手成交约束。
- 由 LLM 自动触发全市场历史回补。

## 9. 实施优先级

建议按以下顺序开发：

1. 新增分红再投入数据落地服务和阶段状态记录。
2. 先落 `stock_basic`、`trade_cal`、`daily` 和 `dividend`。
3. 增加数据健康检查，不做回测也能确认数据是否够用。
4. 补 `daily_basic` 最新快照。
5. 开发本地回测计算和结果表。
6. 最后接页面和 LLM 只读视图。

这个顺序可以先把最容易出问题的数据覆盖、限流、断点续跑跑稳，再进入收益公式和页面展示。

## 10. 当前验收命令

本次已执行以下本地检查：

```bash
/Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend/.venv/bin/ruff check \
  backend/app/services/dividend_reinvestment_service.py \
  backend/app/services/sync_service.py \
  backend/app/schemas/sync.py \
  backend/app/api/routes_sync.py \
  backend/app/services/data_query_service.py \
  backend/tests/test_dividend_reinvestment_service.py \
  backend/tests/test_sync_service_tencent_unadjusted.py \
  backend/tests/test_data_query_service.py

/Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend/.venv/bin/python -m pytest \
  backend/tests/test_dividend_reinvestment_service.py \
  backend/tests/test_sync_service_tencent_unadjusted.py \
  backend/tests/test_data_query_service.py

npm --prefix /Users/salty/codeProject/ai/coding/stock-ah-premium-ai/frontend run build
```

验收结果：

- Ruff：通过。
- 后端目标测试：6 个用例全部通过。
- 前端构建：通过；仅保留 Vite 对既有大 chunk 的体积提示。
