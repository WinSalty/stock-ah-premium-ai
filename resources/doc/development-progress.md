# 开发进度记录

更新日期：2026-05-04

## 当前状态

已按一阶段方案完成主要代码开发和本地 MySQL 初始化验证。当前已按中转服务文档切换为 Tushare Python SDK 调用方式，默认地址为 `http://tsy.xiaodefa.cn`。Tushare Token 已调整为本机文件优先，避免旧环境变量干扰；LLM 已接入 DeepSeek，并通过本机 API Key 文件完成最小调用验证。

## 已完成

- 项目目录调整为前后端混合 coding 项目：`/Users/salty/codeProject/ai/coding/stock-ah-premium-ai`。
- 新增项目级 `AGENTS.md`，明确 `backend/` 继承后端规则、`frontend/` 继承前端规则。
- 后端 FastAPI 项目骨架：
  - 应用入口、CORS、公开设置接口、健康检查。
  - Pydantic 配置，支持环境变量和本机 Tushare Token 文件。
  - SQLAlchemy 会话、模型、Alembic 迁移。
- 数据库与 SQL：
  - `stock_ah_ai` 建库 SQL。
  - 一阶段业务表、任务表、聊天表、官方 AH 校验表。
  - 新增完整建表 SQL 注释版 `resources/sql/03_full_schema_with_comments.sql`，覆盖当前全部业务表、同步表、自选股表和 LLM 会话表，表与字段均配置 `COMMENT`。
  - 新增数据库表结构说明 `resources/doc/database-schema.md`，统一说明建库 SQL、Alembic 迁移、注释版 DDL 和只读视图的分工。
  - LLM 只读视图和只读用户模板 SQL。
  - 新增自选股表 `watchlist_stock`，用于维护用户关注标的、方向、阈值、持有侧和备注。
  - LLM 只读视图已切换到官方 AH 比价口径，并新增官方趋势、最新官方 AH、港股通官方 AH 和自选机会视图。
  - 已在本地 MySQL 5.7 完成建库、Alembic 迁移和只读视图创建验证。
- Tushare 同步：
  - Python SDK 客户端封装，按中转文档设置 `pro._DataApi__http_url`。
  - 使用 `ts.pro_api(token, timeout=...)` 进程内传入 token，避免 SDK 额外写入用户目录缓存文件。
  - Token 读取策略为 `/Users/salty/codeProject/ai/doc/tushare-token.txt` 优先，`TUSHARE_TOKEN` 环境变量兜底。
  - 默认中转地址 `http://tsy.xiaodefa.cn`，支持请求间隔配置，降低触发冷却风险。
  - 数据集配置：A 股基础、A 股日线、A 股交易日历、港股基础、港股日线、港股交易日历、沪深港通名单、外汇日线、官方 AH 比价。
  - 同步任务记录、失败状态、checkpoint、MySQL upsert。
  - 官方 AH 比价落库前校验 A 股、港股是否同时开市，任一市场休市时不写入溢价结果，并清理该日期已有误落数据。
  - 已新增 `20260504_0007` 迁移清理 `official_ah_comparison` 中非联合交易日历史数据，并将自选机会视图分位窗口改为最近 60 条有效交易记录。
  - 同步模式：手工参数、checkpoint 增量补齐、默认历史起点全量重跑。
  - 一键 AH 所需数据同步：基础资料、交易日历、官方 AH 比价、港股通名单、A 股日线、外汇日线。
  - 后端新增 APScheduler 东八区定时增量跑批：按官方更新时点同步港股通名单、A 股日线、官方 AH 比价和外汇日线，并定期刷新基础清单和交易日历。
  - `hk_daily` 当前 token 无法请求，已按要求禁用接口同步，一键同步不会再尝试该接口。
  - 对全市场行情、官方 AH 比价和港股通名单的日期范围同步按交易日拆分请求，降低单次返回上限截断风险。
  - 官方 AH 比价同步后维护 AH 配对。
- 低权限兜底导入：
  - 支持通过 `POST /api/manual-import/ah-pairs` 导入人工 AH 配对。
  - 支持通过 `POST /api/manual-import/fx-rates` 导入人工汇率。
  - 支持通过 CSV 文本接口导入人工 AH 配对和汇率。
  - 前端同步页增加人工导入入口。
  - 增加人工导入服务单元测试。
- A/H 溢价计算：
  - 溢价页面展示已切换为官方 AH 比价表。
  - 已删除历史自算结果表 `ah_premium_daily`、自算服务和统一查询入口。
  - 官方 AH 比价表新增 `is_realtime`、`data_source`、`source_updated_at`，当前日计算结果可标记为实时。
  - 官方 AH 查询新增港股通通道、自选状态、关注方向、目标阈值距离、20/60/120 日均值、60 日中位数、20/80 分位、60 日分位和偏离 60 日均值字段。
  - 均值、中位数和分位指标均按最近 N 条有效官方交易记录计算，不按自然日区间计算。
- 自选股能力：
  - 新增 `GET/POST/PATCH/DELETE /api/watchlist`，支持查询自选股机会状态、新增、更新和停用。
  - 自选机会状态按官方 AH/H/A 口径、港股通通道、用户阈值和数据可用性生成。
- 登录注册与权限：
  - 新增应用用户表、邀请码表和 `20260504_0009` 迁移；预置 `ADMIN/USER` 两种角色。
  - 登录使用用户名和密码，注册必须填写管理员生成的邀请码，新注册用户固定为普通角色。
  - 前端新增登录/注册页和管理员邀请码页；菜单按当前用户权限过滤，普通用户仅展示总览、AH 机会筛选和问答。
  - 新增 `20260504_0010` 迁移，用户表支持展示名称、邮箱、电话、简介和用户粒度菜单权限；用户权限菜单改名为用户管理，管理员可编辑用户基础信息、角色、启用状态和菜单权限。
  - 新增个人信息菜单，当前用户可维护自己的展示名称、邮箱、电话和简介。
  - 自选股和 LLM 会话按 `user_id` 隔离；LLM 自选机会视图新增 `user_id` 字段，生成自选相关 SQL 时按当前用户过滤。
- LLM 问答：
  - OpenAI-compatible Chat API 封装支持 DeepSeek 和阿里 Qwen，问答页面可在 `deepseek-v4-flash`、`deepseek-v4-pro` 与 `qwen3.6-max-preview` 间选择，默认使用 `deepseek-v4-flash`；兼容历史配置 `deepseek-v4-pro[1m]` 到 DeepSeek API 支持的模型名，当前不额外传 `reasoning_effort`。
  - DeepSeek API Key 优先读取 `/Users/salty/codeProject/ai/doc/deepseek-apikey.txt`，`LLM_API_KEY` 仅作兜底；Qwen API Key 优先读取 `/Users/salty/codeProject/ai/doc/qwen-apikey.txt`，`QWEN_API_KEY` 仅作兜底，不把密钥暴露给前端。
  - 投资研究边界判定已从本地关键词匹配切换为 Qwen `qwen3.5-flash` JSON 分类调用；问候、角色身份和“你能做什么”类问题允许返回助手能力介绍，非范围问题改为更自然的引导文案。
  - 已将 LLM 系统角色升级为专业金融投资分析顾问，仅允许股票、估值、A/H 溢价、港股通、组合配置和风险控制等投资研究相关问题。
  - 已调整回答约束：直接输出专业报告，不输出寒暄、JSON/SQL/底层数据来源和模板化免责句；要求给出评级口径、配置倾向、优先级、阈值、触发条件和反证条件。
  - 新增 LLM 专用投资知识库 `resources/doc/llm-knowledge/`，按 A/H 跨市场价差、A 股选股估值、银行与非银、个股研究、宏观产业推演、组合风险与报告框架分组；问答时按问题和上下文选择性读取 Markdown 与 DOCX 片段。
  - 问答页面支持流式响应、Enter 发送和 Shift+Enter 换行。
  - 消息提交后立即清空输入框；数据查询准备失败时降级为无精确数据回答，避免整轮问答直接失败。
  - 非流式 AI 阈值推荐若遇到外部 LLM 异常，会返回可读的 502 错误，不再裸露为 `Internal Server Error`；DeepSeek 错误体会写入后端日志便于排查。非流式 LLM 超时已放宽到 90 秒。
  - LLM SQL 生成后会按本地视图字段清单校验并在字段名执行错误时自动修复重试一次。
  - 新增 `llm_call_metric` 指标表，记录分类、SQL 生成/执行、回答、流式首包和整轮问答耗时，按 `question_id` 串联阶段且不保存问题原文和密钥。
  - 关注/自选股的 H/A 折价、H/A 溢价问题已按对应方向排序，避免把 H 股折价和 H 股溢价混用。
  - AH 溢价、折价和套利类问题会追加候选池、市场分布、自选机会和 `llm-knowledge/ah-premium/` 中的投资研究片段。
  - 只读 SQL Guard：只允许 SELECT、禁止多语句和写库操作、限制白名单视图、自动 limit。
  - 默认 schema 已切换为官方 AH 比价、自选机会和港股通可操作性视图。
  - 会话与消息落库；提交新问题时会读取最近会话历史作为上下文记忆。
  - 会话支持逻辑删除，删除后保留历史消息但不再进入会话列表和读取接口。
  - 问答 API 和前端均不再向用户展示 SQL 原文，前端保留回答和数据摘要表格。
- 统一数据查询：
  - 后端新增 `/api/query/datasets` 和 `/api/query/rows`，按白名单查询已同步数据。
  - 支持 A 股/港股基础信息、交易日历、日线行情、沪深港通名单、外汇、AH 配对、官方 AH 比价、同步任务记录。
  - 支持关键词、日期范围、分页和字段列定义返回。
  - 官方 AH 比价表增加 H/A 比价和 H/A 溢价查询字段。
- A 股选股因子：
  - 新增 `stock_selection_factor_snapshot` 核心宽表，用于 LLM 按蓝筹、低估值、红利和质量指标选股。
  - 新增 `v_stock_selection_latest`、`v_stock_selection_history` 和 `v_stock_factor_dictionary` 只读视图，并纳入 SQL Guard 白名单。
  - 新增 `POST /api/sync/batches/stock-selection-factors`，基于 Tushare 最新估值、指数成分、财务指标、分红和行情表现联网筛选候选池。
  - 已同步 60 只候选股票，因子日期 `2026-04-30`，落库到核心宽表。
- 前端 React 项目：
  - 总览页已调整为自选机会台：指标、自选机会卡片、自选趋势图和自选明细。
  - 总览页新增官方 AH/H/A 溢价趋势折线图，默认跟随自选股，并始终支持手动选择股票和 A/H、H/A 方向。
  - 总览页趋势图支持日期范围缩放、切换股票或方向时重置缩放状态、阈值线、60 日中位数线和 20/80 分位参考线；无自选时保留全市场趋势兜底，折线按真实点位直线连接。
  - 数据同步页：同步说明、一键增量同步、一键全量重跑、单数据集同步、人工导入、任务记录筛选。
  - 数据同步页增加数据集说明字段；任务记录的参数、错误和说明等长字段支持悬浮查看完整内容。
  - 数据查询页：切换查看不同同步数据，支持关键词、日期范围和分页。
  - 统一查询、同步任务表格、智能问答结果和溢价表格已处理长字段省略悬浮；页面时间统一按东八区 `yyyy-MM-dd HH:mm:ss` 展示。
  - AH 溢价页：基于官方 AH 比价表展示，支持港股通/自选/通道/AH 与 H/A 区间筛选、加入自选时维护目标阈值、阈值填写说明、编辑自选、取消自选、派生指标重算、趋势抽屉和公式悬浮提示。
  - AH 机会筛选页：侧边栏菜单已从“溢价”调整为更易理解的“AH 机会筛选”。
  - 总览页自选机会卡片支持拖拽排序，排序结果写回自选股 `sort_order` 并保持自选明细顺序一致。
  - 总览页新增 A/H 价差使用原理说明，强调跨市场换仓和替代配置属性，不将其表述为无风险套利。
  - 总览页和自选阈值设置弹窗新增手动触发的 AI 阈值推荐按钮，LLM 回答要求包含推荐理由和最终阈值答案；页面加载、切换股票和修改字段均不会自动调用 LLM。
  - 同一股票、同一关注方向、同一天的 AI 阈值推荐会保存到前端本地缓存，再次点击直接显示“之前 AI 推荐信息”，不重复调用 LLM。
  - AI 阈值推荐的会话记录只展示简短问题，内部提示词不写入用户可见的聊天内容。
  - 新增 `llm-knowledge/ah-premium/threshold-recommendation-logic.md`，沉淀 A/H 自选阈值的稳定推荐逻辑，减少相同输入下的建议值漂移。
  - 智能问答页：会话列表、历史加载、逻辑删除、东八区时间显示、纯问题输入、基于投研报告随机展示的预设问题、流式回答和数据摘要表格；页面已重构为投研工作台布局，消息区独立滚动，回答表格和数据摘要不再撑破页面。
- 本地运行与验收脚本：
  - `scripts/bootstrap.sh`：安装后端和前端依赖。
  - `scripts/check.sh`：执行 Ruff、pytest、前端构建和生产依赖审计。
  - `scripts/init-db.sh`：创建数据库、执行 Alembic 迁移和只读视图 SQL。
  - `scripts/start-backend.sh`、`scripts/start-frontend.sh`：启动本地服务。
  - `Makefile`：提供 `make bootstrap/check/init-db/backend/frontend` 快捷入口。
  - `resources/doc/startup-guide.md`：完整启动、配置、验证和排错手册。
  - `resources/doc/phase-1-detailed-development-plan.md`：已同步当前实现口径，包括 `hk_daily` 禁用、官方 AH 比价主表、定时增量、长字段悬浮和东八区时间展示。
  - `resources/doc/ah-premium-review-and-display-design.md`：沉淀 A/H 溢价套现评审结论、官方主口径、自选股优先展示和后续落地优先级。
  - `resources/doc/realtime-premium-and-wechat-push-plan.md`：沉淀实时 AH 溢价行情源、Qwen 联网搜索定位和个人微信推送落地方案。
  - `resources/doc/llm-knowledge/README.md`：沉淀 LLM 投资问答知识库分类、使用原则和新增材料登记方式。
- 非真实功能测试资产：
  - 后端公式单元测试。
  - SQL Guard 单元测试。

## 暂未执行

- 启动服务前不会在文档或代码中写入 `/Users/salty/codeProject/ai/doc/tushare-token.txt` 内容。
- 已执行最大限度全量同步；当前本地行数：A 股基础 5512、港股基础 2730、A 股交易日历 730、港股交易日历 730、官方 AH 比价 27176、港股通名单 207769、A 股日线 942927。
- `hk_daily` 当前 token 无法请求，已禁用接口同步；`fx_daily` 请求成功但返回 0 行。
- DeepSeek LLM 已完成最小调用和流式问答验证。
- 依赖 Tushare 的完整端到端重新同步未重复执行。

## 已执行的非功能性检查

- `python3 -m compileall backend/app backend/tests`：通过。
- 后端虚拟环境使用 `/opt/homebrew/bin/python3.13` 创建，`pytest`：11 个单元测试通过。
- `ruff check app tests`：通过。
- `npm install`：完成，生成 `frontend/package-lock.json`。
- `npm run build`：通过。
- `npm audit --omit=dev`：0 个生产依赖漏洞。
- `scripts/init-db.sh`：通过，已创建/更新 `stock_ah_ai` 表和视图；已应用 `20260504_0002`，为官方 AH 比价表补充 H/A 字段并回填历史数据。
- `alembic upgrade head`：已应用 `20260504_0003`，为官方 AH 比价表补充实时标记和来源字段。
- `alembic upgrade head`：新增 `20260504_0004`，创建自选股表。
- `scripts/check.sh`：已在切换 Tushare 中转 SDK、调整 token 文件优先级后重新通过。
- 新增数据查询后，`scripts/check.sh` 已重新通过。
- 新增数据集说明、长字段悬浮、东八区时间展示和定时增量任务后，`scripts/check.sh` 已重新通过。
- 新增官方口径闭环、港股通可操作性、自选股和决策指标后，`scripts/check.sh` 已重新通过，当前 13 个单元测试通过。
- 已移除 Tushare 股票目录全量同步方案及 100 张 `ts_stock_*` 表，切换为选股因子宽表方案。
- 已新增 `20260504_0006` 迁移删除历史自算溢价表 `ah_premium_daily`，代码主链路仅保留官方 AH 比价口径。
- `scripts/init-db.sh`：已应用新的 `20260504_0005`，创建 `stock_selection_factor_snapshot`，并重建 LLM 选股视图。
- `stock_selection_factors` 同步验证：成功写入 60 只候选股票。
- Tushare 中转 SDK 最小连通性：`stock_basic` 携带 `limit=1` 查询成功返回 1 行，未落库。
- DeepSeek 流式问答验证：AH 套利宽问题返回 `meta` 与连续 `delta` 事件，能基于本地候选池生成 Markdown 答案。
- 敏感信息扫描：只发现文档中的 `<local-only>` 占位符，未发现真实 Token、密码或 API Key。

## 待验证事项

- 当前 Tushare 中转 Token 的完整可用接口范围。
- `stock_hsgt`、`stk_ah_comparison`、`fx_daily` 的实际返回字段与当前字段映射是否完全一致。
- 前后端联调、页面响应式截图和真实数据展示。
- LLM 输出 SQL 的长期稳定性和问答答案质量。

## 下一步建议

1. 执行本地 `alembic upgrade head` 或 `./scripts/init-db.sh`，将 `20260504_0004` 自选股表和新版只读视图应用到本地数据库。
2. 启动前后端后添加几只自选股票，验证首页机会卡片、阈值距离、通道、趋势中位数和分位参考线、溢价页加入自选流程。
3. 持续补充 AH 套利研究片段和候选池字段，观察 LLM 宽问题回答质量。
4. 后续修复真实实时接口，再恢复或增强实时刷新能力。
