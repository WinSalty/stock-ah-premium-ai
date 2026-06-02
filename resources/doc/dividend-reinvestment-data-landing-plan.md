# 分红再投入筛选数据落地方案

文档日期：2026-05-29

## 1. 背景与目标

本方案用于支持“长期分红再投入收益”维度的股票筛选能力。目标是把回测所需的基础数据先稳定落到本地 MySQL，再基于本地数据计算每只股票的年度分红再投入明细、累计收益率和年化收益率，避免页面查询或 LLM 问答时实时大批量访问 Tushare。

所需接口、字段、落地表、请求节奏和数据质量校验清单见：[分红再投入所需数据落地清单](./dividend-reinvestment-required-data-landing-plan.md)。

参考截图中的核心口径，本功能需要按股票逐年展示：

- 年份。
- 年末或最新股价。
- 每股分红。
- 分红金额。
- 再投入可买股数。
- 持仓股数。
- 市值。
- 累计收益。
- 累计收益率。
- 平均年化收益率。

当前项目已有 A 股基础表、A 股日线表、A 股每日指标表和 A 股分红表模型，但本地数据覆盖不足以直接支撑 2016 年以来的分红再投入筛选：`a_daily_quote` 当前只覆盖 2025-08-12 至 2026-05-08，`a_dividend` 当前为空。因此需要新增一套受控历史回补和结果缓存链路。

## 2. 约束边界

### 2.1 Tushare 调用限制

当前按用户权限和接口说明执行以下工程约束：

- Tushare 接口调用总速率按 120 次/分钟上限设计。
- 实际任务默认使用 0.6 秒/次的保守间隔，约 100 次/分钟，给网络抖动、中转服务冷却和单次接口耗时留余量。
- 同一时间只允许一个历史回补任务访问 Tushare，避免页面手动同步、定时任务和红利回补并发触发限流。
- 每次外部请求必须记录任务、参数、返回行数、耗时和错误信息，失败后可从断点继续。

### 2.2 数据范围

第一版建议默认范围：

- 开始日期：2016-01-01。
- 结束日期：当前最新可用交易日。
- 股票范围：A 股正常上市股票，默认排除上市未满 10 年、名称含 ST 或退市状态股票。
- 市场范围：仅 A 股。港股、基金和 ETF 不纳入第一版。

### 2.3 计算边界

第一版只做日线级长期回测，不做分钟级、Tick 级或组合级策略回测。所有收益计算均基于本地已落库的日线价格、分红送股和交易日历，不在计算阶段访问 Tushare。

## 3. 数据落地分层

### 3.1 原始数据层

优先复用项目已有表：

| 表 | 数据来源 | 业务用途 |
| --- | --- | --- |
| `a_stock_basic` | `stock_basic` | 股票池、上市日期、行业、市场和上市状态过滤。 |
| `a_trade_calendar` | `trade_cal` | 找除息日后的可交易日、年度最后交易日和最新交易日。 |
| `a_daily_quote` | `daily` | 日收盘价、除息日再投入价格、年度市值和当前市值。 |
| `a_daily_basic` | `daily_basic` | 最新市值、股息率、PE、PB、股本等筛选展示指标。 |
| `a_dividend` | `dividend` | 每股现金分红、送转股、股权登记日、除权除息日和派息日。 |

第一版不要求落全历史 `daily_basic`。`daily_basic` 先用于最新快照筛选；如后续需要按历史估值分位筛选，再单独扩展年末或全量历史每日指标。

### 3.2 回测结果层

建议新增三张表。

#### `dividend_reinvestment_backtest_run`

记录一次回测批次和计算口径。

| 字段 | 说明 |
| --- | --- |
| `id` | 自增主键。 |
| `run_key` | 回测批次唯一键，用于同口径重复执行时定位。 |
| `start_date` | 回测开始日期。 |
| `end_date` | 回测结束日期。 |
| `initial_amount` | 初始投入金额，默认建议 100000 元。 |
| `cash_div_field` | 现金分红口径，`cash_div_tax` 表示税前，`cash_div` 表示税后。 |
| `reinvest_price_policy` | 再投入价格口径，第一版固定为除息日或之后首个交易日收盘价。 |
| `share_rounding_policy` | 买股数量取整口径，第一版建议允许小数股，便于跨股票比较。 |
| `status` | `RUNNING`、`SUCCESS`、`FAILED`。 |
| `stock_count` | 参与计算的股票数。 |
| `summary_count` | 写入摘要行数。 |
| `error_message` | 失败原因。 |
| `started_at` / `finished_at` | 批次起止时间。 |

#### `dividend_reinvestment_backtest_summary`

每只股票每个回测批次一行，用于筛选、排序和列表展示。

| 字段 | 说明 |
| --- | --- |
| `id` | 自增主键。 |
| `run_id` | 回测批次 ID。 |
| `ts_code` | A 股 Tushare 代码。 |
| `symbol` | 股票代码。 |
| `name` | 股票名称。 |
| `industry` | 所属行业。 |
| `list_date` | 上市日期。 |
| `start_trade_date` | 实际开始交易日。 |
| `end_trade_date` | 实际结束交易日。 |
| `initial_amount` | 初始投入金额。 |
| `initial_price` | 起始买入价格。 |
| `initial_shares` | 初始持股数。 |
| `final_price` | 结束日价格。 |
| `final_shares` | 结束日持股数。 |
| `final_market_value` | 结束市值。 |
| `total_cash_dividend` | 回测期累计现金分红。 |
| `total_reinvested_amount` | 回测期累计用于再投入的金额。 |
| `total_reinvested_shares` | 回测期累计再投入买入股数。 |
| `dividend_event_count` | 分红事件次数。 |
| `dividend_year_count` | 有分红的年份数量。 |
| `consecutive_dividend_years` | 从最近一个实际发生分红的年份向前统计的连续分红年数，避免当前未完整年度暂无除权分红时误清零。 |
| `total_return_amount` | 累计收益金额。 |
| `total_return_pct` | 累计收益率。 |
| `annualized_return_pct` | 年化收益率。 |
| `ten_year_avg_annualized_return_pct` | 最近最多 10 个年度明细中，非空年度平均年化收益率的算术平均，用于筛选长期稳定表现。 |
| `latest_dividend_yield_ttm` | 最新 TTM 股息率。 |
| `latest_total_mv` | 最新总市值。 |
| `latest_pe` | 最新 PE，来自最新 `a_daily_basic.pe`。 |
| `latest_pe_ttm` | 最新 PE TTM，来自最新 `a_daily_basic.pe_ttm`。 |
| `latest_pb` | 最新 PB。 |
| `latest_roe` | 最新 ROE，只使用 Tushare 财务指标落地表 `a_financial_indicator.roe`，不再复用选股因子快照。 |
| `rank_score` | 综合排序分。 |
| `data_quality` | 数据质量标记，例如 `COMPLETE`、`PARTIAL_PRICE`、`NO_DIVIDEND`。 |
| `data_issue` | 数据缺口说明。 |

建议唯一键：`run_id + ts_code`。

#### `dividend_reinvestment_backtest_yearly`

每只股票每年一行，用于展示截图中的年度明细。

| 字段 | 说明 |
| --- | --- |
| `id` | 自增主键。 |
| `run_id` | 回测批次 ID。 |
| `ts_code` | A 股 Tushare 代码。 |
| `year` | 年份。 |
| `year_end_trade_date` | 当年最后可用交易日。 |
| `year_end_price` | 年末收盘价。 |
| `cash_div_per_share` | 当年每股现金分红合计。 |
| `cash_div_amount` | 当年现金分红金额。 |
| `stock_div_per_share` | 当年每股送转合计。 |
| `stock_div_shares` | 当年送转增加股数。 |
| `reinvest_price_avg` | 当年分红再投入加权平均价格。 |
| `reinvested_shares` | 当年分红再投入买入股数。 |
| `holding_shares` | 年末持股数。 |
| `market_value` | 年末市值。 |
| `return_amount` | 年末累计收益金额。 |
| `return_pct` | 年末累计收益率。 |
| `annualized_return_pct` | 年末平均年化收益率。 |
| `dividend_event_count` | 当年分红事件次数。 |
| `note` | 异常或补充说明。 |

建议唯一键：`run_id + ts_code + year`。

## 4. Tushare 接口与请求量估算

### 4.1 全量历史回补

以 2016-01-01 至当前日期估算：

| 数据 | 请求方式 | 估算请求数 | 说明 |
| --- | --- | --- | --- |
| `stock_basic` | 全量一次 | 1 | 正常上市 A 股基础信息。 |
| `trade_cal` | 日期范围 | 1 到 3 | 2016 至当前日历。 |
| `daily` | 按 `trade_date` 拉全市场 | 约 2500 | 每个交易日一次，避免单股逐只拉取导致请求量爆炸。 |
| `dividend` | 按开市日的 `ex_date` 拉全市场 | 约 2500 | 除权除息日按交易日发生，跳过周末和节假日以减少无效请求。 |
| `daily_basic` | 最新交易日和少量兜底日 | 20 到 40 | 第一版只做最新筛选指标。 |

合计约 5000 到 5100 次请求。按 100 次/分钟保守速度估算，首次全量回补约 50 分钟。实际耗时还取决于网络、中转服务延迟、MySQL 写入速度和失败重试次数。

### 4.2 日常增量

日常增量请求量很小：

| 数据 | 增量方式 | 日请求量 |
| --- | --- | --- |
| `daily` | 当天交易日全市场 | 1 |
| `daily_basic` | 当天交易日全市场 | 1 |
| `dividend` | 当天 `ex_date` 全市场 | 1 |
| `stock_basic` | 每周或每月刷新 | 摊薄后接近 0 |
| `trade_cal` | 每月或季度刷新未来窗口 | 摊薄后接近 0 |

正常情况下每天 3 到 5 次请求即可完成增量。

## 5. 回补任务设计

### 5.1 任务拆分

建议新增同步数据集：`dividend_reinvestment_data_landing`。

内部拆成以下阶段：

1. `prepare_stock_pool`
   - 同步或确认 `a_stock_basic`。
   - 生成符合上市年限、上市状态和名称过滤的候选股票池。

2. `backfill_trade_calendar`
   - 同步或确认 `a_trade_calendar` 覆盖回测起止日期。
   - 预计算每年最后交易日。

3. `backfill_daily_quote`
   - 按交易日循环调用 `daily(trade_date=YYYYMMDD)`。
   - 写入 `a_daily_quote`，按 `ts_code + trade_date` 幂等 upsert。

4. `backfill_dividend`
   - 按开市交易日循环调用 `dividend(ex_date=YYYYMMDD)`。
   - 只将 `ex_date` 有效的数据写入 `a_dividend`。
   - 后续计算时只采用 `div_proc=实施` 或等价已实施状态。
   - 若发现早期历史分红缺口，可显式开启 `supplement_dividend_by_stock`，对候选股票逐只调用 `dividend(ts_code=...)` 补齐历史实施分红；该阶段请求量约等于候选股票数，只用于修复或全量校准，不作为日常增量默认动作。
   - 外部备选源：AKShare 的 Sina 分红配股明细和 CNINFO 个股历史分红可作为 Tushare 不可用时的人工校准来源，但第一优先级仍使用当前已授权的 Tushare `dividend` 接口，避免引入新依赖和字段单位差异。
   - 资料依据：Tushare `dividend` 接口文档说明支持按 `ts_code`、`ann_date`、`record_date`、`ex_date` 查询；AKShare 文档中 `stock_history_dividend_detail` 提供新浪财经单股分红配股明细，可用于人工复核。

5. `backfill_latest_daily_basic`
   - 从最新交易日向前尝试 20 个交易日，找到可用 `daily_basic` 快照。
   - 写入 `a_daily_basic`，用于筛选和展示。

6. `calculate_backtest`
   - 从本地表读取数据。
   - 计算 summary 和 yearly。
   - 不再访问 Tushare。

### 5.2 断点续跑

建议新增或复用 checkpoint 记录每个阶段的处理位置：

| 阶段 | checkpoint key | checkpoint value |
| --- | --- | --- |
| `backfill_daily_quote` | `dividend_reinvestment.daily.last_trade_date` | 最近成功写入的交易日。 |
| `backfill_dividend` | `dividend_reinvestment.dividend.last_ex_date` | 最近成功处理的除权除息交易日。 |
| `backfill_latest_daily_basic` | `dividend_reinvestment.daily_basic.latest_trade_date` | 最新可用每日指标日期。 |
| `calculate_backtest` | `dividend_reinvestment.backtest.last_ts_code` | 最近成功计算的股票代码。 |

重跑规则：

- 已成功的日期或股票默认跳过。
- 用户选择强制重跑时，仅清理本功能结果表，不删除通用原始表。
- 原始表 upsert 保持幂等，避免重复请求或重复写入造成数据膨胀。
- 计算结果表按 `run_id` 隔离，每次正式回测生成新批次；同口径重算可通过 `run_key` 标记最新批次。

### 5.3 限流和互斥

实现口径：

- Tushare 客户端默认间隔保持 `TUSHARE_REQUEST_INTERVAL_SECONDS=0.6`。
- 历史回补服务启动前获取进程内互斥锁。
- 如果已有 `RUNNING` 状态的红利回补任务，新的同类任务直接拒绝。
- 如果全局已有其他 Tushare 长任务运行，红利回补任务排队或拒绝，避免并发超限。
- 所有阶段写入 `sync_run` 或专用 run 表，页面显示当前阶段、进度日期、请求数、行数和失败原因。
- 回测 summary/yearly 结果按 500 行分块 upsert，避免年度明细批量过大触发 MySQL `max_allowed_packet` 或连接断开。

## 6. 计算口径

### 6.1 基准投入

默认使用固定初始金额，而不是固定初始股数。

建议第一版默认：

- `initial_amount = 100000`。
- 起始买入日为回测开始日期之后第一个有效交易日。
- 初始股数 = 初始金额 / 起始收盘价。
- 第一版允许小数股，便于比较股票之间的真实复利表现；后续可增加整股或一手取整选项。

连续分红年数：

- 从最近一个实际发生分红的年份向前连续计数，遇到首个无分红年份停止。
- 当前年度尚未完整、尚未实施除权除息时，不参与打断连续分红年数。

### 6.2 分红处理

现金分红：

- 默认使用 `cash_div_tax` 税前分红。
- 可配置为 `cash_div` 税后分红。
- 分红金额 = 除息日前持股数 * 每股现金分红。
- 再投入买入股数 = 分红金额 / 再投入价格。

送转股：

- 使用 `stk_div` 处理送转。
- 送转增加股数 = 除权日前持股数 * 每股送转。
- 同一除权除息日同时有现金分红和送转时，先处理送转，再按处理后的持股数计算现金分红或按 Tushare 字段语义固定为登记日持股数；第一版建议在代码注释和文档中明确固定顺序，便于复核。

分红事件过滤：

- `ex_date` 不能为空。
- `div_proc` 应为实施类状态。
- `cash_div_tax`、`cash_div` 和 `stk_div` 全为空或全为 0 的事件不参与收益计算，但可记录为数据异常。

### 6.3 再投入价格

默认口径：

- 使用 `ex_date` 当天收盘价。
- 如果 `ex_date` 当天无行情，取之后第一个可用交易日收盘价。
- 如果之后 10 个交易日仍无价格，跳过该次再投入，并在年度明细 `note` 中记录缺口。

### 6.4 年度估值

年度展示口径：

- 每年取该年最后一个 A 股开市日。
- 如果股票当年最后交易日无行情，取不晚于该年最后交易日的最近一个可用收盘价。
- 当前年度使用 `end_date` 不晚于当前最新可用交易日。

收益计算：

- 年末市值 = 年末持股数 * 年末收盘价。
- 累计收益金额 = 年末市值 - 初始投入金额。
- 累计收益率 = 累计收益金额 / 初始投入金额。
- 平均年化收益率 = `(年末市值 / 初始投入金额) ** (1 / 年数) - 1`。

## 7. 候选筛选策略

为了控制首次开发和回补压力，建议第一版分两级处理。

### 7.1 原始全量落地

`daily` 和 `dividend` 可以按日期全市场落地，因为按日期拉取请求量可控，并且落地后可复用于其他投研能力。

### 7.2 回测入选股票池

计算阶段默认过滤：

- 正常上市。
- 上市日期早于回测开始日前 10 年或至少早于回测开始日。
- 名称不包含 `ST`、`*ST`、`退` 等风险标记。
- 回测期内至少有 5 个分红年度。
- 最新总市值不低于可配置阈值，例如 100 亿元。
- 最新日均成交额或近端流动性阈值可在第二版增加。

页面默认排序和综合分口径：

1. 页面默认按累计分红降序，便于先看长期现金回报贡献。
2. 用户可切换年化收益率、近十年平均年化收益率、累计收益率、最新股息率、PE、PE_TTM、ROE 排序。
3. 综合分以年化收益率为主，叠加近十年平均年化收益率、分红年数、股息率、ROE 和低 PE 温和加分，避免单一高收益或单一低估值主导榜单。
4. PE 和 PE_TTM 来自最新 `a_daily_basic`，不再使用选股因子宽表兜底。
5. ROE 只来自 `a_financial_indicator.roe`；若覆盖不足，应通过 `a_financial_indicator` 同步数据集或分红再投“财务指标补数”任务逐股补齐。

## 8. API 和页面建议

### 8.1 后端 API

当前已落地：

- `POST /api/sync/batches/dividend-reinvestment-data`
  - 触发数据落地和回测计算。
  - 参数包括 `mode`、`start_date`、`end_date`、`initial_amount`、`cash_div_field`。

- `GET /api/dividend-reinvestment/health`
  - 查询股票池、日线、分红、最新每日指标和最近成功回测批次。

- `GET /api/dividend-reinvestment/summaries`
  - 查询摘要结果列表。
  - 支持关键词、行业、数据质量、年化收益率、近十年平均年化收益率、分红年数、连续分红年数、股息率、PE、PE_TTM、ROE、分页和排序。

- `GET /api/dividend-reinvestment/export`
  - 按当前筛选和排序导出 Excel。
  - 文件包含“筛选结果”和“年度明细”两个 sheet；年度明细按榜单顺序和年份升序排列，保证同只股票的数据连续聚合。

- `GET /api/dividend-reinvestment/yearly/{ts_code}`
  - 查询单只股票年度明细。
  - 可传 `run_id`；不传时默认读取最近成功批次。

- `GET /api/dividend-reinvestment/runs`
  - 查询回测批次。

### 8.2 前端页面

已新增菜单：“分红再投筛选”。

页面结构：

- 筛选区：回测批次、关键词、最低年化收益率、最低十年均年化、最低分红年数、最低连续分红、最低股息率、最高 PE、最高 PE_TTM、最低 ROE。
- 测算口径区：位于筛选区下方，可打开弹窗查看计算公式，榜单默认按累计分红降序。
- 摘要表：股票、行业、年化收益率、近十年平均年化收益率、累计收益率、连续分红年数、累计分红、最新股息率、PE、PE_TTM、PB、ROE、数据质量。
- 明细抽屉：展示年度表，字段对齐截图里的“年份、股价、每股分红、分红金额、再投入可买股数、持仓股数、市值、收益、收益率”。
- 导出按钮：按当前筛选条件导出完整 Excel，不受页面分页限制，年度明细中同一股票行连续排列。

### 8.3 Excel 抽样复核结论

使用截图中的国投电力 `600886.SH` 抽样复核后，缺口和差异口径如下：

- 早期分红缺口原因：仅按 `ex_date` 批量回补时，本地 `a_dividend` 曾只覆盖 2020-2025 年，缺少 2016-2019 年实施分红；按 `dividend(ts_code='600886.SH')` 单股补数后，2016-2025 年 10 条现金分红均可落库。
- 已补齐的每股分红：2016 年 `0.27993`、2017 年 `0.202`、2018 年 `0.1667`、2019 年 `0.225`、2020 年 `0.2453`、2021 年 `0.28`、2022 年 `0.1635`、2023 年 `0.275`、2024 年 `0.4948`、2025 年 `0.4565`。
- 与截图 Excel 仍可能不同的原因：截图按 `100000` 股作为初始持仓，页面回测按 `100000` 元初始投入计算；截图年度价格看起来是人工表格口径，页面使用本地 Tushare 日线收盘价、除息日或之后首个交易日收盘价，并允许小数股再投入。
- 工程结论：历史数据少同步的主因是 `dividend(ex_date=...)` 回补对早期实施分红覆盖不完整；已通过 `supplement_dividend_by_stock` 增加逐股补洞能力，并在数据同步页增加“逐股补齐更早分红”开关。

### 8.4 中转稳定性处理

历史同步测试中，`tt.xiaodefa.cn` 在长时间 `daily` 回补时出现过 SSL EOF、IncompleteRead 和短暂维护响应。当前已在 `TushareClient` 增加请求级重试：

- `TUSHARE_REQUEST_MAX_ATTEMPTS` 默认 `5`。
- `TUSHARE_RETRY_BACKOFF_SECONDS` 默认 `3.0`。
- 对 SSL EOF、IncompleteRead、连接断开、短暂维护、超时做退避重试并重建 SDK 连接。
- 对权限不足类错误不重试，直接失败，避免误消耗请求。

## 9. 与现有能力的关系

### 9.1 与 A 股选股因子宽表的关系

现有 `stock_selection_factor_snapshot` 面向蓝筹、低估值、红利和质量因子，当前只保存几十只候选股快照，不适合承载十年分红再投入回测明细。

本方案新增的红利再投入表是独立能力：

- 原始数据复用 `a_daily_quote`、`a_daily_basic`、`a_dividend` 和 `a_financial_indicator`；ROE 不再使用 `stock_selection_factor_snapshot`，缺失时通过财务指标同步任务补齐。
- 回测结果单独落 `dividend_reinvestment_*` 表。
- LLM 如需回答“长期分红再投入表现”问题，应优先查询红利再投入结果表，而不是旧选股宽表。

### 9.2 与 LLM 按需补数的关系

现有 LLM 按需补数面向单股或最多 5 只股票研究，不允许自动全市场扫描，也不允许自动长历史回测。

本方案属于管理员可控的预热型数据任务：

- 不由 LLM 自动触发全量回补。
- LLM 只读取已落库的筛选结果和年度明细。
- 如果数据缺失，面向用户只提示“当前材料不足”，不暴露 Tushare 权限、接口和内部限流策略。

## 10. 验收口径

第一版完成后应满足：

1. 可从 2016-01-01 起按断点续跑方式落地 A 股日线和分红数据。
2. 全量回补遵守 0.6 秒请求间隔，不超过 120 次/分钟限制。
3. 任务失败后可从最后成功日期继续，不重复写入数据。
4. 本地计算阶段不访问 Tushare。
5. 摘要表可按年化收益率、近十年平均年化收益率、累计收益率、连续分红年数、PE、PE_TTM、ROE 筛选或排序。
6. 单只股票可展示与截图类似的年度分红再投入明细。
7. Excel 导出包含筛选结果和年度明细，同只股票的年度数据排在一起，且排序与当前筛选榜单一致。
8. 抽样股票可人工用 Excel 复核核心公式，误差只来自小数股、税前税后或取整口径差异。
9. 项目文档、数据库说明和同步说明同步更新。

## 11. 后续扩展

可在第一版稳定后扩展：

- 增加税后分红、交易成本、整股买入、一手买入等口径开关。
- 增加前复权收益对照，用于校验分红再投入回测结果。
- 增加行业内排名和红利稳定性评分。
- 增加近 3 年、5 年、10 年多窗口对比。
- 增加自选股分红再投入跟踪。
- 增加 LLM 对单只股票分红再投入明细的解释能力。
