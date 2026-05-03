# 开发进度记录

更新日期：2026-05-04

## 当前状态

已按一阶段方案完成主要代码开发，暂不执行真实功能测试。原因是当前 Tushare Token 权限较低，且用户明确要求先尽量完成代码开发，不进行功能测试。

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
  - LLM 只读视图和只读用户模板 SQL。
- Tushare 同步：
  - HTTP 客户端封装。
  - 数据集配置：A 股基础、A 股日线、A 股交易日历、港股基础、港股日线、港股交易日历、沪深港通名单、外汇日线、官方 AH 比价。
  - 同步任务记录、失败状态、checkpoint、MySQL upsert。
  - 官方 AH 比价同步后维护 AH 配对。
- A/H 溢价计算：
  - 港股通通道过滤。
  - A 股/H 股同日行情对齐。
  - HKD/CNY 直接汇率优先，USD/CNH 与 USD/HKD 交叉汇率兜底。
  - 缺 A 股行情、缺 H 股行情、缺汇率、H 股价格为 0 等状态入库。
  - 官方 AH 比价差异字段。
- LLM 问答：
  - OpenAI-compatible Chat API 封装。
  - 只读 SQL Guard：只允许 SELECT、禁止多语句和写库操作、限制白名单视图、自动 limit。
  - 会话与消息落库。
- 前端 React 项目：
  - 总览页：指标、溢价榜、Top 10 图表。
  - 数据同步页：数据集、日期、代码、通道、任务记录。
  - AH 溢价页：筛选、分页表格、计算入口、趋势抽屉。
  - 智能问答页：会话、问题输入、SQL 预览和结果表格。
- 非真实功能测试资产：
  - 后端公式单元测试。
  - SQL Guard 单元测试。

## 暂未执行

- 未读取 `/Users/salty/codeProject/ai/doc/tushare-token.txt` 内容。
- 未调用 Tushare 接口。
- 未调用 LLM API。
- 未连接或初始化本地 MySQL。
- 未执行端到端功能测试。

## 已执行的非功能性检查

- `python3 -m compileall backend/app backend/tests`：通过。
- 后端虚拟环境使用 `/opt/homebrew/bin/python3.13` 创建，`pytest`：3 个单元测试通过。
- `ruff check app tests`：通过。
- `npm install`：完成，生成 `frontend/package-lock.json`。
- `npm run build`：通过。
- `npm audit --omit=dev`：0 个生产依赖漏洞。
- 敏感信息扫描：只发现文档中的 `<local-only>` 占位符，未发现真实 Token、密码或 API Key。

## 待验证事项

- Tushare 低权限 Token 可用接口范围。
- `stock_hsgt`、`hk_daily`、`stk_ah_comparison`、`fx_daily` 的实际返回字段与当前字段映射是否完全一致。
- MySQL 5.7 环境下 Alembic 迁移和只读视图脚本。
- 前后端联调、页面响应式截图和真实数据展示。
- LLM 输出 SQL 的稳定性和问答答案质量。

## 下一步建议

1. 在确认可以做功能测试后，先用本机 MySQL 跑 `00_create_database.sql` 和 `alembic upgrade head`。
2. 用低权限 Tushare Token 跑 `stock_basic`、`trade_cal` 等基础接口，记录权限不足的数据集。
3. 若 AH 官方比价或港股通接口权限不足，先导入人工 AH 配对 CSV 和汇率 CSV，完成自算链路验证。
4. 配置 LLM Key 后验证 SQL Guard 和问答闭环。
