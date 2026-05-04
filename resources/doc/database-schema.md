# 数据库表结构说明

更新日期：2026-05-04

## 维护口径

项目数据库名为 `stock_ah_ai`。实际表结构迁移以 `backend/alembic/versions/` 为准，完整建表 SQL 注释版统一维护在 `resources/sql/03_full_schema_with_comments.sql`，用于文档审阅、新环境结构核对和字段含义确认。

相关 SQL 文件分工：

- `resources/sql/00_create_database.sql`：创建数据库。
- `resources/sql/01_readonly_views.sql`：创建 LLM 只读查询视图。
- `resources/sql/02_readonly_user_template.sql`：创建只读用户模板。
- `resources/sql/03_full_schema_with_comments.sql`：当前完整 `CREATE TABLE` 参考 SQL，所有表和字段均配置 `COMMENT`。
- `resources/sql/04_tushare_stock_data_schema.sql`：Tushare 股票数据目录 15000 积分及以下接口的 `ts_stock_*` 建表 SQL，所有表和字段均配置 `COMMENT`。
- `resources/doc/tushare-stock-data-tables.md`：Tushare 股票数据目录接口、本地表名和数据描述映射文档。

## 当前表清单

核心行情与交易日历：

- `a_stock_basic`：A 股基础信息。
- `hk_stock_basic`：港股基础信息。
- `a_trade_calendar`：A 股交易日历。
- `hk_trade_calendar`：港股交易日历。
- `a_daily_quote`：A 股日线行情。
- `hk_daily_quote`：港股日线行情，当前 token 无权限时仅保留结构。

A/H 溢价与可交易性：

- `hsgt_constituent`：沪深港通标的名单。
- `fx_rate_daily`：外汇汇率日线。
- `ah_stock_pair`：AH 股票配对。
- `official_ah_comparison`：Tushare 官方 AH 比价快照，当前主展示口径。
- `ah_premium_daily`：自算港股通 AH 溢价结果，当前仅作实时、扩展和校验口径保留。
- `watchlist_stock`：用户自选 AH 股票。

任务、质量与问答：

- `sync_run`：数据同步任务运行记录。
- `sync_checkpoint`：数据同步断点。
- `data_quality_issue`：数据质量问题记录。
- `llm_chat_session`：LLM 问答会话。
- `llm_chat_message`：LLM 问答消息。

Tushare 股票数据目录补充表：

- `ts_stock_*`：Tushare `doc_id=14` 股票数据目录中权限要求 15000 积分及以下的接口落库表，每个 SDK 接口单独一张表，表名和说明见 `resources/doc/tushare-stock-data-tables.md`。

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

Tushare 股票数据目录的批量补充表单独维护在 `04_tushare_stock_data_schema.sql` 和 `tushare-stock-data-tables.md`，避免主业务表 SQL 过大影响日常审阅。
