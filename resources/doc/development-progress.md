# 开发进度记录

更新日期：2026-05-30

## 当前状态

已按一阶段方案完成主要代码开发和本地 MySQL 初始化验证。当前已按中转服务文档切换为 Tushare Python SDK 调用方式，默认地址为 `https://tt.xiaodefa.cn`。Tushare Token 已调整为本机文件优先，避免旧环境变量干扰；LLM 已接入 DeepSeek，并通过本机 API Key 文件完成最小调用验证。

## 已完成

- 已按分红再投入数据落地方案完成首版代码接入：新增回测批次、股票级摘要和年度明细三张模型表及 `20260529_0040` Alembic 迁移；新增 `dividend_reinvestment_data_landing` 同步数据集，按 `stock_basic`、`trade_cal`、`daily`、`dividend`、最新 `daily_basic`、本地回测计算顺序落地数据，复用 Tushare 客户端默认 0.6 秒限流；新增 `POST /api/sync/batches/dividend-reinvestment-data`，同步页增加“同步分红再投数据”入口，数据查询白名单增加三张回测结果表。新增 `GET /api/dividend-reinvestment/health`、`/runs`、`/summaries` 和 `/yearly/{ts_code}`，前端新增“分红再投筛选”菜单，支持数据健康概览、回测批次选择、收益/分红/估值条件筛选和单股年度明细抽屉；`20260530_0041` 迁移已给既有管理员补充分红再投菜单权限。针对 Tushare 中转长跑时的 SSL EOF、IncompleteRead 和短暂维护响应，客户端新增请求级退避重试并重建 SDK 连接，权限错误仍快速失败。分红回补已从自然日请求优化为按开市交易日 `ex_date` 请求；增量同步修复了 checkpoint 误改回测起点的问题，回测结果写入改为 500 行分块 upsert，避免真实 MySQL 大 SQL 断连。已完成真实数据初始化并生成最新成功回测批次 `3`：`a_daily_quote` 10741682 行，覆盖 2016-01-04 至 2026-05-29；`a_dividend` 25871 行，覆盖 2019-08-01 至 2026-05-29；`a_daily_basic` 6441 行，最新至 2026-05-29；回测股票摘要 2392 条、年度明细 26312 条。已补充单元测试覆盖数据落地、本地回测、统一同步入口、查询白名单、请求级重试、榜单筛选、交易日分红回补、增量回测起点和分块写入；本轮 Ruff、目标 pytest、前端构建和真实查询验收均已通过。
- 新增 `resources/doc/dividend-reinvestment-data-landing-plan.md` 和 `resources/doc/dividend-reinvestment-required-data-landing-plan.md`，沉淀分红再投入筛选的数据落地方案和所需数据清单：明确 2016 年以来 A 股日线、分红、交易日历和最新每日指标的落地范围，按 Tushare 120 次/分钟限制采用 0.6 秒保守限流和全局互斥，设计断点续跑、原始数据复用、回测批次表、摘要表和年度明细表，并补充接口字段、请求节奏、数据质量校验、只读视图和第一版不做事项。
- 已按 `resources/doc/text-to-image-service-plan.md` 落地文生图基础服务：后端新增 86GameStore/OpenAI Images 兼容 client、图片生成 service、受鉴权文件读取接口、用户级历史隔离、管理员全量审计、每日次数表和 Alembic 迁移；图片统一保存到 `IMAGE_GEN_STORAGE_DIR` 指向的本地独立目录，支持 URL/Base64 返回落盘和参考图本地保存。前端新增“图片生成”菜单、移动端适配图库、尺寸选择、参考图上传、历史回看和管理员每日次数维护/重置；普通用户默认开放，每人每天默认 10 次，外部供应商调用失败会返还次数。API Key 仍只通过环境变量或本机未入库文件读取，不写入项目代码、SQL、文档或前端产物。
- 机会筛选页面已改名为“机会筛选与关注”，自选关注模型从仅支持 A/H 配对扩展为 `PAIR`、`A_ONLY`、`H_ONLY` 三类：A/H 配对仍支持机会阈值、AI 阈值推荐、持有侧和双市场股价提醒；单 A 股、单 H 股只开放对应市场的股价提醒，页面隐藏溢价阈值和 AI 推荐配置。后端新增统一关注标的唯一键、候选标的搜索接口和单市场提醒扫描逻辑；只读自选机会视图继续只暴露 A/H 配对，避免单股关注被误用于价差机会判断。
- 移动端 App 化体验改造：新增 `resources/doc/mobile-app-experience-plan.md`，记录移动端问答主界面改造目标、风险点、开发计划和验收口径；前端在不改变桌面端 `Layout.Sider` 主路径的前提下新增移动端应用壳，手机端使用顶部应用栏、底部主导航和更多菜单抽屉承载全局入口。移动端登录态恢复或登录成功后优先进入“问答”，若当前用户没有问答权限则回退到第一个授权页面。智能问答页移动端新增会话抽屉和内部顶部栏，聊天历史成为主区域，输入区固定在底部，保留模型选择、流式回答、数据摘要、单条导出、会话导出和雪球草稿能力；桌面端问答仍保持左侧会话栏和右侧工作区结构。
- 问答回答支持发布到雪球草稿：确认雪球创作者草稿接口正文按 HTML 片段提交后，新增 `chat_xueqiu_publish` 独立动作权限，默认仅管理员拥有，用户管理页可单独授权；问答页每条已落库回答展示“发布雪球”按钮，点击后后端调用 LLM 将 Markdown 回答转换为雪球长文 HTML，其中 Markdown 表格强制转换为原生 HTML table，再复用雪球 Cookie、请求头、草稿保存/正式发布、失败 PushPlus 提醒和发布流水。雪球流水表扩展为多来源，打板报告标记 `LIMIT_UP_REPORT`，问答回答标记 `CHAT_ANSWER` 并记录对应 assistant 消息 ID，便于审计和排查。
- 雪球定时发布已收紧为 T-1 报告发布窗口：进程级 job 仅在周二到周六按分钟级唤起，服务层再按东八区当前日期二次校验，只处理当天推导出的最新上一 A 股交易日打板报告；若报告不存在、未 READY、内容为空或交易日不匹配，则跳过本轮等待后续调度，避免周一/周日或旧报告被误保存到雪球。
- 新增雪球发布管理模块：后端新增 `xueqiu_publish_credential`、`xueqiu_publish_setting` 和 `xueqiu_publish_record`，用于本地保存雪球创作者后台 Cookie 登录态摘要、页面定时配置、草稿/发布流水、请求摘要和雪球响应；新增 `xueqiu_publish` 菜单权限并默认授予管理员，普通用户不自动获得入口。新增 `/api/xueqiu-publish/...` 管理接口，支持保存登录态、验证登录态、配置工作日定时、预览最新 READY 打板报告转换后的雪球长文、保存草稿、正式发布和查看流水详情。`XUEQIU_PUBLISH_SCHEDULER_ENABLED=true` 默认注册分钟级工作日检查任务，页面可配置是否真正执行定时、执行保存草稿或正式发布、东八区小时/分钟和默认封面；页面默认不启用定时、不自动公开发布。前端新增“雪球发布”管理员菜单，提供登录态配置、定时配置、报告预览、保存草稿、正式发布确认和流水查看；手动勾选“强制新建/重试”时会新增一条流水并重新创建草稿，适配管理员已在雪球网页端删除草稿后重新创建草稿的场景，旧流水保留用于审计。封面 URL 会自动移除雪球 `!800.jpg` 等展示尺寸后缀后再提交，默认封面为 `https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png`，页面支持一键恢复默认图或去掉封面。雪球请求头按正常浏览器同源请求补齐 `Origin`、`Referer`、`User-Agent`、`X-Requested-With` 等字段；遇到验证码、风控或接口变更时记录失败并交由人工处理，不保存账号密码；草稿或发布失败后会通过 PushPlus 给默认管理员发送失败提醒，并保留推送流水。
- 打板推送模块新增接收人级周末晚间复推开关：`weekend_replay_enabled` 只影响周六、周日缓存报告复推，常规 KPL 数据就绪推送和管理员手动推送仍按接收人启用状态执行。已新增分享表 `limit_up_report_share`、创建分享接口、分享列表接口、分享失效接口和公开查看接口，管理员可为 READY 报告生成 1 小时到 7 天的临时链接或永久链接，再次点击分享时可查看、复制和失效已生成链接；报告列表操作改为逐行文字按钮，完整报告弹窗支持预览和源码查看；外部查看人无需登录即可直接阅读报告，有限期链接过期或链接撤销后会失效并记录公开访问次数。
- 新增 `resources/doc/llm-tushare-on-demand-stock-data-plan.md`，沉淀 LLM 股票问答通用按需补数方案：基于 Tushare 数据分类抽象 `MarketDataDemand`、数据包白名单、缓存限流和补数审计；自动补数只允许 A 股、短区间、低频、缓存优先，不自动全市场批量拉取；个股投资分析报告作为第一优先级优化场景，提示词只教分析方法和证据链，不用死板模板过度约束 LLM 推理。最终回答只暴露材料覆盖和材料缺口，不暴露积分、权限、接口名和内部补数策略。
- 已按方案落地 LLM 股票按需补数链路：新增 `a_daily_basic`、三张财务报表核心表、`a_financial_indicator`、`a_dividend`、`a_forecast` 和补数审计表；新增股票解析器、Tushare 白名单抓取器和按需编排器。LLM 路由支持 `data_demands`，后端接受 `quote_valuation`、`financial_statement`、`dividend_forecast` 三类数据包；命中缓存时不调用 Tushare，名称歧义会先基于本地股票基础表召回候选再让 LLM 在候选内语义消歧，明确多股对比时允许 5 只以内逐只补数。
- 个股投资分析报告提示词已优化：回答上下文新增 `market_data_context`，报告场景要求区分可观察事实、推断和假设，围绕商业质量、盈利增长、资产负债、现金流、估值、分红、业绩预告、A/H 相关性和反证条件建立证据链，同时保留 LLM 自主组织报告结构的自由度。
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
  - 新增个股研究只读视图 `v_stock_quote_valuation_trend`、`v_stock_financial_period_summary`、`v_stock_research_context_latest` 和 `v_market_data_fetch_health`，并纳入 SQL Guard 白名单和只读用户授权模板。
  - 新增自选股表 `watchlist_stock`，用于维护用户关注标的、方向、阈值、持有侧和备注。
  - LLM 只读视图已切换到官方 AH 比价口径，并新增官方趋势、最新官方 AH、港股通官方 AH 和自选机会视图。
  - 已在本地 MySQL 5.7 完成建库、Alembic 迁移和只读视图创建验证。
- Tushare 同步：
  - Python SDK 客户端封装，按中转文档设置 `pro._DataApi__http_url`。
  - 使用 `ts.pro_api(token, timeout=...)` 进程内传入 token，避免 SDK 额外写入用户目录缓存文件。
  - Token 读取策略为 `/Users/salty/codeProject/ai/doc/tushare-token.txt` 优先，`TUSHARE_TOKEN` 环境变量兜底。
  - 默认中转地址 `https://tt.xiaodefa.cn`，支持请求间隔配置，降低触发冷却风险。
  - 数据集配置：A 股基础、A 股日线、A 股交易日历、港股基础、港股日线、港股交易日历、沪深港通名单、外汇日线、官方 AH 比价。
  - 同步任务记录、失败状态、checkpoint、MySQL upsert。
  - 官方 AH 比价落库前校验 A 股、港股是否同时开市，任一市场休市时不写入溢价结果，并清理该日期已有误落数据。
  - 已新增 `20260504_0007` 迁移清理 `official_ah_comparison` 中非联合交易日历史数据，并将自选机会视图分位窗口改为最近 60 条有效交易记录。
  - 同步模式：手工参数、checkpoint 增量补齐、默认历史起点全量重跑。
  - 一键 AH 所需数据同步：基础资料、交易日历、官方 AH 比价、港股通名单、A 股日线、外汇日线。
  - 后端新增 APScheduler 东八区定时增量跑批：按官方更新时点同步港股通名单、A 股日线、官方 AH 比价和外汇日线，并定期刷新基础清单和交易日历。
  - `hk_daily` 当前 token 无法请求，已按要求禁用接口同步，一键同步不会再尝试该接口。
  - 对全市场行情、官方 AH 比价和港股通名单的日期范围同步按交易日拆分请求，降低单次返回上限截断风险。
  - 港股通名单同步改为只保留最新生效日期的一份数据；页面和 API 判断港股通可操作性时统一使用当前最新名单。
  - 官方 AH 比价同步后维护 AH 配对。
  - Tushare 官方 AH 比价历史覆盖不足时，已在 `water-stock` 增加 Baidu 历史补齐跑批：读取用户自选股，拉取 A/H 全量日 K 与 `HKDCNY` 汇率，只要 A 股收盘价、H 股收盘价和同日汇率三类数据齐全就向 `official_ah_comparison` 插入缺失行，不再依赖本地交易日历覆盖范围；已有唯一键记录一律跳过不覆盖。新增 `historical_premium_backfill_record` 记录每个 A/H 股票对补数状态，已完成股票对后续定时任务会在请求 Baidu 前跳过，失败或未记录股票对保留重试。招商银行单票本地测试已补入 `BAIDU_HISTORY_BACKFILL` 历史行，并验证重跑插入 0 条。
  - 已按腾讯不复权方案新增 `tencent_unadjusted_daily_quote`、`waterstock_fx_rate_daily` 和 `historical_ah_unadjusted_backfill_run` 三张表、Alembic 迁移、SQLAlchemy 模型和查询白名单；后端新增腾讯不复权 K 线客户端，以及同步页调用的一键接口 `/api/sync/batches/tencent-unadjusted`，内部只同步 `watchlist_stock` 中启用且未完成追跑的 A/H 不复权日线，默认日期边界为 2018-01-01 至当前日期，再追跑不复权 AH 比价。追跑只取 A 股不复权收盘价、H 股不复权收盘价和 HKD/CNY 汇率三方同日齐全的数据，先删除同日同股票对的 `BAIDU_HISTORY_BACKFILL` 行，再插入 `TENCENT_UNADJUSTED_BACKFILL`，但不覆盖 `TUSHARE_OFFICIAL`、实时计算或人工来源；写入主表时会从 `ah_stock_pair` 或已有官方主表行继承 A/H 名称，并通过 `20260507_0025` 迁移回填早期腾讯补数空名称行，保证数据查询页按中文股票名可检索历史补数。腾讯客户端按自然年分段拉取并将落库行情源标记为 `TENCENT_KLINE`。当前腾讯不复权补数未注册定时任务，触发入口包括同步页手动按钮和新增/恢复关注自选股时的单票后台追跑；关注触发会先检查该股票对是否已有 `RUNNING` 或 `COMPLETED` 记录，缺记录或失败记录才会重新触发。
  - `water-stock` 已新增 HKD/CNY 历史汇率独立写入方法 `syncHkdCnyHistoryToStockAhDatabase(String startDate, String endDate)`，写入 `stock-ah-premium-ai.waterstock_fx_rate_daily` 并按 `currency_pair + rate_date + data_source` 幂等更新；新增 `stock-ah.fx-history.enabled=false` 的低频调度开关，不再由 Java 项目参与不复权 AH 比价计算。
  - 新增 `resources/sql/04_backfill_ah_trade_calendar_from_cmb.sql`，用招商银行 A/H 已补齐行情日期作为 AH 联合交易日兜底基准，幂等补齐 `a_trade_calendar` 与 `hk_trade_calendar` 缺失开市日期；已在本地和服务器 `stock_ah_ai` 执行，招商银行趋势经联合交易日过滤后可从 2018-09-03 返回。
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
  - 登录页新增“记住登录”选项，默认勾选；勾选后后端签发 30 天 token，前端持久保存，取消勾选时仅在当前浏览器会话保存。
  - 新增 `20260504_0010` 迁移，用户表支持展示名称、邮箱、电话、简介和用户粒度菜单权限；用户权限菜单改名为用户管理，管理员可编辑用户基础信息、角色、启用状态和菜单权限。
  - 新增个人信息菜单，当前用户可维护自己的展示名称、邮箱、电话和简介。
  - 自选股和 LLM 会话按 `user_id` 隔离；LLM 自选机会视图新增 `user_id` 字段，生成自选相关 SQL 时按当前用户过滤。
  - 新增 `20260505_0015` 迁移，在 `app_user` 既有用户表中补充总览趋势图指标显示配置 JSON 字段，并提供按当前用户读取和保存的设置接口。
- 消息推送与提醒：
  - 新增 PushPlus 好友消息模块，支持从 `/Users/salty/codeProject/ai/doc/pushplus.txt` 同时解析用户 token 和 SecretKey，不向前端返回敏感凭据。
  - 新增个人信息页 PushPlus 绑定区：绑定入口融合在基础资料中，生成绑定二维码、刷新绑定状态、解除绑定和测试推送；普通用户界面不展示内部绑定票据和回调实现细节。
  - 新增 `pushplus_binding` 与 `alert_event` 表，以及 `20260505_0013` 迁移；提醒事件按 dedupe key 去重。
  - 自选股新增股价提醒配置，支持 A 股和 H 股两侧分别设置大于等于或小于等于目标价。
  - 自选股提醒新增消息推送开关，默认开启；用户关闭后保留提醒条件但不发送 PushPlus 消息，也不强制绑定。
  - 后端新增交易日提醒扫描任务，阈值提醒要求 A/H 共同交易日，股价提醒要求对应市场交易日；非交易日不推送。
  - 提醒扫描已改为交易时段实时判断：调度器默认在 `ALERT_SCAN_HOURS=9-16` 内每秒执行一次，服务层再按 A 股 `09:30-11:30`、`13:00-15:00` 与港股 `09:30-12:00`、`13:00-16:00` 过滤；A/H 溢价阈值只在两地重叠时段触发。
  - 阈值提醒和股价提醒均读取 `realtime_quote_snapshot` 最新有效快照；实时 A/H 溢价计算要求 A 股、H 股和 `HKD/CNY` 汇率快照日期均等于本轮扫描日/东八区当天，任一日期错配都会返回 `STALE`，不计算指标、不写回官方 AH 主表，也不触发阈值提醒；股价提醒要求对应市场报价质量为 `REALTIME`。
  - PushPlus 提醒频率已改为按偏离档位触发：首次达到条件推送一次；阈值提醒每多偏离 1 个百分点新增一档，股价提醒每多偏离目标价 2% 新增一档；同一用户同一交易日同类提醒累计最多 5 次。
  - PushPlus 绑定流程已调整为扫码回调自动绑定：二维码归属管理员 PushPlus 账号，`content` 仅作为短格式带签名的系统用户绑定票据；好友列表和全量绑定列表仅管理员可查看。
  - PushPlus 绑定入口新增显著说明：扫码关注公众号后，微信收到“好友增加成功”即代表绑定成功，无需点击链接进行付费或实名认证；绑定成功展示优先使用好友备注或昵称，不再把好友 ID 当作昵称展示。
  - PushPlus 绑定功能保留在个人信息页；已绑定用户不再展示二维码绑定入口，也不能重复生成二维码或覆盖绑定；同一个 PushPlus 好友只能绑定一个系统用户；管理员的好友列表、用户绑定信息管理和“系统用户 + PushPlus 好友”手动绑定已移入用户管理菜单，绑定时会把好友令牌仅保存到后端。
  - PushPlus 测试消息、阈值提醒和股价提醒统一使用 HTML 模板发送，消息采用非紫色轻量卡片和价差信号图样式，并展示触发类型、标的、交易日、当前阈值/价格和目标阈值/价格等明细。
  - 默认管理员账号无法添加自己为 PushPlus 好友时，测试消息、阈值提醒和股价提醒会特殊走 PushPlus 一对一消息，继续使用原 PushPlus 用户 token；普通用户仍走好友消息和绑定校验。
  - 自选股保存提醒配置时会校验当前用户必须已有 PushPlus 绑定，未绑定时前端弹出二维码引导，后端同步拒绝未绑定提醒保存。
  - 新增 `pushplus_message_log` 推送流水表和管理员查询接口；测试推送、阈值提醒、股价提醒都会记录实际推送时间、系统用户、PushPlus 接收对象、标题、内容、状态、消息流水号和错误信息，用户管理页可直接查看。
  - PushPlus 管理已从用户管理拆分为独立菜单，新增 `pushplus` 菜单权限并通过 `20260508_0030` 迁移给既有管理员补齐默认权限；PushPlus 推送记录支持按关键词、状态和系统用户搜索；阈值提醒 HTML 明细新增同次实时计算使用的 A 股价格、H 股价格和 `HKD/CNY` 汇率。
- LLM 问答：
  - OpenAI-compatible Chat API 封装支持 DeepSeek 和阿里 Qwen，问答页面可在 `deepseek-v4-flash`、`deepseek-v4-pro` 与 `qwen3.6-flash` 间选择，默认使用 `deepseek-v4-flash`；兼容历史配置 `deepseek-v4-pro[1m]` 到 DeepSeek API 支持的模型名，当前不额外传 `reasoning_effort`。
  - DeepSeek API Key 优先读取 `/Users/salty/codeProject/ai/doc/deepseek-apikey.txt`，`LLM_API_KEY` 仅作兜底；Qwen API Key 优先读取 `/Users/salty/codeProject/ai/doc/qwen-apikey.txt`，`QWEN_API_KEY` 仅作兜底，不把密钥暴露给前端。
  - 投资研究边界、是否需要结构化数据和是否需要按需补充市场数据已合并到 `deepseek-v4-flash` 单次 JSON 前置路由；问候、角色身份和“你能做什么”类问题允许返回助手能力介绍，非范围问题改为更自然的引导文案。
  - 已将 LLM 系统角色升级为专业金融投资分析顾问，仅允许股票、估值、A/H 溢价、港股通、组合配置和风险控制等投资研究相关问题。
  - 已调整回答约束：直接输出专业报告，不输出寒暄、JSON/SQL/底层数据来源和模板化免责句；要求给出评级口径、配置倾向、优先级、阈值、触发条件和反证条件。
  - 个股深度分析已退出本地个股研报依赖：公司层面的投资判断优先走 Tushare 按需补数和只读视图上下文，避免旧静态研报覆盖最新财务、行情和资金流变化。
  - 问答页面支持流式响应、Enter 发送和 Shift+Enter 换行；预设提问池已改为围绕单股补数、24 期财务质量、资金流、A/H 配置和风险反证等投研场景随机展示。
  - 总览页自选明细表格右侧趋势按钮已接入走势图切换，点击后会展示对应 A/H 标的和方向的溢价走势。
  - 问答链路新增快路径：问候类问题本地秒回；报告分析类问题由前置路由决定是否跳过 SQL；前端发送后展示“理解问题、整理信息、形成框架、组织回答”等用户可感知进度，不暴露内部处理细节。
  - 消息提交后立即清空输入框；数据查询准备失败时降级为无精确数据回答，避免整轮问答直接失败。
  - 非流式 AI 阈值推荐若遇到外部 LLM 异常，会返回可读的 502 错误，不再裸露为 `Internal Server Error`；DeepSeek 错误体会写入后端日志便于排查。非流式 LLM 超时已放宽到 90 秒。
  - LLM SQL 生成后会按本地视图字段清单校验并在字段名执行错误时自动修复重试一次。
  - 新增 `llm_call_metric` 指标表，记录分类、SQL 生成/执行、回答、流式首包和整轮问答耗时，按每轮问答唯一 `question_id` 串联阶段且不保存问题原文和密钥。
  - 新增管理员 LLM 耗时查询接口和前端页面，支持按追踪 ID、会话、用户、来源、模型、阶段和日期范围查询，并展示调用阶段数、成功数、平均耗时、最大耗时和平均首包。
  - LLM 耗时页面的摘要卡片、表格字段和阶段值已补充小问号悬浮说明，解释阶段流水、首包、Chunk、字符数和行数的采集口径，避免把阶段无关的 0 误判为异常。
  - LLM 耗时指标新增 `phase_label`、`phase_description` 和 `request_payload_json` 字段，记录阶段中文含义以及实际调用 LLM 时的请求参数和上下文 messages；`request_payload_json` 使用 MySQL `LONGTEXT`，避免完整上下文超过普通 `TEXT` 限制；页面阶段列显示中文名和阶段码，参数列通过弹窗查看完整 JSON。`Internal` 来源表示本地快路径或整轮耗时汇总，不是外部模型调用。
  - LLM 耗时参数弹窗改为结构化展示请求参数：顶部汇总模型、温度、流式开关和消息数，下方按 `system/user` 等 role 分块展示 messages 内容，便于排查上下文。
  - LLM 耗时指标新增 `response_content` 字段，使用 MySQL `LONGTEXT` 记录大模型返回的原始响应内容；流式回答在 `answer_stream` 完成记录中保存拼接后的完整内容。页面表格已将“参数”移动到“耗时”后，并在其后新增“响应”查看弹窗。
  - LLM 耗时追踪 ID 已改为每轮问答生成 32 位随机 UUID，不再按问题文本哈希，避免不同会话重复提问时阶段记录混在同一个追踪 ID 下。
  - LLM 耗时指标新增 `conversation_title` 和 `user_name` 字段；对话标题由用户提问清洗截取生成，页面列顺序调整为“时间、对话标题、追踪 ID…响应、用户名称…”，便于管理员按问题主题和用户排查。
  - LLM 耗时页面查询按钮已增加显式提交版本号，点击“查询”即使筛选条件和当前页未变化也会重新拉取最新指标，便于按追踪 ID 连续排查。
  - 关注/自选股的 H/A 折价、H/A 溢价问题已按对应方向排序，避免把 H 股折价和 H 股溢价混用。
  - AH 溢价、折价和套利类问题会追加候选池、市场分布和自选机会等结构化上下文，不再注入额外静态投研片段。
  - LLM 个股补数上下文的财务报表、财务指标、主营业务、审计、快报、预告和分红数据统一保留最近 24 期，并同步纳入个股资金流向 `moneyflow` 作为短期交易行为参考。
  - LLM 同会话追问已新增轻量回答路径：带有会话历史且明显是在质疑、修正、继续前文的消息，不再进入问题路由、SQL、按需补数和完整报告模板，直接由模型结合前文自主回答；若同一会话里明确切换到新的股票代码、标的或独立分析任务，仍走原结构化数据路由。
  - LLM 个股补数上下文已为元级金额补充亿元派生字段和中文标签字段，避免模型在回答中把营业收入、归母净利润、经营现金流等财务金额换算少一位或多一位。
  - 已删除 LLM 自动静态投研材料注入链路和旧材料文档目录；回答上下文只保留会话历史、页面上下文、结构化市场观察和按需补数结果，避免旧方法论或静态研报稀释最新数据。
  - LLM 前置路由已保留数据包分类，但改为“证据菜单”口径：路由模型会结合本地股票候选和用户研究意图主动选择需要补齐的数据包；最终回答按问题自主组织，只有完整个股研究才使用完整报告结构，A/H、行业、组合和开放策略问题不再机械套同一模板。
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
  - 总览页已调整为自选机会台：指标、自选机会卡片和自选趋势图。
  - 总览页新增官方 AH/H/A 溢价趋势折线图，默认跟随自选股，并始终支持手动选择股票和 A/H、H/A 方向。
  - 总览页溢价图表新增图表类型切换，支持走势折线、分位区间和偏离柱状三种视角，分别用于观察时间趋势、20/60/80 分位区间和相对 60 日中位数偏离。
  - 总览页趋势图支持日期范围缩放、切换股票或方向时重置缩放状态、阈值线、60 日中位数线和 20/80 分位参考线；无自选时保留全市场趋势兜底，折线按真实点位直线连接。
  - 数据同步页：同步说明、一键增量同步、一键全量重跑、单数据集同步、人工导入、任务记录筛选。
  - 数据同步页增加数据集说明字段；任务记录的参数、错误和说明等长字段支持悬浮查看完整内容。
  - 数据查询页：切换查看不同同步数据，支持关键词、日期范围和分页；数值类字段展示时统一四舍五入保留三位小数，代码、日期、状态、ID 等标识字段保持原样。
  - 统一查询、同步任务表格、智能问答结果和溢价表格已处理长字段省略悬浮；页面时间统一按东八区 `yyyy-MM-dd HH:mm:ss` 展示。
  - AH 溢价页：基于官方 AH 比价表展示，支持港股通/自选/通道/AH 与 H/A 区间筛选、加入自选时维护目标阈值、阈值填写说明、编辑自选、取消自选、趋势抽屉和公式悬浮提示；页面已移除手工“重算派生”按钮，实时刷新由后台写回官方主表。
  - AH 机会筛选页：侧边栏菜单已从“溢价”调整为更易理解的“AH 机会筛选”。
  - 总览页自选机会卡片支持拖拽排序，排序结果写回自选股 `sort_order` 并保持自选明细顺序一致。
  - 总览页新增 A/H 价差使用原理说明，强调跨市场换仓和替代配置属性，不将其表述为无风险套利。
  - 总览页 A/H 价差说明块改为从 200 条 100 字以内的股票知识点、名词解释、投资纪律和吉利话中随机抽取展示。
  - 总览页自选机会卡片新增 A/H 最新股价、溢价目标阈值和 A/H 双市场股价提醒阈值展示，并支持在卡片上直接设置自选配置或取消自选，设置项复用 AH 机会筛选页的关注方向、阈值、PushPlus 推送、A/H 股价提醒和持有侧逻辑。
  - 总览页自选机会卡片始终通过 `/api/watchlist` 读取官方 AH 比价主表口径；交易时段前端会后台触发 `/api/ah-premiums/realtime?only_watchlist=true`，后端用实时快照计算后写回 `official_ah_comparison` 并标记 `is_realtime`，再刷新自选卡片数据。实时写回时严格区分数据日期和生成时间：`trade_date` 使用 A/H 报价自身的 `quote_time` 推导，且只有 A/H 报价日期一致并等于东八区当天时才允许写回官方主表，避免历史快照被标记为实时；`source_updated_at`/`updated_at` 才表示系统生成或写入时间。卡片右下角不再展示更新时间。
  - 实时计算时间由后端按 UTC 记录、前端统一转东八区展示，避免本地无时区时间被重复加 8 小时后显示到次日；总览卡片本身已移除该时间展示。
  - 总览页自选机会卡片的核心指标值已补充语义色；原“今日价差锦囊”更名为“今日投研词条”，并追加 100 条股票相关专业金融名词解释；已移除自选明细表格区域。
  - 总览页趋势图主线颜色已调整，并新增指标显示配置，可按当前用户保存溢价走势、60 日中位数、20/80 分位和目标阈值线的显示状态。
  - 总览页和自选阈值设置弹窗新增手动触发的 AI 阈值推荐按钮，LLM 回答要求包含推荐理由和最终阈值答案；页面加载、切换股票和修改字段均不会自动调用 LLM。
  - 总览页和自选阈值设置弹窗的 AI 阈值推荐等待态已补充与智能问答类似的阶段文字，展示理解阈值场景、整理价差分位、形成推荐框架和组织执行条件等进度。
  - 同一股票、同一关注方向、同一天的 AI 阈值推荐会保存到前端本地缓存，再次点击直接显示“之前 AI 推荐信息”，不重复调用 LLM。
  - AI 阈值推荐的会话记录只展示简短问题，内部提示词不写入用户可见的聊天内容。
  - 智能问答页：会话列表、历史加载、逻辑删除、东八区时间显示、纯问题输入、基于结构化投研场景随机展示的预设问题、流式回答和数据摘要表格；页面已重构为投研工作台布局，消息区独立滚动，回答表格和数据摘要不再撑破页面；新增最新消息自动滚动锚点并优化问答间距，生成中状态改用真实加载组件，避免伪进度动效和问题气泡视觉遮盖；已移除前端 Markdown 纠错补丁，改为在 LLM 系统提示词中约束 GFM 标题、表格和块级边界。
  - 智能问答页流式回答期间的自动滚动改为“贴近底部才跟随”，用户手动滚动查看历史内容时不再被持续拉回底部，避免鼠标滚动时内容闪烁。
  - 智能问答页追问流式滚动进一步改为按动画帧合并滚动请求，并忽略程序滚动触发的 `onScroll`，减少分片响应时的闪烁和位置抖动。
  - 智能问答问数模式已覆盖“给我近三年某公司财报数据”这类未显式写“只要数据”的请求；只要用户没有要求分析、对比、报告或投资判断，就直接返回 Tushare 按需补数/只读视图数据，并保留后续可继续索取的数据类型引导。
  - 智能问答的数据摘要和问数模式 Markdown 表头已扩充为中文字段名，覆盖行情估值、财务摘要、利润表、现金流量表、资产负债表、分红预告和 A/H 溢价字段；数据摘要不再截断列数，改用横向滚动承接更多字段。
  - 智能问答页预设问题按钮改为点击后直接发送，仍复用输入框提交的同一套流式问答逻辑。
  - 智能问答页新增会话批量勾选删除，后端提供当前用户范围内的批量逻辑删除接口；页面支持点击下载当前会话全部回答或单条回答为 Word 文档，导出时使用固定布局 OOXML 表格、显式列宽和重复表头，提升 Windows Word、WPS 和网页版 Word 的表格兼容性。
  - 智能问答系统提示词加强 Markdown 稳定性约束：第一块“核心结论”禁止使用表格，固定改用项目符号；表格只允许从第二块开始，并要求独立成块、前后空行和 GFM 列数合法，降低首段表格渲染失败概率。
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
  - `resources/doc/tencent-unadjusted-ah-backfill-plan.md`：沉淀腾讯不复权历史 K 线、water-stock 汇率独立表、stock-ah-premium-ai 追跑历史 AH 比价和查询页接入的实施方案。
  - `resources/doc/server-deployment-guide.md`：沉淀单机服务器部署记录，覆盖 MySQL 同机直连、无 Nginx 跨端口访问、云安全组/CORS 排障、服务器空库通过应用 Tushare 同步数据、仅初始化管理员账号等首次部署经验。
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
- 新增同会话追问轻量回答路径和 LLM 上下文亿元派生字段后，`pytest tests/test_llm_service.py tests/test_market_data_orchestrator.py -q` 通过，56 个单元测试通过；`ruff check app/services/llm_service.py app/services/llm_metric_definitions.py app/services/market_data_orchestrator.py tests/test_llm_service.py tests/test_market_data_orchestrator.py` 通过。
- 增强启动、停止和重启脚本后，`bash -n scripts/*.sh` 通过；已分别用 `BACKEND_PORT=18000`、`FRONTEND_PORT=15173` 验证启动诊断、整项目重启和停止诊断，并确认后端 `/api/health` 返回正常。
- 拆分 PushPlus 独立菜单、推送记录搜索和阈值提醒价格/汇率明细后，`alembic upgrade head` 已应用 `20260508_0030`，`pytest tests/test_auth_service.py tests/test_notification_service.py` 36 个单元测试通过，`ruff check` 目标文件通过，`npm run build` 通过。
- 新增 LLM 项目级日调用限流，默认 `LLM_DAILY_CALL_LIMIT=100`，按 `llm_call_metric` 中外部模型主调用 phase 统计，不计首包、SQL 执行和总耗时等辅助指标。
- 新增实时行情抽象接口首版落地，创建 `realtime_quote_snapshot` 表、数据库行情 provider、实时 AH/H/A 溢价计算服务和 `GET /api/ah-premiums/realtime` 读取接口；`alembic upgrade head` 已应用 `20260505_0016`，`./scripts/check.sh` 通过。
- `water-stock` 已在 `master` 最新代码上补充 stock-ah 实时喂数模块：独立连接 `stock_ah_ai`，按 A/H 共同交易日、港股收盘口径交易时段和用户自选股每秒写入 `realtime_quote_snapshot`，并用非重入调度避免上一轮未完成时并发抓取；接口请求前将 stock-ah 的 Tushare 风格代码转换为 water-stock/Baidu 使用的纯数字代码。
- 自选股提醒已改为实时快照触发，交易时间默认每秒扫描一次；`backend/.venv/bin/python -m pytest backend/tests/test_notification_service.py -q` 和针对变更文件的 `ruff check` 通过。
- 实时 H/A 溢价改为按官方 `ah_comparison` 两位小数口径反推，避免 H/A 阈值判断与官方表存在精确公式口径偏差。
- 阈值推荐阶段文字补充后，`npm run build` 通过。
- LLM 耗时字段说明补充后，`npm run build` 通过。
- 智能问答流式滚动修复后，`npm run build` 通过。
- 智能问答预设问题直接发送改造后，`npm run build` 通过。
- 腾讯港股不复权日线降级到腾讯未复权日线后，`pytest tests/test_tencent_kline_service.py` 通过，针对变更文件的 `ruff check` 通过。
- 智能问答 Markdown 表格约束优化后，`ruff check app/services/llm_service.py` 和 `pytest tests/test_llm_service.py -q` 通过。
- LLM 耗时参数弹窗格式化优化后，`npm run build` 通过。
- LLM 耗时响应内容字段和页面响应弹窗补充后，后端指标测试、服务测试和前端构建通过。
- LLM 耗时查询按钮、问数模式识别、中文字段名和流式滚动闪烁修复后，`npm --prefix frontend run build` 通过；后端变更文件已通过 `py_compile`，当前可见 Python 环境缺少 `pytest` 和 `ruff` 模块，未能执行后端单元测试和 lint。
- LLM 耗时新字段迁移已在本地 MySQL 执行到 `20260505_0017`，确认 `phase_label`、`phase_description` 和 `request_payload_json` 字段存在；使用内部指标写入验证新统计可以落库。
- A/H 双市场股价提醒改造后，`alembic upgrade head` 已应用 `20260506_0019`，确认 `watchlist_stock` 仅保留 A/H 两套股价提醒配置列；针对变更文件的 `ruff check`、`pytest tests/test_notification_service.py -q` 和前端 `npm run build` 均通过。
- 实时溢价写回官方 AH 比价表、总览卡片移除右下角时间并改为官方表主口径读取后，`ruff check app/services/realtime_premium_service.py tests/test_realtime_premium_service.py`、`pytest tests/test_realtime_premium_service.py -q` 和前端 `npm run build` 均通过。
- 移动端 App 化体验改造后，`npm --prefix frontend run build` 通过；使用本地 mock API 和 Chrome DevTools Protocol 验证桌面 1366x900 仍渲染桌面侧边栏布局，移动 390x844 默认渲染问答主界面、底部导航、输入区和会话抽屉。
- 移动端体验回归修复后，补充严格 viewport 配置、移动端输入控件 16px 字号、移动端页面切换回顶和表格触摸滚动策略；`npm --prefix frontend run build` 通过，使用本地 mock API 和 Chrome DevTools Protocol 验证 390x844 视口下问答首次渲染宽度正确、菜单切换到 AH 机会筛选后滚动位置归零、机会筛选表格支持触摸横向拖动且页面支持纵向拖动。
- AH 机会筛选表格移动端横向拖动修复后，移动视口下自动取消溢价表固定列，避免 Ant Design fixed column 覆盖层拦截触摸滑动；`npm --prefix frontend run build` 通过，使用本地 mock API 和 Chrome DevTools Protocol 验证 390x844 视口下表格不存在固定列覆盖层，并可从表格左侧区域手势横向拖动。
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

## 2026-05-07 LLM 问答数据链路优化

- LLM 问答链路彻底退出旧选股因子宽表：`llm_service` 不再为选股、低估值、红利等问题默认生成 `v_stock_selection_latest` 查询，SQL Guard 也不再把 `v_stock_selection_latest`、`v_stock_selection_history` 和 `v_stock_factor_dictionary` 放入 LLM 白名单；历史同步和查询页能力暂保留，但不作为智能问答数据来源。
- 个股研究按需 Tushare 字段扩展：利润表新增投资收益、公允价值变动收益、营业总成本、费用、减值、营业外收支、少数股东损益、EBIT/EBITDA；资产负债表新增长期股权投资、投资性房地产、应收/存货、固定资产、在建工程、无形资产、商誉、有息负债、合同负债、权益项目；现金流新增收付款拆解、投资回收、购建固定资产支出、借款/偿债/分红付息现金流；财务指标新增扣非净利润、扣非 ROE、ROA、权益乘数、单季度收入/利润同比和每股经营现金流。
- 只读摘要视图扩充：`v_stock_financial_period_summary` 和 `v_stock_research_context_latest` 已输出上述利润质量、现金流质量和资产结构字段，便于 LLM 对“利润是否来自主业、现金流是否覆盖利润、估值口径是否可靠”做交叉核验。
- 新增“问数模式”：用户明确表达“只要数据、不要分析、返回数据、财报数据、估值数据”等意图且未要求分析时，后端直接把结构化数据格式化为 Markdown 表格，并提示可继续返回行情估值、财务摘要、现金流、利润质量、分红/业绩预告、主营业务构成、A/H 溢价和自选股阈值数据；用户要求分析时仍走原投研回答链路。
  - 放宽通用问答边界：翻译、知识解释、改写、润色、编程概念等普通问答由通用 LLM prompt 直接回答，不再套用投资助手拒答边界；仅违法违规交易、敏感信息和账号越权类请求继续拒绝。
  - 个股分析报告提示词优化：报告类回答要求先做数据核验，再区分事实、推断和假设，重点核查扣非净利润、投资收益、公允价值变动、减值、经营现金流覆盖、资产结构和估值口径，避免仅因表面 PE/PB 偏低给出乐观判断。
- 个股研究上下文继续扩展为内部白名单接口组合：新增 `business_profile`、`shareholder_governance` 和 `capital_flow_light` 三类数据包；分别补入 `fina_mainbz`、`fina_audit`、`express`、`top10_holders`、`top10_floatholders`、`stk_holdernumber`、`pledge_stat` 和 `moneyflow`。财务、主营和分红底层补数周期扩展到最近 8 年，业绩预告和业绩快报保留最近 5 年，个股资金流底层保留最近 60 个自然日；LLM 上下文仍只取摘要视图最近少量记录，避免原始明细过量塞入 prompt。
- 只读视图和 SQL Guard 同步扩充：新增 `v_stock_business_profile_summary`、`v_stock_shareholder_governance_summary` 和 `v_stock_moneyflow_recent`，并将报告提示词升级为同时检查主营收入/利润来源、审计意见、业绩快报、股东集中度、股东户数、质押压力和短期资金流，明确资金流只解释交易情绪，不替代基本面证据。

## 2026-05-07 AI 阈值推荐快路径优化

- 总览页和 AH 机会筛选页的“AI 推荐阈值”入口新增结构化 `threshold_recommendation` 上下文，只传页面已有的 A/H 代码、关注方向、持有侧、当前阈值、当前价差、60 日中位数、20/80 分位、当前分位和港股通通道；后端据此识别固定阈值场景，不再进入通用问题路由、股票消歧、Tushare 按需补数和 `v_watchlist_opportunity` 辅助查询。
- 后端新增阈值推荐确定性计算器，按 `median + 0.65 * (p80 - median)`、当前分位高于 80% 取 `max(base, current)`、历史分位缺失时给 2 到 5 个百分点缓冲等规则稳定生成建议阈值；LLM 只解释这个紧凑结果，避免相同页面输入下答案大幅漂移。
- 阈值推荐支持流式调用和专用耗时阶段：`threshold_answer`、`threshold_answer_stream`、`threshold_answer_stream_first_chunk`、`threshold_done`、`threshold_stream_done`，管理员可在 LLM 耗时页面直接区分阈值快路径和通用问答链路。
- 模型未配置时，阈值推荐会返回本地确定性 Markdown 兜底答案，避免固定场景因外部模型不可用完全无法使用；模型配置正常时仍由 LLM 补充推荐理由和执行条件。

## 2026-05-09 财报异常问答补包优化

- 排查服务器 LLM 耗时追踪 `0b448bd3f02c44248b94fe264fac6e1f`：本地与服务器 `llm_call_metric`、`llm_market_data_fetch_run`、`llm_market_data_fetch_item` 表结构一致，不存在部署漂移；问题原文当前落在 `conversation_title`，请求上下文落在 `request_payload_json`，模型响应落在 `response_content`。
- 该追踪中前置路由只返回 `financial_statement`，补数审计也只调用财务报表和财务指标包，未触发审计意见、业绩快报、前十大股东、前十大流通股东、股东户数和质押比例相关上下文，导致回答阶段只能基于财务异常模式推断并把可补结构化材料列为缺口。
- `MarketDataOrchestrator` 新增财报异常专项语义扩展：当问题出现年报/季报异常、财务报表更改、会计政策或会计估计变更、差错更正、追溯调整、重述、审计意见、业绩快报等信号时，即使路由只给 `financial_statement`，后端也会自动补充 `business_profile` 与 `shareholder_governance`。
- 投研回答提示词新增外部材料边界：最终回答只能说明当前材料覆盖项和缺口项；公告原文、公司回复或补充披露未覆盖时，只写“当前材料未覆盖，需后续以正式披露校验”，不得暴露积分、权限、接口名、数据库表和内部补数策略。

## 2026-05-08 港股财务问答与 24 期财务上下文优化

- 追踪 ID `336c51e8e24f41278255c60ad611866c` 排查结论：用户问“中国电力”时，前置路由仍按旧 A 股边界处理，明确回复“港股不在 A 股数据范围内”，导致未触发 Tushare 补数，最终只能生成无结构化数据支撑的泛化回答。已将路由、股票解析和补数编排从 A 股单市场扩展为 A 股/港股双市场。
- 港股自动补数首批只开放 `financial_statement`：新增 `hk_financial_indicator` 和 `hk_financial_statement_item` 两张表，分别承接 `hk_fina_indicator` 与 `hk_income`、`hk_balancesheet`、`hk_cashflow`。港股三大报表按“指标名/指标值”窄表落库，所有接口仍由后端白名单固定字段、固定周期和单股参数控制，LLM 不能直接指定 Tushare API。
- 新增港股只读视图 `v_hk_stock_research_context_latest`、`v_hk_financial_period_summary` 和 `v_hk_financial_statement_item_summary`，并纳入 SQL Guard 白名单、只读用户授权模板和完整注释版 DDL。港股上下文默认提供最近 24 期财务指标摘要与最多 80 条三大报表项目摘要；行情、资金流、股东治理和分红等港股数据域暂不自动补数，回答中需作为材料缺口说明。
- 股票解析器已支持完整港股代码和五位港股代码，例如 `02380.HK`、`02380`；名称召回新增 `hk_stock_basic`，可把“中国电力”解析为本地港股候选，再由 LLM 语义消歧或唯一命中后进入港股财务补数。
- 追踪 ID `eb1464aceafe446a8bd884a5ee7bc6db` 排查结论：陕西煤业问题的 Tushare 补数已成功，财务、主营、分红等数据行进入上下文；回答偏重近两年不是数据缺失，而是提示词和答案组织没有强制先检查完整 20/24 期覆盖期。已在回答 payload 增加 `financial_context_contract`，并在报告提示词中要求先概括完整覆盖期趋势，再单独点评最近两年；问数模式财务数据展示上限同步调整为 24 行。
- 本地 MySQL 真实验证：使用临时库和真实 Tushare Token 调用 `02380.HK` 港股财务包，成功写入 1934 行，其中港股财务指标 16 行、三大报表项目 1918 行，最新报告期为 2025-12-31；再通过 `MarketDataOrchestrator.ensure_for_question` 验证“中国电力 02380.HK 财务质量怎么看”可完成补数、构造港股 latest/financial_periods/statement_items 上下文。
- A/H 双上市和港股通问题已补确定性保护：当用户问题包含“港股通、AH、A/H、H 股、两地、溢价、折价、择边”等跨市场词，并且本地 `ah_stock_pair` 有配对时，股票解析器会同时召回 A 股与 H 股；编排器在混合上下文中追加 `v_latest_official_ah_premium` 最新官方 AH/H/A 价差和港股通通道信息。类似“招商银行港股通和 A/H 价差怎么看”会形成 `600036.SH + 03968.HK` 的 `CROSS_MARKET_MULTI` 上下文，不再只分析单边。
- 个股按需补数成功后已跳过通用 SQL：如果前置路由已经给出 `data_demands`，且编排器返回 `market_data_context`，回答阶段直接使用补数上下文，不再额外调用 SQL 生成器查询普通视图。该优化避免“分析腾讯”这类港股问题在补入 `00700.HK` 财务数据后，又误生成 A 股视图 SQL，减少耗时和材料干扰；若补数失败没有上下文，仍保留 SQL 兜底。
- 后端专项检查已通过：`pytest tests/test_stock_identity_resolver.py tests/test_market_data_orchestrator.py tests/test_tushare_stock_research_fetcher.py tests/test_llm_service.py` 共 47 个用例通过，`ruff check app tests` 通过。完整空库 Alembic 回放仍受旧迁移中 MySQL 专用语句和历史视图依赖影响，本轮新增迁移在现有本地库继续升级的路径需要单独验证。
