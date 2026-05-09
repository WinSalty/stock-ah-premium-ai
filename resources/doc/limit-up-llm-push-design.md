# 打板数据 LLM 推送功能技术方案

## 1. 背景与目标

本功能用于在 Tushare 打板专题数据更新后，自动生成 A 股涨停与连板复盘报告，并通过 PushPlus 推送给管理员配置的系统用户。核心目标不是简单罗列涨停股票，而是把涨停原因、题材强度、连板梯队、封板质量、技术状态和资金热度整理成可阅读的完整报告，交给 DeepSeek Pro 模型做后续连板可能性、题材延续性和风险信号分析。

业务约束如下：

- 仅使用 Tushare 15000 积分及以下可用接口，高权限接口只作为未来扩展，不进入首版主流程。
- `kpl_list` 作为主数据源之一，因为它包含开盘啦题材、涨停原因、连板状态、竞价与封单等打板关键字段。
- `kpl_list` 文档口径为次日 8:30 更新，因此交易日当天晚上不再推送。
- 数据更新后立刻调用 LLM 生成完整 HTML 报告并推送；同一交易日、同一数据快照和同一提示词版本只调用一次 LLM。
- 周五交易日数据通常周六早上更新，生成后正常推送；周六晚上和周日晚上继续推送同一份缓存报告，不重复调用 LLM。
- 推送内容使用长 HTML；后台保留完整报告，支持管理员查看历史报告和发送记录。
- 接收人配置只选择系统用户，系统用户必须已有 PushPlus 绑定或属于当前默认管理员个人 PushPlus 通道。
- 模型固定使用 `deepseek-v4-pro`，请求参数传 `reasoning_effort="max"`。

## 2. Tushare 数据源

首版数据源限定为可在 15000 积分内使用或可降级的接口：

| 接口 | 用途 | 首版策略 |
| --- | --- | --- |
| `kpl_list` | 开盘啦涨停、炸板、跌停和竞价榜单，含题材、涨停原因、连板状态、竞价成交额、封单、换手率等 | 主数据源，必须在最新交易日有数据后才触发生成 |
| `limit_list_ths` | 同花顺涨停板行情，含涨停原因、封板时间、开板次数、封单额、成交额、换手率等 | 主数据源，失败时记录数据质量但不阻塞 |
| `limit_list_d` | 每日涨跌停统计和个股涨跌停明细 | 补充涨跌停生态、炸板和连板字段 |
| `limit_step` | 涨停连板天梯 | 重点识别二连、三连和空间板 |
| `limit_cpt_list` | 涨停最强板块统计 | 题材强度、板块持续性和板块内梯队 |
| `top_list` | 龙虎榜每日明细 | 补充资金接力、榜单原因和成交占比 |
| `daily`、`daily_basic` | 日线和估值换手字段 | 本地计算 MA、量能、换手、位置和短期涨幅 |

接口调用原则：

- 按交易日请求，避免全市场宽窗口扫描。
- `kpl_list` 缺失时不生成报告，进入等待状态；其它接口缺失时在报告上下文 `data_quality` 中标注。
- 每个接口保留原始 JSON 快照，便于排查 Tushare 字段变化和权限失败。
- 技术指标只对涨停池、二连三连和重点候选股拉取短窗口，控制调用量。
- 技术指标优先读取本地 `a_daily_quote` 批量行情；本地缺口股票才调用 Tushare `daily` 兜底。
- `daily_basic` 优先读取本地最新交易日记录，本地不完整时按交易日批量调用一次 Tushare，再筛选关注股票，避免逐股请求拖慢推送。

## 3. 交易日与调度

### 3.1 常规交易日

- 每天 08:31 到 09:30，每 5 分钟检查一次最近 A 股交易日的 `kpl_list` 数据是否可用。
- 一旦发现最新交易日 `kpl_list` 有数据：
  1. 抓取全部打板专题和辅助数据。
  2. 构建结构化上下文并计算数据快照 hash。
  3. 查询报告缓存，命中则直接推送；未命中则调用 LLM 生成报告。
  4. 生成完成后立即推送给启用的接收人。
  5. 写入推送计划和 PushPlus 流水，防止重复推送。

### 3.2 周五数据

- 周五交易日数据按 `kpl_list` 次日更新口径，在周六上午生成并推送。
- 周六 22:00 和周日 22:00 推送同一份周五缓存报告。
- 周末复推只发送缓存内容，不重新抓数据、不重新调用 LLM；是否接收周末晚间复推由接收人配置里的 `weekend_replay_enabled` 独立控制，不影响常规数据就绪推送和管理员手动推送。

### 3.3 幂等规则

- 报告缓存唯一键：`trade_date + model + prompt_version + data_snapshot_hash`。
- 推送计划唯一键：`analysis_id + scheduled_kind + scheduled_at + user_id`。
- 定时任务可重跑，已发送记录不重复发送；失败记录可由管理员手动重试。
- 早盘轮询虽然会多次触发，但 `DATA_READY` 业务计划时间固定为交易日次日 08:30（东八区），命中缓存后不会重复推送。
- 周六、周日复推计划时间固定为当日配置小时（默认 22:00 东八区），同一天补跑不会重复推送。

## 4. 数据模型

新增表：

### 4.1 `limit_up_analysis_cache`

保存一次交易日打板报告和上下文快照。

关键字段：

- `trade_date`：交易日。
- `model`：固定 `deepseek-v4-pro`。
- `prompt_version`：提示词版本，首版 `limit-up-v1`。
- `data_snapshot_hash`：上下文数据 hash。
- `status`：`PENDING`、`GENERATING`、`READY`、`FAILED`。
- `title`：报告标题。
- `content_html`：完整 HTML 报告。
- `content_markdown`：模型原始 Markdown 或规范化文本。
- `context_json`：送入模型的结构化上下文。
- `data_quality_json`：接口成功/失败/缺失情况。
- `generated_at`、`error_message`。

### 4.2 `limit_up_push_recipient`

管理员配置哪些系统用户接收打板报告。

关键字段：

- `user_id`：系统用户。
- `enabled`：是否启用。
- `weekend_replay_enabled`：是否接收周六和周日晚间缓存报告复推。
- `created_by_user_id`、`updated_by_user_id`：配置操作者。

### 4.3 `limit_up_push_delivery`

记录打板报告的业务推送计划和状态。实际 PushPlus 请求仍复用 `pushplus_message_log`。

关键字段：

- `analysis_id`：报告缓存 ID。
- `user_id`：接收用户。
- `scheduled_kind`：`DATA_READY`、`SATURDAY_REPLAY`、`SUNDAY_REPLAY`、`MANUAL`。
- `scheduled_at`：计划推送时间。
- `status`：`PENDING`、`SENT`、`FAILED`、`SKIPPED`。
- `pushplus_message_log_id`：关联 PushPlus 流水。
- `error_message`、`sent_at`。

### 4.4 `limit_up_report_share`

保存已生成报告的临时公开分享链接。

关键字段：

- `analysis_id`：报告缓存 ID。
- `share_token`：随机分享 token，不包含报告 ID 或用户信息。
- `expires_at`：过期时间，空值表示永久有效。
- `created_by_user_id`：创建分享的管理员。
- `revoked_at`：撤销时间，预留给后续主动失效能力。
- `last_viewed_at`、`view_count`：公开查看统计。

## 5. 后端服务设计

### 5.1 `LimitUpTushareFetcher`

职责：按交易日抓取打板专题数据和短窗口日线数据。

关键规则：

- `kpl_list` 是触发源；若最新交易日无数据，返回 `data_ready=false`。
- 对可选接口捕获权限或网络异常，写入 `data_quality`，不让单个辅助接口拖垮主流程。
- 对技术指标股票池做上限控制，例如最多 120 只，优先二连、三连、高标和题材代表股。

### 5.2 `LimitUpContextBuilder`

职责：把原始接口行整理成 LLM 更容易消化的结构。

输出结构：

- `trade_date`、`generated_basis`。
- `market_emotion`：涨停、炸板、跌停、最高连板、二连三连数量、炸板率。
- `themes`：题材排名、涨停数、连板数、代表股、原因摘要。
- `limit_up_stocks`：涨停池摘要。
- `focus_stocks`：二连、三连、高标、强封单、早盘板、回封板。
- `technical_indicators`：MA、短期涨幅、换手、成交量放大、位置分位。
- `capital_signals`：龙虎榜和热榜信息。
- `data_quality`：接口完整性。

### 5.3 `LimitUpLlmAnalysisService`

职责：复用现有 LLM 端点、耗时记录、日限额和 fallback 机制，新增“打板报告”调用封装。

调用参数：

- `model="deepseek-v4-pro"`
- `reasoning_effort="max"`
- `temperature=0.2`
- `phase="limit_up_analysis"`

提示词策略：

- 给模型明确分析维度，不强制固定模板。
- 强调可自由判断题材强弱、资金接力、连板概率和反证条件。
- 要求输出长 HTML，适合 PushPlus 展示。
- 明确不编造数据；数据缺失时标注不确定性。

### 5.4 `LimitUpPushService`

职责：报告生成、缓存命中、接收人查询、推送和业务流水管理。

核心方法：

- `ensure_latest_analysis_and_push()`：KPL 数据可用后生成并立即推送。
- `push_weekend_replay()`：周六/周日复推周五缓存。
- `manual_regenerate()`：管理员手动重生成。
- `manual_push()`：管理员手动推送指定报告。

## 6. API 与前端

新增菜单权限：`limit_up_push`，默认只给管理员。

新增后端路由：`/api/limit-up-push/...`

接口：

- `GET /reports`：查询历史报告。
- `GET /reports/{id}`：查看完整报告。
- `POST /reports/generate-latest`：管理员手动生成最新报告。
- `POST /reports/{id}/push`：管理员手动推送指定报告。
- `POST /reports/{id}/shares`：管理员为已生成报告创建临时分享链接。
- `GET /reports/{id}/shares`：管理员查询指定报告已生成的分享链接。
- `DELETE /reports/{id}/shares/{share_id}`：管理员将指定分享链接置为失效。
- `GET /public-shares/{token}`：查看分享报告，无需登录，有限期链接过期或链接撤销后不可访问。
- `GET /recipients`：查询系统用户接收配置。
- `PUT /recipients`：保存接收配置。
- `GET /deliveries`：查询推送计划与结果。
- `GET /reports` 支持按关键词、状态、交易日筛选；`GET /deliveries` 支持按关键词、状态、接收用户筛选。

前端页面：`LimitUpPushPage`。

页面模块：

- 接收人设置：只展示系统用户、PushPlus 绑定状态、接收启用状态和周末晚间复推开关，未绑定用户直接禁用。
- 最新报告：展示交易日、生成时间、状态、模型、数据质量、完整 HTML 报告预览。
- 历史报告：按交易日、状态搜索。
- 推送记录：展示业务推送状态和 PushPlus 流水状态。
- 操作按钮：生成最新报告、推送选中报告、创建临时分享、查看已有分享链接、手动失效分享链接、刷新。

## 7. 测试与验收

后端测试：

- Tushare 抓取器：模拟 `kpl_list` 缺失、可用、辅助接口失败。
- 上下文构建：验证二连三连、高标、题材聚合和技术指标字段。
- 缓存幂等：同一 hash 不重复调用 LLM。
- 周末复推：周六/周日使用周五报告，并按接收人的周末晚间开关过滤。
- 接收人：只向启用且可推送用户发送。
- 报告分享：只允许 READY 报告创建分享，支持有限期和永久链接；有限期 token 过期后无法读取，管理员手动失效后也不可继续读取，公开查看会记录访问次数。

前端验证：

- 管理员能看到菜单，普通用户不显示。
- 接收人配置、报告列表、完整报告查看、推送记录搜索可用。
- 管理员可为已生成报告创建临时或永久分享，重复打开分享弹窗时能看到已生成链接并复制或失效；外部查看人无需登录即可打开分享页，有限期链接过期或手动失效后显示不可用。
- 长 HTML 报告在后台预览中不破坏布局。

运维验收：

- Alembic 迁移可执行。
- 后台任务启动日志明确。
- LLM 耗时页面能看到 `limit_up_analysis` 阶段记录。
- PushPlus 消息流水能搜索到打板报告标题和接收人。

## 8. 本地验收记录

验收时间：2026-05-08。

已完成内容：

- 已执行 Alembic 迁移 `20260508_0031_add_limit_up_push.py`，本地 MySQL 已新增报告缓存、接收人配置、业务推送流水三张表。
- 已给管理员补齐 `limit_up_push` 菜单权限，并将 admin 配置为打板推送接收人。
- 使用真实 Tushare 数据生成 `2026-05-07` 上下文：`kpl_list` 126 条，`limit_step` 34 条，二连 16 只，三连 5 只，最高 10 连。
- 批量化技术指标后，真实上下文构建耗时约 4.45 秒；`daily` 本地命中 113 只关注股票，`daily_basic` 通过交易日批量调用补齐 113 只。
- 已使用 `deepseek-v4-pro` 和 `reasoning_effort=max` 生成报告，报告缓存状态 `READY`，HTML 长度约 4753 字符。
- 已通过 PushPlus 真实推送给 admin，业务流水与 `pushplus_message_log` 均为 `SENT`。
- 已通过接口验证报告列表、接收人列表、推送流水均可返回。
- 已通过浏览器烟测确认打板推送菜单、报告列表、接收人和流水页签可访问。

已执行校验：

- `backend/.venv/bin/python -m compileall app tests/test_limit_up_push_service.py`
- `backend/.venv/bin/pytest tests/test_limit_up_push_service.py`
- `frontend npm run build`
