# 打板报告多轮分析与筹码补数改造计划

更新日期：2026-06-05

## 1. 背景与目标

当前打板推送模块在 KPL 数据就绪后，将涨停池、连板天梯、题材、龙虎榜和短窗口技术指标一次性组装为 `context`，再调用一次 LLM 生成完整 HTML 报告。该方式实现简单，但在涨停股数量较多时，首板、两连、三连、高连板和原始补充数据会同时进入上下文，容易造成上下文过大、重点稀释和模型分析不稳定。

本次改造目标是把打板报告从“单轮大上下文分析”升级为“多轮分层分析 + LLM 挑选重点股票 + Tushare 筹码接口回调补数 + 最终汇总报告”。改造后仍保留现有 KPL 数据就绪判断、报告缓存、PushPlus 推送、分享链接和雪球发布读取最终报告的主流程，只调整报告生成内部流水线。

## 2. 需求口径

- 首板不做大篇幅逐股分析，只在独立轮次总结题材发酵价值、首板扩散方向和需要观察的题材线索。
- 两连、三连股票进入重点分析候选池；若两连和三连合计不超过 20 只，允许全部进入筹码补数和重点分析，也允许 LLM 剔除明显弱票。
- 若两连和三连合计超过 20 只，由 LLM 按板块龙头、题材前排、连板状态、封板质量、资金信号和辨识度筛选，最多保留 20 只。
- 高连板部分也允许 LLM 挑选分析和推荐；高连板候选来自四连及以上、空间板、题材龙头和高辨识度个股。
- 高连板若数量不多可全量分析；若数量较多，建议最多筛选 10 只进入重点分析，数量通过配置项控制。
- 对 LLM 选中的两连、三连和高连板重点股票，按需调用 Tushare 每日筹码及胜率、每日筹码分布接口进行补数。
- 两连、三连和高连板重点分析不只判断连板可能性，也要补充下一个 A 股交易日的溢价可能性、触发条件、失败条件和风险提示。
- 最终报告由多个阶段分析结果汇总生成，包含市场情绪、首板题材、两连三连重点观察、高连板与龙头、次日溢价观察、反证信号和最后总结。

## 3. 官方接口依据

### 3.1 `cyq_perf` 每日筹码及胜率

- 官方文档：https://tushare.pro/document/2?doc_id=293
- 接口名：`cyq_perf`
- 输入参数：`ts_code` 必填，`trade_date`、`start_date`、`end_date` 可选。
- 关键输出：`trade_date`、`his_low`、`his_high`、`cost_5pct`、`cost_15pct`、`cost_50pct`、`cost_85pct`、`cost_95pct`、`weight_avg`、`winner_rate`。
- 业务用途：判断获利盘比例、筹码成本中枢、上方压力区和短线接力的筹码友好度。

### 3.2 `cyq_chips` 每日筹码分布

- 官方文档：https://tushare.pro/document/2?doc_id=294
- 接口名：`cyq_chips`
- 输入参数：`ts_code` 必填，`trade_date`、`start_date`、`end_date` 可选。
- 关键输出：`trade_date`、`price`、`percent`。
- 业务用途：压缩成筹码压力摘要，不直接把所有原始价格分布行塞给 LLM；用于判断现价上方筹码压力、筹码集中度和次日溢价阻力。

## 4. 总体架构

改造后的报告生成流水线如下。

```text
基础打板数据快照
  -> 首板题材发酵分析
  -> 两连/三连候选选择
  -> 高连板候选选择
  -> cyq_perf + cyq_chips 按需补数
  -> 两连/三连重点分析
  -> 高连板与龙头重点分析
  -> 最终报告合成
  -> 缓存、推送、分享和雪球发布复用现有链路
```

`LimitUpPushService.ensure_analysis_for_trade_date()` 保持为外部入口。内部将原 `_generate_llm_report(context)` 拆为一个 pipeline 编排方法，例如 `_generate_multi_stage_llm_report(context)`，由该方法负责多轮调用、补数、阶段缓存和最终 HTML 合成。

## 5. 数据分层

基础上下文仍由现有 KPL、涨停榜、连板天梯、最强板块、龙虎榜、本地日线和每日指标组成，但进入 LLM 前要拆分为更小的子上下文。

### 5.1 `first_board_context`

数据范围：

- KPL 中状态为首板或可识别为一板的股票。
- 题材聚合结果。
- 代表股、涨停原因、封板时间和基础强弱字段。

分析目标：

- 总结题材扩散方向。
- 判断首板是否具备后续发酵价值。
- 输出题材级结论，不展开大量个股。

### 5.2 `chain_board_context`

数据范围：

- 两连、三连股票。
- 题材、涨停原因、封板状态、封单、换手、龙虎榜资金信号、短窗口技术指标。

分析目标：

- 先由 LLM 筛选最多 20 只重点候选。
- 再对重点候选补充筹码数据。
- 判断晋级三板、四板的可能性和下一个交易日溢价可能性。

### 5.3 `high_board_context`

数据范围：

- 四连及以上股票。
- 空间板、题材龙头、高辨识度个股。
- 题材梯队和资金信号。

分析目标：

- 由 LLM 挑选高连板重点标的，建议最多 10 只。
- 可对重点高连板同样补充筹码数据。
- 判断空间板地位、分歧承接、题材带动性、高位断板风险和是否适合继续接力观察。

### 5.4 `market_context`

数据范围：

- 涨停数量、二连数量、三连数量、最高连板、连板天梯数量。
- 题材排名、最强板块、龙虎榜整体资金信号。
- 数据质量记录。

分析目标：

- 为最终报告提供情绪周期、市场强弱和风险基调。

## 6. 多轮 LLM 节点

### 6.1 首板题材分析节点

输入：`first_board_context`、`market_context` 的轻量摘要。

输出建议使用结构化 JSON：

```json
{
  "html_fragment": "<h3>首板题材发酵</h3>...",
  "theme_candidates": [
    {
      "theme": "题材名称",
      "representative_stocks": ["股票A", "股票B"],
      "fermentation_value": "强/中/弱",
      "reason": "题材发酵理由"
    }
  ],
  "risk_flags": ["风险提示"]
}
```

容错规则：如果 JSON 解析失败，保留模型原始文本作为 `html_fragment`，`theme_candidates` 置空，并在阶段数据质量中记录 `PARSE_FALLBACK`。

### 6.2 两连三连候选选择节点

输入：`chain_board_context` 的两连、三连精简行。

输出必须是 JSON，最多 20 只：

```json
{
  "selected_stocks": [
    {
      "ts_code": "000001.SZ",
      "name": "示例股份",
      "board_status": "2连板",
      "theme": "人工智能",
      "theme_role": "板块前排/龙头/跟风",
      "selection_reason": "入选理由",
      "priority": 1
    }
  ],
  "excluded_summary": "未入选股票的主要原因"
}
```

筛选原则：

- 两连、三连合计不超过 20 只时，可以全部入选，但仍允许剔除明显弱票。
- 超过 20 只时，必须筛选到 20 只以内。
- 优先板块龙头、题材前排、封板质量更好、资金信号更强、辨识度更高、连板状态更清晰的股票。

容错规则：如果 LLM 未返回合法 JSON，服务层按连板高度、题材热度、龙虎榜净买额、封板状态和技术指标做确定性排序，截取前 20 只。

### 6.3 高连板候选选择节点

输入：`high_board_context`。

输出必须是 JSON，默认最多 10 只：

```json
{
  "selected_stocks": [
    {
      "ts_code": "000001.SZ",
      "name": "示例股份",
      "board_status": "5连板",
      "theme": "人工智能",
      "leader_role": "空间板/题材龙头/高辨识度",
      "selection_reason": "入选理由",
      "risk_level": "高/中/低"
    }
  ],
  "high_board_cycle_view": "高连板周期判断"
}
```

筛选原则：

- 关注四连及以上、空间板、题材龙头和带动梯队的股票。
- 高连板推荐必须显著提示高位接力风险、断板风险和流动性风险。
- 输出允许分为“重点观察”“谨慎观察”“放弃观察”。

### 6.4 筹码补数节点

输入：两连三连候选 + 高连板候选去重后的股票列表。

调用策略：

- 只对 LLM 选中的候选股票调用 `cyq_perf` 和 `cyq_chips`。
- 查询窗口建议为交易日前最近 20 个自然日，后续可通过配置调整。
- 单股接口失败不阻塞整份报告，失败股票继续使用原有行情和技术指标分析。
- 接口失败、权限不足、空数据和截断情况写入 `data_quality`。

输出不直接暴露原始 `cyq_chips` 全量行，而是压缩为：

```json
{
  "ts_code": "000001.SZ",
  "cyq_perf_latest": {
    "trade_date": "2026-06-04",
    "winner_rate": 63.2,
    "weight_avg": 12.34,
    "cost_50pct": 12.1,
    "cost_85pct": 13.2,
    "cost_95pct": 13.8
  },
  "cyq_summary": {
    "winner_rate_trend": "上升/下降/稳定/缺失",
    "close_to_weight_avg_pct": 3.5,
    "upper_chip_pressure_pct": 28.4,
    "chip_concentration": "集中/分散/缺失",
    "next_day_premium_bias": "偏友好/中性/压力较大/缺失",
    "summary": "筹码摘要"
  }
}
```

### 6.5 两连三连重点分析节点

输入：候选股票基础数据、技术指标、资金信号、筹码摘要。

输出要求：

- 分别覆盖两连和三连。
- 给出晋级条件、失败条件和次日溢价判断。
- 用表格展示核心观察字段。
- 对明显弱势或筹码压力较大的股票给出谨慎或放弃观察理由。

### 6.6 高连板与龙头分析节点

输入：高连板候选、题材梯队、资金信号、筹码摘要、市场情绪。

输出要求：

- 判断空间板地位和题材带动性。
- 识别高位分歧承接、断板风险和情绪退潮信号。
- 允许给出重点观察/谨慎观察/放弃观察的推荐分层。
- 不得把高连板接力写成低风险建议。

### 6.7 最终报告合成节点

输入：各阶段结构化摘要和 HTML 片段，不再输入全部原始涨停池。

最终报告建议结构：

1. 市场情绪概览。
2. 首板题材发酵价值。
3. 两连三连重点观察与次日溢价判断。
4. 高连板与龙头接力观察。
5. 反证信号和风险提示。
6. 最后总结。

最终输出仍为纯 HTML 片段，继续适配 PushPlus、后台预览、公开分享和雪球长文转换。

## 7. 配置项建议

新增配置项：

```text
LIMIT_UP_PUSH_CHAIN_FOCUS_STOCK_LIMIT=20
LIMIT_UP_PUSH_HIGH_BOARD_FOCUS_STOCK_LIMIT=10
LIMIT_UP_PUSH_CYQ_LOOKBACK_DAYS=20
LIMIT_UP_PUSH_STAGE_CACHE_ENABLED=true
LIMIT_UP_PUSH_FINAL_PROMPT_VERSION=limit-up-multi-stage-v1
```

配置口径：

- `CHAIN_FOCUS_STOCK_LIMIT` 控制两连、三连重点候选总上限，默认 20。
- `HIGH_BOARD_FOCUS_STOCK_LIMIT` 控制高连板重点候选上限，默认 10。
- `CYQ_LOOKBACK_DAYS` 控制筹码接口查询窗口。
- `STAGE_CACHE_ENABLED` 控制阶段缓存是否启用。
- `FINAL_PROMPT_VERSION` 用于区分新旧报告生成口径，避免与现有单轮报告缓存混用。

## 8. 缓存与数据模型

### 8.1 主报告缓存

继续使用 `limit_up_analysis_cache` 保存最终报告和最终上下文摘要。

建议调整：

- `prompt_version` 使用新版本，例如 `limit-up-multi-stage-v1`。
- `context_json` 保存 pipeline 摘要、阶段输出索引、入选股票列表和数据质量，不再保存过大的全量原始上下文。
- `data_snapshot_hash` 应覆盖基础打板数据、候选选择结果、补数摘要和阶段提示词版本。

### 8.2 阶段缓存表

建议新增 `limit_up_analysis_stage_cache`：

| 字段 | 说明 |
| --- | --- |
| `id` | 自增主键 |
| `analysis_id` | 可为空；最终主报告创建后回填 |
| `trade_date` | A 股交易日 |
| `stage_key` | `FIRST_BOARD`、`CHAIN_SELECTION`、`HIGH_BOARD_SELECTION`、`CYQ_SUPPLEMENT`、`CHAIN_FOCUS`、`HIGH_BOARD_FOCUS`、`FINAL_REPORT` |
| `model` | 阶段调用模型 |
| `prompt_version` | 阶段提示词版本 |
| `input_hash` | 阶段输入哈希 |
| `status` | `PENDING`、`GENERATING`、`READY`、`FAILED` |
| `output_json` | 结构化输出 |
| `content_html` | 阶段 HTML 片段 |
| `error_message` | 失败摘要 |
| `generated_at` | 生成完成时间 |

唯一键建议：

```text
trade_date + stage_key + model + prompt_version + input_hash
```

### 8.3 筹码补数缓存表

可选新增 `limit_up_stock_supplement_cache`：

| 字段 | 说明 |
| --- | --- |
| `id` | 自增主键 |
| `trade_date` | 报告交易日 |
| `ts_code` | 股票代码 |
| `start_date` | 筹码窗口开始日期 |
| `end_date` | 筹码窗口结束日期 |
| `cyq_perf_json` | `cyq_perf` 原始或精简数据 |
| `cyq_chips_summary_json` | `cyq_chips` 压缩摘要 |
| `data_quality_json` | 单股补数质量 |
| `status` | `READY`、`PARTIAL`、`FAILED` |

唯一键建议：

```text
trade_date + ts_code + start_date + end_date
```

如果希望先降低迁移规模，第一版也可以只把筹码摘要保存在阶段缓存中，不单独落补数缓存表；但生产上建议独立缓存，便于失败重试和排查。

## 9. 幂等与异常处理

- KPL 仍是数据就绪硬条件，`kpl_list` 无数据时不生成报告。
- 辅助接口、筹码接口失败不阻断最终报告，但必须写入 `data_quality`。
- 阶段 LLM 失败时，当前报告状态置为 `FAILED`，保留已完成阶段缓存，后续重跑从失败阶段继续。
- 阶段 JSON 解析失败时，优先走确定性兜底，而不是直接放弃报告。
- 两连三连候选和高连候选去重后再补数，避免同一股票重复调用 Tushare。
- 同一阶段相同输入哈希命中缓存时，不重复调用 LLM。
- 同一股票相同筹码窗口命中补数缓存时，不重复调用 Tushare。
- 最终推送仍复用 `limit_up_push_delivery` 的业务唯一键，避免重复发送。

## 10. 实施步骤

### 10.1 后端阶段

1. 重构上下文构建：在现有 `_assemble_context()` 基础上拆出首板、两连三连、高连板和市场摘要。
2. 新增阶段提示词和阶段调用封装：支持 HTML 文本阶段和严格 JSON 阶段。
3. 新增 JSON 解析与兜底筛选：两连三连最多 20 只，高连板最多 10 只。
4. 新增筹码补数方法：封装 `cyq_perf`、`cyq_chips` 调用和压缩摘要计算。
5. 新增多轮 pipeline 编排：首板分析、候选选择、补数、重点分析、高连分析、最终合成。
6. 新增阶段缓存和可选筹码补数缓存模型、Alembic 迁移和 SQL 注释版更新。
7. 调整 `limit_up_analysis_cache` 写入内容：最终报告保持原字段，`context_json` 保存 pipeline 摘要。
8. LLM 指标记录继续使用 `phase="limit_up_analysis"`，可在 `conversation_title` 或 payload 中区分 stage。

### 10.2 前端阶段

1. 报告详情弹窗继续展示最终 HTML 和源码。
2. 详情中增加阶段数据质量摘要，例如“首板分析、两连三连筛选、筹码补数、高连分析、最终合成”。
3. 展示两连三连入选名单和高连板入选名单，便于管理员核对 LLM 为什么分析这些票。
4. 推送、分享和雪球发布入口不改变。

### 10.3 文档阶段

1. 更新 `resources/doc/limit-up-llm-push-design.md`，说明报告生成已升级为多轮 pipeline。
2. 更新 `resources/doc/development-progress.md`，记录实施进度和验证结果。
3. 更新 `resources/sql/03_full_schema_with_comments.sql`，补充新表 DDL 注释。
4. 如新增环境变量，更新 `backend/.env.example` 和服务器部署说明。

## 11. 测试计划

后端单元测试：

- KPL 缺失时仍不生成报告。
- 首板、两连、三连、高连板分组正确。
- 两连三连数量超过 20 时，LLM 候选结果被限制到 20 只以内。
- 两连三连 LLM JSON 解析失败时，确定性兜底筛选生效。
- 高连板数量超过配置上限时，LLM 或兜底筛选结果不超过上限。
- 高连板分析输出允许推荐分层，但必须包含高位风险提示。
- 只对入选候选调用 `cyq_perf` 和 `cyq_chips`。
- `cyq_chips` 原始分布可压缩为筹码压力摘要，不把大原始行直接塞进最终报告。
- 单股筹码接口失败时，最终报告仍生成，数据质量标记为 `PARTIAL` 或 `FAILED`。
- 阶段缓存命中后不重复调用 LLM。
- 补数缓存命中后不重复调用 Tushare。
- 最终报告仍写入 `limit_up_analysis_cache`，状态为 `READY`。
- PushPlus 手动推送、周末复推和分享链接继续读取最终报告。

前端验证：

- 报告列表正常展示新版本报告。
- 完整报告预览和源码查看正常。
- 阶段质量摘要和候选名单展示正常。
- 手动生成、手动推送、分享链接不受影响。

建议执行：

```bash
backend/.venv/bin/python -m compileall app tests/test_limit_up_push_service.py
backend/.venv/bin/pytest tests/test_limit_up_push_service.py
npm --prefix frontend run build
```

如涉及真实 Tushare 和真实 LLM 验收，应先由用户确认后再执行。

## 12. 风险与取舍

- 多轮 LLM 会增加调用次数和耗时，需要依赖阶段缓存降低重复成本。
- `cyq_chips` 原始行可能较大，必须压缩后再送入 LLM。
- LLM 选股存在不稳定性，必须提供确定性兜底筛选，避免 JSON 异常导致报告失败。
- 高连板推荐具有更高风险，提示词和最终报告必须显著提示高位接力、断板和流动性风险。
- 阶段缓存会增加表结构复杂度，但能显著提升失败重试和排查能力。
- 第一版可以先实现阶段缓存，补数缓存按复杂度决定是否同步落表；若真实运行发现 Tushare 调用压力大，再补独立补数缓存表。

## 13. 验收标准

- 涨停数量较多时，最终报告不再直接依赖单次超大上下文。
- 首板只输出题材发酵简述，不占用过多报告篇幅。
- 两连三连最多 20 只进入重点补数和分析。
- 高连板可由 LLM 挑选并给出重点观察、谨慎观察或放弃观察推荐。
- 入选股票能使用 `cyq_perf` 和 `cyq_chips` 的筹码摘要辅助判断。
- 报告同时覆盖连板可能性和下一个交易日溢价可能性。
- 最终 HTML 报告可正常预览、推送、分享和进入雪球发布链路。
- 阶段失败可定位，重跑不会无意义重复所有已完成阶段。
