# 打板报告推送投资建议重构开发方案

- 创建日期：2026-06-12
- 关联文档：`limit-up-llm-push-design.md`（首版设计）、`limit-up-multi-stage-analysis-refactor-plan.md`（多阶段改造）、`limit-up-analysis-improvement-implementation-summary.md`（落地说明）、`chat-agent-refactor-design-and-plan.md`（问答 Agent 化，输出口径参照系）
- 目标：把打板报告推送链路（PushPlus + 雪球）的推送内容，从"完整复盘报告"重构为"基于报告结果生成的最终投资建议"，建议的内容口径对齐问答模块"风险高收益型推荐"的回答标准（风险前置、候选标的分层、晋级理由、触发/失败条件、非模板化风险提示）。
- 本方案只做方案设计与任务划分，不修改任何业务代码；不含工时估算，按阶段与依赖顺序排列。

---

## 1. 背景与目标

### 1.1 现状

当前打板推送链路（`backend/app/services/limit_up_push_service.py`）：

1. 早盘轮询任务（`backend/app/jobs/limit_up_push_jobs.py:23-36`，默认 8-9 点的 31/36/41/46/51/56 分）触发 `ensure_latest_analysis_and_push()`，KPL 数据就绪后经六阶段 LLM 流水线（首板题材 → 两三连筛选 → 高连板筛选 → 筹码补数 → 两三连重点 → 高连板重点 → 最终合成）生成完整 HTML 复盘报告，落 `limit_up_analysis_cache`。
2. `push_report()`（service:388-448）把 `analysis.title` + `analysis.content_html`（整篇长报告）原样推给所有启用接收人的 PushPlus。
3. 雪球定时任务（`xueqiu_publish_jobs.py`）经 `XueqiuPublishService.save_or_publish_latest_by_scheduler` → `_build_article`（xueqiu_publish_service.py:935-942）同样取整篇 `content_html`，追加固定免责段后发布长文。

### 1.2 问题

- 推送的是"复盘资料"而不是"行动结论"。微信端阅读长 HTML 报告成本高，用户真正需要的是次日竞价前可直接执行的观察/参与建议。
- 问答模块已经存在同源的"风险高收益型推荐"口径（`backend/app/services/agent/prompts.py:55-57`：以最新 READY 打板报告为数据源，风险放在结论之前），但推送链路没有复用这套结论化输出，两条链路对同一份报告给出的"最终产出"形态不一致。

### 1.3 目标

1. 新增"投资建议"生成环节：以多阶段流水线的结构化结果为输入，生成一份独立的、结论化的投资建议内容，落库缓存。
2. PushPlus 与雪球两个渠道默认推送投资建议，保留按配置回退推完整报告的能力。
3. 建议内容口径对齐问答"风险高收益型推荐"：风险前置、候选分层、每只标的给晋级逻辑与触发/失败条件、禁止模板化免责句但必须有真实风险提示段、不暴露底层数据来源。
4. 完整报告的生成、缓存、后台查看、公开分享能力全部保留不变（建议是"附加产物"，不是替换报告本体）。

### 1.4 非目标

- 不做按接收人风险偏好的个性化建议（现有架构中所有接收人收同一份内容，个性化口径只存在于问答模块；如需个性化属架构级新增，另行立项）。
- 不改报告六阶段流水线本身的分析逻辑与提示词。
- 不新增推送渠道（企业微信等维持搁置状态）。
- 不动神奇九转链路（保持软关闭现状，但方案预留同构扩展点）。

---

## 2. 现状关键事实与决策依据

以下事实直接决定方案选型，逐条列出出处。

### 2.1 建议生成的输入材料已经结构化存在

多阶段流水线把阶段结果写回 `context["pipeline"]`（limit_up_push_service.py:1756-1765），包含：

- `selected_chain_stocks` / `selected_high_board_stocks`：入选标的，含 `score_detail`（题材卡位/封板质量/资金信号等强中弱枚举）、`selection_reason`、`priority` 或 `risk_level`；
- `stock_supplements`：逐股筹码摘要（`winner_rate_trend`、`upper_chip_pressure_pct`、`next_day_premium_bias` 偏友好/中性/压力较大）；
- `first_board`：题材发酵候选与风险旗标；
- `market_context.emotion_cycle`：炸板率、1进2/2进3 晋级率、昨日涨停溢价与高开率等数值指标；
- `chain_focus_html` / `high_board_focus_html`：两个重点分析阶段的 HTML 片段（含次日竞价观察清单）。

`FINAL_REPORT` 阶段的输入 `final_input`（service:1738-1748）正是上述材料的压缩版（经 `_stocks_for_final_prompt` service:2243-2278 瘦身）。**投资建议阶段直接复用同一份 `final_input` 作为输入，无需新增取数。**

### 2.2 问答"风险高收益型推荐"的输出口径（参照系）

- 数据源规则（prompts.py:55-57）："以最新 READY 打板报告为数据源……回答必须显著提示高波动、高回撤与失败风险，把风险放在结论之前。"
- 免责口径（prompts.py:85-86）：禁止"不构成投资建议""仅供参考"等模板化免责句，但打板/短线类高风险推荐必须有明确的风险提示段。
- 不暴露来源（prompts.py:83-84）：不提及 SQL、数据库、工具名，可以说"从当前可观察数据看"。
- 金标验收（backend/tests/golden/chat_golden_set.json:21-22，g004）：`risk_banner=true`、回答须含"打板/涨停/晋级"类内容。
- 数据字典口径（data_catalog.py:149）："回答时从报告正文提取观察标的、晋级理由、触发条件和风险。"

### 2.3 渠道硬约束：必须输出 HTML

- PushPlus 模板硬编码 HTML（pushplus_client.py:151，常量 `PUSHPLUS_HTML_TEMPLATE`；config 的 `pushplus_template` 配置实际未被读取），不存在 markdown 分支。
- 雪球长文正文为 HTML 片段（xueqiu_publish_service.py:935-942），打板报告链路允许 table（现行整报含表格已正常发布）；问答回答发布链路才有"禁 table、仅 h2/h3/p/strong/em/ul/ol/li/br/hr"的转换约束（:56-67），且其转换函数签名绑死 `LlmChatMessage`，不可直接复用。
- 问答输出契约要求 Markdown 且禁止 HTML（prompts.py:79-82），与渠道约束直接冲突。后端无 markdown→HTML 库依赖（`backend/pyproject.toml` 无 markdown/mistune 类依赖）。

**结论：建议阶段直接生成 HTML 片段（与本服务其余阶段一致），只移植问答口径的"内容规则"，不移植其"Markdown 载体"。**

### 2.4 LLM 调用方式选型：沿用服务内直连，不复用 AgentEngine

| 维度 | 复用 AgentEngine | 服务内直连（`_chat_completion_with_reasoning`） |
|---|---|---|
| 日限额 | `agent_iteration` phase 计入 `llm_daily_call_limit`（默认 100/日），且**所有经 LlmClient 的调用都过限额闸门**（llm_client.py:683-737）——问答用量打满后早盘推送会被 `LlmDailyLimitExceeded` 拦截 | phase=`limit_up_analysis` 不在 `LLM_EXTERNAL_CALL_PHASES`（llm_client.py:47-58），不受问答用量挤兑 |
| 确定性 | 工具循环自主决策，可能多次取数、输出形态不可控，无 JSON/HTML 形态约束 | 单次调用、prompt 完全可控、有阶段缓存幂等与确定性兜底惯例 |
| 输出载体 | 受输出契约约束为 Markdown（禁 HTML），需二次转换 | 直接产 HTML |
| 推理力度 | `LlmClient.chat_completion` 不支持 `reasoning_effort` 参数（llm_client.py:229-237） | 支持（service:2615），与报告各阶段同配置 |
| 指标 | phase=agent_iteration 与问答混在一起 | 沿用 `_record_llm_metric`（service:2658-2683），可单列新 phase |

**结论：投资建议作为多阶段流水线的新增阶段实现，复用 `_run_text_stage` + `_stage_cache_payload` 基建；"类似问答"是指内容口径对齐，不是字面复用问答引擎。**

### 2.5 落库与推送取数点

- `push_report` 入口校验并发送的都是主表字段（`analysis.content_html`，service:402-435）；雪球 `_resolve_analysis` 同样只认主表 `content_html`（xueqiu_publish_service.py:738-754）；报告详情 API 也读主表。**建议正文必须落在 `limit_up_analysis_cache` 主表新列上**，仅存阶段缓存表无法被推送/发布/详情链路消费。
- 阶段缓存基建对 `stage_key` 完全泛型（唯一键 trade_date+stage_key+model+prompt_version+input_hash，`analysis_id` 经 `_active_limit_up_analysis_id` 自动回填，service:1917-1992），**新增 stage_key 零迁移可用**。
- `XueqiuPublishRecord.source_type` 为自由字符串无枚举约束（notification.py:418-462），**新增建议类 source_type 无需迁移**。
- Alembic 迁移线性链 head 为 `20260612_0048_add_agent_chat_columns.py`，下一序号 0049；写法规范（uk_/idx_ 命名、LONGTEXT variant、中文 docstring、downgrade 逆序）以 0047/0048 为样本。

### 2.6 不 bump 主表 `prompt_version` 的理由

主缓存唯一键含 `prompt_version`（默认 `limit-up-v1`，service:340）。若 bump，会导致同快照重新生成整份报告（六阶段 LLM 全部重调），代价大且与"报告本体不变"的目标矛盾。本方案采用**回填式设计**：建议列对既有 READY 报告为 NULL，推送前检测缺失则按需补生成，不触发报告重算。建议自身的提示词版本走阶段缓存版本机制（`_stage_prompt_version`，service:2564-2571；该方法需小幅重构以支持按阶段独立版本，见 3.2.3），独立演进。

---

## 3. 方案设计

### 3.1 总体架构

建议回填不挂在各个调度入口上，而是**下沉到两个内容消费点内部**（`push_report` 与雪球 `_resolve_analysis`），保证定时、手动、补发所有路径行为一致；且回填只在 `content_mode==ADVICE` 时触发，REPORT 模式是零行为差异的严格回滚通道。

```
任意入口（早盘轮询 / 周末复推 / 手动推送 / 雪球定时 / 雪球手动）
  └── push_report(...) 或 _resolve_analysis(...)                          ← 改造（统一收口）
        ├── mode=REPORT → 完整报告（现行为逐字节一致，不触发建议生成）
        └── mode=ADVICE
              ├── advice READY → 推送/发布建议（新标题口径）
              ├── advice PENDING → 同步调用 ensure_advice_for_analysis() 回填   ← 新增
              │       ├── 成功 → 推送/发布建议
              │       └── 失败 → 置 FAILED，走下一分支
              ├── advice FAILED → 按渠道降级开关：降级推/发完整报告，或本次跳过
              └── advice GENERATING（他方在生成且未僵死）→ 本次跳过，下轮重试
```

报告六阶段流水线、报告缓存状态机、推送/发布幂等流水全部保持不变；`ensure_analysis_for_trade_date` 不感知建议（报告生成与建议生成解耦，建议失败永不影响报告 READY）。

### 3.2 投资建议生成：新增 `INVESTMENT_ADVICE` 阶段

#### 3.2.1 入口方法 `ensure_advice_for_analysis(analysis) -> LimitUpAnalysisCache`

新增于 `LimitUpPushService`，职责与边界：

- 前置条件：`analysis.status == READY` 且 `content_html` 非空；否则直接返回（建议依附于已完成报告）。
- 幂等与并发抢占：`advice_status == READY` 且 `advice_html` 非空时直接返回，不重调 LLM。生成前先以**条件更新抢占锁**进入 GENERATING：`UPDATE ... SET advice_status='GENERATING' WHERE id=? AND advice_status IN ('PENDING','FAILED')` 并立即 commit；读到他方未僵死的 GENERATING 时直接返回不生成。僵死判定仿照报告既有机制（`_is_generating_stale`，service:2740-2753）：基于 `_now_naive` 与该行 `updated_at` 比对，阈值复用 `LIMIT_UP_PUSH_GENERATING_STALE_MINUTES`。该锁是必选项——早盘轮询（5 分钟一次）与雪球调度（每分钟触发，`xueqiu_publish_jobs.py:28-31`，时点过后全天补发窗口）会在同进程线程池并发进入本方法；阶段缓存唯一键只保证"落库幂等"（`_save_stage_cache` 撞唯一键即吞掉，service:1989-1992），**拦不住并发窗口内的重复 LLM 调用**，必须靠状态机抢占。
- 输入组装：优先从 `context_json.pipeline` 还原 `final_input` 同构材料（market_context + first_board + 入选股压缩行 + 两个重点阶段 HTML 片段）；**兼容兜底**：旧报告（多阶段改造前生成）`context_json` 无 `pipeline` 时，退化为以 `content_markdown` 为材料——注意该列实际存的是 FINAL_REPORT 阶段的原始 LLM 输出，即**整篇 HTML 报告正文**（service:1767-1768），并非 Markdown。兜底分支须先剥 ``` 代码块围栏（复用 `_normalize_report_html` 的清洗逻辑）、设定输入截断上限（整报体积远大于 final_input 压缩材料），且 user prompt 为该路径单独写"从报告正文提取观察标的、晋级理由、触发条件和风险"的指令段（对齐 data_catalog.py:149 口径）。
- 执行：调用 `_run_text_stage(LIMIT_UP_STAGE_INVESTMENT_ADVICE, ...)`，system prompt 复用 `_stage_system_prompt`（注入情绪周期定位与"退潮/冰点不得激进接力"约束，service:1994-2007），user prompt 见 3.2.2。注意 `_run_text_stage` 对非 focus 阶段失败是直接 raise 不落失败缓存（service:1842-1854），建议阶段的失败兜底在本方法内 try/except 收口，不依赖阶段缓存的 failed 语义。
- 落库：`advice_html`（经 `_normalize_report_html` + `_wrap_html` 规整，与报告同样适配 PushPlus 容器样式）、`advice_markdown`（LLM 原始输出，对齐主表双存惯例）、`advice_status=READY`、`advice_generated_at`、清空 `advice_error`。
- 失败处理：**建议失败不改变报告状态**。捕获异常后 `advice_status=FAILED`、`advice_error` 截断 1000 字，并把一条 `INVESTMENT_ADVICE / FAILED_FALLBACK` 阶段质量项（`_stage_quality_item`，service:2555-2562）写入 **`context_json.pipeline.stage_quality`**（旧报告无 pipeline 结构时先补建只含 stage_quality 的空 pipeline）——列表页降级标识 `_has_stage_fallback`（service:3113-3127）只读这条路径、不读 `data_quality_json`，写错位置标识不会点亮。
- 重试口径（防无界重试）：FAILED 不在内容消费点自动重试。自动重试仅限**早盘轮询入口**，且距上次尝试（该行 `updated_at`）超过 `LIMIT_UP_PUSH_GENERATING_STALE_MINUTES` 冷却窗口才允许（早盘轮询窗口仅 8-9 点共 12 次，叠加冷却后当日自动重试次数有界）；雪球调度入口只消费 READY 建议，FAILED 时按降级开关处理、**不触发重试**（否则每分钟调度会放大为全天重试）。管理员可经新 API 强制重新生成（见 3.6），这是 FAILED 的主要人工恢复通道。

#### 3.2.2 建议阶段提示词口径（草案，实施时定稿）

user prompt 要点（移植问答口径 + 推送场景约束）：

1. 角色与任务：基于给定的打板分析阶段结果，输出一份次日可执行的"高风险短线投资建议"，读者是接受高波动、高回撤的进取型投资者。
2. 结构硬约束（顺序固定）：
   - **风险提示段置于全文最前**（对齐 prompts.py:56-57"把风险放在结论之前"）：当日情绪周期定位、整体仓位态度、高波动/高回撤/失败风险的明确提示；禁止"不构成投资建议""仅供参考"等模板句（对齐 prompts.py:85-86）。
   - **核心结论**：3-5 条要点，给出当日参与/观望的总判断。
   - **候选标的分层**：重点观察 / 谨慎观察 / 放弃观察（对齐高连板阶段既有分层口径），每只标的限 100 字内，必须含：晋级逻辑、次日竞价触发条件（竞价弱于 X% 放弃 / X%~Y% 低吸观察 / 高开超 Y% 警惕，对齐评审固化的竞价观察清单口径）、失败/止损条件、筹码压力提示（来自 next_day_premium_bias）。
   - **反证信号**：什么情况下整套建议作废（如情绪周期跌入退潮期的具体数值信号）。
3. 周期约束：退潮期、分歧期默认下调所有接力评级；冰点期只输出观察清单、不输出参与建议（对齐评审已固化口径）。
4. 数据纪律：精确数值必须来自给定材料，缺失标注不确定性，不编造；不提及 JSON、阶段、数据库等底层来源（对齐 prompts.py:83-84、:88）。
5. 载体：只输出纯 HTML 片段，用 h2/h3/p/ul/ol/table/strong，不要 Markdown 代码块、不要 html/body（对齐 `_final_report_prompt` 惯例，service:2128-2136）；总篇幅显著短于完整报告（建议全文控制在适合微信单屏~三屏阅读的量级，具体字数上限实施时联调确定）。

#### 3.2.3 阶段常量与版本

- 新增 `LIMIT_UP_STAGE_INVESTMENT_ADVICE = "INVESTMENT_ADVICE"`（与既有常量并列，service:83-88）。
- 阶段版本：现有 `_stage_prompt_version`（service:2564-2571）**不是按阶段的映射，而是统一公式** `f"{final_prompt_version}:{stage_key.lower()}:v3"`——直接套用会让建议阶段落为 `:v3`，且无法单独 bump。本任务需先把该方法重构为"按 stage_key 查映射、缺省回退统一公式"的结构：既有六阶段的版本串必须逐字节不变（保持 `:v3`，否则击穿全部阶段缓存），`INVESTMENT_ADVICE` 单列独立起版（如 `:investment_advice-v1`），后续仅调建议提示词时只 bump 该条目。
- LLM 指标：现状 `_record_llm_metric` 把 phase 硬编码为 `limit_up_analysis`（service:2658-2683），`_chat_completion_with_reasoning`（service:2599-2656）与 `_run_text_stage` 均无 phase 入参。需为这三层增加可选 `phase` 参数（默认 `limit_up_analysis` 保持既有阶段兼容），建议阶段传 `limit_up_advice`，并在 `backend/app/services/llm_metric_definitions.py` 登记 label/描述（未登记会回退原名，不阻断）；**不加入** `LLM_EXTERNAL_CALL_PHASES`（与 `limit_up_analysis` 同口径，不占问答日限额）。

### 3.3 数据模型变更

#### 3.3.1 `limit_up_analysis_cache` 新增列（Alembic 迁移 `20260612_0049_add_limit_up_advice_columns.py` 或顺延序号）

| 列 | 类型 | 说明 |
|---|---|---|
| `advice_status` | String(16) NOT NULL server_default "PENDING" | 建议状态机：PENDING / GENERATING / READY / FAILED；存量行随默认值落 PENDING，推送层视作"缺失待回填" |
| `advice_html` | Text/LONGTEXT 可空 | 规整后的建议 HTML（PushPlus/雪球/详情页共用） |
| `advice_markdown` | Text/LONGTEXT 可空 | LLM 原始输出（对齐 content_markdown 双存惯例） |
| `advice_generated_at` | DateTime 可空 | 建议生成时间（UTC-naive，沿用 `_now_naive` 口径） |
| `advice_error` | Text 可空 | 失败原因（截断 1000 字） |

- 迁移写法对齐 0047/0048 样本：中文 docstring（创建日期/author）、逐列 `comment=`、`sa.Text().with_variant(mysql.LONGTEXT(), "mysql")`、downgrade 逆序删列并注明回滚不影响既有数据。
- 不新增索引（建议查询总是经主键/既有 trade_date+status 索引）。
- 同步更新：SQLAlchemy 模型（notification.py:113-145）、`resources/sql/03_full_schema_with_comments.sql`、`resources/doc/database-schema.md`（该文档 :118 明确要求四处同步）。

#### 3.3.2 阶段缓存与雪球流水

- `limit_up_analysis_stage_cache`：零迁移，新 stage_key 直接写入。
- `XueqiuPublishRecord.source_type`：新增常量 `XUEQIU_SOURCE_LIMIT_UP_ADVICE = "LIMIT_UP_ADVICE"`，零迁移；建议类发布流水与整报流水按 source_type 区分，幂等查重（`_latest_record_for_mode`）需把 source_type 纳入过滤条件，避免"先发过整报、切到建议模式后被旧流水挡住不再发布"。

### 3.4 推送链路改造（PushPlus）

#### 3.4.1 `push_report` 内容选择与建议回填收口

- 方法签名不变，内部按 `settings.limit_up_push_content_mode` 取内容：
  - `ADVICE`（重构后默认）：标题用建议标题口径（如 `f"{trade_date:%Y-%m-%d} 打板投资建议（高风险）"`，实施时定稿），正文 `advice_html`；
  - `REPORT`：维持现行为（`analysis.title` + `content_html`）逐字节一致，**不触发任何建议生成与新列写入**，作为严格回滚通道。
- **建议回填收口在本方法内部**（而非各调度入口）：`ADVICE` 模式下 `advice_status==PENDING` 时，先同步调用 `ensure_advice_for_analysis` 回填再决定推送内容。这样早盘轮询、周末复推、**手动推送（MANUAL）**、乃至推送任意存量历史报告（迁移后全部 PENDING）走的是同一条回填路径，没有"绕过建议生成推出空内容"的入口。
- `ADVICE` 模式各状态分支（含 MANUAL）：
  - `READY` → 推建议；
  - `PENDING` → 同步回填：成功推建议，失败转入 FAILED 分支；
  - `FAILED` 且 `limit_up_push_advice_fallback_to_report=True`（默认）→ 降级推完整报告，流水照常记 SENT（推送不因建议失败而中断早盘交付）；MANUAL 推送同样降级成功，管理员可先经重生成端点修复建议再手动补推（MANUAL 无业务计划查重，可重复推送）；
  - `FAILED` 且降级开关关闭 → 定时入口本轮不推送（不建流水），由早盘轮询冷却重试（3.2.1）或管理员介入；MANUAL 入口直接返回明确错误信息（"建议生成失败且降级已关闭"），不静默跳过；
  - `GENERATING`（他方在生成且未僵死）→ 定时入口本轮跳过下轮再推；MANUAL 返回"建议生成中请稍后重试"。
- 入口校验从"`content_html` 非空"扩展为"所选模式对应正文可得（含回填后）"。
- 推送幂等机制完全不变：`limit_up_push_delivery` 唯一键与跨 analysis 业务查重（service:2925-2991）不受内容模式影响——同一计划无论推的是建议还是降级整报，只发一次。

#### 3.4.2 调用链各入口

- `ensure_latest_analysis_and_push`（service:285-309）与 `push_weekend_replay`（service:450-471）：**无需插入回填代码**，回填已收口在 `push_report` 内。周末复推场景：周五建议已缓存时复推零新增 LLM 调用，维持"周末只发缓存"的既定口径；周五报告存在但建议缺失（如重构上线后的第一个周末）时经统一回填路径一次性补生成，属回填而非重算。
- 手动推送端点（routes_limit_up_push.py:129-155）：行为随 `push_report` 自动继承内容模式与回填，无需改路由；MANUAL 分支预期行为见 3.4.1。
- 切回 `ADVICE` 首日（此前运行在 REPORT 模式、建议未生成）：早盘第一次推送会现场补生成建议，列入测试用例。

### 3.5 雪球发布改造

- 建议回填收口在 `_resolve_analysis`（:738-754）：`ADVICE` 模式下若 `advice_status==PENDING`，同步调用 `LimitUpPushService.ensure_advice_for_analysis` 回填——定时调度（`save_or_publish_latest_by_scheduler` :379-423）、**手动发布（`save_or_publish_report` :249-312）与预览（:231-247 一线的预览端点）**共用该收口，避免手动/预览路径在改造后直接抛"未找到可发布"。校验条件：`advice_status==READY and advice_html 非空`；`FAILED` 时按 `xueqiu_limit_up_advice_fallback_to_report` 开关（默认 false，见 3.7）决定回退整报还是本次不发布——**雪球调度入口不触发 FAILED 重试**（每分钟调度 + 全天补发窗口会放大为无界重试，见 3.2.1）。
- `_build_article`（:935-942）：按 `settings.xueqiu_limit_up_content_mode` 分支：
  - `ADVICE`：新标题口径（如 `f"{trade_date} 打板观察与投资建议（高风险）"`，受 50 字硬限 `XUEQIU_TITLE_MAX_LENGTH` 约束）、正文 `_unwrap_report_body(advice_html)`；
  - `REPORT`：现行为。
  - 两种模式都保留发布层追加的"不构成任何投资建议"免责段（:938-941）——该免责是平台合规层口径，与 LLM 内容层"禁模板免责句"不冲突（前者是代码追加、后者约束模型输出，两层各司其职）。
- 幂等查重采用**两级闸门**（`_latest_record_for_mode` :866-887 有两个调用方，必须一并改造）：
  1. **同源防双发总闸**（调度层已发检查 :410-417 与 `_get_or_create_record` :772-797 共用）：同一 `analysis_id + publish_mode` 下，**任意 source_type** 已有 DRAFTED/PUBLISHED 流水即不再自动创建/发布——防止"降级发过整报 → 建议补好后又追发一篇建议"或来回切换内容模式导致同一交易日同源内容在公开平台重复发文。**明确取舍：降级发布整报后，当日建议补好也不追发**；如需改发建议，由管理员在雪球网页端删除旧文后走手动 force 通道。
  2. **source_type 维度**仅作用于流水记录与 force 场景：建议类流水写 `source_type=LIMIT_UP_ADVICE`（零迁移），管理员勾选 force 时按 (analysis_id, mode, source_type) 维度新建流水，保留旧流水审计。
- 手动发布端点（routes_xueqiu_publish.py:145-175）：默认随配置模式；是否在请求体暴露 per-request 内容模式选择，实施时按前端需要决定（首版可不暴露）。

### 3.6 API 与前端改造

#### 3.6.1 后端 API

- `LimitUpReportListItem`（schemas/limit_up_push.py:58-76）：新增 `advice_status: str = "PENDING"`。
- `LimitUpReportDetail`（:79-92）：新增 `advice_html?`、`advice_markdown?`、`advice_generated_at?`、`advice_error?`。
- 新增端点 `POST /api/limit-up-push/reports/{report_id}/advice/regenerate`（管理员）：强制重新生成指定报告的建议（绕过 `advice_status==READY` 幂等与 FAILED 冷却，阶段缓存允许失败重跑语义不变），响应复用 `LimitUpActionResponse`。用于建议质量不满意或失败后的人工介入。**该端点随阶段二交付**（ADVICE 模式上线即需要人工恢复通道），前端按钮在阶段三补齐，期间可经 API 直调。
- 推送、分享、流水、接收人端点请求/响应结构不变。

#### 3.6.2 前端（`frontend/src/pages/LimitUpPushPage.tsx`、`frontend/src/api/limitUpPush.ts`）

- 报告表格新增"建议"状态列（Tag：READY/FAILED/PENDING）。
- 「查看」弹窗（line 473-520）在既有"预览/源码/阶段"三 Tab 基础上新增"建议"Tab：渲染 `advice_html` 预览 + 失败时显示 `advice_error` + 管理员"重新生成建议"按钮（调新端点）。
- 推送弹窗文案提示当前推送内容模式（建议/整报），避免管理员误判推送物。
- 公开分享页（LimitUpSharePage.tsx）维持展示完整报告不变（分享场景定位是复盘资料外发）。

### 3.7 配置项

```env
# 推送内容模式：ADVICE=推送投资建议（重构后默认）；REPORT=推送完整报告（回滚通道）
LIMIT_UP_PUSH_CONTENT_MODE=ADVICE
# PushPlus 渠道：建议生成失败时是否降级推送完整报告（默认开，保障早盘交付）
LIMIT_UP_PUSH_ADVICE_FALLBACK_TO_REPORT=true
# 雪球发布内容模式，独立于 PushPlus（两渠道受众不同，允许分别回滚）
XUEQIU_LIMIT_UP_CONTENT_MODE=ADVICE
# 雪球渠道：建议失败时是否降级发布完整报告（默认关——公开平台宁可当日不发，
# 也不在"建议模式"下发出与预期不符的整报；与 PushPlus 降级开关独立）
XUEQIU_LIMIT_UP_ADVICE_FALLBACK_TO_REPORT=false
```

- 建议阶段的模型与推理力度沿用 `LIMIT_UP_PUSH_MODEL` / `LIMIT_UP_PUSH_REASONING_EFFORT`，不另设配置（与报告各阶段一致，减少口径分叉）。
- 配置落 `backend/app/core/config.py` limit_up 段（:194-244）与 xueqiu 段（:265-289），alias 全大写对齐现有惯例。

### 3.8 顺带修正项（本次任务触碰范围内）

- `data_catalog.py:146-152` 对 `limit_up_analysis_cache` 的列描述与真实表结构不符（声称存在 `report_type`、`source_payload_json` 列，实际没有）。本次为该表新增建议列，必须同步修正该数据字典条目（真实列清单 + 新增 advice 列），否则问答模型可能写出查询不存在列的 SQL。修正后问答侧"风险高收益型推荐"还可优先引用 `advice_markdown`（已是结论化内容），该优化作为字典描述的引导性说明，不改问答代码。

---

## 4. 实施阶段与任务划分

> 不含工时估算；任务按依赖顺序排列，每阶段验收通过后进入下一阶段。

### 阶段一：建议生成链路（纯后端，不动推送行为）

| 任务 | 内容 | 验收标准 |
|---|---|---|
| S1-1 | Alembic 迁移 0049 新增主表 advice 五列；同步 SQLAlchemy 模型、`database-schema.md`、`03_full_schema_with_comments.sql` | 迁移可升可降；存量行 advice_status=PENDING（server_default 与 ORM default 一致）；四处文档/模型一致 |
| S1-2 | 新增 `LIMIT_UP_STAGE_INVESTMENT_ADVICE` 常量；把 `_stage_prompt_version` 重构为按 stage_key 映射（缺省回退统一公式）；建议 user prompt 构造函数（含旧报告兜底路径专用指令段） | prompt 含 3.2.2 全部结构硬约束；既有六阶段版本串逐字节不变（阶段缓存不击穿）；建议阶段版本独立可 bump |
| S1-3 | 实现 `ensure_advice_for_analysis`：GENERATING 条件更新抢占锁 + 僵死恢复、输入组装（pipeline 优先、content_markdown 兜底含围栏剥离与截断）、`_run_text_stage` 执行、规整落库、失败置 FAILED + 质量项写入 context_json.pipeline.stage_quality、FAILED 冷却重试口径 | 同输入命中阶段缓存不重调 LLM；并发双入口只产生一次 LLM 调用（抢占锁测试）；GENERATING 僵死可恢复；建议失败不影响报告 READY 且列表 has_stage_fallback=true；旧报告（无 pipeline）可生成建议 |
| S1-4 | `_chat_completion_with_reasoning` / `_record_llm_metric` / `_run_text_stage` 增加可选 phase 参数（默认 limit_up_analysis）；`llm_metric_definitions.py` 登记 `limit_up_advice` | 既有六阶段指标 phase 不变；建议阶段指标记为 limit_up_advice；不计入日限额 |
| S1-5 | 单元测试：生成成功/失败/幂等/并发抢占/僵死恢复/旧报告兜底/缓存复用 | 新增测试全绿；既有 `test_limit_up_push_service.py` 26 个测试不回归 |

依赖：S1-1 先行；S1-3 依赖 S1-1、S1-2；S1-4 可与 S1-3 并行；S1-5 收尾。

### 阶段二：推送与发布切换（行为变更）

| 任务 | 内容 | 验收标准 |
|---|---|---|
| S2-1 | 新增四个配置项（3.7），默认值按表 | 配置缺省时行为=ADVICE+PushPlus 降级开+雪球降级关；显式 REPORT 时与现行为逐字节一致（不触发建议生成、不写新列） |
| S2-2 | `push_report` 内部收口：内容模式分支 + 标题口径 + PENDING 同步回填 + FAILED/GENERATING 分支（含 MANUAL 行为，3.4.1） | ADVICE 模式推送正文为 advice_html；PENDING→现场回填后推送（含 MANUAL 与历史报告）；FAILED+降级开→推整报且流水 SENT；FAILED+降级关→定时不建流水、MANUAL 返回明确错误；推送幂等不回归（同计划只发一次）；周末复推命中缓存建议时零新增 LLM 调用；建议失败报告列表 has_stage_fallback=true |
| S2-3 | 雪球：`_resolve_analysis` 收口回填/`_build_article`/两级幂等闸门（调度层 :410 已发检查 + `_get_or_create_record`）按 3.5 改造，新增 `LIMIT_UP_ADVICE` source_type | ADVICE 模式发布正文为建议+免责段；标题不超 50 字；同 analysis 同 mode 任意 source_type 已 DRAFTED/PUBLISHED 不重复自动发文（降级整报后不追发建议）；force 通道可按 source_type 新建流水；手动发布与预览路径可触发回填；雪球 FAILED 不重试、按独立降级开关处理；REPORT 模式行为不变 |
| S2-4 | 新增 `POST /reports/{report_id}/advice/regenerate` 端点（管理员，3.6.1） | FAILED/质量不满意场景可经 API 强制重生成；非管理员 403 |
| S2-5 | 单元测试：内容模式矩阵（ADVICE 就绪/PENDING 回填/FAILED 降级/降级关闭/REPORT）、MANUAL 分支、周末复推、切回 ADVICE 首日补生成、雪球两级闸门 | 新增测试全绿；既有推送/雪球测试不回归 |

依赖：阶段一全部验收通过后开始；S2-2、S2-3、S2-4 依赖 S2-1；S2-5 收尾。

### 阶段三：API 与前端

| 任务 | 内容 | 验收标准 |
|---|---|---|
| S3-1 | schema 扩展（列表 advice_status、详情 advice 四字段） | 详情接口返回建议内容；列表接口返回建议状态 |
| S3-2 | 前端：报告表格建议状态列、查看弹窗"建议"Tab（预览/错误/重生成按钮，调 S2-4 端点）、推送弹窗模式提示 | 管理员可在后台查看并重生成建议；非管理员只读 |
| S3-3 | 路由/服务层测试 + 前端构建 | 后端测试全绿；`npm run build` 通过 |

依赖：阶段二验收通过后开始；S3-2 依赖 S3-1。

### 阶段四：数据字典修正与文档同步

| 任务 | 内容 | 验收标准 |
|---|---|---|
| S4-1 | 修正 `data_catalog.py` 打板表条目（真实列 + advice 列 + 引导优先读 advice_markdown） | 字典列清单与 ORM 模型逐列一致；问答金标 g004 用例回归通过 |
| S4-2 | 更新本方案实施状态、`development-progress.md` 等关联文档 | 文档与落地行为一致 |

依赖：阶段三完成后收尾。

---

## 5. 测试计划

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend
./.venv/bin/python -m pytest tests/test_limit_up_push_service.py tests/test_xueqiu_publish_service.py tests/test_notification_service.py -q
```

重点用例设计（沿用既有 mock 模式：FakeTushareClient / FakeNotificationService / monkeypatch `_run_text_stage`）：

1. 建议生成：成功落库五列；`_run_text_stage` 抛错 → advice_status=FAILED、报告仍 READY、质量项写入 context_json.pipeline.stage_quality、列表 `has_stage_fallback=true`（含旧报告补建 pipeline 场景）。
2. 并发与僵死：两路并发进入 `ensure_advice_for_analysis` 只产生一次 LLM 调用（抢占锁）；GENERATING 超过 stale 阈值（`_now_naive` 打桩）可被接管重跑；未超阈值不重跑。
3. 回填收口：已 READY 报告（advice_status=PENDING）经任意入口（定时 `ensure_latest_analysis_and_push`、MANUAL `push_report`、雪球 `_resolve_analysis`）推送/发布前自动补建议，报告六阶段零重调；切回 ADVICE 首日（REPORT 模式期间未生成）现场补生成。
4. 内容模式矩阵：ADVICE 就绪 → 正文为 advice_html、标题为建议口径；FAILED+降级开 → 正文为 content_html、流水 SENT；FAILED+降级关 → 定时不建流水、MANUAL 返回明确错误；REPORT → 与现行为一致且零建议生成调用。
5. 重试节流：FAILED 后冷却窗口内早盘轮询不重试、窗口外重试；雪球调度入口对 FAILED 不触发重试。
6. 幂等：同计划多轮轮询只推一次（沿用既有 `test_latest_analysis_push_is_idempotent_across_polling` 扩展模式断言）。
7. 周末复推：周五建议已缓存 → 复推零 LLM 调用；周五建议缺失 → 仅建议阶段补调一次。
8. 雪球两级闸门：建议模式发布流水 source_type=LIMIT_UP_ADVICE；同 analysis 同 mode 已有任意 source_type 的 DRAFTED/PUBLISHED 流水 → 不重复自动发文（降级整报后建议补好不追发）；force 可新建建议流水。
9. 旧报告兜底：context_json 无 pipeline 的 READY 报告可用 content_markdown（实为整报 HTML 原文，剥围栏+截断后）生成建议。
10. 问答回归：`chat_golden_set.json` g004（风险高收益型推荐）行为不回归（阶段四数据字典修正后执行）。

真实 LLM / 真实 PushPlus / 真实雪球的线上验收需用户确认后执行（对齐既有惯例）。

---

## 6. 风险与取舍

| 风险 | 对策 |
|---|---|
| 雪球公开发布"投资建议"类内容的合规敏感度高于复盘资料 | 发布层免责段保留；标题与正文明示"高风险"；提供 `XUEQIU_LIMIT_UP_CONTENT_MODE=REPORT` 独立回滚；上线首周建议雪球侧先保持 REPORT 或 DRAFT 模式人工审看 |
| PushPlus 正文长度上限无法从代码确认 | 建议本身显著短于整报，风险低；仍把"建议全文在微信端完整渲染"列为线上验收项，超限再加截断策略 |
| 建议与报告内容不一致（建议引用了报告里没有的标的/数值） | 建议输入严格限定为 pipeline 结构化材料（与最终报告同源）；prompt 强制"数值必须来自材料"；后台"建议"Tab 便于人工抽查 |
| 建议生成失败导致早盘无推送 | 默认降级推整报，保障交付；失败质量项写入 pipeline.stage_quality 使 has_stage_fallback 在列表页可见；重生成端点随阶段二交付，管理员修复后可 MANUAL 补推（MANUAL 不受幂等限制） |
| 多调度入口并发重复调 LLM / GENERATING 僵死停摆 | GENERATING 条件更新抢占锁为必选项（3.2.1）；阶段缓存唯一键只保证存储幂等、不保证并发去重，不依赖它防并发；僵死基于 `_now_naive` 与 stale 阈值接管；FAILED 重试限早盘轮询 + 冷却窗口，雪球调度不重试 |
| 切换模式/降级后雪球同源重复发文 | 两级闸门（3.5）：同 analysis 同 mode 任意 source_type 已发即不自动再发；source_type 仅用于流水区分与 force 通道 |

取舍说明：

- **不复用 AgentEngine**：日限额挤兑、输出载体冲突、非确定性三个硬因素（2.4），"类似问答"落在内容口径而非执行引擎。
- **建议作为附加产物而非替换报告**：保留完整报告的后台/分享/审计价值，回滚成本最低；代价是主表多五列与一次额外 LLM 调用（每交易日 +1 次，不计问答限额，量级可忽略）。
- **不 bump 主表 prompt_version**：回填式设计避免整报重算（2.6）。

---

## 7. 总体验收标准

1. 交易日早盘：KPL 数据就绪后，接收人微信收到的是结论化投资建议（风险段前置、候选分层、竞价触发/失败条件），而非完整复盘报告；后台报告详情仍可查看完整报告与建议两份内容。
2. 雪球定时发布的长文正文为建议内容（含发布层免责段），流水 source_type 为 LIMIT_UP_ADVICE。
3. 配置切回 `REPORT` 模式后，两渠道行为与重构前一致（回滚通道有效）。
4. 建议生成失败时：默认配置下整报降级推送成功、列表页可见降级标识、管理员可一键重生成建议。
5. 周末复推不新增 LLM 调用（建议已缓存场景）。
6. 既有测试全绿（含问答金标 g004），新增测试覆盖第 5 节用例清单。
7. 数据库迁移可升可降，`database-schema.md`、`03_full_schema_with_comments.sql`、ORM、data_catalog 四处一致。

---

## 8. 实施时需确认事项

1. PushPlus 微信端建议全文渲染效果与长度（线上实测验收项）。
2. 建议标题与雪球标题的最终文案口径（本方案给出草案，实施时定稿）。
3. 雪球侧上线节奏：首周是否先 DRAFT/REPORT 模式人工审看再切 ADVICE 自动发布（产品决策）。
4. 按接收人风险偏好定制建议内容：本方案明确不做（非目标 1.4），如有需要另行立项。
