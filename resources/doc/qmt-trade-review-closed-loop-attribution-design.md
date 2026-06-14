# 信号-执行-结果 闭环归因设计

更新日期：2026-06-13

> 本文是【量化复盘页面】系列设计的核心子模块。整体复盘页分为「当日交易情况」「历史交易情况/净值曲线」「闭环归因」三大块，本文只覆盖**闭环归因**部分——把 `信号(limit_up_selected_stock)` × `实际成交(qmt_trade)` × `次日行情结果(tencent_unadjusted_daily_quote)` 三者 join，回答"我们的信号到底执行得怎么样、信号本身准不准"。账户级绩效指标（夏普/回撤/TWR 净值曲线等）、QMT 落表与快照采集口径在同系列其它章节定义，本文只引用其表结构，不重复展开。

---

## 0. 在复盘页中的定位

闭环归因是复盘页里"最有钱味"的一块：账户级看板回答"赚没赚钱"，闭环归因回答"为什么赚/亏，下次怎么改"。它把一条信号从「计划买入」到「实际成交」再到「次日兑现」的全链路拆开，分别归因到：

- **执行环节**：计划的票有没有买进？买不进的是不是恰好最强的票（逆向选择）？
- **信号环节**：信号给的连板先验/隔日溢价先验，和实盘真实兑现吻合吗？哪个分组（龙头强度/角色/战法/情绪周期）的信号最准？
- **价格环节**：实盘成交价比信号侧理论涨停价、比回测假设买入价差了多少（滑点归因）？
- **闸门环节**：空仓日如果当时买了会怎样（行情反事实）？空仓闸门到底有没有救我们？

下游消费者：人工复盘看板（主），以及未来给 LLM 复盘报告做结构化输入（次）。

---

## 1. 数据来源与关联键

### 1.1 三方数据来源

| 角色 | 主表 | 关键字段 | 时间口径 |
| --- | --- | --- | --- |
| 信号侧（计划） | `limit_up_selected_stock` | `ts_code`、`trade_date`(=T 信号日)、`target_trade_date`(=T+1 买入日)、`leader_strength_score`(龙头强度分)、`role`(角色)、`strategy`(战法)、`market_state`(情绪周期)、`tradable_flag`(可成交性)、`continuation_prob`(连板先验)、`next_day_premium_prob`(隔日溢价先验)、`signal_close`(T 日收盘价)、`limit_up_price`(T 日理论涨停价)、`reasonable_open_high_low`/`reasonable_open_high_high`(合理高开区间) | `trade_date`/`target_trade_date` 为东八区交易日 `DATE` |
| 执行侧（实际） | `qmt_trade`（成交流水，account_id+traded_id 去重）、`qmt_order`（委托）、`qmt_position_daily_snapshot`（收盘持仓快照） | `stock_code`、`traded_time`、`traded_price`、`traded_volume`、`traded_amount`、`order_id`、`offset_flag`(买卖方向)、`order_remark`/`strategy_name` | `traded_time`/`order_time` 为时间戳 → 转东八区，入库 UTC naive |
| 结果侧（行情） | `tencent_unadjusted_daily_quote`（不复权日线 `adjust_type='NONE'`） | `open`、`high`、`low`、`close`、`pre_close`、`vol`、`amount`、`limit_status`(若有，否则按主板/创业板规则现算) | 不复权，按交易日 |
| 日历 | `a_trade_calendar` | `cal_date`、`is_open`、用于 T→T+1→T+2 映射 | 交易日 |
| 身份解析 | `stock_identity_resolver` | 统一 `ts_code` ↔ QMT `stock_code`(如 `600000.SH`/`000001.SZ`) | — |

### 1.2 关联键设计（核心）

三方代码格式不统一是第一道坎，必须先归一：

1. **代码归一键 `norm_code`**：信号侧 `limit_up_selected_stock.ts_code`、行情侧 `tencent_unadjusted_daily_quote.ts_code` 已是 `600000.SH` 形态；QMT 侧 `qmt_trade.stock_code` 通常也是 `600000.SH`/`000001.SZ`，但需经 `stock_identity_resolver` 做一次校验/兜底（处理 `SH600000`、`600000`、北交所 `.BJ` 等历史脏数据）。统一产出带交易所后缀的 `norm_code`，作为三方 join 的代码键。

2. **交易日键**：
   - 计划↔执行 join：`limit_up_selected_stock.target_trade_date == DATE(qmt_trade.traded_time 转东八区)`，即"这只票的 T+1 买入日"对齐"QMT 实际成交日"。
   - 执行/计划↔结果 join：用 `a_trade_calendar` 把买入日 `B`(=target_trade_date) 映射到 `B`(买入当日结果)、`next_open_date = trade_cal_next(B)`(隔日卖出结果)。打板隔日卖典型为 `B → B 次一交易日` 1 个交易日。

3. **完整归因主键**：`(account_id, norm_code, target_trade_date)`。一只票在某买入日的归因是一行。多笔成交先按该键聚合成"该票当日加权成交均价 + 总成交量"，再参与归因。

4. **buy/sell 配对（已实现盈亏用）**：闭环归因主看"信号→次日兑现"，盈亏既可用**行情盯市口径**（次日 close/卖出基准价 vs 成交价，不依赖真实卖出流水，覆盖率高），也可用**真实已实现口径**（FIFO 撮合 `qmt_trade` 的 buy/sell，依赖隔日真实卖出流水）。两者分列，详见 §3。

### 1.3 join 关系全景

```
limit_up_selected_stock (计划, key=norm_code+target_trade_date)
        │  LEFT JOIN  (计划是否下单)
        ▼
   qmt_order (委托, 同 norm_code+下单日)
        │  LEFT JOIN  (下单是否成交)
        ▼
   qmt_trade (成交, 聚合到 norm_code+成交日, offset_flag=买入)
        │  INNER JOIN (买入日当日行情/可成交性判定)
        ▼
   tencent_unadjusted_daily_quote @ 买入日 B
        │  INNER JOIN via a_trade_calendar (B → 次一交易日)
        ▼
   tencent_unadjusted_daily_quote @ 隔日 B+1  (兑现结果)
```

关键：**计划侧用 LEFT JOIN 起头**，这样"计划买但没买进/没下单"的票不会被 INNER JOIN 丢掉——漏单成本（未成交机会成本）正是闭环归因最值钱的部分，绝不能 join 没了。

---

## 2. 计划 vs 实际（执行漏斗 + 逆向选择量化）

### 2.1 漏斗四级口径

对某一买入日 `B`（= `target_trade_date`）：

| 级别 | 定义 | 来源 |
| --- | --- | --- |
| N 重点候选 | 当日 watchlist 重点候选只数。口径：`limit_up_selected_stock` 中 `target_trade_date=B` 且 `tradable_flag` 标记为"重点/可参与"的行（或按 `leader_strength_score` 取 Top-K，口径在文档固化）。 | 信号侧 |
| M 实际下单 | QMT 当日对这批票真正报过单的只数 = `qmt_order` 中 `norm_code` 命中候选集且下单日=B。 | 执行侧 |
| K 实际成交 | 当日真正买进（`traded_volume>0`）的只数 = `qmt_trade` 买入聚合后 `norm_code` 命中候选集。 | 执行侧 |
| 部分成交 | 下单了但 `traded_volume < order_volume` 的只数（排队未全成）。 | 执行侧 |

漏斗流失指标：
- **下单率** = M / N（候选里有多少真去下单了，反映执行端是否漏挂）。
- **成交率** = K / M（下单里有多少买进了）。
- **整体兑现率** = K / N。
- **买不进只数/比例** = (N − K) / N，并细分原因：
  - `未下单`(N−M)：执行端没挂（系统漏挂/主动放弃）。
  - `一字未成`：下单了但买入日 B 行情 `open == limit_up_price`（一字板，`low==high==limit`），`traded_volume=0`。
  - `秒封未成`：B 日封住涨停（`close==limit_up_price` 且开板时间极短/封单大），挂单未排到。
  - `排队未成/部成`：下单但限价未触及或排队靠后。
  买不进原因判定优先用 `qmt_order.order_status`(废单/已撤/未成) + B 日行情形态，行情形态判定细则见 §5。

### 2.2 逆向选择量化（是不是最强的票没买到）

核心命题：买不进的票，往往是当日**最强**的票（一字/秒封），这会系统性拉低实盘相对信号的兑现——必须量化。

做法：对买入日 B 的候选集，按"信号强度"排序，看**买进组**与**买不进组**的强度分布差异。

- 强度代理：`leader_strength_score`（龙头强度分位）、`continuation_prob`（连板先验）。
- 指标：
  - **强度分位差** = avg(买不进组 `leader_strength_score` 分位) − avg(买进组 分位)。显著 > 0 即存在逆向选择（强的没买到）。
  - **Top 强度命中率** = 买进组里 `leader_strength_score` 排进当日候选 Top-N 的占比，对照候选整体 Top-N 占比。
  - **错失最强单**：当日候选里 `leader_strength_score` 最高的票是否买进；连续多日最强票买不进是强逆向选择信号。
- 同时算"买不进组的次日反事实收益"（§3 盯市口径）对比"买进组真实/盯市收益"，把逆向选择翻译成**钱**：买不进组次日平均涨幅显著高于买进组，说明漏掉的正是肉最多的票。

---

## 3. 信号命中（先验 vs 实际兑现校准）

### 3.1 单票兑现盈亏的两套口径

| 口径 | 公式 | 用途 | 依赖 |
| --- | --- | --- | --- |
| **盯市口径（mark-to-market，主口径）** | 隔日卖出基准价 `P_sell` 相对买入成交均价 `P_buy` 的收益率 = `(P_sell − P_buy)/P_buy`。`P_sell` 默认取隔日 `open`（打板隔日开盘出典型），可配置为隔日 `close` 或隔日均价。`P_buy` = `qmt_trade` 当日买入加权成交均价（买不进的反事实组用 B 日理论涨停价或合理买入价）。 | 覆盖率高、不依赖真实卖出流水，可同时给"买进组"和"买不进反事实组"算收益，是先验校准与逆向选择量化的主口径。 | 仅需买入成交 + 行情 |
| **真实已实现口径（realized）** | FIFO 撮合 `qmt_trade` 的 buy/sell：已实现盈亏 = Σ(卖出额 − 配对买入成本)。 | 与账户对账、真实落袋收益。 | 需隔日真实卖出流水 |

两者并列展示，差异本身就是"实盘卖点 vs 隔日开盘基准"的执行 alpha/损耗。涨停隔日卖、T+1 不可当日卖，已实现只能 T+2 及以后出现，盯市口径填补 T+1 当晚即可复盘的空档。

### 3.2 先验档位 vs 实际命中

信号侧给两个先验概率：`continuation_prob`（次日续板概率先验）、`next_day_premium_prob`（隔日溢价为正概率先验）。校准就是看"先验说的概率档"和"实盘真实发生率"对不对得上。

把先验概率分档（如 `[0,0.2),[0.2,0.4),[0.4,0.6),[0.6,0.8),[0.8,1.0]`），每档内统计：

- **实际续板率** = 该档买进票里隔日真涨停（或真续板）只数 / 该档买进只数。对照档位中值 → 画**校准曲线/可靠性图**（reliability diagram），理想是对角线。
- **实际隔日溢价为正率** = 该档隔日 `open`(或 close) > 买入价的只数占比，对照 `next_day_premium_prob` 档位中值。
- **每档平均隔日收益率**（盯市口径），看先验高档是不是真的收益更高（单调性）。
- 校准误差指标：**ECE（Expected Calibration Error）** = Σ(档内样本占比 × |实际发生率 − 先验档中值|)，一个数概括信号校准好坏。

> 注意"档内样本占比"用买进组算实盘校准；同时用全候选集（含买不进反事实）算"信号本身的校准"，区分**信号准不准**（全候选）与**我们买的票准不准**（买进组）。

### 3.3 分组实盘盈亏对照回测预期

按四个维度分组，每组统计实盘盈亏，对照回测预期：

| 分组维度 | 字段 | 复盘问题 |
| --- | --- | --- |
| 龙头强度分位 | `leader_strength_score` 分位桶 | 强度越高实盘收益越高吗？强度与买不进率的权衡。 |
| 角色 | `role`（如 龙头/中军/补涨/分歧转一致 等口径） | 哪类角色实盘最赚/最容易买不进？ |
| 战法 | `strategy` | 哪套战法实盘兑现最好，对照回测胜率/盈亏比。 |
| 情绪周期 | `market_state`（启动/高潮/震荡/退潮/冰点/空仓） | 是否"在对的周期做对的票"。退潮/冰点期实盘是否该收手。 |

每组输出列：买进只数、成交率、买不进率、实盘平均隔日收益率（盯市）、实盘胜率、实盘盈亏比、对照回测预期收益/胜率的差值（`实盘 − 回测`），高亮系统性偏离组（实盘持续跑输回测的组，多半是滑点+逆向选择吃掉的）。

---

## 4. 滑点归因

三个价格基准，逐级拆解从"信号决策"到"回测假设"再到"实盘成交"的差额（Implementation Shortfall 思路，正负都标，单位 bps 与 元/股）：

| 价格 | 定义 | 来源 |
| --- | --- | --- |
| `P_signal_limit` | 信号侧用 T 日 `signal_close` 算的理论涨停价（主板 ×1.10、创业板 ×1.20，四舍五入到分） | 信号侧 |
| `P_reasonable` | 信号侧给的合理高开区间 `[reasonable_open_high_low, reasonable_open_high_high]`（买入日 B 合理开盘买点区间） | 信号侧 |
| `P_backtest` | 回测假设买入价（口径与回测引擎对齐：一字/秒封不计、否则按 B 日开盘或合理价成交） | 回测口径 |
| `P_actual` | QMT 实际买入加权成交均价 = `qmt_trade` 当日买入 `Σtraded_amount / Σtraded_volume` | 执行侧 |

滑点分解：

- **信号→实盘总滑点** = `(P_actual − P_signal_limit)/P_signal_limit`（实盘比信号侧理论涨停价高买了多少，即追高代价）。
- **合理区间偏离** = `P_actual` 落在 `[P_reasonable_low, P_reasonable_high]` 内/上沿/超出的占比与超出幅度（买太贵的比例）。
- **回测→实盘执行差** = `(P_actual − P_backtest)/P_backtest`（实盘比回测假设差多少，这是回测乐观度的直接度量）。
- 汇总：按分组（§3.3 维度）算平均滑点 bps，定位"哪类票实盘买得最贵"。把"回测→实盘执行差"乘以各组实盘成交量，得到**滑点吃掉的总收益（元）**，与逆向选择漏单成本并列，构成"实盘比回测差多少"的钱口径拆解。

> 注意：滑点只对"买进组"有 `P_actual`。买不进组无成交价，其损耗记在 §2 漏单/逆向选择成本，不混入滑点。

---

## 5. 空仓闸门有效性回看（行情反事实）

命题：`market_state=空仓` 的日子，闸门让我们没买；但如果当时按信号买了会怎样？用行情反事实验证闸门救没救我们。

做法：

1. 取所有 `market_state=空仓` 的 `target_trade_date`，以及当日**本应入选**的候选集（信号侧即使空仓也应落 `limit_up_selected_stock` 候选行，只是闸门把 `tradable_flag`/下单决策关掉；若空仓日不落候选，则退化为"取当日全市场涨停池"做反事实，口径需固化）。
2. 对每只反事实候选，用 §3.1 盯市口径算"假设按 B 日合理价/理论涨停价买入、隔日开盘卖出"的反事实收益率（一字/秒封按买不进不计收益，与回测口径一致）。
3. 闸门有效性指标：
   - **空仓日反事实组合收益率**（等权/按强度加权两种）。显著 < 0 → 闸门有效（避开了亏损）；显著 > 0 → 闸门误杀（错过了机会，需检讨情绪周期判定）。
   - **避损金额** = 反事实亏损 × 假设仓位规模（按当时可用资金或固定仓位口径）。
   - **闸门胜率** = 空仓日里反事实收益为负的天数占比（越高说明越多次正确空仓）。
   - 对照：把空仓日反事实收益和**实际参与日**真实收益放一起，看闸门是否把账户挡在了亏损日之外、留在了赚钱日之内。

> 反事实是"如果买了"的假设，必须明确标注非真实成交，且与真实业绩物理分区展示，避免误读为实际亏损/收益。

---

## 6. 归因 SQL 思路（不落最终 SQL，给可落地骨架）

所有计算建议落成**只读视图 + 物化归因表**两层：盘后批处理把当日闭环归因算好写入 `qmt_signal_attribution_daily`（一股一买入日一行），页面只读该表 + 轻量视图聚合，避免页面实时跑多表 join。

### 6.1 代码归一 CTE

```sql
-- 思路：先把三方代码统一成带交易所后缀的 norm_code
WITH norm_signal AS (
  SELECT s.*, resolve_norm_code(s.ts_code) AS norm_code   -- 借 stock_identity_resolver 逻辑
  FROM limit_up_selected_stock s
  WHERE s.target_trade_date = :B
),
trade_agg AS (   -- 多笔成交聚合到 票×买入日，只取买入方向
  SELECT resolve_norm_code(t.stock_code) AS norm_code,
         DATE(CONVERT_TZ(t.traded_time,'+00:00','+08:00')) AS buy_date,  -- UTC naive→东八区
         SUM(t.traded_volume) AS buy_vol,
         SUM(t.traded_amount) AS buy_amt,
         SUM(t.traded_amount)/NULLIF(SUM(t.traded_volume),0) AS p_actual  -- 加权成交均价
  FROM qmt_trade t
  WHERE t.offset_flag = :BUY_FLAG
  GROUP BY 1,2
)
```

### 6.2 计划漏斗（LEFT JOIN 起头，保住漏单）

```sql
SELECT ns.norm_code, ns.leader_strength_score, ns.continuation_prob,
       (o.order_id IS NOT NULL) AS placed,        -- 是否下单
       COALESCE(ta.buy_vol,0) > 0  AS filled,     -- 是否成交
       ta.p_actual
FROM norm_signal ns
LEFT JOIN qmt_order o
  ON o.norm_code = ns.norm_code AND o.order_date = ns.target_trade_date
LEFT JOIN trade_agg ta
  ON ta.norm_code = ns.norm_code AND ta.buy_date = ns.target_trade_date;
-- N=count(*), M=sum(placed), K=sum(filled)，买不进=NOT filled
```

### 6.3 次日结果 join（经交易日历映射隔日）

```sql
-- 买入日 B 行情（判一字/秒封）+ 隔日 B1 行情（兑现）
LEFT JOIN tencent_unadjusted_daily_quote qB
  ON qB.ts_code = ns.norm_code AND qB.trade_date = ns.target_trade_date
LEFT JOIN ( -- 交易日历取 B 的下一交易日
  SELECT cal_date, LEAD(cal_date) OVER (ORDER BY cal_date) AS next_open
  FROM a_trade_calendar WHERE is_open = 1
) cal ON cal.cal_date = ns.target_trade_date
LEFT JOIN tencent_unadjusted_daily_quote qB1
  ON qB1.ts_code = ns.norm_code AND qB1.trade_date = cal.next_open;
-- 盯市收益 = (qB1.open - p_actual)/p_actual （买进组）
-- 反事实收益 = (qB1.open - 合理买入价)/合理买入价 （买不进/空仓反事实组）
-- 一字判定：qB.low = qB.high（且=涨停价）→ 反事实不计收益
```

### 6.4 先验校准与分组（写入物化表后聚合）

```sql
-- 先验校准：按 continuation_prob 分档，对照实际续板率
SELECT prob_bucket(continuation_prob) AS bucket,
       COUNT(*) AS n,
       AVG(continuation_prob) AS prior_mid,
       AVG(CASE WHEN next_day_limit_up THEN 1 ELSE 0 END) AS actual_rate
FROM qmt_signal_attribution_daily
WHERE filled = 1
GROUP BY 1;

-- 分组实盘 vs 回测：按 market_state / role / strategy / 强度分位
SELECT market_state,
       AVG(mark_to_market_ret) AS real_ret,
       AVG(win_flag) AS real_win_rate,
       AVG(backtest_expected_ret) AS bt_ret,
       AVG(mark_to_market_ret) - AVG(backtest_expected_ret) AS gap
FROM qmt_signal_attribution_daily
GROUP BY market_state;
```

### 6.5 建议落库表 `qmt_signal_attribution_daily`（一股一买入日一行）

字段族（具体 DDL 在落地阶段写迁移 + `03_full_schema_with_comments.sql` 同步）：

- 主键/关联：`account_id`、`norm_code`、`target_trade_date`（信号买入日）、`signal_trade_date`(T)。
- 信号侧快照：`leader_strength_score`、`leader_strength_pctl`、`role`、`strategy`、`market_state`、`tradable_flag`、`continuation_prob`、`next_day_premium_prob`、`signal_close`、`limit_up_price`、`reasonable_open_high_low/high`。
- 执行侧：`placed`(是否下单)、`filled`(是否成交)、`order_volume`、`buy_volume`、`p_actual`(加权成交均价)、`miss_reason`(未下单/一字/秒封/排队未成/部成)。
- 结果侧：`buy_date_open/high/low/close`、`next_open_date`、`next_open/high/low/close`、`next_day_limit_up`(隔日是否续板)、`mark_to_market_ret`(盯市收益)、`realized_ret`(真实已实现，可空)。
- 滑点：`slippage_vs_signal_bps`、`slippage_vs_backtest_bps`、`reasonable_zone_flag`。
- 反事实：`is_counterfactual`(空仓/买不进反事实标记)、`counterfactual_ret`。
- 审计：`backtest_expected_ret`、`computed_at`(UTC naive)。

时间口径：`traded_time`/`order_time` 为时间戳 → `CONVERT_TZ(...,'+00:00','+08:00')` 取东八区交易日；`computed_at` 用 `datetime.now(UTC).replace(tzinfo=None)` 入库 UTC naive，前端 `formatEast8DateTime` 展示；`target_trade_date` 等 `DATE` 字段本身即东八区交易日，不做时区换算。

---

## 7. 页面呈现

三屏组织，对应"执行—信号—闸门"：

### 7.1 计划漏斗（执行有效性）

- 顶部漏斗图：`N 重点候选 → M 实际下单 → K 实际成交`，每级标只数 + 流失率（下单率/成交率/整体兑现率）。
- 漏斗下方"买不进明细表"：列出 N−K 只未成交票，标 `miss_reason`、`leader_strength_score` 分位、买入日行情形态、反事实隔日涨幅；按强度倒序，最强买不进的票置顶。
- **逆向选择卡片**：买进组 vs 买不进组的平均强度分位、Top 强度命中率、两组反事实/真实隔日平均涨幅对比（一句话结论："最强的 X 只票里买进了 Y 只，漏掉的次日平均 +Z%"）。

### 7.2 分组对照表 + 先验 vs 实际校准图（信号有效性）

- **分组对照表**：行=分组（可切换 龙头强度分位/角色/战法/情绪周期），列=买进只数、成交率、买不进率、实盘隔日收益(盯市)、实盘胜率、盈亏比、回测预期、实盘−回测 gap；gap 为负且显著的组红色高亮。
- **校准图（reliability diagram）**：x=先验档位中值（`continuation_prob`/`next_day_premium_prob`），y=实际发生率，叠加 y=x 对角线；点在对角线下方=先验偏乐观。同屏给 ECE 数值。买进组与全候选集两条曲线对照（"我们买的票" vs "信号本身"）。
- 每档平均隔日收益柱状图，验证高先验档是否真的高收益（单调性）。

### 7.3 滑点与闸门（价格与风控有效性）

- **滑点瀑布图**：`P_signal_limit → P_backtest → P_actual` 逐级差额（bps + 元/股 + 总金额），并按分组看哪类票买得最贵。
- **空仓闸门回看面板**：空仓日列表，每日反事实组合收益率（等权/强度加权），闸门胜率、累计避损金额；空仓日反事实收益 vs 实际参与日真实收益对照折线，直观看闸门是否挡在亏损日外。所有反事实数据加"假设未成交"水印/灰底，物理区隔真实业绩。

### 7.4 时间维度

- 默认"当日"视图（单一 `target_trade_date`）+ "历史区间"视图（按交易日聚合，看校准/逆向选择/滑点随时间的趋势）。
- 区间统计 win rate/盈亏比/校准 ECE 的滚动曲线，识别信号或执行是否在退化。

---

## 8. 阶段与验收

> 按 CLAUDE.md 约束，只按阶段+任务划分、给验收标准与依赖顺序，不含工期/工时预估。

### 阶段 P0：关联键与归因数据底座（依赖：`limit_up_selected_stock`、`qmt_trade`/`qmt_order` 已落表）

- 任务：实现代码归一逻辑（三方 `norm_code` 统一，复用/对齐 `stock_identity_resolver`）；实现 `traded_time` 时间戳→东八区交易日映射；建 `qmt_signal_attribution_daily` 表（迁移 + 模型 + `03_full_schema_with_comments.sql` + `database-schema.md` 同步）。
- 验收：给定一个买入日，能产出该日全部候选的归因行；计划侧 LEFT JOIN 不丢任何买不进票；代码归一对 `.SH/.SZ/.BJ`、无后缀、`SH` 前缀脏数据全部命中；时间字段东八区交易日与 `a_trade_calendar` 一致。

### 阶段 P1：计划 vs 实际漏斗 + 逆向选择（依赖：P0）

- 任务：实现漏斗四级口径与买不进原因判定（结合 `order_status` + 买入日行情形态）；实现逆向选择量化（强度分位差、Top 强度命中率、错失最强单、买进/买不进两组反事实收益对比）。
- 验收：N/M/K 与 QMT 当日委托/成交流水手工核对一致；一字/秒封判定与买入日行情形态一致；逆向选择卡片在构造的"最强票一字买不进"样例上给出正向逆向选择信号。

### 阶段 P2：信号命中校准 + 分组对照（依赖：P0、且结果侧 `tencent_unadjusted_daily_quote` 隔日行情可得）

- 任务：实现盯市与真实已实现两套盈亏口径；先验分档校准（续板率、隔日溢价为正率、ECE、reliability diagram 数据）；四维分组对照表与实盘−回测 gap。
- 验收：盯市收益 = `(隔日open − 加权成交均价)/加权成交均价` 精确可复算；校准曲线在样例数据上正确落点；分组聚合只数与明细行汇总一致；买进组与全候选集两条校准曲线分别正确。

### 阶段 P3：滑点归因（依赖：P0、P2）

- 任务：实现三基准价计算（理论涨停价、合理高开区间、回测假设价）与三段滑点分解（信号→实盘、合理区间偏离、回测→实盘），分组滑点均值与滑点吃掉的总收益（元）。
- 验收：理论涨停价按主板/创业板规则与四舍五入到分正确；`P_actual` 与成交流水加权均价一致；回测→实盘执行差与回测引擎假设买入价口径对齐、可对账。

### 阶段 P4：空仓闸门反事实回看（依赖：P0、P2；需确认空仓日是否落候选行）

- 任务：固化空仓日反事实候选口径；实现反事实收益、闸门胜率、累计避损金额；反事实与真实业绩物理区隔展示。
- 验收：反事实一字/秒封不计收益与回测口径一致；空仓日反事实收益与实际参与日真实收益分区无混算；反事实数据全部带"假设未成交"标注。

### 阶段 P5：页面呈现（依赖：P1–P4 对应数据就绪）

- 任务：实现计划漏斗屏、分组对照表 + 校准图屏、滑点瀑布 + 闸门面板屏；当日/历史区间切换；时间统一 `formatEast8DateTime` 展示。
- 验收：三屏指标与后端归因表数值一致；买不进明细可下钻到单票；反事实数据有视觉区隔；历史区间趋势曲线随日期范围正确刷新。

---

## 9. 关键口径约束（落地前必须固化，避免歧义）

- **隔日卖出基准价 `P_sell`**：默认隔日 `open`，可配 `close`/隔日均价；一旦选定全页统一，文档固化。
- **"重点候选 N"口径**：`tradable_flag` 标记 vs `leader_strength_score` Top-K，二选一并固化；空仓日是否落候选行决定 §5 反事实是否退化为全市场涨停池。
- **买不进原因判定阈值**：一字（`low==high==涨停价`）、秒封（封住涨停且开板时长/封单阈值）的具体阈值需按战法定义并写入文档。
- **盈亏成本法**：真实已实现口径用 FIFO 还是移动加权，必须与 QMT/券商对账单一致，否则部分平仓中间值对不上账。
- **滑点决策价二选一不混用**：信号决策价（全链路损耗，含延迟）与下单到达价（QMT 纯执行质量）分开标注，本文闭环归因主用"信号侧理论价/合理价 vs 实盘成交价"全链路口径。
- **反事实非真实**：所有反事实（买不进、空仓）收益必须标注"假设未成交"，与真实业绩物理分区，禁止并入真实盈亏汇总。
- **回测对账口径**：`backtest_expected_ret`、回测假设买入价必须与回测引擎同口径（不复权、一字/秒封不计、T→T+1 交易日历映射），否则"实盘 vs 回测 gap"失真。
