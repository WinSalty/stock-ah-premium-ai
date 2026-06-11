# 智能问答模块 Agent 化重构进度说明

- 关联设计文档：`chat-agent-refactor-design-and-plan.md`（v3）
- 本文档按阶段记录实施进度、验证结果与遗留事项；每个阶段交付时更新对应小节。

## 阶段状态总览

| 阶段 | 内容 | 状态 | 提交 |
| --- | --- | --- | --- |
| 准备 | 基线修复（存量 lint / 失败测试）+ `pre-agent-refactor` tag | 已完成 | 9998d61 |
| 阶段 0 | 前置解耦与基线（llm_client 抽取 / 金标集 / 配置骨架） | 已完成 | 6da8df7 |
| 阶段 1 | Agent 引擎替换与旧链路退役（S1-1~S1-7） | 已完成 | a3d2f01 / 5187240 / 本节提交 |
| 阶段 2 | 联网搜索（博查 web_search / fetch_url / 注入防护） | 未开始 | - |
| 阶段 3 | Python 沙箱执行（sandbox_runner / run_python） | 未开始 | - |
| 阶段 4 | 图表呈现（Chart DSL → ECharts） | 未开始 | - |
| 阶段 5 | 治理收尾（配额口径 / 并发 / 指标治理 / 文档同步） | 未开始 | - |

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

## 阶段 2：联网搜索

（待交付时补充）

## 阶段 3：Python 沙箱执行

（待交付时补充）

## 阶段 4：图表呈现

（待交付时补充）

## 阶段 5：治理收尾

（待交付时补充）
