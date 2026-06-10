# 打板推送模块涨停分析改造落地说明

- 创建日期：2026-06-10
- 涉及代码：`backend/app/services/limit_up_push_service.py`、`backend/app/core/config.py`、`backend/tests/test_limit_up_push_service.py`
- 参考方案：`resources/doc/limit-up-analysis-code-review-and-improvement-plan.md`
- 落地目标：按复核后的结论尽可能完成原方案内容，同时修正原方案中与 Tushare `kpl_list` 官方口径不一致的部分。

## 一、已落地处理

### 1. 早盘轮询幂等与快照稳定性

- `ensure_latest_analysis_and_push` 增加当日 READY 报告优先复用逻辑，并限定同 model、同 prompt_version，避免早盘轮询时因为上游数据行序或补数扰动重复生成 LLM 报告。
- `_snapshot_hash` 增加递归规范化逻辑，对 list 元素按交易日、代码、题材/名称等稳定键排序后再序列化，避免同一业务快照仅因列表顺序变化产生不同哈希。
- 推送流水增加服务层业务幂等：非手动推送按 `trade_date + scheduled_kind + scheduled_at + user_id` 查询已有流水，避免跨 analysis_id 重复推送。

### 2. GENERATING 僵死恢复

- 新增配置 `LIMIT_UP_PUSH_GENERATING_STALE_MINUTES`，默认 30 分钟。
- `ensure_analysis_for_trade_date` 遇到同快照 `GENERATING` 记录时，会判断 `updated_at` 是否超过阈值；超过后复用原记录重置并重跑，避免进程中断导致当日报告永久卡住。
- 超时判断按数据库 `updated_at` 的东八区 naive 口径比较，没有改动现有 UTC-naive 入库字段的展示/存储口径。

### 3. KPL 口径、情绪统计与昨日对照

- 主涨停池显式传 `tag="涨停"`。虽然 Tushare 官方文档确认 `kpl_list.tag` 默认就是涨停，但显式传参能固定代码口径。
- 额外拉取 `tag="炸板"` 与 `tag="跌停"`，用于炸板率和质量提示，不再把它们混入涨停池。
- `_market_emotion` 改为基于 `_board_level` 的显式板高统计，废弃子串匹配，避免“12连板被计入二连”等问题。
- `_board_level` 支持 `N天M板`，无法识别时返回 0，并在分层上下文中过滤，避免未知状态默认归为首板。
- 新增 `emotion_cycle`：包含炸板率、1进2/2进3/3进4 晋级率、昨日涨停今日平均涨幅/高开率、最高板变化。

### 4. 数据增强

- `_compact_stock_row` 透出 `tag`、`board_level`、`limit_type`、`market_type`、`open_times`、`seal_ratio_pct` 等字段。
- 增加 10cm/20cm/30cm 涨停制度识别，并在两三连和高连板上下文中加入 `stocks_by_limit_type` 分组。
- `theme_summary` 增加题材内部 `ladder`，按板高和封流比保留前 5 个标的，支持题材内龙一、龙二和卡位判断。
- 最高板高度不再从 `limit_step.nums` 提取，改为直接由 KPL 状态识别；`limit_step` 仅作为梯队记录数量参考。

### 5. LLM 阶段稳定性与 Prompt 升级

- JSON 阶段调用 `_chat_completion_with_reasoning(..., json_mode=True)`，请求体透传 `response_format={"type":"json_object"}`，原 `_extract_json_payload` 保留为二道防线。
- CHAIN_FOCUS / HIGH_BOARD_FOCUS 文本阶段增加确定性 HTML 降级，LLM 异常时用入选理由、连板状态和筹码摘要生成表格，不阻断最终合成。
- FINAL_REPORT 仍保留失败抛错，不做降级，确保最终报告质量底线；依赖阶段缓存和 GENERATING 超时恢复进行后续重试。
- Prompt 增加情绪周期定位框架，要求先判断启动期/发酵期/高潮期/分歧期/退潮期/冰点期，并让个股观察与周期一致。
- 选股阶段增加固定评分维度：题材地位、封板质量、资金信号、筹码/技术状态。
- 重点分析阶段增加每股篇幅约束和次日竞价观察清单要求。
- 最终合成输入瘦身：移除完整 `supplements` 和 `stage_quality` 原文，仅保留压缩后的入选股票字段、筹码结论字段和两个重点 HTML 片段。
- 阶段缓存版本从 `:v1` 升为 `:v2`，默认 `LIMIT_UP_PUSH_FINAL_PROMPT_VERSION` 升为 `limit-up-multi-stage-v2`，避免新 prompt 命中旧阶段缓存。

### 6. 低风险清理

- 删除未被多阶段管道调用的旧 `_limit_up_user_prompt`。
- `_is_st_stock_row` 仅对含 `ts_code` 的个股行生效，避免概念/题材接口中板块名称包含 ST 时被误删。
- 修正 `_chat_completion_with_reasoning` 里 `client.post(...)` 的闭括号缩进，让响应处理逻辑保持在清晰的调用边界之后。

## 二、未完全按原方案处理的部分

### 1. P0-2 未按“涨停池可能混入炸板/跌停”定性处理

原方案认为 `kpl_list` 不传 `tag` 可能返回涨停、炸板、跌停等混合行。复核 Tushare 官方文档后确认：`tag` 参数默认为 `涨停`。因此本次没有把该问题继续按 P0 处理，也没有把默认返回视作混合池。

实际处理方式是：

- 主池显式传 `tag="涨停"`，保证口径清晰。
- 炸板和跌停通过额外请求单独拉取，只用于情绪周期，不混入涨停股候选池。
- 保留并修复 `_market_emotion` 子串统计问题，因为这是代码内真实存在的统计风险。

### 2. 未做数据库唯一索引迁移

原方案建议把 delivery 唯一键从 `analysis_id` 改为 `trade_date + scheduled_kind + user_id`。当前仓库没有 Alembic 版本目录，本次若直接改模型唯一约束，无法同步提供可执行迁移和历史重复流水清理脚本，风险大于收益。

实际处理方式是：

- 暂保留数据库结构不变。
- 在服务层新增 `_delivery_for_business_plan`，非手动推送按交易日、计划类型、计划时间和用户查重，先满足线上重复推送防护。
- 若后续建立迁移体系，再补数据库唯一索引与历史数据清理 SQL。

### 3. 未新增指数锚

原方案建议加入上证/深成指数、两市成交额、涨跌家数等大盘环境锚。当前本地模型未发现指数日线表，若临时接入 `index_daily` 会引入新接口权限、数据质量记录和可能的额外同步设计。

实际处理方式是：

- 本次未新增指数接口。
- 先完成与现有 KPL、日线、daily_basic、筹码接口直接相关的数据增强。
- 后续如需指数锚，建议先补本地指数表或明确 Tushare 指数接口权限，再纳入 data_quality 体系。

### 4. `raw_supplement` 未从 `context_json` 完全移除

原方案建议把 `raw_supplement` 移出快照或单独存档。当前后台详情页和既有测试仍依赖该字段可见性，本次没有删除该字段。

实际处理方式是：

- 删除不被消费的 `analysis_instructions`。
- 保留 `raw_supplement` 作为审计上下文。
- 通过 `_snapshot_hash` 规范化解决行序扰动问题，降低它对重复生成的影响。

## 三、测试覆盖

新增或调整的测试覆盖：

- 快照列表行序变化哈希不变。
- 当日 READY 报告复用，接口行序变化不重复生成、不重复推送。
- GENERATING 超过阈值后复用原记录重跑。
- 情绪统计基于显式板高，并计算炸板率、晋级率、昨日溢价。
- JSON 阶段开启 `json_mode`。
- 重点文本阶段 LLM 失败时降级输出 HTML。

已执行：

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend && .venv/bin/python -m py_compile app/services/limit_up_push_service.py app/core/config.py tests/test_limit_up_push_service.py
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend && .venv/bin/pytest tests/test_limit_up_push_service.py
```

目标验证结果：

- 变更文件 Python 编译通过。
- `tests/test_limit_up_push_service.py` 结果：`23 passed`。

补充执行过后端测试全集：

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend && .venv/bin/pytest tests
```

结果：`239 passed, 2 failed`。失败用例为 `tests/test_auth_service.py::test_profile_update_only_changes_basic_fields` 与 `tests/test_market_data_orchestrator.py::test_orchestrator_uses_cache_for_recent_quote_package`，均不在本次打板推送改造触碰范围内，需另行排查。

## 四、上线注意事项

- `LIMIT_UP_PUSH_FINAL_PROMPT_VERSION` 默认已从 `limit-up-multi-stage-v1` 升级到 `limit-up-multi-stage-v2`，上线后阶段缓存会按新版本重新生成。
- 主报告 `LIMIT_UP_PUSH_PROMPT_VERSION` 未强制升级，避免报告主缓存整体失效；早盘自动任务会优先复用当天同主版本 READY 报告。
- 新增炸板/跌停/昨日涨停 KPL 请求会增加少量 Tushare 调用，但仍在现有轮询链路内记录 data_quality，失败不阻断主报告生成。

## 五、代码评审意见（追加）

- 评审日期：2026-06-11
- 评审对象：commit `bb40118`（完善打板推送分析稳定性与情绪指标）
- 评审方式：逐行阅读 `limit_up_push_service.py` 全部 diff、`config.py`、新增测试；核对模型字段（`ADailyQuote.pre_close` 存在）；复跑 `tests/test_limit_up_push_service.py` 结果 `23 passed`，与第三节声明一致（后端全集的 2 个既有失败用例未复验）。

### 总体结论

实现与原方案对应良好：早盘幂等、快照规范化、服务层推送查重、情绪周期指标、分层数据增强、Prompt 升级和文本阶段降级均已按预期落地；对未按原方案处理部分（kpl_list tag 默认口径复核、不做唯一索引迁移、不加指数锚）的说明诚实且理由成立。**评审结论：通过，但 P1-1 需尽快跟进。**

### 需处理项

**P1-1 `_is_generating_stale` 的时区基准依赖数据库服务器时区，存在环境性失效风险**

`updated_at` 由 `TimestampMixin` 的 `func.now()` 生成（数据库服务器时间），代码注释断言其为东八区 naive 并用 `_now_local()` 对齐比较。但项目其它应用写入字段（`generated_at`、`sent_at`）口径是 UTC naive（`_now_naive()`），同一张表存在两种时间基准；该比较的正确性完全取决于生产 MySQL 的 `time_zone` 变量，而 `database_url` 与 engine 配置均未固化该变量。若部署环境 MySQL 为 UTC（Docker 默认常见），`_now_local()` 恒比 `updated_at` 快约 8 小时，30 分钟阈值瞬间满足——**所有 GENERATING 记录都会被判定为僵死**，正在生成中的报告可能被并发入口（手动 `generate-latest` + 调度器）重置重跑。

现有测试仅用 monkeypatch 同时固定两端时间验证了"超阈值重跑"的正例；没有用数据库真实生成的 `updated_at` 验证"未超阈值不重置"的负例（SQLite 的 `CURRENT_TIMESTAMP` 恰好是 UTC，真实负例测试可以直接暴露该问题）。

建议修复方向：不依赖 server 生成的 `updated_at` 做僵死判断，改为在进入 GENERATING 时由应用写入 `generation_started_at`（沿用 `_now_naive()` UTC naive 口径），比较两个同口径时间；若暂不加字段，至少在部署文档中固化"MySQL `time_zone` 必须为 +8:00"的约束，并补充上述负例测试。

### 建议处理项

**P2-1 焦点股票选取与板级识别口径不一致**

`_focus_ts_codes` 仍用旧子串匹配（"2连"/"3连"/"连板"/"首板"）挑选技术指标补数对象，而分层上下文已改用增强后的 `_board_level`（支持 "N天M板"）。状态形如 "5天3板" 的股票会进入 `chain_board_context` 参与 LLM 筛选，但拿不到 technical 指标，LLM 评分和兜底排序（依赖 `amount_ratio_5d`）对这类股票失真。建议 `_focus_ts_codes` 统一改用 `_board_level(row) >= 1` 口径。

**P2-2 炸板率分母可能对"回封股"重复计数**

KPL 口径中"炸板后回封"的股票可能同时出现在 `tag=涨停` 与 `tag=炸板` 两个池，`Decimal(len(today_rows) + len(broken_rows))` 会把回封股计入两次，炸板率系统性偏高。建议按 `ts_code` 去重：分母取两池代码并集，或炸板池先剔除已在涨停池中的代码，并在 `emotion_cycle` 输出中注明口径。需要先用真实交易日数据验证 KPL 两池是否确有交集。

**P2-3 降级片段会固化为当日最终报告，无自动重试入口**

CHAIN_FOCUS / HIGH_BOARD_FOCUS 降级后 FINAL_REPORT 正常合成，analysis 进入 READY；早盘轮询的 READY 早退逻辑使降级内容成为当日最终推送内容，后续不会自动重试（失败阶段缓存虽不会被复用，但没有重入点）。属可接受的设计取舍，但建议：发生 `FAILED_FALLBACK` 时在报告列表接口上暴露"含降级片段"标识（stage_quality 中已有记录，前端可读取），便于管理员决定是否手动重新生成。

### 记录项（Nit）

- `_canonicalize_for_hash` 对所有 list 排序，哈希对元素顺序不敏感：`selected_stocks` 的 priority 顺序变化（语义不同）会命中同一阶段缓存。当前 selection 元素自带 `priority` 字段、排序不丢信息，实际影响极小，仅作记录。
- `optional_payload["prev_trade_date"] = [{"trade_date": ...}]` 把标量塞进行集合形状传参，`_market_emotion` 再从 `rows[0]` 取回，绕路；直接给 `_assemble_context` / `_market_emotion` 增加 `prev_trade_date` 参数更直接。
- `_prev_limit_up_premium_metrics` 的 `quote_sample_count` 取行情命中映射大小，而 `avg_pct_chg` 实际样本是 `pct_values` 数量，两者可能不同，字段命名易误读。
- 高连板筛选 prompt 未像两三连筛选那样加入 `score_detail` 固定评分维度，第一节"选股阶段增加固定评分维度"的表述实际只覆盖了 chain selection，建议补齐或修正表述。

### 信息项（FYI）

- DeepSeek `json_object` 模式要求消息中包含 "json" 字样，现有 JSON 阶段 prompt 均含"输出严格 JSON"，满足约束；后续修改 prompt 时注意保留该字样，否则兼容接口会直接报错。
