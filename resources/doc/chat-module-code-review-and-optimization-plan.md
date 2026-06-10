# 智能问答模块代码评审与问数链路优化方案

- 创建日期：2026-06-10
- 评审范围：`backend/app/api/routes_chat.py`、`backend/app/services/llm_service.py`、`backend/app/services/sql_guard_service.py`、`backend/app/schemas/chat.py`、`backend/app/db/models/chat.py`、`frontend/src/pages/ChatPage.tsx`、`frontend/src/api/chat.ts`
- 评审目的：梳理问答模块当前实现质量，识别缺陷与风险，对整体问数（NL→SQL/补数→回答）链路和提示词体系提出优化方向，并给出分阶段开发计划。

## 一、现状链路梳理

单轮问答的完整链路（流式与非流式共用核心逻辑）：

```
用户提问
  ├─ 1. 服务介绍拦截（本地关键词，命中直接返回固定文案）
  ├─ 2. 阈值推荐拦截（前端传 threshold_recommendation 时走专用链路，本地确定性公式 + LLM 解释）
  ├─ 3. 追问分流（有会话历史时调用轻量 LLM 判断 follow_up / new_task）
  │     └─ follow_up 且置信度 ≥ 0.55 → 只带历史直接回答，跳过路由和问数
  ├─ 4. 前置路由（LLM 输出 is_answerable / needs_sql / answer_mode / data_demands）
  │     ├─ 本地确定性覆盖：分红再投关键词强制 SQL 路由；投资推荐入口强制偏好澄清/推荐路由
  │     └─ 路由失败 → 本地关键词兜底路由
  ├─ 5. 股票识别（直接抽取 LLM 验真 → 失败回落候选消歧 LLM）
  ├─ 6. 数据准备（_prepare_answer）
  │     ├─ 按需补数（MarketDataOrchestrator，最多 5 只，A 股 6 类数据包 / 港股仅财务包）
  │     └─ SQL 链路：默认 SQL 模板 → LLM 生成 → SqlGuard 白名单校验 → 执行 → 失败 repair 重试 1 次
  ├─ 7. 回答生成（按 answer_mode 选择风格策略，组装大 JSON prompt，流式/非流式调用）
  └─ 8. 指标落库（llm_call_metric 记录每阶段耗时、payload、响应全文）
```

外部 LLM 调用点：追问分流、前置路由、股票直接识别、候选消歧、生成 SQL、修复 SQL、最终回答，单轮最多约 7 次外部调用，全部计入项目日限额（默认 100 次/天）。

## 二、代码评审发现

### 2.1 P0 缺陷（建议立即修复）

#### B1. 问候关键词误拦截正常问题

`llm_service.py` 的 `_is_service_intro_question` 用子串匹配且在所有链路最前面拦截：

```python
if self._is_service_intro_question(question):
    return ChatAnswer(answer=SERVICE_INTRO_MESSAGE, ...)
```

用户输入“你好，帮我分析一下招商银行”会因包含“你好”直接返回能力介绍文案，真实分析诉求被吞掉。修复口径：只有当问题去除问候词后剩余内容为空（或长度低于阈值）才返回介绍文案；或将该判断并入前置路由的 `general` 分支，由路由模型判定。

#### B2. 阈值推荐流式被整体缓冲，流式名存实亡

`_normalize_threshold_recommendation_stream` 中 `buffer = "".join(chunks)` 会先消费完整个上游流再一次性 yield，前端在阈值推荐场景看不到任何打字效果，长回答时等待体验等同非流式。修复口径：改为增量规整——按行缓冲，仅在检测到 `## 标题` 粘连时做局部修补；或维持整体规整但仅对“最后一段落库内容”处理，流式分片原样下发。

#### B3. 前端流式解析单行异常导致整轮中断

`frontend/src/api/chat.ts` 第 110 行 `JSON.parse(line)` 没有 try/catch。后端任何一行输出异常（如代理截断、日志混入），整个 while 循环抛错中断，已收到的分片之后的 done 事件全部丢失，且 messageId 拿不到导致“发布雪球”等后续操作不可用。修复口径：单行 parse 失败时记录并跳过该行，不中断流读取。

### 2.2 P1 风险（近期处理）

#### R1. 单轮问答 LLM 调用次数过多，日限额口径失真

一轮个股分析问题典型消耗：追问分流 1 + 前置路由 1 + 股票识别 1~2 + 回答 1 = 4~5 次外部调用；带 SQL 修复时更多。`LLM_EXTERNAL_CALL_PHASES` 把辅助阶段全部计入 100 次/天限额，实际用户可用的“有效问答轮数”只有 20~25 轮，且限流提示文案说的是“调用次数”，用户无法理解为什么问了 20 个问题就触发 100 次限额。

#### R2. 追问分流对每条带历史的消息都打一次 LLM

`_is_follow_up_question` 在第二轮之后的每条消息上都先调用一次外部模型，叠加首包延迟约 1~3 秒，且失败时静默回落。该判断与前置路由（同样输入历史）功能高度重叠。

#### R3. 指标落库复用请求级 DB 会话并中途 commit

`_record_llm_metric` 直接在调用方传入的 `self.db` 上 `add + commit`。在 `routes_chat.create_message` 同步链路中，LlmService 的指标 commit 与路由层的业务 commit 交错；若未来有人在调用 `answer()` 前在同一会话上留有未提交业务变更，会被指标 commit 连带提交，形成隐性事务边界破坏。建议指标写入独立短会话（`SessionLocal()`）或队列异步落库。

#### R4. 指标表存储无治理

每次外部调用都把完整 request payload（含整段 prompt、最多 60 行市场数据 JSON）与响应全文写入 `llm_call_metric` 的 LONGTEXT 字段。问答活跃时该表膨胀速度远超业务表，且无保留期/归档策略。建议：payload 采样存储（如失败必存、成功按 10% 采样）+ 定期清理任务（如保留 90 天）。

#### R5. 流式 worker 线程无并发上限

`create_message_stream` 每个请求起一个 daemon 线程并各自开 `SessionLocal()`。并发流式问答没有上限控制，极端情况下耗尽数据库连接池。建议加信号量（如同时 8 个活跃流）或复用线程池。

#### R6. SqlGuard 的两个边界

1. `forbidden_pattern` 对字符串字面量误伤：`WHERE latest_forecast_type = '业绩预告:UPDATE'` 这类含禁用词的合法 SELECT 会被拒（当前数据下概率低，但属于已知误伤面）；建议改为仅依赖 sqlglot AST 判定语句类型，正则只作前置粗筛。
2. CTE 不可用：`WITH t AS (...) SELECT ... FROM t` 中别名 `t` 会被 `find_all(exp.Table)` 当作表名而触发白名单拒绝。LLM 在复杂筛选（分红再投跨表排名）时倾向生成 CTE，目前只能靠 repair 重写，浪费一次调用。建议在 guard 中收集 CTE 别名并从白名单校验中排除。

#### R7. 非流式失败留下“无回答的用户消息”

`create_message` 中用户消息先 commit，LLM 失败后抛 502，但用户消息已落库。历史会话里出现孤立提问。前端 `buildTurns` 虽然容忍，但下一轮 `_recent_history` 会把这条无回答的提问带进上下文，可能干扰追问分流判断。建议失败时补写一条“回答失败”assistant 消息（与流式链路对齐，流式已经这么做了）。

### 2.3 P2 工程质量（持续改进）

- **E1. `llm_service.py` 体量失控**：4568 行单文件混合了路由、提示词、SQL 生成、阈值公式、指标、HTTP 客户端、Markdown 工具。建议拆分为 `llm/` 包：`client.py`（端点与 fallback）、`router.py`（路由与本地兜底）、`prompts.py`（全部提示词与字段字典）、`sql_planner.py`（生成/修复/守卫调用）、`threshold.py`、`metrics.py`。
- **E2. 三层路由规则叠加，维护成本高**：LLM 路由 + 本地关键词强制覆盖（分红再投/投资推荐）+ 失败兜底关键词路由，三套规则对同一问题可能给出不同结论，新增业务模式（如后续“九转推送”问答）要同时改三处。
- **E3. 关键词表脆弱**：`INVESTMENT_KEYWORDS` 含“日本”“风险”等高误伤词；`AGGRESSIVE_INVESTMENT_KEYWORDS` 含“风险”，靠保守词优先的顺序规避“低风险”误判，属于隐式契约，没有测试保护。
- **E4. 死代码与冗余**：`rows` 字段已决定不回传前端，但 `_parse_rows`、流事件 `rows: []`、前端 `ChatStreamEvent.rows`、`updateTurnResponse` 的 rows 合并、`sendChatMessage`（非流式前端函数）均为残留；`_local_ts_code`、`_is_investment_related_question`、`_generate_answer`、`_route_stock_candidates` 疑似无调用方。
- **E5. 魔法字符串跨端重复**：默认会话标题“新的数据问答”在前端 `chat.ts`、后端 schema 默认值、`_touch_session` 判断三处硬编码，改一处即破坏改名逻辑。
- **E6. 前端 turn 配对脆弱**：`buildTurns` 用“最后一个无回答的 turn”反向配对 assistant 消息，连续两条用户消息（失败重试场景）会错配。消息已有自增 id，可按相邻配对。
- **E7. `_extract_json` 贪婪正则**：`r"\{.*\}"` 在模型输出多段 JSON 或附带说明时取最大跨度，易解析失败；`generate_sql` 未像股票识别那样传 `response_format={"type":"json_object"}`。

## 三、问数逻辑流程优化方向

### 3.1 路由合并：一次调用完成分流（核心优化）

把目前串行的 3~4 次辅助 LLM 调用（追问分流 → 前置路由 → 股票直接识别 → 候选消歧）合并为**单次结构化路由调用**，输出统一 JSON：

```json
{
  "turn_type": "follow_up | new_task",
  "is_answerable": true,
  "answer_mode": "stock_research | ... | general",
  "needs_sql": false,
  "stocks": [{"name": "招商银行", "ts_code": "600036.SH", "market": "A", "confidence": 0.97}],
  "packages_hint": ["quote_valuation", "financial_statement"],
  "reason": "..."
}
```

- 股票代码验真仍由本地 `StockIdentityResolver` 二次确认，验真失败再触发一次候选消歧（变成兜底路径而非常规路径）。
- 预期收益：单轮辅助调用从 3~4 次降到 1~2 次，首包延迟减少 2~5 秒，日限额内有效问答轮数提升约一倍。
- 风险控制：合并后的路由提示词更长，需要用回归用例集（见 3.5）验证各 answer_mode 命中率不回退。

### 3.2 本地确定性规则降级为兜底

当前分红再投/投资推荐关键词在路由前强制拦截，属于“规则压模型”。目标态：

1. 把这些业务模式的判定要求写进合并路由提示词（已有雏形），由模型主判；
2. 本地关键词只在两处生效：路由模型失败时的兜底、以及对模型结果的**校验纠偏**（如分红再投关键词命中但模型给了 stock_research，才强制覆盖——这一条现状已实现，保留）；
3. 收敛关键词表：删除“日本”等无关词，把保守/进取偏好词判断改为带否定词处理的小函数并补单测。

### 3.3 SQL 链路强化

1. `generate_sql` / `repair_sql` 统一传 `response_format={"type":"json_object"}`，降低解析失败率；
2. SqlGuard 支持 CTE（白名单校验排除 CTE 别名），减少 repair 次数；
3. schema 描述瘦身：当前每次生成 SQL 都把全量 schema 字符串（约 4K tokens）塞进 prompt，可按路由 answer_mode 只下发相关视图子集（分红再投只给三张表 + 打板缓存，AH 问题只给溢价/自选视图，个股问数只给 Tushare 视图）；
4. `_default_sql_for_question` 的关键词模板保留，但记录命中指标（phase=`default_sql`），便于评估模板与 LLM 生成的命中分布。

### 3.4 回答阶段 token 预算与材料裁剪

当前 `_answer_prompt` 的 payload 可能同时携带：60 行 SQL 结果 + 4 组 AH 补充查询（最多 90 行）+ 5 只股票的补数上下文（每只最多 24 期财务摘要）+ 8 轮历史。建议：

1. 引入简单 token 估算（字符数/1.6），设定回答 prompt 预算（如 24K chars），超限时按优先级裁剪：补数上下文 > SQL 结果 > AH 补充查询 > 更早历史；
2. `_supporting_data` 改为路由驱动：只有 answer_mode 为 open_research 且问题涉及 AH 择边时才查询，避免“招商银行财报分析”这类问题也带上 90 行溢价数据；
3. 财务摘要在问数（data_only）场景保留全字段，在分析场景按指标白名单裁剪列（收入/利润/扣非/现金流/ROE/负债率/估值等核心列），减少无效 token。

### 3.5 建立问数链路回归用例集

现有 `test_llm_service.py` 主要测确定性函数。建议补充一份**路由金标集**（fixture JSON）：50~80 条真实问题 → 期望 answer_mode / needs_sql / 股票识别结果，路由提示词或关键词每次改动跑全量比对。预设问题列表（ChatPage 中 29 条）天然是种子用例。

## 四、提示词优化方向

### 4.1 提示词外置与版本化

全部系统提示词目前内联在 `llm_service.py` 顶部（约 700 行常量）。建议迁移到 `backend/app/services/llm/prompts/` 目录，每个提示词一个 `.md` 或 `.py` 模块，带版本号注释；`LlmCallMetric` 增加 `prompt_version` 字段，使指标页能对比提示词版本前后的耗时、失败率与回答质量。

### 4.2 路由提示词瘦身分层

`QUESTION_ROUTER_SYSTEM_PROMPT` 当前约 80 行，混合了：判定规则、9 种 answer_mode 定义、6 类数据包目录、A/H 业务约束、输出格式。问题：

- 数据包目录与 `_packages_for_semantic_stock` 的本地关键词规则重复表达同一映射，存在口径漂移；
- 大量“如果用户问 X 必须返回 Y”的硬编码案例，本质是把单测写进了提示词。

优化口径：提示词分三段组装——固定判定规则（短）+ 按需注入的业务模式说明（仅当会话历史触发相关上下文时注入分红再投/打板段落）+ 输出 schema。配合 3.1 的合并路由一起重写。

### 4.3 格式约束收敛到一处

Markdown 格式规则（标题独行、表格前后空行、GFM 分隔行等）目前在 `INVESTMENT_ADVISOR_SYSTEM_PROMPT`、`_answer_prompt` 文首指令、`DIVIDEND_REINVESTMENT_MARKDOWN_EXAMPLE`、阈值推荐提示词中重复出现 4 次，措辞略有差异。建议抽成单一 `MARKDOWN_OUTPUT_CONTRACT` 常量统一拼接，修订一处全局生效。

### 4.4 回答风格策略改为结构化字段

`_answer_style_policy` 返回长文本段落，模型需要从散文里再解析要求。可改为结构化 JSON（`{"structure": ["核心结论","财务趋势表",...], "table_required": true, "risk_banner": false}`），降低被忽略概率，也便于做输出后校验（如检测 risk_banner 模式下首段是否含风险提示）。

### 4.5 输出后校验补强

现有 `_strip_forbidden_preamble` + 阈值标题规整是事后修补的正确思路，可扩展：

- 对 `aggressive_limit_up_recommendation` 校验回答是否包含风险提示段，缺失时在文首注入固定风险横幅（业务要求“显著提示风险”目前完全依赖模型自觉）；
- 对包含表格的回答做一次轻量 GFM 合法性检查（列数一致性），不合法时仅记录指标，为提示词迭代提供数据。

## 五、开发计划

### 阶段一：缺陷修复

| 任务 | 内容 | 验收标准 |
| --- | --- | --- |
| P0-1 | 修复问候词误拦截（B1） | “你好，帮我分析招商银行”进入个股研究链路；纯“你好”仍返回介绍；补单测 |
| P0-2 | 阈值推荐流式增量化（B2） | 阈值推荐首包时间与普通流式问答同量级；落库 Markdown 仍合法 |
| P0-3 | 前端流式解析容错（B3） | 模拟坏行注入，流继续读取且 done 事件正常处理 |
| P0-4 | 非流式失败补写 assistant 消息（R7） | 模型异常后会话历史含失败说明消息，与流式口径一致 |

### 阶段二：问数链路降本提速

| 任务 | 内容 | 验收标准 |
| --- | --- | --- |
| P1-1 | 合并路由调用（3.1，含追问分流并入） | 普通个股问题外部辅助调用 ≤ 2 次；路由金标集命中率不低于现状 |
| P1-2 | 建路由金标回归用例集（3.5） | ≥ 50 条用例入库，CI 可跑 |
| P1-3 | 日限额口径调整（R1） | 仅 answer/answer_stream 计入用户可感知配额，辅助调用单独限额与监控 |
| P1-4 | SQL 链路强化（3.3：json_object、CTE 支持、schema 按需下发） | repair 触发率下降；CTE 用例通过 guard |
| P1-5 | 流式并发上限（R5） | 并发超限时排队或友好报错，连接池不耗尽 |

### 阶段三：提示词治理（可与阶段二并行）

| 任务 | 内容 | 验收标准 |
| --- | --- | --- |
| P2-1 | 提示词外置 + 版本号（4.1） | 提示词集中在 prompts 模块；metric 记录 prompt_version |
| P2-2 | 路由提示词分层重写（4.2，与 P1-1 同步落地） | 提示词长度下降 ≥ 30%；金标集回归通过 |
| P2-3 | Markdown 契约收敛（4.3） | 格式规则单点维护；现有渲染用例不回退 |
| P2-4 | 风格策略结构化 + 风险横幅校验（4.4/4.5） | 打板推荐回答 100% 含风险提示段 |

### 阶段四：工程化与可观测性

| 任务 | 内容 | 验收标准 |
| --- | --- | --- |
| P3-1 | `llm_service.py` 拆包（E1） | 单文件 ≤ 1000 行；现有测试全绿 |
| P3-2 | 指标落库独立会话 + 采样与保留期（R3/R4） | 指标写入不再 commit 请求会话；清理任务上线 |
| P3-3 | 回答 token 预算与材料裁剪（3.4） | 超长材料场景 prompt 字符数受控；回答质量抽查不回退 |
| P3-4 | 死代码清理与前端 turn 配对修正（E4/E6） | rows 残留链路移除；连续用户消息配对正确 |

### 依赖与顺序说明

- 阶段一独立，可立即执行；
- P1-1（合并路由）是 P1-3、P2-2 的前置，三者建议同一迭代内完成，避免路由提示词改两遍；
- P3-1 拆包建议放在路由与提示词改造之后，避免迁移中叠加逻辑变更；
- 每阶段交付前跑 `scripts/check.sh` 与路由金标集。

## 六、风险与回滚

1. **路由合并的判定回退风险**：合并提示词后某些 answer_mode 命中率可能下降。对策：金标集先行（P1-2 先于 P1-1 验收），新旧路由灰度共存一个开关（settings 配置 `llm_router_mode=legacy|unified`），异常时秒级回退。
2. **提示词外置的行为漂移**：迁移过程必须字节级保持现有提示词内容不变（先迁移后修改，两次提交分开）。
3. **限额口径调整的成本风险**：辅助调用不再占用用户配额后总调用量可能上升，需在 LLM 耗时页增加“辅助调用/回答调用”分维度日报，观察一周再决定是否调整辅助限额。
