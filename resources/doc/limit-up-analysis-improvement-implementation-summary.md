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
