# 打板推送模块涨停分析逻辑评审与改进落地方案

- 创建日期：2026-06-10
- 评审对象：`backend/app/services/limit_up_push_service.py`（2544 行）、`backend/app/jobs/limit_up_push_jobs.py`
- 评审目标：对涨停数据采集、上下文分层、多阶段 LLM 分析和推送链路做代码评审，并结合 A 股打板（涨停接力）实战知识，给出整体逻辑与 Prompt 的改进建议和落地步骤。
- 结论概览：当前六阶段管道（首板题材 → 两三连筛选 → 高连板筛选 → 筹码补数 → 重点分析 → 最终合成）结构清晰、缓存和兜底完整；但存在 **快照哈希不稳定导致重复生成/重复推送** 的 P0 风险、**涨停池可能混入炸板/跌停行** 的口径风险，且情绪周期分析缺少“昨日对照”这一打板复盘的核心维度。

---

## 一、代码问题清单（按优先级）

### P0-1 快照哈希不稳定，可能造成同一交易日重复调 LLM、重复推送

**位置**：`ensure_analysis_for_trade_date`、`_snapshot_hash`、`_build_context_snapshot`

**问题**：
- `_snapshot_hash` 对整个 context 做 `json.dumps(sort_keys=True)` 后取 SHA256。`sort_keys` 只排序 dict 键，**不排序 list 元素**。Tushare 同一接口两次调用返回的行序可能不同（分页、上游排序不保证稳定），行序变化 → 哈希变化。
- 早盘任务在 8–9 点每隔几分钟轮询一次（`limit_up_push_poll_hours=8-9`）。第一轮生成并推送 READY 报告后，若后续轮询时任一接口行序变化或数据被上游修订，`_analysis_for_snapshot` 按新哈希查不到旧记录，会**新建一份分析、完整重跑 LLM 管道，并产生新的 delivery 流水再次推送给所有接收人**——`_get_or_create_delivery` 的幂等键包含 `analysis_id`，跨 analysis 无法去重。

**修复方案**：
1. 在 `ensure_latest_analysis_and_push` 中，构建快照前先查 `_latest_ready_analysis(trade_date)`；当日已有 READY 报告（同 model + prompt_version）则直接复用并走 `push_report`（推送流水本身幂等，已发送的会跳过），不再重建快照。需要强制重算时走手动接口并显式传 `force=True`。
2. `_snapshot_hash` 入参先做**规范化**：各 list 按稳定键排序（如 `(ts_code, trade_date)`、题材名），再序列化。这样即使保留“数据变化才重算”的语义，也不会被行序扰动。
3. （可选）delivery 幂等键从 `analysis_id` 改为 `trade_date + scheduled_kind + user_id`，从数据库层面杜绝同一交易日同一计划的重复推送。需要 alembic 迁移调整唯一索引。

### P0-2 涨停池口径未过滤炸板/跌停，情绪统计被污染

**位置**：`_build_context_snapshot`（`kpl_list` 调用未传 `tag` 过滤）、`_market_emotion`

**问题**：
- Tushare `kpl_list` 不传 `tag` 时可能同时返回涨停、炸板、跌停、自然涨停回封等多类行，当前把全部行当作“涨停池”喂给后续所有阶段（题材聚合、首板/连板分层、LLM 上下文）。
- `_market_emotion.limit_up_count` 用 `"板" in value or "涨停" in value` 统计，“炸板”同样包含“板”，会被计入涨停数；`second_board_count` 用 `"2" in value and "连" in value`，“12连板”会同时被计入二连，统计口径失真。

**修复方案**：
1. `kpl_list` 调用显式传 `tag="涨停"`（或拉全量后按 `status`/`tag` 字段拆分为 `limit_up_rows`、`broken_rows`、`limit_down_rows` 三个池）。**建议拆池而非丢弃**：炸板池是计算炸板率的必要输入（见二-1）。
2. `_market_emotion` 全部改用 `_board_level` 与显式状态枚举统计，废弃子串匹配：二连数 = `board_level == 2` 的行数，依此类推。
3. `_board_level` 增强：兼容“N天M板”格式（取 M 作为板数），无法识别时返回 0 并单列“未识别层级”而不是默认按首板处理，避免高板股被误归入首板上下文。

### P1-1 GENERATING 状态无超时恢复，进程崩溃后当日报告永久卡死

**位置**：`ensure_analysis_for_trade_date`（`existing.status == GENERATING` 直接 return）

**问题**：LLM 多阶段全程可能耗时十几分钟；若进程在生成中途崩溃，记录停留在 GENERATING，后续每轮轮询都直接返回该记录并跳过推送，当日报告永远不会完成。

**修复方案**：判断 GENERATING 记录的 `updated_at` 距今超过阈值（建议 30 分钟，配置化为 `LIMIT_UP_PUSH_GENERATING_STALE_MINUTES`）时视为僵死，走 `_reset_analysis_for_retry` 重跑。阶段缓存（`LimitUpAnalysisStageCache`）已按输入哈希命中，重跑只补失败的阶段，成本可控。

### P1-2 文本阶段无兜底，任一失败导致整份报告 FAILED

**位置**：`_run_text_stage`（对比 `_run_json_stage` 有 fallback_payload）

**问题**：CHAIN_FOCUS、HIGH_BOARD_FOCUS、FINAL_REPORT 三个文本阶段任何一次 LLM 调用异常都会向上抛出，整份分析标记 FAILED，当日早盘推送窗口内可能反复失败。

**修复方案**：
- CHAIN_FOCUS / HIGH_BOARD_FOCUS 失败时降级为确定性 HTML 片段（用 `selection` 里的入选理由 + 筹码摘要拼表格，标注“LLM 重点分析不可用”），不阻断最终合成。
- FINAL_REPORT 是唯一不可降级的阶段，保留抛错，但依赖 P1-1 的僵死恢复 + 阶段缓存保证下一轮只重试该阶段。

### P1-3 JSON 阶段靠正则截取 JSON，建议改用结构化输出

**位置**：`_extract_json_payload`、`_chat_completion_with_reasoning`

**问题**：当前从响应里 `find("{") / rfind("}")` 截取，模型在 JSON 前后输出说明文字或嵌套不完整时解析失败率高，触发兜底会丢失 LLM 筛选质量。

**修复方案**：DeepSeek 兼容接口支持 `response_format={"type": "json_object"}`。给 `_chat_completion_with_reasoning` 增加 `json_mode: bool = False` 参数，JSON 阶段开启；`_extract_json_payload` 保留作为二道防线。

### P2-1 `_highest_chain` 把 limit_step 的家数误当连板高度

**位置**：`_highest_chain`

**问题**：`limit_step.nums` 语义是“该梯队的股票家数”，不是连板数；从中 `re.findall(r"\d+")` 取最大值，会把“某梯队有 38 家”当成“最高 38 连板”。

**修复方案**：最高板高度只从 KPL `status` 的“N连”中取（已有第二个循环），删除对 `limit_step.nums` 的数字提取；limit_step 改为输出**梯队分布**（如 `{1板: 45, 2板: 12, 3板: 5, 4板+: 2}`）进 `market_context`，这对情绪判断比单一最高板更有价值。

### P2-2 死代码与上下文冗余

- `_limit_up_user_prompt` 是旧单阶段路径的提示词，多阶段管道已不引用，删除。
- `context["analysis_instructions"]`、`context["raw_supplement"]`（最多 560 行原始数据）只入库存档、不被任何阶段消费，膨胀 `context_json` 体积并扰动快照哈希。建议：`raw_supplement` 移出哈希参与范围或单独存档字段；`analysis_instructions` 删除。
- `_final_report_prompt` 把 `supplements`（全部筹码原始行）和 `stage_quality` 整体塞入最终合成提示词，而筹码数据已在 CHAIN_FOCUS / HIGH_BOARD_FOCUS 消费过。最终合成只需要：market_context、first_board 结果、两个 focus 的 HTML 片段、入选名单（含 selection 理由）。瘦身后能显著降低最贵一跳的 token 成本。

### P2-3 其他小问题

- `_chat_completion_with_reasoning` 中 `client.post(...)` 的闭括号缩进异常，`response.text` 实际执行在 `with` 块外（httpx 非流式响应已读完所以不报错，但一旦改成 `stream=True` 即踩坑），修正缩进。
- `_is_st_stock_row` 按 `name` 含 "ST" 过滤对所有接口生效，`limit_cpt_list` 的 `name` 是概念名，理论上存在误删；ST 过滤应只作用于含 `ts_code` 的个股行。
- `push_report` 逐接收人 commit、`_record_llm_metric` 每次 commit，当前规模可接受，接收人上百时再改批量。

---

## 二、打板领域逻辑改进（数据与分析维度）

当前 context 是**单日截面**，而打板的核心方法论是**情绪周期 + 日际对照**。以下按价值排序：

### 1. 引入昨日对照，计算情绪周期核心指标（价值最高）

打板情绪判断的三大硬指标当前全部缺失：

| 指标 | 计算口径 | 数据来源 |
|---|---|---|
| 炸板率 | 当日炸板家数 /（涨停 + 炸板家数） | kpl_list 拆池（见 P0-2） |
| 连板晋级率 | 今日 N+1 板家数 / 昨日 N 板家数（重点 1进2、2进3） | 今日 + 昨日 KPL 池对照 |
| 昨日涨停溢价 | 昨日涨停股今日平均涨幅 / 高开率 | 昨日 KPL 池 + 本地 `a_daily_quote` 当日行情 |

**落地**：`_build_context_snapshot` 同时取 `prev_trade_date` 的 KPL 数据（当日报告生成时昨日数据必然已稳定，且可从昨日 `LimitUpAnalysisCache.context_json` 直接复用，零额外 API 成本）；新增 `_emotion_cycle_metrics(today_pool, prev_pool, prev_quotes)` 写入 `market_context.emotion_cycle`。这是 Prompt 改进（三-1 周期定位）的数据前提。

### 2. 区分 10cm / 20cm 涨停（market_type 已采集未使用）

20cm（创业板/科创板）两连板的空间约等于 10cm 三四连板，封板难度和次日溢价分布完全不同。当前 `_board_level` 和分层上下文不区分制度板块，会把 20cm 二板与 10cm 二板混在同一池子里让 LLM 同等对待。

**落地**：`_compact_stock_row` 透出 `market_type`；`chain_board_context` / `high_board_context` 内按 10cm/20cm 分组；选股与重点分析提示词中明确“20cm 连板按更高空间等级评估，但同时提示 20cm 断板回撤更深”。

### 3. 封单质量改为相对值：封流比

绝对封单金额对大小盘股不可比。增加预计算字段 `seal_ratio = 封单金额 / 流通市值`（`limit_order`、`free_float`/`circ_mv` 均已采集），以及 `炸板回封次数`（limit_list_d 的 `open_times` 已采集未透出到 compact row）。封流比 > 3%~5% 通常视为强封板，这类先验直接写进选股提示词比让模型自己从原始数字里悟出来可靠得多。

### 4. 大盘环境锚

情绪判断没有指数锚（上证/深成涨跌、两市成交额、涨跌家数）。本地若已有指数日线表则零成本补入 `market_context.index_snapshot`；没有则加一个 Tushare `index_daily` 可选接口（纳入 data_quality 体系）。

### 5. 题材内部梯队（龙一/龙二卡位）

`_theme_summary` 只有题材聚合计数，没有题材内按板高排序的梯队结构。打板实战里“龙一断板、龙二补位”是关键交易逻辑。**落地**：theme_summary 每个题材附 `ladder: [{name, board_level, seal_ratio}]`（按板高降序前 5），让 CHAIN/HIGH 阶段能判断个股在题材内的卡位。

### 6. 封板时间口径

`lu_time`（首封时间）已采集，但提示词未引导使用。秒板/早盘板与尾盘偷袭板的次日溢价分布差异显著。在选股阶段提示词中明确：“结合首封时间评估封板质量：开盘 30 分钟内封板且未开板为最强，尾盘 14:30 后首封需降级处理”。

---

## 三、Prompt 改进建议

### 1. 系统提示词加入情绪周期定位框架（依赖二-1 数据）

当前 `_stage_system_prompt` / `_limit_up_system_prompt` 没有给模型周期分析框架。建议最终合成与两个 focus 阶段的系统提示词中加入：

```
先根据 emotion_cycle（炸板率、1进2/2进3 晋级率、昨日涨停溢价、最高板高度变化）把当日定位为：
启动期 / 发酵期 / 高潮期 / 分歧期 / 退潮期 / 冰点期 之一，并说明依据。
周期定位必须约束后续所有个股建议：退潮期和分歧期默认下调所有接力评级，
冰点期只输出观察不输出参与建议；不允许个股结论与周期定位矛盾。
```

这是打板复盘最重要的纪律性约束，能显著减少“退潮期还在推高位接力”这类危险输出。

### 2. 选股阶段给出显式评分维度与排序要求

`_chain_selection_prompt` 目前只罗列了筛选角度。改为要求模型对每只候选输出固定维度的简短评分（题材地位 / 封板质量(封流比+首封时间+开板次数) / 资金信号 / 筹码或技术状态），并按总分排序输出 `priority`。固定维度的好处：兜底排序 `_fallback_rank_stocks` 可以与 LLM 评分维度保持同构，两条路径输出可比。

### 3. 重点分析阶段限制篇幅、强制输出竞价观察清单

CHAIN_FOCUS / HIGH_BOARD_FOCUS 提示词增加：
- “每只股票分析不超过 150 字，禁止复述输入数据原文”；
- 强制输出**次日竞价观察清单**：每只入选股给出 `竞价高开幅度区间 + 对应动作（竞价弱于X%放弃 / X%~Y%低吸观察 / 高开超Y%警惕核按钮）`。打板推送的实际使用场景是次日 9:15–9:25 竞价决策，这是报告对用户最有行动价值的部分，目前提示词完全没有覆盖。

### 4. 最终合成阶段输入瘦身（对应 P2-2）

`_final_report_prompt` 的 `final_input` 移除 `supplements` 与 `stage_quality` 原文，只保留每股筹码摘要中的结论字段（`next_day_premium_bias`、`upper_chip_pressure_pct`）。预计削减最终一跳 30%+ 输入 token。

### 5. 工程化细节

- JSON 阶段开启 `response_format json_object`（P1-3）。
- 提示词中的输出 schema 用单独常量维护并纳入 `_stage_prompt_version` 版本号管理（当前版本号写死 `:v1`，改 schema 不改版本会命中旧缓存）。**任何提示词改动必须同步 bump `LIMIT_UP_PUSH_FINAL_PROMPT_VERSION`**，否则阶段缓存导致新提示词不生效。

---

## 四、落地排期建议

| 阶段 | 内容 | 涉及文件 | 验证 |
|---|---|---|---|
| 第一期（修复，0.5~1 天） | P0-1 复用当日 READY 报告 + 哈希规范化；P0-2 涨停/炸板拆池与统计口径修正；P1-1 GENERATING 僵死恢复；P2-3 缩进修正 | `limit_up_push_service.py` | `test_limit_up_push_service.py` 补：行序扰动哈希不变、炸板行不计入涨停数、僵死 GENERATING 重跑 |
| 第二期（数据增强，1~2 天） | 二-1 昨日对照情绪指标；二-2 10cm/20cm 分层；二-3 封流比与开板次数透出；P2-1 梯队分布 | `limit_up_push_service.py`（context 组装层） | 用历史交易日回放 `_assemble_context`，人工核对 emotion_cycle 数值与开盘啦 APP 口径一致 |
| 第三期（Prompt 升级，1 天） | 三-1 周期框架；三-2 评分维度；三-3 竞价清单与篇幅限制；三-4 final 瘦身；P1-3 json_mode；**同步 bump prompt_version** | `limit_up_push_service.py`（prompt 方法）、`config.py` | 选 3 个典型交易日（高潮日/退潮日/冰点日）人工评审报告质量；对比改造前后 token 消耗（`LlmCallMetric`） |
| 第四期（可选） | P0-1 方案 3 delivery 唯一键迁移；二-4 指数锚；二-5 题材梯队；P1-2 文本阶段降级 | service + alembic 迁移 | 迁移前清理历史重复 delivery |

注意事项：
- 所有新增/修改代码按项目规范补充中文注释（业务意图、边界条件、重跑口径）。
- 涉及时间字段处理时维持现有口径：东八区交易日、UTC-naive 入库，不做盲目 ±8 小时修正。
- 改动 context 结构会改变快照哈希，上线当日会对最近交易日重新生成一次报告，属预期行为；建议在非轮询时段（下午）部署，避开早盘推送窗口。

---

## 五、本次评审未改动代码

本文档仅为评审与方案，未修改任何业务代码。实施时建议按四中的分期逐期提交，每期独立可回滚。
