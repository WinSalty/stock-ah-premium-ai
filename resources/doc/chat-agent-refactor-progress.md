# 智能问答模块 Agent 化重构进度说明

- 关联设计文档：`chat-agent-refactor-design-and-plan.md`（v3）
- 本文档按阶段记录实施进度、验证结果与遗留事项；每个阶段交付时更新对应小节。

## 阶段状态总览

| 阶段 | 内容 | 状态 | 提交 |
| --- | --- | --- | --- |
| 准备 | 基线修复（存量 lint / 失败测试）+ `pre-agent-refactor` tag | 已完成 | 9998d61 |
| 阶段 0 | 前置解耦与基线（llm_client 抽取 / 金标集 / 配置骨架） | 已完成 | 本节提交 |
| 阶段 1 | Agent 引擎替换与旧链路退役（S1-1~S1-7） | 未开始 | - |
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

## 阶段 1：Agent 引擎替换与旧链路退役

（待交付时补充）

## 阶段 2：联网搜索

（待交付时补充）

## 阶段 3：Python 沙箱执行

（待交付时补充）

## 阶段 4：图表呈现

（待交付时补充）

## 阶段 5：治理收尾

（待交付时补充）
