# 数据库表结构说明

更新日期：2026-05-07

## 维护口径

项目数据库名为 `stock_ah_ai`。实际表结构迁移以 `backend/alembic/versions/` 为准，完整建表 SQL 注释版统一维护在 `resources/sql/03_full_schema_with_comments.sql`，用于文档审阅、新环境结构核对和字段含义确认。

相关 SQL 文件分工：

- `resources/sql/00_create_database.sql`：创建数据库。
- `resources/sql/01_readonly_views.sql`：创建 LLM 只读查询视图。
- `resources/sql/02_readonly_user_template.sql`：创建只读用户模板。
- `resources/sql/03_full_schema_with_comments.sql`：当前完整 `CREATE TABLE` 参考 SQL，所有表和字段均配置 `COMMENT`。

## 当前表清单

核心行情与交易日历：

- `a_stock_basic`：A 股基础信息。
- `hk_stock_basic`：港股基础信息。
- `a_trade_calendar`：A 股交易日历。
- `hk_trade_calendar`：港股交易日历。
- `a_daily_quote`：A 股日线行情。
- `hk_daily_quote`：港股日线行情，当前 token 无权限时仅保留结构。
- `tencent_unadjusted_daily_quote`：腾讯公开 K 线接口同步的 A/H 不复权历史日线，用于替代不准确的 Baidu 前复权历史补数口径。
- `waterstock_fx_rate_daily`：`water-stock` 写入的 HKD/CNY 历史汇率独立表，供不复权历史 AH 比价追跑读取。

A/H 溢价与可交易性：

- `hsgt_constituent`：沪深港通标的名单；同步后仅保留表内最新生效日期的数据，用于判断当前港股通可操作性。
- `fx_rate_daily`：外汇汇率日线。
- `ah_stock_pair`：AH 股票配对。
- `official_ah_comparison`：Tushare 官方 AH 比价快照，当前主展示口径。
- `historical_ah_unadjusted_backfill_run`：腾讯不复权历史 AH 比价补数执行记录；追跑时允许删除并替换 `BAIDU_HISTORY_BACKFILL` 行，但不覆盖 `TUSHARE_OFFICIAL` 行。
- `realtime_quote_snapshot`：实时行情快照表，作为 `RealtimeQuoteProvider` 的首个落地数据源；外部任务写入 A 股、港股和 HKD/CNY 报价，本项目按最新有效快照计算实时 AH/H/A 溢价。
- `watchlist_stock`：用户自选 AH 股票，按 `user_id` 隔离。

用户、角色与邀请码：

- `app_user`：应用登录用户，预置 `ADMIN` 和 `USER` 两种角色；保存展示名称、邮箱、电话、简介、用户粒度菜单权限和总览趋势图指标配置。
- `invitation_code`：注册邀请码，由管理员生成，注册成功后记录使用用户和时间。

官方 AH 比价只保留 A 股交易日历、港股交易日历同时开市的日期；任一市场休市时，同步服务会跳过该日期的溢价结果，并清理该日期已有误落数据。历史自算结果表 `ah_premium_daily` 已由迁移 `20260504_0006` 删除。

溢价均值、中位数、20/80 分位和历史分位均按最近 N 条有效官方交易记录计算，不按自然日区间计算；`v_watchlist_opportunity.premium_percentile_60` 也使用最近 60 条有效官方溢价记录。

A 股选股因子：

- `stock_selection_factor_snapshot`：LLM 选股用核心宽表，保存蓝筹、低估值、红利和质量因子候选股票快照。

LLM 按需个股研究数据：

- `a_daily_basic`：单股按需补取的 A 股每日估值指标，用于报告中的估值位置、股息率、市值和换手率分析。
- `a_income_statement`：单股利润表核心字段，保存近年营收、利润、费用和每股收益等报告证据。
- `a_balance_sheet`：单股资产负债表核心字段，保存资产、负债、权益、货币资金、应收、存货和借款等字段。
- `a_cashflow_statement`：单股现金流量表核心字段，保存经营、投资、筹资现金流和期末现金等字段。
- `a_financial_indicator`：单股财务指标核心字段，保存 ROE、毛利率、净利率、资产负债率、收入和净利润同比等指标。
- `a_dividend`：单股分红送股记录，用于报告中的股息回报、分红稳定性和执行进度分析。
- `a_forecast`：单股业绩预告记录，用于报告中的业绩前瞻、反证条件和跟踪指标分析。
- `llm_market_data_fetch_run`：LLM 按需市场数据抓取批次审计，记录问题追踪 ID、单股代码、数据包、缓存命中、状态和行数。
- `llm_market_data_fetch_item`：LLM 按需市场数据抓取明细审计，记录每个白名单 Tushare 接口的参数、字段、耗时和错误摘要。

按需补数硬边界：当前仅面向 15000 积分 Tushare 权限设计，自动流程只允许单只 A 股、短区间、低频、缓存优先的数据包补齐；不允许 LLM 任意选择 Tushare 接口、字段或全市场批量拉取。LLM 读取时只通过 `v_stock_quote_valuation_trend`、`v_stock_financial_period_summary`、`v_stock_research_context_latest` 和 `v_market_data_fetch_health` 等只读视图消费整理后的上下文。

任务、质量与问答：

- `sync_run`：数据同步任务运行记录。
- `sync_checkpoint`：数据同步断点。
- `data_quality_issue`：数据质量问题记录。
- `pushplus_binding`：PushPlus 好友绑定表，保存系统用户与 PushPlus 好友的后端发送令牌映射，不向前端返回好友令牌。
- `alert_event`：提醒事件表，保存阈值提醒和股价提醒触发时的去重键、推送标题、推送内容和发送状态。
- `pushplus_message_log`：PushPlus 推送消息流水表，记录测试推送、阈值提醒和股价提醒实际提交给 PushPlus 的时间、接收用户、接收对象、标题、内容、状态、消息流水号和错误信息，供管理员审计查看。
- `llm_chat_session`：LLM 问答会话，用于保存投资问答主题和更新时间，按 `user_id` 隔离，`deleted_at` 非空表示会话已逻辑删除。
- `llm_chat_message`：LLM 问答消息，用于保存用户问题、助手回答、内部查询口径和结果预览，支持后续会话上下文记忆。
- `llm_call_metric`：LLM 调用耗时指标，按每轮问答唯一 `question_id` 串联路由、SQL、回答和流式首包等阶段；新增 `conversation_title` 和 `user_name` 保存对话标题与用户展示名称；`phase_label`、`phase_description` 解释阶段中文含义，`request_payload_json` 使用 `LONGTEXT` 记录实际发送给 LLM 的请求 JSON 和上下文 messages，不保存鉴权头和 API Key；`response_content` 使用 `LONGTEXT` 记录大模型返回的原始响应内容，流式回答保存拼接后的完整内容。

## 使用建议

新环境初始化优先执行：

```bash
./scripts/init-db.sh
```

需要人工审阅字段含义、检查表注释或生成数据库说明时，查看：

```bash
resources/sql/03_full_schema_with_comments.sql
```

后续新增表或字段时，需要同步更新 Alembic 迁移、SQLAlchemy 模型、`03_full_schema_with_comments.sql` 和本文档表清单。
