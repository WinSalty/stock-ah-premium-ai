# 开发进度记录

更新日期：2026-05-04

## 当前状态

已按一阶段方案完成主要代码开发和本地 MySQL 初始化验证。当前已按中转服务文档切换为 Tushare Python SDK 调用方式，默认地址为 `http://tsy.xiaodefa.cn`。Tushare Token 已调整为本机文件优先，避免旧环境变量干扰；LLM Key 尚未配置。

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
  - 已在本地 MySQL 5.7 完成建库、Alembic 迁移和只读视图创建验证。
- Tushare 同步：
  - Python SDK 客户端封装，按中转文档设置 `pro._DataApi__http_url`。
  - 使用 `ts.pro_api(token, timeout=...)` 进程内传入 token，避免 SDK 额外写入用户目录缓存文件。
  - Token 读取策略为 `/Users/salty/codeProject/ai/doc/tushare-token.txt` 优先，`TUSHARE_TOKEN` 环境变量兜底。
  - 默认中转地址 `http://tsy.xiaodefa.cn`，支持请求间隔配置，降低触发冷却风险。
  - 数据集配置：A 股基础、A 股日线、A 股交易日历、港股基础、港股日线、港股交易日历、沪深港通名单、外汇日线、官方 AH 比价。
  - 同步任务记录、失败状态、checkpoint、MySQL upsert。
  - 官方 AH 比价同步后维护 AH 配对。
- 低权限兜底导入：
  - 支持通过 `POST /api/manual-import/ah-pairs` 导入人工 AH 配对。
  - 支持通过 `POST /api/manual-import/fx-rates` 导入人工汇率。
  - 支持通过 CSV 文本接口导入人工 AH 配对和汇率。
  - 前端同步页增加人工导入入口。
  - 增加人工导入服务单元测试。
- A/H 溢价计算：
  - 港股通通道过滤。
  - A 股/H 股同日行情对齐。
  - HKD/CNY 直接汇率优先，USD/CNH 与 USD/HKD 交叉汇率兜底。
  - 自算 A/H 比价、A/H 溢价，并由 A/H 反推 H/A 比价、H/A 溢价后落表。
  - 缺 A 股行情、缺 H 股行情、缺汇率、H 股价格为 0 等状态入库。
  - 官方 AH 与 H/A 比价、溢价差异字段。
- LLM 问答：
  - OpenAI-compatible Chat API 封装。
  - 只读 SQL Guard：只允许 SELECT、禁止多语句和写库操作、限制白名单视图、自动 limit。
  - 会话与消息落库。
- 统一数据查询：
  - 后端新增 `/api/query/datasets` 和 `/api/query/rows`，按白名单查询已同步数据。
  - 支持 A 股/港股基础信息、交易日历、日线行情、沪深港通名单、外汇、AH 配对、官方 AH 比价、自算 AH 溢价、同步任务记录。
  - 支持关键词、日期范围、分页和字段列定义返回。
  - 官方 AH 比价表增加 H/A 比价和 H/A 溢价查询字段。
- 前端 React 项目：
  - 总览页：指标、溢价榜、Top 10 图表。
  - 总览页新增官方 AH/H/A 溢价趋势折线图，默认展示招商银行 H/A 溢价，并支持选择股票和方向。
  - 总览页趋势图支持日期范围缩放，扩大图表显示区域；溢价榜调整到走势图下方；股票选择下拉项在 A/H 名称相同时合并为单名展示。
  - 数据同步页：数据集、日期、代码、通道、任务记录。
  - 数据查询页：切换查看不同同步数据，支持关键词、日期范围和分页。
  - AH 溢价页：筛选、分页表格、计算入口、趋势抽屉。
  - 智能问答页：会话、问题输入、SQL 预览和结果表格。
- 本地运行与验收脚本：
  - `scripts/bootstrap.sh`：安装后端和前端依赖。
  - `scripts/check.sh`：执行 Ruff、pytest、前端构建和生产依赖审计。
  - `scripts/init-db.sh`：创建数据库、执行 Alembic 迁移和只读视图 SQL。
  - `scripts/start-backend.sh`、`scripts/start-frontend.sh`：启动本地服务。
  - `Makefile`：提供 `make bootstrap/check/init-db/backend/frontend` 快捷入口。
  - `resources/doc/startup-guide.md`：完整启动、配置、验证和排错手册。
- 非真实功能测试资产：
  - 后端公式单元测试。
  - SQL Guard 单元测试。

## 暂未执行

- 启动服务前不会在文档或代码中写入 `/Users/salty/codeProject/ai/doc/tushare-token.txt` 内容。
- 已执行最近 7 个共同交易日批量同步；`hk_daily` 因官方频率限制未补齐。
- 未调用 LLM API。
- 未执行依赖 Tushare 或 LLM 的端到端功能测试。

## 已执行的非功能性检查

- `python3 -m compileall backend/app backend/tests`：通过。
- 后端虚拟环境使用 `/opt/homebrew/bin/python3.13` 创建，`pytest`：10 个单元测试通过。
- `ruff check app tests`：通过。
- `npm install`：完成，生成 `frontend/package-lock.json`。
- `npm run build`：通过。
- `npm audit --omit=dev`：0 个生产依赖漏洞。
- `scripts/init-db.sh`：通过，已创建/更新 `stock_ah_ai` 表和视图；已应用 `20260504_0002`，为官方 AH 比价和自算溢价表补充 H/A 字段并回填历史数据。
- `scripts/check.sh`：已在切换 Tushare 中转 SDK、调整 token 文件优先级后重新通过。
- 新增数据查询后，`scripts/check.sh` 已重新通过。
- Tushare 中转 SDK 最小连通性：`stock_basic` 携带 `limit=1` 查询成功返回 1 行，未落库。
- 敏感信息扫描：只发现文档中的 `<local-only>` 占位符，未发现真实 Token、密码或 API Key。

## 待验证事项

- 当前 Tushare 中转 Token 的完整可用接口范围。
- `stock_hsgt`、`hk_daily`、`stk_ah_comparison`、`fx_daily` 的实际返回字段与当前字段映射是否完全一致。
- 前后端联调、页面响应式截图和真实数据展示。
- LLM 输出 SQL 的稳定性和问答答案质量。

## 下一步建议

1. 用当前 Tushare 中转 Token 跑 `stock_basic`、`trade_cal` 等基础接口，记录权限不足的数据集。
2. 若 AH 官方比价或港股通接口权限不足，先导入人工 AH 配对 CSV 和汇率 CSV，完成自算链路验证。
3. 配置 LLM Key 后验证 SQL Guard 和问答闭环。
4. 启动前后端后做页面联调和响应式截图验证。
