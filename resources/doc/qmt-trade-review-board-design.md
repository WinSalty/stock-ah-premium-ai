# 服务侧量化复盘看板设计（QMT 实盘成交 + 收益复盘）

文档日期：2026-06-13

## 0. 文档定位与边界

本文档规划在信号侧（Linux 现有项目 `stock-ah-premium-ai`，FastAPI 后端 + React 前端 + MySQL `stock_ah_ai`）新增一个【量化复盘看板】页面：

- 看到执行侧 Windows VPS 上 QMT 实际成交了什么（买/卖/价/量/额/时间，并尽量回挂对应信号）。
- 对【当日交易情况】和【历史交易情况】做统计与复盘（收益率、胜率、回撤、滑点、分布等）。

边界约束（沿用已确定架构，不在本文档推翻）：

- 解耦架构：信号侧与执行侧只通过 MySQL / 只读接口通信。本看板属于信号侧消费端，**只读** QMT 落库数据，不直连 QMT、不下单、不发起任何写交易动作。
- 执行侧 Windows QMT 负责盘中回调实时写入与收盘快照落库（详见第 2 章数据采集职责）；信号侧只负责聚合查询与展示。
- 时间口径遵循项目 `AGENTS.md`：后端 `UTC naive` 入库，前端用 `formatEast8DateTime` 统一转东八区展示；数据库自动生成时间（`CURRENT_TIMESTAMP`/`server_default=func.now()`）按东八区本地理解，前端展示需传 `{ naiveAsEast8: true }`。QMT 回调里的 `traded_time`/`order_time` 是 int 时间戳，落库前先转为 `UTC naive`，并固化口径到执行侧文档与表注释。
- 鉴权与现有页面一致：所有 `/api/review/*` 端点都挂 `CurrentUser`（Bearer Token，`get_current_user` 依赖），并按 `user_id` 隔离（QMT 账户与登录用户的映射见第 3.5 节）。
- 只读视图沿用现有惯例：`v_` 前缀、注册进 `sql_guard_service.whitelist_tables`、`resources/sql/01_readonly_views.sql` 落 SQL、`03_full_schema_with_comments.sql` 与 `database-schema.md` 同步表清单。

## 1. QMT API 能力对账（设计依据，决定哪些字段自己算）

xtquant `xttrader` 的关键事实（用于约束聚合口径，避免对原生 API 字段做错误假设）：

- `query_stock_asset` 返回单个 `XtAsset`，仅 6 个字段：`account_type`、`account_id`、`cash`、`frozen_cash`、`market_value`、`total_asset`。**不直接给净值、当日盈亏、累计收益率、浮动盈亏**，且 `total_asset` 是当日实时快照而非历史每日净值。
- `query_stock_positions` 返回 `list[XtPosition]`：原生稳定字段为 `stock_code`、`volume`、`can_use_volume`（T+1 可卖部分）、`open_price`（成本）、`market_value`。**原生不含 `float_profit`/`position_profit`/`profit_rate`/`last_price`**——这些是 KhQuant 等第三方框架补充字段，浮动盈亏须自己用行情现价计算。
- `query_stock_orders` / `query_stock_trades` 只返回**当日**委托/成交，且**没有任何按日期范围查询历史的接口**。隔日后当日数据被清空，前一日成交/委托/资产无法再从 API 取回。
- `XtTrade` 含 `stock_code`、`order_type`（买卖方向）、`traded_id`、`traded_time`、`traded_price`、`traded_volume`、`traded_amount`、`order_id`、`strategy_name`、`order_remark`、`offset_flag`，**无 `realized_pnl` 字段**。
- 回调：`on_stock_order`/`on_stock_trade`/`on_stock_position`/`on_stock_asset`/`on_order_error`/`on_cancel_error`/`on_order_stock_async_response`/`on_disconnected`。无 `on_connected`。
- 出入金：API 不提供出入金流水，必须另建出入金台账，否则 `total_asset` 差分会被资金进出污染。

结论（三类口径，决定数据流）：
1. **QMT 直接给**：成交价/量/额、当日委托与成交全集、持仓 `volume`/`open_price`、当前 `total_asset`/`cash`/`market_value`。
2. **执行侧必须每日落快照**：历史成交流水（以 `account_id + traded_id` 去重）、每日收盘资产快照、每日收盘持仓快照——否则历史净值曲线与历史成交不可还原。
3. **聚合层（信号侧或执行侧）自己算**：浮动盈亏（现价−成本×volume）、已实现盈亏（成交流水 FIFO 撮合）、当日盈亏（资产差分扣净入金）、累计收益率（TWR/Modified Dietz）。

> 字段集存在 xtquant 版本差异（GitHub 镜像/新版本额外有 `avg_price`/`frozen_volume`/`on_road_volume`/`yesterday_volume`/`direction`/`offset_flag`）。执行侧落库前应在目标机器对实际安装版本用 `vars(obj)` 实测确认，避免 `AttributeError`；本文档表结构以可稳定取到的字段为准，扩展字段允许为 NULL。

## 2. 数据采集职责（执行侧写、信号侧读）

执行侧 Windows QMT 进程职责（本文档只约定落库口径，实现归执行侧设计文档）：

- 盘中：订阅回调，`on_stock_trade` 实时写入成交流水（以 `traded_id` 幂等去重）、`on_stock_order` 写入/更新委托、`on_order_error`/`on_cancel_error` 写入失败回报。
- 收盘后（A 股 15:00 之后定时一次）：调 `query_stock_asset`/`query_stock_positions`，写入当日收盘资产快照与持仓快照；持仓快照同步盯市现价（`realtime_quote_snapshot.last_price` 或当日收盘价）以便算浮动盈亏。
- 进程保活：`run_forever()` 常驻，`on_disconnected` 检测断线后主动重连重订阅；每日开盘前重建 session。
- 出入金：QMT 不给流水，需在执行侧或运营侧维护出入金台账表（手工/对账单导入），写入净入金。

信号侧职责（本文档主体）：聚合查询 + 复盘指标计算 + 页面展示，全部只读上述表。

## 3. 数据模型（新增表，库 `stock_ah_ai`）

所有表前缀 `qmt_`。时间字段：业务时间戳字段（`*_time`）入库 `UTC naive`；`created_at`/`updated_at` 用 `server_default=func.now()`（东八区本地理解）。交易日字段 `trade_date` 用 `DATE`。

### 3.1 `qmt_trade`（成交流水，当日+历史统一）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | BIGINT PK | 自增主键 |
| `account_id` | VARCHAR(32) | QMT 资金账号 |
| `trade_date` | DATE | 成交所属交易日（东八区自然交易日） |
| `traded_id` | VARCHAR(64) | QMT 成交编号，与 `account_id` 唯一去重键 |
| `order_id` | BIGINT | 关联委托编号 |
| `stock_code` | VARCHAR(16) | 证券代码（QMT 格式，如 `000001.SZ`） |
| `resolved_ts_code` | VARCHAR(16) | 经 `stock_identity_resolver` 归一后的代码，便于回挂信号 |
| `side` | VARCHAR(8) | `BUY`/`SELL`，由 `order_type`/`offset_flag` 归一 |
| `traded_price` | DECIMAL(12,4) | 成交均价 |
| `traded_volume` | INT | 成交数量 |
| `traded_amount` | DECIMAL(18,4) | 成交金额 |
| `traded_time` | DATETIME | 成交时间（UTC naive） |
| `strategy_name` | VARCHAR(64) | QMT 策略名 |
| `order_remark` | VARCHAR(128) | 委托备注（可携带信号 key 便于回挂） |
| `created_at`/`updated_at` | DATETIME | 落库时间 |

唯一索引：`uk_account_traded (account_id, traded_id)`；普通索引：`(account_id, trade_date)`、`(resolved_ts_code, trade_date)`。

### 3.2 `qmt_order`（委托，含失败/废单，用于成功率与漏单）

| 字段 | 说明 |
| --- | --- |
| `id` PK / `account_id` / `trade_date` / `order_id`（唯一）/ `stock_code` / `resolved_ts_code` |
| `side`：`BUY`/`SELL` |
| `order_volume` / `price` / `price_type`（报价类型）|
| `traded_volume` / `traded_price`：已成数量与均价 |
| `order_status`（int 枚举：已报/部成/已成/已撤/废单）/ `status_msg`（描述）|
| `order_time`（UTC naive）/ `strategy_name` / `order_remark` |
| `error_id` / `error_msg`：来自 `on_order_error`，下单失败原因 |
| `created_at`/`updated_at` |

唯一索引：`uk_account_order (account_id, order_id)`。

### 3.3 `qmt_asset_daily_snapshot`（每日收盘资产快照，净值曲线基石）

| 字段 | 说明 |
| --- | --- |
| `id` PK / `account_id` / `trade_date`（与 account 唯一）|
| `total_asset`：收盘总资产 |
| `cash` / `frozen_cash` / `market_value` |
| `net_cash_flow`：当日净入金（入金正、出金负），来自出入金台账 |
| `realized_pnl`：当日已实现盈亏（FIFO 撮合产出，落库便于历史回看）|
| `float_pnl`：当日收盘持仓浮动盈亏合计 |
| `snapshot_source`：`QMT_CLOSE` / `MANUAL` |
| `created_at`/`updated_at` |

唯一索引：`uk_account_date (account_id, trade_date)`。

### 3.4 `qmt_position_daily_snapshot`（每日收盘持仓快照）

| 字段 | 说明 |
| --- | --- |
| `id` PK / `account_id` / `trade_date` / `stock_code` / `resolved_ts_code` |
| `volume`：总持仓 / `can_use_volume`：可卖（T+1 口径）|
| `open_price`：成本 / `mark_price`：盯市现价（收盘价或快照价）|
| `market_value`：市值 / `float_pnl`：浮动盈亏=(mark_price−open_price)×volume |
| `holding_days`：持有交易日数（按 `a_trade_calendar` 计）|
| `created_at`/`updated_at` |

唯一索引：`uk_account_date_stock (account_id, trade_date, stock_code)`。

### 3.5 `qmt_account`（账户与登录用户映射 + 出入金台账头）

| 字段 | 说明 |
| --- | --- |
| `id` PK / `account_id`（唯一）/ `user_id`：关联 `app_user`，用于鉴权隔离 |
| `display_name` / `account_type` / `is_active` |
| `created_at`/`updated_at` |

### 3.6 `qmt_cash_flow`（出入金台账，TWR 切段依据）

| 字段 | 说明 |
| --- | --- |
| `id` PK / `account_id` / `trade_date` / `flow_time`（UTC naive）|
| `amount`：金额（入金正、出金负）/ `flow_type`：`DEPOSIT`/`WITHDRAW` |
| `is_large_flow`：是否大额（影响 TWR 是否当日真实切段，见第 4 章）|
| `note` / `created_at`/`updated_at` |

### 3.7 信号回挂（可成交性复盘的关键）

成交回挂信号：以 `qmt_trade.resolved_ts_code` + `trade_date` 关联到 `limit_up_selected_stock`（信号侧已规划：`trade_date=T` 信号日、`target_trade_date=T+1` 买入日；含 龙头强度分/角色/战法/情绪周期 `market_state`/可成交性 `tradable_flag`/连板先验）。回挂条件：`qmt_trade.trade_date = limit_up_selected_stock.target_trade_date AND resolved_ts_code 一致`。买不进/漏单复盘：以 `limit_up_selected_stock`（计划买入全集）LEFT JOIN `qmt_trade`（实际成交），未成交即买不进，可再按 `tradable_flag`/`market_state`/战法分组。

## 4. 收益率与盈亏口径（计算公式，必须固化）

### 4.1 当日盈亏（分子剔除出入金）

```
当日总盈亏 = 今日 total_asset − 昨日 total_asset − 当日净入金(net_cash_flow)
其中 净入金 = Σ入金 − Σ出金（入金正、出金负）
```

当日总盈亏再拆为两列单独展示（互不重叠）：

```
当日已实现盈亏 realized_pnl  = 当日所有 SELL 成交经 FIFO 撮合得出的平仓盈亏合计（已扣买入成本）
当日浮动盈亏   float_pnl     = Σ 收盘未平仓持仓 (mark_price − open_price) × volume
校验恒等式（无费用/分红口径下应近似成立）：
  当日总盈亏 ≈ 当日已实现盈亏 + 当日浮动盈亏变动 − 交易费用
```

> T+1 约束：当日买入计入 `volume` 但不可卖（`can_use_volume` 不含当日买入），故当日买入标的当日只可能贡献浮动盈亏，不可能贡献已实现盈亏；已实现盈亏只来自当日卖出。

### 4.2 当日收益率（单日 Modified Dietz，剔除现金流时点）

```
当日收益率 r = (V1 − V0 − CF) / (V0 + Σ(CF_i × w_i))
  V1 = 今日 total_asset，V0 = 昨日 total_asset
  CF = 当日净现金流合计，CF_i = 第 i 笔现金流，w_i = 该现金流在当日内停留时长占比
  小额现金流可近似 w_i=0.5（半日权重）；当日无出入金时退化为 (V1−V0)/V0
```

页面「当日收益率」卡片必须标注是否含出入金，避免把入金当作收益。

### 4.3 账户级历史净值曲线（TWR，剔除出入金影响）

子区间法（出入金当日切段）：

```
单段持有期收益 HPR_i = (段末资产 − 段初资产 − 段内净入金) / 段初资产
账户累计 TWR = ∏(1 + HPR_i) − 1
净值序列 NAV_t = NAV_{t-1} × (1 + r_t)，NAV_0 = 1（归一净值，用于画曲线，已剔除出入金）
```

工程落地口径：
- 逐交易日用单日 Modified Dietz 算 `r_t`（4.2），链式相乘得净值曲线，作为日频 TWR 近似——不要求每笔出入金时点精确估值。
- **大额出入金**当日要用真实收盘资产做切段（`qmt_cash_flow.is_large_flow=1` 标记），不能只用 Modified Dietz 近似（GIPS 口径）。
- 评价 QMT 操盘水平用 TWR（剔除出入金时点与规模影响）；如另需评价「投资者实际拿到的钱」可补 MWR/IRR，作为次要口径。

### 4.4 风险与风险调整指标（日频，年化乘 √252）

```
累计收益率 = NAV_end / NAV_start − 1
年化收益率 = (1 + 区间总收益)^(365 / 区间自然日数) − 1
最大回撤 MDD = max_t( (峰值_t − NAV_t) / 峰值_t )，峰值_t = 截至 t 的滚动最高 NAV
  另列：回撤时长（峰→恢复）、恢复时间（谷→创新高）
夏普 Sharpe = (日均收益 − 日无风险利率) / 日收益标准差 × √252
索提诺 Sortino = (日均收益 − 日无风险利率) / 下行偏差 × √252
  下行偏差 = sqrt( Σ min(r_i − MAR, 0)^2 / N )，MAR 取 0 或无风险利率
卡玛 Calmar = 年化收益率 / |最大回撤|
```

无风险利率口径：打板隔日持仓周期极短，无风险利率影响极小，默认取 0 并在页面文案注明；如需精确可取一年期国债折日。分子收益、无风险利率、分母波动率必须同一时间口径（日频）。

### 4.5 交易级指标（成交流水撮合）

```
单票已实现盈亏：FIFO 撮合（A 股默认口径，与 QMT/券商对账单对齐便于对账）
  卖出按最早买入批次成本结转，已实现盈亏 = (卖价 − 该批次买价) × 平仓量 − 费用
日胜率   = 盈利交易日数 / 总交易日数（账户级，区别于单笔胜率）
单笔胜率 = 盈利平仓笔数 / 总平仓笔数
盈亏比   = 平均每笔盈利 / 平均每笔亏损
盈利因子 = 总盈利 / 总亏损（>1 即整体盈利）
持有天数 = 卖出日 − 买入日（按 a_trade_calendar 交易日计；打板隔日卖典型为 1）
```

> FIFO 与移动加权在部分平仓时中间值不同，但持仓全清后累计已实现盈亏相等；固定 FIFO 并在页面标注，便于与 QMT 资金账单对账。

### 4.6 下单成功率 / 买不进 / 滑点

```
下单成功率 = 完全成交委托数 / 全部有效委托数（废单/失败计为不成功）
买不进只数 = 计划买入(limit_up_selected_stock) 中无任何买入成交的标的数
成交漏斗   = 计划标的(limit_up_selected_stock) → 实际挂单(qmt_order) → 实际成交(qmt_trade)，逐级算流失率
滑点（两套基准，分开展示，不合成一个数字）：
  信号链路滑点 = (实际买入成交均价 − 信号决策价) / 信号决策价   ← 衡量信号→执行全链路损耗（含延迟）
  执行质量滑点 = (实际成交均价 − 下单时刻最新价) / 下单时刻价     ← 衡量 QMT 纯撮合质量
  以 bps 表示；买不进的计划单按「未成交机会成本」单列，不当作没发生（Implementation Shortfall 漏单成本）
```

信号决策价取 `limit_up_selected_stock` 信号生成时价格或 `tencent_unadjusted_daily_quote` 中 T 日收盘价（口径在文档固化，与回测「一字/秒封买不进不计收益」一致）。

## 5. 后端 API 设计（`/api/review/*`，全部挂 CurrentUser）

新增路由文件 `backend/app/api/routes_review.py`，`main.py` 以 `prefix="/api"`、`tags=["review"]` 挂载；服务层 `backend/app/services/review/`（聚合 + 指标计算 + FIFO 撮合）；schema `backend/app/schemas/review.py`。所有端点按当前用户映射的 `account_id` 过滤（`qmt_account.user_id = current_user.id`），未绑定账户返回空结果而非 500。

### 5.1 端点列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/review/accounts` | 当前用户可见 QMT 账户列表（供切换）|
| GET | `/api/review/daily` | 当日复盘汇总：当日总/已实现/浮动盈亏、收益率、成功率、买不进只数、战法/题材分布 |
| GET | `/api/review/trades` | 成交清单（买/卖/价/量/额/时间/回挂信号），支持 `trade_date`、`side`、分页 |
| GET | `/api/review/positions` | 当日/指定日收盘持仓 + 浮动盈亏（分票）|
| GET | `/api/review/orders` | 委托清单（含失败/废单），用于成交漏斗与成功率下钻 |
| GET | `/api/review/history` | 历史复盘：净值曲线点列 + 累计/年化/MDD/夏普/索提诺/卡玛/日胜率 |
| GET | `/api/review/history/trades-stats` | 单票胜率盈亏比、持有天数分布、滑点分布 |
| GET | `/api/review/history/periodic` | 月度/周度统计（收益、胜率、笔数、换手）|
| GET | `/api/review/funnel` | 计划→挂单→成交漏斗，可按 `tradable_flag`/`market_state`/战法分组 |

公共查询参数：`account_id`（缺省取当前用户默认账户）、`trade_date` 或 `start_date`/`end_date`、`group_by`（战法/题材/情绪周期）。日期范围用 `a_trade_calendar` 校验为交易日。

### 5.2 响应字段约定（节选，时间字段标注来源供前端格式化）

- `/api/review/daily` 返回：`trade_date`、`total_pnl`、`realized_pnl`、`float_pnl`、`daily_return`、`order_success_rate`、`unfilled_count`、`by_strategy[]`（战法→笔数/盈亏）、`by_theme[]`（题材→笔数/盈亏）、`by_market_state[]`（情绪周期分组）。
- `/api/review/history` 返回：`nav_curve[]`（`trade_date`、`nav`、`drawdown`）、`cum_return`、`annual_return`、`max_drawdown`、`mdd_duration_days`、`recovery_days`、`sharpe`、`sortino`、`calmar`、`day_win_rate`。
- 时间字段：`traded_time`/`order_time` 为 `UTC naive`（前端 `formatEast8DateTime(value)`）；`created_at`/`updated_at` 为东八区本地（前端 `formatEast8DateTime(value, { naiveAsEast8: true })`）；`trade_date` 为纯日期，前端直出不转换。

### 5.3 聚合 SQL 思路

只读视图（`v_` 前缀，落 `01_readonly_views.sql`，注册进 `sql_guard_service.whitelist_tables`，供后端聚合与 LLM 问答只读复用）：

- `v_qmt_daily_pnl`：按 `account_id, trade_date` 聚合资产快照差分得当日总盈亏，JOIN `qmt_cash_flow` 当日净入金，带出 `realized_pnl`/`float_pnl`。SQL 思路：
  ```sql
  SELECT a.account_id, a.trade_date,
         a.total_asset - prev.total_asset - COALESCE(cf.net_flow,0) AS total_pnl,
         a.realized_pnl, a.float_pnl,
         (a.total_asset - prev.total_asset - COALESCE(cf.net_flow,0))
           / NULLIF(prev.total_asset + COALESCE(cf.weighted_flow,0),0) AS daily_return
  FROM qmt_asset_daily_snapshot a
  JOIN qmt_asset_daily_snapshot prev   -- 用 a_trade_calendar 取上一交易日，避免自然日漏算
    ON prev.account_id = a.account_id AND prev.trade_date = (上一交易日)
  LEFT JOIN (SELECT account_id, trade_date,
                    SUM(amount) net_flow,
                    SUM(amount*0.5) weighted_flow   -- 小额半日权重；大额由服务层精确切段
             FROM qmt_cash_flow GROUP BY account_id, trade_date) cf
    ON cf.account_id = a.account_id AND cf.trade_date = a.trade_date;
  ```
  上一交易日用 `a_trade_calendar` 子查询取，禁止用 `trade_date - 1` 自然日。
- `v_qmt_trade_with_signal`：`qmt_trade` LEFT JOIN `limit_up_selected_stock`（`resolved_ts_code = a_stock_code AND trade_date = target_trade_date`），带出战法/题材/`market_state`/`tradable_flag`/角色/连板先验，供成交清单与分组统计。
- `v_qmt_fill_funnel`：`limit_up_selected_stock`（计划买入全集，按 `target_trade_date`）LEFT JOIN `qmt_order`、`qmt_trade`，逐级标记是否挂单/是否成交，供漏斗与买不进统计。
- 净值曲线、夏普/索提诺/卡玛、FIFO 撮合等**链式/有状态**计算放服务层 Python（视图只做行级聚合），逐交易日序列计算后返回。年化与回撤在服务层基于 `nav_curve` 序列滚动计算。

## 6. 前端页面设计（React + antd + echarts，复用现有 `pages/` 与时间工具）

新增页面 `frontend/src/pages/QmtReviewPage.tsx`，路由与菜单按现有 `app_user` 菜单权限模型接入（与 `LimitUpPushPage` 等同级）；API 封装在 `frontend/src/api/`，数据拉取用 `@tanstack/react-query`；所有时间展示统一走 `formatEast8DateTime`。

页面顶部：账户切换 + 日期/区间选择（默认最新交易日 / 近 N 交易日）。两个 Tab：

### 6.1 当日复盘 Tab

- 盈亏卡片区（antd `Statistic` 卡片组）：当日总盈亏、当日已实现盈亏、当日浮动盈亏（三列分开，红涨绿跌按 A 股习惯）、当日收益率（标注是否含出入金）、下单成功率、买不进只数。
- 今日成交清单（antd `Table`）：方向/代码名称/成交价/量/额/时间/回挂信号（战法/题材/`market_state`/角色）。`traded_time` 用 `formatEast8DateTime`。
- 当日分布（echarts 饼图/柱状图）：按战法分布、按题材分布、按情绪周期分布（笔数与盈亏双视角切换）。
- 成交漏斗（echarts 漏斗图）：计划→挂单→成交，旁列各级流失率与买不进明细，可按 `tradable_flag`/战法分组。

### 6.2 历史复盘 Tab

- 净值曲线（echarts 折线图）：归一净值 NAV（TWR 口径，已剔除出入金）+ 回撤面积（次坐标）+ 出入金切段标记点。
- 绩效指标卡片组：累计收益率、年化收益率、最大回撤（含回撤时长/恢复时间）、夏普、索提诺、卡玛、日胜率。
- 交易质量区：单票胜率盈亏比表（echarts 散点：横轴胜率、纵轴盈亏比，气泡大小=笔数）、持有天数分布（直方图）、滑点分布（直方图，信号链路滑点 vs 执行质量滑点分开两图）。
- 周期统计（antd `Table` + echarts 柱状图）：月度/周度收益、胜率、笔数、换手。

口径标注一致性：页面所有收益率/盈亏卡片需用 tooltip 标明口径（TWR、是否含出入金、FIFO、滑点基准），与本文档第 4 章公式一一对应；与现有页面一致采用「只读视图口径」，不在前端做任何盈亏二次推算。

## 7. 与现有约定的一致性清单

- 时间：QMT 时间戳转 `UTC naive` 入库；`*_time` 前端 `formatEast8DateTime(value)`；DB 自动时间前端 `formatEast8DateTime(value, { naiveAsEast8: true })`；`trade_date` 直出。
- 鉴权：所有端点 `CurrentUser` 依赖，按 `qmt_account.user_id` 隔离。
- 只读：信号侧只读 QMT 表，不写交易；新增 `v_qmt_*` 视图注册进 `sql_guard_service` 白名单并落 `01_readonly_views.sql`。
- 代码归一：成交/持仓代码经 `stock_identity_resolver` 落 `resolved_ts_code`，便于回挂信号与跨表 JOIN。
- 交易日：所有「上一交易日/持有天数/区间」用 `a_trade_calendar`，禁止自然日加减。
- 文档同步：新增表需同步 Alembic 迁移、SQLAlchemy 模型、`03_full_schema_with_comments.sql`、`database-schema.md` 表清单。
- 注释：新增模型/服务/视图/聚合分支补中文注释，说明业务意图、边界（T+1、出入金、买不进）与重跑/异常口径。

## 8. 实施阶段与依赖顺序（按阶段+任务划分，给验收标准；不含工期）

### P0 口径与文档（前置）
- 任务：固化本设计文档收益率/盈亏/滑点/FIFO 口径；与执行侧确认 QMT 落库表与出入金台账可得性。
- 验收：执行侧能稳定写入第 3 章六张表；时间口径与 `AGENTS.md` 一致。
- 依赖：无。

### P1 数据模型与采集对接
- 任务：建 `qmt_trade`/`qmt_order`/`qmt_asset_daily_snapshot`/`qmt_position_daily_snapshot`/`qmt_account`/`qmt_cash_flow` 表与 Alembic 迁移、SQLAlchemy 模型；同步 `03_full_schema_with_comments.sql` 与 `database-schema.md`。
- 验收：表与索引建成，去重键生效（重复 `traded_id` 不产生重复行）；`resolved_ts_code` 正确回填。
- 依赖：P0。

### P2 只读视图与 SQL Guard
- 任务：落 `v_qmt_daily_pnl`/`v_qmt_trade_with_signal`/`v_qmt_fill_funnel` 到 `01_readonly_views.sql`，注册进 `sql_guard_service.whitelist_tables`。
- 验收：视图可查；上一交易日按 `a_trade_calendar` 取；LLM 只读视图白名单生效。
- 依赖：P1。

### P3 当日复盘后端 + 前端
- 任务：实现 `/api/review/accounts|daily|trades|positions|orders|funnel` 与服务层（含 FIFO 撮合、当日 Modified Dietz）；前端「当日复盘」Tab。
- 验收：当日总/已实现/浮动盈亏三列分开且校验恒等式近似成立；成交清单回挂信号正确；成功率与买不进只数与漏斗口径一致；时间展示东八区无 ±8 小时错误。
- 依赖：P2。

### P4 历史复盘后端 + 前端
- 任务：实现 `/api/review/history|history/trades-stats|history/periodic`（TWR 净值曲线、年化/MDD/夏普/索提诺/卡玛/日胜率、单票胜率盈亏比、持有天数/滑点分布、周期统计）；前端「历史复盘」Tab。
- 验收：净值曲线已剔除出入金（大额切段生效）；各指标与公式一致；滑点两套基准分开展示。
- 依赖：P3。

### P5 鉴权隔离与回归
- 任务：账户-用户映射隔离校验；后端单测覆盖差分口径、FIFO、TWR、买不进；菜单权限接入。
- 验收：不同用户只见各自账户数据；单测通过；与现有页面口径文案一致。
- 依赖：P4。

## 9. 验收标准（总）

- 用户可在看板看到 QMT 实际成交（买/卖/价/量/额/时间）并回挂到信号（战法/题材/情绪周期）。
- 当日盈亏明确拆分总/已实现/浮动三列，且当日收益率剔除出入金并标注口径。
- 历史净值曲线用 TWR 剔除出入金；累计/年化/MDD/夏普/索提诺/卡玛/日胜率口径与本文档公式一致。
- 下单成功率、买不进只数、成交漏斗、滑点（信号链路 vs 执行质量两套）可查并可按战法/情绪周期下钻。
- 时间、鉴权、只读视图口径与现有 `formatEast8DateTime`/`CurrentUser`/`sql_guard` 完全一致；信号侧不发起任何写交易动作。
