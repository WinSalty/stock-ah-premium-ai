# 智能问答模块 Agent 化重构进度说明

- 关联设计文档：`chat-agent-refactor-design-and-plan.md`（v3）
- 本文档按阶段记录实施进度、验证结果与遗留事项；每个阶段交付时更新对应小节。

## 阶段状态总览

| 阶段 | 内容 | 状态 | 提交 |
| --- | --- | --- | --- |
| 准备 | 基线修复（存量 lint / 失败测试）+ `pre-agent-refactor` tag | 已完成 | 9998d61 |
| 阶段 0 | 前置解耦与基线（llm_client 抽取 / 金标集 / 配置骨架） | 已完成 | 6da8df7 |
| 阶段 1 | Agent 引擎替换与旧链路退役（S1-1~S1-7） | 已完成 | a3d2f01 / 5187240 / 本节提交 |
| 阶段 2 | 联网搜索（博查 web_search / fetch_url / 注入防护） | 已完成 | 本节提交 |
| 阶段 3 | Python 沙箱执行（sandbox_runner / run_python） | 已完成 | 本节提交 |
| 阶段 4 | 图表呈现（Chart DSL → ECharts） | 已完成 | 本节提交 |
| 阶段 5 | 治理收尾（配额口径 / 并发 / 指标治理 / 文档同步） | 已完成 | 本节提交 |

## 准备阶段：基线修复与文档评审（2026-06-12）

### 文档评审结论

对照代码现状（含上一轮会话遗留的阶段 0 未提交改动）完成设计文档全量评审，结论与修订点已写入设计文档第八节（v3）。要点：

- 总体设计成立：2.3 删除边界、3.11 旧能力迁移映射、第四节对旧评审文档编号（B1-B3/R1-R7/E1-E7/P 系列）的处置映射核对无误。
- 9 项设计修订：llm_client 需扩展 messages+tools 接口；日限额 phase 口径必须随切换更新（安全网）；recommend_threshold 改零参数工具；ChartSpec kline 类型矛盾修正；前端改造补充 OverviewPage/PremiumPage 两处调用方；模型口径统一 agent_model；E6 提前到 S1-5；SqlGuard 现状更正；非流式失败落库保持 HTTP 状态码契约。
- 4 项实施口径澄清：金标集基线跑批的成本/配额冲突（全量跑批由使用者择机手动触发）；沙箱 RLIMIT_AS 的 macOS 平台差异；阶段 0 既有进度认定；alembic 命名惯例。

### 基线修复

发现 HEAD 上 `scripts/check.sh` 本身是红的（与问答模块无关的遗留问题）：

- 144 个 ruff 错误（143 E501 + 1 F401），集中在 `limit_up_push_service.py`（102）与其测试（36），为此前打板推送相关提交遗留。
- 2 个失败测试：`test_auth_service::test_profile_update_only_changes_basic_fields`（默认权限清单新增 dividend_reinvestment 后断言未更新，已改为对齐 `DEFAULT_ROLE_PERMISSIONS` 单点定义）；`test_market_data_orchestrator::test_orchestrator_uses_cache_for_recent_quote_package`(写死 2026-06-01 漂移出 7 天新鲜度窗口，已改为动态当日日期）。

修复后 `check.sh` 全绿，作为独立提交先行落库，使后续每阶段"check.sh 全绿"验收有效；并打 tag `pre-agent-refactor` 作为旧链路回滚锚点。

## 阶段 0：前置解耦与基线（2026-06-12 交付）

### S0-1 抽取 llm_client（完成）

- 新增 `backend/app/services/llm_client.py`：端点选择/双端点 fallback/同步与流式 chat completion（含 response_format）/可重试判定/日调用硬上限/`llm_call_metric` 指标落库，全部自 `llm_service.py` 逐行平移（行为一致性已比对：超时常量、限额时区与容错放行、fallback 触发条件、payload 构造、截断长度均不变）。
- 指标独立短会话（R3）按 opt-in 设计：构造时传 `metric_session_factory=SessionLocal` 即用独立会话写指标。雪球发布已切换并 opt-in；问答主链路暂不传（有意保持旧链路行为不变，Agent 引擎接入时显式传入，R3 在新引擎中终态落地）。
- 依赖方切换：`xueqiu_publish_service` 完整切到 `LlmClient.chat_completion` 公开接口（消除私有方法越界调用）；`limit_up_push_service` / `nine_turn_push_service` 的 `LLM_CHAT_TIMEOUT_SECONDS` import 切到 llm_client（两者对 llm_service 的唯一依赖，自建 reasoning 调用按最小改动原则保留）。
- `llm_service.py` 改为委托 llm_client 并经 re-export 维持旧 import 路径，净删约 550 行平移代码。

### S0-2 金标集（脚本与用例集交付；基线跑批待手动触发）

- `backend/tests/golden/chat_golden_set.json`：58 条用例、21 个类别，覆盖推荐三段式、个股研究、分红再投、自选阈值、问数、通用问答、拒答边界、追问、时效联网、沙箱计算、出图、注入对抗与阈值推荐。
- `backend/tests/golden/run_golden_set.py` + `scripts/run-golden-set.sh`：进程内调用引擎（自动识别 Agent/旧链路），支持 `--category/--ids/--limit` 采样、`--resume` 断点续跑、命中日限额优雅中止；产出按类别命中率的 Markdown 报告（默认写 `.runtime/golden-reports/`）。
- 基线跑批未自动执行（见设计文档 v3 修订 10）：全量约 200~400 次外部 LLM 调用，超过日限额且产生真实费用，由使用者择机执行 `./scripts/run-golden-set.sh --engine legacy --report-tag baseline`。

### S0-3 配置骨架（完成）

- `config.py` 新增设计 3.8 全部 13 项配置（agent/bocha/沙箱），带业务口径中文注释；`resolve_bocha_api_key()` 文件优先、环境变量兜底；`.env.example` 同步。
- 新增 `tests/test_config.py` 4 用例：key 文件优先+strip、env 兜底、缺省 None、默认值与设计 3.8 一致。

### 验证

- `ruff check app tests` 零错误；`pytest` 248 passed；前端 `npm run build` + `npm audit --omit=dev` 通过。
- 配置缺省时现有行为完全不变（全量测试通过佐证）。

## 阶段 1：Agent 引擎替换与旧链路退役（2026-06-12 交付）

### 交付内容

- **S1-1 引擎骨架**（`backend/app/services/agent/`）：`engine.py` 主循环（非流式迭代解析 tool_calls + 最终回答重发流式 + 迭代耗尽强制收尾 + 失败统一 error 事件）、`tool_registry.py`（OpenAI specs/配额强制/异常转错误文本）、`events.py`（六类事件与 NDJSON 协议对齐）、`budget.py`（轮内配额组、材料截断、messages 预算压缩、LlmDailyLimitExceeded 迁入）、`prompts.py`（系统提示词 v1，`PROMPT_VERSION="agent-v1"`，能力声明随工具目录动态拼装）、`data_catalog.py`（数据字典单点定义）。`llm_client` 扩展 messages+tools 非流式/流式接口（fallback/日限额/指标三件套生效）；`agent_iteration` 计入日限额安全网（v3 修订 2）。
- **S1-2 本地三工具**：`query_database`（SqlGuard 强化为纯 AST 判定 + CTE 支持 + 多语句解析判定；执行错误回填模型自修复，替代旧 repair_sql；分红再投 status 兼容口径改入工具描述，不再静默改写 SQL）、`get_stock_data`（复用编排器与识别器，歧义返回候选让模型确认）、`recommend_threshold`（零参数化，公式逐行平移并有数值回归保护）。
- **S1-3 路由切换**：流式 worker 消费引擎事件流转发真实进度；失败统一落 assistant 消息（流式与非流式一致，R7）；非流式聚合兼容，HTTP 状态码契约不变（429/502，v3 修订 9）；每次工具执行写 `llm_call_metric`（phase=tool_*，provider 可标注外部供应商）。
- **S1-4 数据迁移**：`20260612_0048` 增量迁移（`tool_trace_json`/`charts_json`/`prompt_version`），已在本机 MySQL 执行验证可升；历史接口透出解析后的 charts/tool_trace。
- **S1-5 前端协议对齐**：新事件联合类型 + 坏行容错（B3）；真实工具时间线（流式实时 + 完成后折叠"本轮执行 N 步"）；`buildTurns` 相邻配对（E6 提前修复）；删除假进度轮播与模型选择器（v3 修订 6）；Overview/Premium 阈值入口适配（v3 修订 5）；chart 事件先存储，阶段 4 渲染。
- **S1-6 提示词与业务回归**：真实端到端用例 4/4 通过——本地取数（g064，自主调 query_database 查 AH 溢价）、泛推荐反问偏好（g001，零工具调用）、违法请求拒答（g043）、阈值工具（g100，公式值 10.55 正确引用）。指标链路验证：单轮 2 次 agent_iteration + 工具计量 + answer_stream，全部带 prompt_version。
- **S1-7 旧链路退役**：删除 `llm_service.py`（约 4100 行）与 `test_llm_service.py`（58 用例）；llm_client 行为测试迁移为 `tests/test_llm_client.py`（10 用例，端点/降级/限额/指标/messages 接口）；金标跑批器 legacy 模式改为指引切换 `pre-agent-refactor` tag 补跑。

### 验证

- `ruff check` 零错误；后端 `pytest` 240 passed（新增引擎 13 / 工具 20 / SqlGuard 6 / 路由 7 / llm_client 10）；前端 `npm run build`（tsc + vite）通过。
- 回滚口径：S1-7 删除为独立 commit，revert 即恢复旧链路；DB 变更全为增列无损。

### 遗留与说明

- 金标集全量基线/回归跑批仍由使用者择机执行（费用与日限额约束，见 v3 修订 10）。
- 一轮典型消耗 2~5 次外部 LLM 调用（实测简单取数问题 3 次），与设计预估一致。

## 阶段 2：联网搜索（2026-06-12 交付）

- **S2-1 web_search**（`tools/web_search.py`）：博查 Bocha API（httpx 15s 超时、失败重试 1 次）；结果包 `<external_content>` 数据块；进程内 LRU+TTL（128/10 分钟）缓存；key 缺失或当日配额（`agent_web_search_daily_limit`，计数基准 phase=tool_web_search/tool_fetch_url）用尽时 web 工具整体从目录降级移除，系统提示词能力声明同步收敛为"无联网能力"。
- **S2-2 fetch_url**：标准库 HTMLParser 正文抽取（丢弃 script/style/nav）；SSRF 防护 `_assert_public_http_url`——DNS 解析后拒绝私网/回环/链路本地/保留地址，仅 80/443，重定向禁自动跟随、逐跳重新校验。
- **S2-3 注入防护**：三层——`<external_content>` 数据块包裹 + `sanitize_external_text` 转义协议词（`{{chart:`、`</external_content>`）+ 系统提示词"外部内容安全规则"段（仅联网开启时注入）声明块内文字是数据非指令。
- 测试：`test_agent_web_search.py` 22 用例（主路径/缓存/重试/转义/SSRF 5 段网段/重定向防护/正文抽取/配额降级/提示词）。
- 已知项（个人项目可接受，记入阶段 5 跟踪）：DNS rebinding TOCTOU（校验与建连各解析一次 DNS）；外部数据双引号未转义（数据在正文行非属性内，风险低）；配额时区依赖 DB 服务器时钟（与 created_at 的 server_default 口径需在阶段 5 统一）。

## 阶段 3：Python 沙箱执行（2026-06-12 交付）

- **S3-1 SandboxExecutor + sandbox_runner**：`sandbox_runner.py` 是自包含独立脚本（不 import 项目模块），以 `{venv_python} -I sandbox_runner.py main.py {cpu} {mem}` 启动；四层约束——隔离子进程（-I + 环境白名单仅 PATH/LANG + 临时 cwd + start_new_session）、rlimit（CPU/AS/FSIZE，macOS 上 RLIMIT_AS 设置失败容错降级，v3 修订 11）、audit hook（禁 socket/subprocess/os.exec*/fork/ctypes.dlopen、禁工作目录外写）、父进程墙钟超时整组 SIGKILL。关键修复：装钩子前预热 pandas/numpy，避免合法 C 扩展加载被"禁动态加载"误杀。
- **S3-2 run_python 工具**：本轮 query_database/get_stock_data 完整结果写入沙箱 `data/` 目录 + manifest.json 回填；stdout/stderr 截断；非零退出模型可修正重试。
- **S3-3 审计与配额**：代码与输出经引擎统一写 `llm_call_metric`（phase=tool_run_python）；日配额 `agent_run_python_daily_limit` 用尽当日降级。
- 测试：`test_agent_sandbox.py` 14 通过 + 1 跳过（真实子进程：合法 pandas 计算/死循环 CPU 杀/墙钟超时/socket/subprocess/os.system/越界写/目录内写/非零退出/stdout 截断/manifest/配额；超内存用例 macOS 跳过）。真实端到端：g080"画 A/H 溢价走势图"完整经过 4 次取数→2 次沙箱计算→render_chart。

## 阶段 4：图表呈现（2026-06-12 交付）

- **S4-1 Chart DSL + render_chart**：`chart_schema.py` pydantic 模型同步导出 JSON Schema 作工具参数；按 chart_type 联动校验（line/bar/scatter 标量等长、kline 四元组、pie 扇区名等长、dual_axis 左右轴齐全），消除 list[float] 与四元组类型矛盾（v3 修订 4）；`render_chart` 校验通过→自增 chart_id→登记 turn_state→返回 `{{chart:cN}}` 占位符，引擎据 extra 下发 chart 事件；轮内 4 张配额。
- **S4-2/S4-3 前端渲染**：`ChatChart.tsx` 把 ChartSpec 映射为 ECharts option（统一色板、6 图型、双轴、移动端自适应、空数据占位、note 数据来源）；ChatPage 按 `{{chart:id}}` 正则分段交替渲染文本与图表，未引用图表末尾兜底，未知 id 渲染为空；Word 导出占位符降级为"【图表】标题 + 数据表格"。
- **S4-4 出图策略**：提示词补充"图表确实比文字更有助理解时才出图，单值不出图"，与计算/搜索策略统一调版。
- 测试：`test_agent_chart.py` 13 用例（6 图型 × 合法/非法校验矩阵 + 占位符登记 + 配额）；前端 `npm run build` 通过。

## 阶段 5：治理收尾（2026-06-12 交付）

- **S5-1 配额按轮计费（R1）**：`_enforce_daily_round_limit` 按当日（东八区）用户消息条数校验 `chat_daily_round_limit`（默认 50），在落库用户消息前校验，超限返回 429"今日问答次数已达上限 N 轮"，不产生孤立提问；流式与非流式入口均接入。内部 `llm_daily_call_limit` 继续作安全网。
- **S5-2 流式并发上限（R5）+ 指标治理（R4）**：进程级 `BoundedSemaphore(chat_stream_max_concurrency=8)`，流式请求限时获取名额（`chat_stream_acquire_timeout_seconds=15`），拿不到返回 503 繁忙；worker `finally` 释放，启动前异常路径也释放，无名额泄漏。指标保留期清理 `llm_metric_maintenance.cleanup_expired_metrics`（分批删除早于 `llm_metric_retention_days=90` 天的记录）+ `scripts/cleanup-llm-metrics.sh`（手动/cron 触发，不挂主进程调度）。
- **S5-3 魔法字符串治理（E5）**：默认会话标题统一为 `schemas/chat.py` 的 `DEFAULT_CHAT_SESSION_TITLE` 常量，schema 默认值、`_session_title` 兜底、`_touch_session` 改名判定三处后端引用同一常量（修正此前"新的数据问答"/"新的投资问答"不一致）。E6（前端 turn 配对）已在 S1-5 提前修复。
- **S5-4 文档同步**：`startup-guide.md`（智能问答改为 Agent 引擎说明、联网/沙箱/两层配额/并发/无模型选择器）、`database-schema.md`（llm_chat_message 新增列、llm_call_metric 的 phase 维度与 prompt_version、保留期清理）、本进度文档与设计文档状态同步更新。
- 测试：`test_chat_governance.py` 6 用例（按轮限额阻断/放行/非流式接入、信号量获取释放平衡、指标清理删旧留新/关闭不删）。
- 已知后续项（非阻塞，记录备查）：联网搜索的 DNS rebinding TOCTOU 与外部数据双引号转义、配额时区与 DB 服务器时钟口径统一、指标 payload 成功采样（当前全量存储，留 `LLM_METRIC_RETENTION_DAYS` 清理控膨胀）——个人项目当前规模可接受，列为后续增强。

## 试用反馈修复（2026-06-12，上线后第一轮真实试用）

| 问题 | 根因 | 修复 |
| --- | --- | --- |
| 回答出现奇怪标签直接渲染（追踪 219bddf9） | 设计 3.1"最终回答重发流式"缺陷：迭代已产出无工具回答，但重发的流式请求不带 tools，模型二次生成时改判去调工具，把 DeepSeek DSML 工具调用语法当正文输出 | 引擎改为**直接复用迭代内容**分片下发（每轮还省 1 次外部调用）；保留的流式收尾路径（迭代耗尽/内容异常补救）加双层防护：先注入禁止工具语法指令，流式头部缓冲 64 字符做协议泄漏检测，命中即吞掉整段改发兜底文案。新增 3 个单测覆盖复用/补救/拦截路径 |
| 图表先渲染后页面似已结束、回答最后突然出现（追踪 eefc10a0） | LLM 迭代期（实测 10.7s）无任何事件下发，前端等待提示只在"无工具事件"时显示，工具步骤完成后到首个 delta 之间没有进行中指示 | 时间线常驻"正在分析与组织回答..."思考行（Spin），覆盖首个事件前/工具步骤之间/最终回答生成前三段空窗；原 LlmProgressNote 等待提示收敛进时间线避免双指示 |
| 移动端无法正常显示 ECharts 图表 | echarts-for-react + size-sensor 在聊天气泡容器环境下测量失效：echarts 实例创建但 canvas 图层从未绘制（本地浏览器复现确认，部分环境 ResizeObserver 完全不触发） | ChatChart 改为直接管理 echarts 实例：初始化显式传像素宽高（官方对尺寸不可测容器的标准做法）+ rAF 轮询等待容器完成布局 + ResizeObserver 与 window resize 双保险跟踪尺寸；本地移动端视口（375px）复现验证 canvas 正常绘制 |

注：复用迭代内容后，纯回答轮次的指标只有 `agent_iteration`（无 `answer_stream`），LLM 耗时页按 phase 查看时口径相应变化；`answer_stream` 仅出现在迭代耗尽强制收尾与补救生成两条路径。

## 试用反馈修复·第二轮（2026-06-12）

| 问题 | 根因 | 修复 |
| --- | --- | --- |
| 回答为空（追踪 977cf4a3） | 用户追问"再给我一遍图"，模型直接输出上一轮的 `{{chart:c1}}` 占位符；图表登记按轮隔离，本轮未登记，前端按输出净化口径把未知占位符渲染为空 → 整条回答为空 | 三层：①提示词 v2 输出契约声明"占位符仅当轮有效，重新展示必须重新调用 render_chart"；②引擎对最终回答剥离未登记占位符；③剥离后为空时回填纠错指令继续迭代，给模型重新出图（或改文字）的机会。真实回归：同场景模型重新查库+重新登记图表，回答完整 |
| 时间线出现"配额"字样不可理解 | 模型反复调同一工具触顶轮内配额（搜索/抓取各 3 次、取数合计 6 次），工具失败步骤摘要"本轮配额已用尽"原样上时间线 | 面向用户的摘要改为"本轮调用次数已达单轮上限，已基于已有数据继续"（回填给模型的说明保留原文）；取数配额组 6→8（个股全景分析实测频繁触顶） |
| 个股分析质量回退（追踪 7b6e1175 vs 旧 891617856） | 旧链路的 11 条研究员方法论（`_stock_report_instruction`）与"多年财务趋势表"契约未移植进新系统提示词；模型转而把分红再投回测表年化当核心论据 | 提示词 v2 移植 11 条个股研究方法论（利润质量拆解/现金流对照/资产负债匹配/估值交叉验证/按公司类型调整重点/数据缺口与反证条件/先看完整覆盖期再点评近两年+第二节先给财务趋势表）；工具策略明确：个股基本面分析以 get_stock_data 数据包为主材料，回测表仅限分红再投/保守型筛选场景 |
| LLM 耗时页一轮对话占多条记录排查不便 | Agent 化后一轮产生多条 phase 记录（迭代/工具/收尾），明细平铺 | 后端新增 `GET /llm-metrics/rounds` 按 question_id 聚合分页（阶段数/LLM调用数/工具数/失败标记/总耗时/起止时间）；前端改 Tabs 双视图：默认"按对话轮"一轮一行、展开懒加载阶段明细（缓存已加载轮），原"阶段明细"视图保留为兜底排查入口 |

- 提示词版本 `agent-v1` → `agent-v2`（prompt_version 随指标落库可对比效果）。
- 新增测试：引擎占位符净化/纠错重试 3 例、rounds 聚合口径 1 例；配额摘要断言更新。

## 重构完成总结

七个阶段（准备 + 阶段 0~5）全部交付：旧的固定流水线问答已彻底替换为 LLM 通过 function calling 自主编排工具的 Agent 引擎，新增联网搜索、Python 沙箱计算、受控图表三类能力，前端从假进度升级为真实执行时间线与内嵌图表。后端 294 passed + 1 skipped（macOS 平台跳过），前端 `npm run build` 通过，全程 `scripts/check.sh` 口径绿。旧链路删除为独立 commit，回滚 tag `pre-agent-refactor` 可用，DB 变更全为增列无损。金标集（58 用例）与跑批器就位，全量回归/基线跑批因真实 LLM 费用由使用者按需触发。
