# 开发进度记录

更新日期：2026-05-05

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
  - 新增 `20260505_0015` 迁移，在 `app_user` 既有用户表中补充总览趋势图指标显示配置 JSON 字段，并提供按当前用户读取和保存的设置接口。
- 消息推送与提醒：
  - 新增 PushPlus 好友消息模块，支持从 `/Users/salty/codeProject/ai/doc/pushplus.txt` 同时解析用户 token 和 SecretKey，不向前端返回敏感凭据。
  - 新增个人信息页 PushPlus 绑定区：绑定入口融合在基础资料中，生成绑定二维码、刷新绑定状态、解除绑定和测试推送；普通用户界面不展示内部绑定票据和回调实现细节。
  - 新增 `pushplus_binding` 与 `alert_event` 表，以及 `20260505_0013` 迁移；提醒事件按 dedupe key 保证同一提醒同一交易日只推送一次。
  - 自选股新增股价提醒配置，支持选择 A 股或 H 股、大于等于或小于等于目标价。
  - 自选股提醒新增消息推送开关，默认开启；用户关闭后保留提醒条件但不发送 PushPlus 消息，也不强制绑定。
  - 后端新增交易日提醒扫描任务，阈值提醒要求 A/H 共同交易日，股价提醒要求对应市场交易日；非交易日不推送。
  - PushPlus 绑定流程已调整为扫码回调自动绑定：二维码归属管理员 PushPlus 账号，`content` 仅作为短格式带签名的系统用户绑定票据；好友列表和全量绑定列表仅管理员可查看。
  - PushPlus 绑定功能保留在个人信息页；已绑定用户不再展示二维码绑定入口，也不能重复生成二维码或覆盖绑定；同一个 PushPlus 好友只能绑定一个系统用户；管理员的好友列表、用户绑定信息管理和“系统用户 + PushPlus 好友”手动绑定已移入用户管理菜单，绑定时会把好友令牌仅保存到后端。
  - PushPlus 测试消息、阈值提醒和股价提醒统一使用 HTML 模板发送，消息采用非紫色轻量卡片和价差信号图样式，并展示触发类型、标的、交易日、当前阈值/价格和目标阈值/价格等明细。
  - 自选股保存提醒配置时会校验当前用户必须已有 PushPlus 绑定，未绑定时前端弹出二维码引导，后端同步拒绝未绑定提醒保存。
- LLM 问答：
  - OpenAI-compatible Chat API 封装支持 DeepSeek 和阿里 Qwen，问答页面可在 `deepseek-v4-flash`、`deepseek-v4-pro` 与 `qwen3.6-flash` 间选择，默认使用 `deepseek-v4-flash`；兼容历史配置 `deepseek-v4-pro[1m]` 到 DeepSeek API 支持的模型名，当前不额外传 `reasoning_effort`。
  - DeepSeek API Key 优先读取 `/Users/salty/codeProject/ai/doc/deepseek-apikey.txt`，`LLM_API_KEY` 仅作兜底；Qwen API Key 优先读取 `/Users/salty/codeProject/ai/doc/qwen-apikey.txt`，`QWEN_API_KEY` 仅作兜底，不把密钥暴露给前端。
  - 投资研究边界、是否需要结构化数据、是否需要知识库和知识分类已合并到 Qwen `qwen3.6-flash` 单次 JSON 前置路由；问候、角色身份和“你能做什么”类问题允许返回助手能力介绍，非范围问题改为更自然的引导文案。
  - 已将 LLM 系统角色升级为专业金融投资分析顾问，仅允许股票、估值、A/H 溢价、港股通、组合配置和风险控制等投资研究相关问题。
  - 已调整回答约束：直接输出专业报告，不输出寒暄、JSON/SQL/底层数据来源和模板化免责句；要求给出评级口径、配置倾向、优先级、阈值、触发条件和反证条件。
  - 新增 LLM 专用投资知识库 `resources/doc/llm-knowledge/`，按 A/H 跨市场价差、A 股选股估值、银行与非银、个股研究、宏观产业推演、组合风险与报告框架分组；问答时按问题和上下文选择性读取 Markdown 与 DOCX 片段。
  - 已将中国神华、格力电器、宁德时代、比亚迪、长江电力和寒武纪 2026 版公司价值投资报告整理到 `llm-knowledge/company-research/value-investing-2026/`，个股深度投资报告分类通过稳定子目录通配读取，按公司名、股票代码和价值投资关键词命中。
  - 问答页面支持流式响应、Enter 发送和 Shift+Enter 换行；预设提问池已补充中国神华、格力电器、宁德时代、比亚迪、长江电力和寒武纪价值投资报告相关问题。
  - 总览页自选明细表格右侧趋势按钮已接入走势图切换，点击后会展示对应 A/H 标的和方向的溢价走势。
  - 问答链路新增快路径：问候类问题本地秒回；报告分析类问题由前置路由决定是否跳过 SQL；LLM 知识库 DOCX/Markdown 解析增加进程内缓存。知识库注入改为在前置路由中给模型轻量目录简介，由模型判断是否需要读取材料以及读取哪些分类，不再对每个问题按关键词默认塞材料。前端发送后展示“理解问题、整理信息、形成框架、组织回答”等用户可感知进度，不暴露内部处理细节。
  - 消息提交后立即清空输入框；数据查询准备失败时降级为无精确数据回答，避免整轮问答直接失败。
  - 非流式 AI 阈值推荐若遇到外部 LLM 异常，会返回可读的 502 错误，不再裸露为 `Internal Server Error`；DeepSeek 错误体会写入后端日志便于排查。非流式 LLM 超时已放宽到 90 秒。
  - LLM SQL 生成后会按本地视图字段清单校验并在字段名执行错误时自动修复重试一次。
  - 新增 `llm_call_metric` 指标表，记录分类、SQL 生成/执行、回答、流式首包和整轮问答耗时，按 `question_id` 串联阶段且不保存问题原文和密钥。
  - 新增管理员 LLM 耗时查询接口和前端页面，支持按追踪 ID、会话、用户、来源、模型、阶段和日期范围查询，并展示调用阶段数、成功数、平均耗时、最大耗时和平均首包。
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
  - 总览页 A/H 价差说明块改为从 200 条 100 字以内的股票知识点、名词解释、投资纪律和吉利话中随机抽取展示。
  - 总览页自选机会卡片新增 A/H 最新股价、溢价目标阈值和股价提醒阈值展示。
  - 总览页趋势图主线颜色已调整，并新增指标显示配置，可按当前用户保存溢价走势、60 日中位数、20/80 分位和目标阈值线的显示状态。
  - 总览页和自选阈值设置弹窗新增手动触发的 AI 阈值推荐按钮，LLM 回答要求包含推荐理由和最终阈值答案；页面加载、切换股票和修改字段均不会自动调用 LLM。
  - 同一股票、同一关注方向、同一天的 AI 阈值推荐会保存到前端本地缓存，再次点击直接显示“之前 AI 推荐信息”，不重复调用 LLM。
  - AI 阈值推荐的会话记录只展示简短问题，内部提示词不写入用户可见的聊天内容。
  - 新增 `llm-knowledge/ah-premium/threshold-recommendation-logic.md`，沉淀 A/H 自选阈值的稳定推荐逻辑，减少相同输入下的建议值漂移。
  - 智能问答页：会话列表、历史加载、逻辑删除、东八区时间显示、纯问题输入、基于投研报告随机展示的预设问题、流式回答和数据摘要表格；页面已重构为投研工作台布局，消息区独立滚动，回答表格和数据摘要不再撑破页面。
  - 新增 LLM 耗时菜单，管理员默认拥有权限，可在用户管理中单独授权或收回。
- 本地运行与验收脚本：
  - `scripts/bootstrap.sh`：安装后端和前端依赖。
  - `scripts/check.sh`：执行 Ruff、pytest、前端构建和生产依赖审计。
  - `scripts/init-db.sh`：创建数据库、执行 Alembic 迁移和只读视图 SQL。
  - `scripts/start-backend.sh`、`scripts/start-frontend.sh`：启动本地服务，启动前输出目录、端口、版本、关键配置文件和端口占用诊断。
  - `scripts/stop-backend.sh`、`scripts/stop-frontend.sh`、`scripts/stop.sh`：按端口停止后端、前端或全部服务。
  - `scripts/restart-backend.sh`、`scripts/restart-frontend.sh`、`scripts/restart.sh`：重启服务；整项目重启会后台拉起前后端并将日志写入 `.runtime/logs/`。
  - `Makefile`：提供 `make bootstrap/check/init-db/backend/frontend/stop/restart` 快捷入口。
  - `resources/doc/startup-guide.md`：完整启动、配置、验证和排错手册。
  - `resources/doc/phase-1-detailed-development-plan.md`：已同步当前实现口径，包括 `hk_daily` 禁用、官方 AH 比价主表、定时增量、长字段悬浮和东八区时间展示。
  - `resources/doc/ah-premium-review-and-display-design.md`：沉淀 A/H 溢价套现评审结论、官方主口径、自选股优先展示和后续落地优先级。
  - `resources/doc/realtime-premium-and-wechat-push-plan.md`：沉淀实时 AH 溢价行情源、Qwen 联网搜索定位和个人微信推送落地方案；已补充 `realtime_quote_snapshot` 喂数约定和实时读取 API。
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
- 本轮已执行真实 MySQL 的 `alembic upgrade head`，本地库已应用到 `20260505_0016`。

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
- 新增 LLM 耗时查询页面后，`scripts/check.sh` 已重新通过，当前 35 个单元测试通过。
- 新增 PushPlus 好友推送、股价提醒和交易日去重提醒后，`ruff check app tests` 通过，`pytest` 40 个单元测试通过，`npm run build` 通过。
- 调整 PushPlus 扫码自动绑定和提醒保存绑定校验后，`ruff check app tests` 通过，`pytest` 42 个单元测试通过，`npm run build` 通过。
- 拆分个人绑定、提醒弹窗绑定、用户管理页 PushPlus 管理，并新增消息推送开关后，`alembic upgrade head` 已应用 `20260505_0014`，`ruff check app tests` 通过，`pytest` 44 个单元测试通过，`npm run build` 通过。
- 新增总览随机锦囊、自选卡片股价/阈值展示和用户级趋势图指标配置后，`python3 -m compileall app tests`、`ruff check app tests`、`pytest`（56 个单元测试）、`npm run build`、`npm audit --omit=dev` 和 `./scripts/check.sh` 均通过。
- 增强启动、停止和重启脚本后，`bash -n scripts/*.sh` 通过；已分别用 `BACKEND_PORT=18000`、`FRONTEND_PORT=15173` 验证启动诊断、整项目重启和停止诊断，并确认后端 `/api/health` 返回正常。
- 新增 LLM 项目级日调用限流，默认 `LLM_DAILY_CALL_LIMIT=100`，按 `llm_call_metric` 中外部模型主调用 phase 统计，不计首包、SQL 执行和总耗时等辅助指标。
- 新增实时行情抽象接口首版落地，创建 `realtime_quote_snapshot` 表、数据库行情 provider、实时 AH/H/A 溢价计算服务和 `GET /api/ah-premiums/realtime` 读取接口；`alembic upgrade head` 已应用 `20260505_0016`，`./scripts/check.sh` 通过。
- `water-stock` 已在 `master` 最新代码上补充 stock-ah 实时喂数模块：独立连接 `stock_ah_ai`，按 A/H 共同交易日、交易时段和用户自选股每秒写入 `realtime_quote_snapshot`，并用非重入调度避免上一轮未完成时并发抓取。
- 敏感信息扫描：只发现文档中的 `<local-only>` 占位符，未发现真实 Token、密码或 API Key。

## 待验证事项

- 当前 Tushare 中转 Token 的完整可用接口范围。
- `stock_hsgt`、`stk_ah_comparison`、`fx_daily` 的实际返回字段与当前字段映射是否完全一致。
- 前后端联调、页面响应式截图和真实数据展示。
- LLM 输出 SQL 的长期稳定性和问答答案质量。

## 下一步建议

1. 新环境执行 `alembic upgrade head` 或 `./scripts/init-db.sh`，确保表结构和只读视图与当前代码一致。
2. 启动前后端后添加几只自选股票，验证首页机会卡片、阈值距离、通道、趋势中位数和分位参考线、溢价页加入自选流程。
3. 持续补充 AH 套利研究片段和候选池字段，观察 LLM 宽问题回答质量。
4. 后续修复真实实时接口，再恢复或增强实时刷新能力。
