# 项目启动手册

更新日期：2026-05-05

## 1. 目录与端口

项目根目录：

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai
```

默认端口：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`
- MySQL：`127.0.0.1:3306`

服务器单机部署时，可继续使用前端 `5173`、后端 `8000`、MySQL 本机 `3306` 的端口划分；公网部署、无 Nginx 反代和云防火墙排障见：[单机服务器部署记录](./server-deployment-guide.md)。

## 2. 环境要求

- Python：3.11+，本机已验证 `/opt/homebrew/bin/python3.13`。
- Node.js：支持 Vite 5 的版本。
- MySQL：本机 MySQL 5.7，连接说明见 `/Users/salty/codeProject/ai/doc/mysqluse.md`。
- Tushare：使用 Python `tushare` SDK，默认中转地址 `https://tt.xiaodefa.cn`，同步接口运行时优先读取本机文件 `/Users/salty/codeProject/ai/doc/tushare-token.txt`，环境变量 `TUSHARE_TOKEN` 作为兜底。
- LLM：运行智能问答时默认接入 DeepSeek OpenAI-compatible API，优先读取本机文件 `/Users/salty/codeProject/ai/doc/deepseek-apikey.txt`，环境变量 `LLM_API_KEY` 作为兜底，默认 API 模型 `deepseek-v4-flash`；页面可切换 DeepSeek Pro `deepseek-v4-pro` 或阿里 Qwen `qwen3.6-flash`，Qwen Key 优先读取 `/Users/salty/codeProject/ai/doc/qwen-apikey.txt`；项目级外部模型调用默认日限额为 `LLM_DAILY_CALL_LIMIT=100`。
- 文生图：默认接入 86GameStore OpenAI Images 兼容接口，优先读取本机文件 `/Users/salty/codeProject/ai/doc/86gamestore-image-apikey.txt`，环境变量 `IMAGE_GEN_API_KEY` 作为兜底；图片默认保存到 `/opt/stock-ah-premium-ai/data/generated-images`，用于和代码目录分离，部署时需确保后端运行用户可写。

启动 MySQL：

```bash
brew services start local/old-mysql/mysql@5.7
```

确认 MySQL 客户端：

```bash
/opt/homebrew/opt/mysql@5.7/bin/mysql --version
```

## 3. 首次安装依赖

```bash
./scripts/bootstrap.sh
```

脚本会执行：

- 使用 `/opt/homebrew/bin/python3.13` 创建 `backend/.venv`。
- 安装后端依赖和开发检查工具。
- 执行 `npm install` 安装前端依赖。

如果 Python 路径不同：

```bash
PYTHON_BIN=/path/to/python3.11 ./scripts/bootstrap.sh
```

## 4. 配置文件

创建后端本地配置：

```bash
cp backend/.env.example backend/.env
```

默认数据库连接：

```bash
STOCK_AH_DB_URL=mysql+pymysql://root@127.0.0.1:3306/stock_ah_ai?charset=utf8mb4
```

可选配置：

```bash
TUSHARE_TOKEN=
TUSHARE_TOKEN_FILE=/Users/salty/codeProject/ai/doc/tushare-token.txt
TUSHARE_API_URL=https://tt.xiaodefa.cn
TUSHARE_REQUEST_INTERVAL_SECONDS=0.6
SYNC_SCHEDULER_ENABLED=true
SYNC_SCHEDULER_TIMEZONE=Asia/Shanghai
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY_FILE=/Users/salty/codeProject/ai/doc/deepseek-apikey.txt
LLM_API_KEY=
LLM_MODEL=deepseek-v4-flash
LLM_DAILY_CALL_LIMIT=100
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY_FILE=/Users/salty/codeProject/ai/doc/qwen-apikey.txt
QWEN_API_KEY=
QWEN_QUESTION_ROUTER_MODEL=deepseek-v4-flash
IMAGE_GEN_BASE_URL=https://api.86gamestore.com
IMAGE_GEN_API_KEY_FILE=/Users/salty/codeProject/ai/doc/86gamestore-image-apikey.txt
IMAGE_GEN_API_KEY=
IMAGE_GEN_MODEL=gpt-image-2
IMAGE_GEN_TIMEOUT_SECONDS=300
IMAGE_GEN_DAILY_LIMIT_DEFAULT=10
IMAGE_GEN_STORAGE_DIR=/opt/stock-ah-premium-ai/data/generated-images
APP_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

不要把真实 Token、数据库密码、LLM Key 或文生图 Key 写入仓库。若 shell 中残留旧 `TUSHARE_TOKEN`，项目仍会优先使用 `TUSHARE_TOKEN_FILE` 指向的文件，避免误用旧 token；DeepSeek、Qwen 和文生图 Key 同理优先使用本机文件。

智能问答仅面向投资研究问题。后端会先用 `deepseek-v4-flash` 做单次 JSON 前置路由，同时判断是否可答、是否需要结构化数据、是否需要按需补充市场数据，再为选定问答模型注入专业金融投资分析顾问角色、最近会话上下文、页面上下文、数据摘要和按需补数结果；前端只展示报告和数据摘要表格，不展示 SQL 或底层查询过程。若历史环境中仍配置 `deepseek-v4-pro[1m]`，后端会在请求 DeepSeek 时自动归一化为 API 支持的 `deepseek-v4-pro`；当前不额外传 `reasoning_effort`。

Tushare 中转服务文档见 `https://tt.xiaodefa.cn/docs`。项目后端已按其 SDK 方式设置。文档示例使用 `ts.set_token(token)`，项目实现采用 `ts.pro_api(token, timeout=...)` 直接传入 token，避免 SDK 把 token 额外写到用户目录缓存文件：

```python
import tushare as ts

pro = ts.pro_api(token, timeout=30)
pro._DataApi__http_url = "https://tt.xiaodefa.cn"
```

如中转服务返回超时或冷却提示，优先调大 `TUSHARE_REQUEST_INTERVAL_SECONDS`，不要高频重试。

## 5. 初始化数据库

```bash
./scripts/init-db.sh
```

脚本会执行：

- 创建数据库 `stock_ah_ai`。
- 运行 Alembic 表结构迁移。
- 创建 LLM 只读查询视图。

完整建表 SQL 注释版维护在 `resources/sql/03_full_schema_with_comments.sql`。该文件用于文档审阅、新环境结构核对和字段含义确认；日常初始化仍以 `./scripts/init-db.sh` 执行的 Alembic 迁移为准。

验证表和视图：

```bash
/opt/homebrew/opt/mysql@5.7/bin/mysql -u root stock_ah_ai -e "SHOW TABLES;"
```

## 6. 启动后端

```bash
./scripts/start-backend.sh
```

启动脚本会输出：

- 项目根目录、后端目录、绑定地址和健康检查地址。
- `backend/.env` 是否存在，以及数据库连接的脱敏摘要。
- Tushare、DeepSeek、Qwen 本机密钥文件是否存在。
- 后端调度开关、Python 版本、Uvicorn 版本。
- 端口占用诊断；如果 `8000` 已被占用，会列出占用进程并提示停止命令。

可改端口启动：

```bash
BACKEND_PORT=8001 ./scripts/start-backend.sh
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

公开配置检查：

```bash
curl http://127.0.0.1:8000/api/settings/public
```

## 7. 启动前端

新开一个终端：

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai
./scripts/start-frontend.sh
```

启动脚本会输出：

- 项目根目录、前端目录、绑定地址和后端代理目标。
- `VITE_API_BASE_URL` 当前状态。
- Node.js、npm 版本。
- 端口占用诊断；如果 `5173` 已被占用，会列出占用进程并提示停止命令。

可改端口启动：

```bash
FRONTEND_PORT=5174 ./scripts/start-frontend.sh
```

浏览器访问：

```text
http://127.0.0.1:5173
```

## 8. 停止和重启

停止单个服务：

```bash
./scripts/stop-backend.sh
./scripts/stop-frontend.sh
```

停止前后端：

```bash
./scripts/stop.sh
```

重启单个服务，默认仍以前台方式启动：

```bash
./scripts/restart-backend.sh
./scripts/restart-frontend.sh
```

重启整个项目会先停止前后端，再后台拉起两个服务，并把日志写入 `.runtime/logs/`：

```bash
./scripts/restart.sh
tail -f .runtime/logs/backend.log
tail -f .runtime/logs/frontend.log
```

使用非默认端口重启：

```bash
BACKEND_PORT=8001 FRONTEND_PORT=5174 ./scripts/restart.sh
```

## 9. 常用命令

```bash
make bootstrap
make check
make init-db
make backend
make frontend
make stop
make restart
```

等价脚本：

```bash
./scripts/bootstrap.sh
./scripts/check.sh
./scripts/init-db.sh
./scripts/start-backend.sh
./scripts/start-frontend.sh
./scripts/stop.sh
./scripts/restart.sh
```

## 10. 非外部依赖检查

```bash
./scripts/check.sh
```

检查内容：

- 后端 `ruff check app tests`。
- 后端 `pytest`。
- 前端 `npm run build`。
- 前端 `npm audit --omit=dev`。

该命令不调用 Tushare、不调用 LLM、不执行真实数据同步。

## 11. 低权限兜底导入

当 Tushare AH 比价或外汇接口权限不足时，可以在前端“数据同步 / 人工导入”页粘贴 CSV。

AH 配对 CSV：

```csv
a_ts_code,hk_ts_code,a_name,hk_name,effective_start_date,effective_end_date,is_active
600000.SH,00005.HK,浦发银行,汇丰控股,2026-05-04,,true
```

汇率 CSV：

```csv
rate_pair,rate_date,mid_rate,source,raw_ts_code
HKD_CNY,2026-05-04,0.9200,MANUAL,
```

也可以直接调用接口：

```bash
curl -X POST http://127.0.0.1:8000/api/manual-import/ah-pairs/csv \
  -H "Content-Type: application/json" \
  -d '{"content":"a_ts_code,hk_ts_code\n600000.SH,00005.HK\n"}'
```

## 12. 数据同步顺序

同步入口在前端“数据同步 / 接口同步”页。

溢价页面以 `official_ah_comparison` 为展示主表。官方 `ah_comparison` 每天盘后更新；日间如果需要刷新当前日计算结果，可在“AH 官方比价”页点击“刷新实时”，结果会写回官方 AH 比价表并通过 `is_realtime` 标记来源。官方 AH 比价落库前会校验 A 股、港股交易日历，任一市场休市时跳过该日期的溢价结果，并清理该日期已有误落数据。均值、中位数和分位指标按最近 N 条有效官方交易记录计算，不按自然日天数计算。

推荐优先使用“一键模式”：

1. `增量同步`：按各数据集 checkpoint 自动补齐最近缺口，并保留 2 天重叠窗口以覆盖延迟修正。
2. `全量重跑`：按本项目默认历史起点重新请求并 upsert，本地已有记录会被更新，不会产生重复数据。

如果需要人工控制范围，可在单数据集同步里选择“按输入参数”，再填写交易日、日期范围、代码或港股通通道。行情类全市场日期范围会按交易日拆分请求；指定单个 `ts_code` 时会优先用接口原生日期范围。

默认一键同步会按 AH 溢价计算所需顺序执行：

1. `stock_basic`
2. `hk_basic`
3. `trade_cal`
4. `hk_tradecal`
5. `ah_comparison`
6. `stock_hsgt` 的 `SH_HK`、`SZ_HK`
7. `a_daily`
8. `fx_daily`

`hk_daily` 当前 token 无法请求，已禁用接口同步，一键同步不会再尝试该接口。若后续有可用权限，再重新启用。

分红再投筛选的 ROE 字段只读取 `a_financial_indicator.roe`。如果榜单中 ROE 大量为空，可在单数据集同步里运行 `A 股财务指标（a_financial_indicator）`，或在“同步分红再投数据”表单勾选“逐股补齐 ROE 财务指标”后重跑。普通 Tushare `fina_indicator` 接口需要按单只股票请求，因此后端会基于本地 `a_stock_basic` 在市股票逐股同步；该任务请求量较大，默认定时安排在周六 22:20 执行。

若 Tushare 官方 `stk_ah_comparison` 历史覆盖不足，可使用 `water-stock` 的 Baidu 全量日 K 补齐自选股缺失比价。补齐任务读取 `watchlist_stock`，分别拉取 A 股、H 股和 `HKDCNY` 汇率历史数据；只要 A 股收盘价、H 股收盘价和同日汇率三类数据在同一日期都存在，就向 `official_ah_comparison` 插入一行，不再依赖本地交易日历覆盖范围。写入使用 `insert ignore`，同一 `trade_date + a_ts_code + hk_ts_code` 已存在时直接跳过，重跑不会覆盖 Tushare 官方行或实时计算行。`historical_premium_backfill_record` 记录每个 A/H 股票对的补数状态，已完成的股票对后续定时任务会在请求 Baidu 前跳过；失败或未记录的股票对仍会在下次重试。

招商银行单票测试可在 `water-stock` 启动参数中设置：

```bash
--stock-ah.realtime.enabled=false \
--stock-ah.historical-premium.enabled=true \
--stock-ah.historical-premium.target-a-ts-codes=600036.SH
```

默认全量起点：

- `ah_comparison`、`stock_hsgt`、`a_daily`、`fx_daily`：`2025-08-12`。
- `trade_cal`、`hk_tradecal`：`2025-01-01`，并额外同步未来约 1 年日历。
- `stock_basic`、`hk_basic`：基础清单接口不带日期范围，增量和全量都会刷新当前全表。
- `hk_daily`：当前禁用，不设置全量重跑入口。

任务记录可按数据集、状态和开始时间范围筛选；权限不足或接口失败会在记录里显示为 `FAILED`，错误详情可悬浮或点击查看。

### A 股选股因子同步

LLM 选股不再同步 Tushare 股票目录原始大表，而是维护核心宽表 `stock_selection_factor_snapshot`。

同步入口：

```bash
curl -X POST "http://127.0.0.1:8000/api/sync/batches/stock-selection-factors" \
  -H "Content-Type: application/json" \
  -d '{"mode":"full"}'
```

该任务会联网读取 Tushare 最新 `daily_basic`、指数成分、财务指标、分红、业绩预告和日线行情，筛选几十只蓝筹、低估值和红利候选股票。LLM 只读视图为 `v_stock_selection_latest`、`v_stock_selection_history` 和 `v_stock_factor_dictionary`。

### 定时增量同步

后端启动时默认开启 APScheduler 后台任务，所有时间按东八区执行，可用 `SYNC_SCHEDULER_ENABLED=false` 临时关闭。

当前增量任务按 Tushare 文档更新时点和本项目数据依赖设置：

| 时间 | 数据集 | 参数 | 依据 |
| --- | --- | --- | --- |
| 工作日 09:05 | `stock_basic` | `mode=incremental` | 基础清单接口不带日期范围，早盘前刷新当前全表 |
| 工作日 09:10 | `hk_basic` | `mode=incremental` | 基础清单接口不带日期范围，早盘前刷新当前全表 |
| 周一 08:35 | `trade_cal` | `mode=incremental` | 交易日历支持日期范围，每周补齐并维持未来窗口 |
| 周一 08:40 | `hk_tradecal` | `mode=incremental` | 港股交易日历支持日期范围，每周补齐并维持未来窗口 |
| 工作日 09:25 | `stock_hsgt` | `type=SH_HK` | Tushare 文档提示 `stock_hsgt` 每天 09:20 更新 |
| 工作日 09:28 | `stock_hsgt` | `type=SZ_HK` | Tushare 文档提示 `stock_hsgt` 每天 09:20 更新 |
| 工作日 16:15 | `a_daily` | `mode=incremental` | Tushare 文档提示 `daily` 交易日 15:00-16:00 入库 |
| 工作日 17:10 | `ah_comparison` | `mode=incremental` | Tushare 文档提示 `stk_ah_comparison` 每天盘后 17:00 更新 |
| 周一至周六 07:30 | `fx_daily` | `mode=incremental` | 外汇接口交易日按 GMT，东八区早间补齐上一 GMT 交易日 |

定时任务仍走 `sync_run` 记录和 checkpoint。若某次接口权限不足或返回失败，任务会落 `FAILED`，下一次仍按 checkpoint 加 2 天重叠窗口继续补齐。`hk_daily` 已禁用，不会被定时任务调用。

## 13. 页面显示规则

- 时间字段统一按东八区 `yyyy-MM-dd HH:mm:ss` 展示；纯日期字段保持 `yyyy-MM-dd`。
- 同步任务、统一查询、智能问答结果和溢价表格中的长字段会单行省略，悬浮展示完整内容。
- 错误信息过长时，可在同步任务记录中悬浮查看完整错误，也可以点击“查看”打开详情弹窗。
- 日期类表格列已适当加宽，避免固定长度字段被换行挤压。

## 14. 常见问题

### Python 版本不对

现象：

```text
requires-python >=3.11
```

处理：

```bash
PYTHON_BIN=/opt/homebrew/bin/python3.13 ./scripts/bootstrap.sh
```

### MySQL 客户端找不到

现象：

```text
MySQL client not found
```

处理：

```bash
MYSQL_BIN=/opt/homebrew/opt/mysql@5.7/bin/mysql ./scripts/init-db.sh
```

### 后端连接数据库失败

确认 `.env` 中的 `STOCK_AH_DB_URL` 指向本地库：

```bash
grep STOCK_AH_DB_URL backend/.env
```

确认 MySQL 正在运行：

```bash
brew services list | grep mysql
```

### 前端请求 404 或网络错误

确认后端已经启动：

```bash
curl http://127.0.0.1:8000/api/health
```

确认前端由 Vite 启动，开发代理会把 `/api` 转发到后端。

### 服务器登录页提示 CORS 或请求后端失败

无 Nginx 反代、前端访问 `http://<server-ip>:5173` 时，浏览器会直接请求 `http://<server-ip>:8000/api/...`。因此除了后端 `APP_CORS_ORIGINS` 包含 `http://<server-ip>:5173` 外，云服务器安全组也必须放行 TCP `8000`。只放行 `5173` 会导致首页能打开，但登录接口失败，浏览器控制台可能显示为 CORS 错误。

先在服务器本机确认服务监听和 CORS：

```bash
ssh ubuntu@<server-ip> 'systemctl is-active stock-ah-backend stock-ah-frontend mysql'
ssh ubuntu@<server-ip> 'ss -ltnp | grep -E ":(8000|5173)"'
ssh ubuntu@<server-ip> 'curl -i -s -X OPTIONS http://127.0.0.1:8000/api/auth/login \
  -H "Origin: http://<server-ip>:5173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"'
```

再从本地网络直连后端公网端口：

```bash
curl --noproxy '*' --max-time 8 -i http://<server-ip>:8000/api/health
```

如果服务器本机正常、本地直连 `8000` 超时，优先处理云安全组或云防火墙。MySQL `3306` 不需要对公网开放，后端同机直连即可。完整部署记录见：[单机服务器部署记录](./server-deployment-guide.md)。

### LLM 问答返回未配置

确认 `backend/.env` 中已经配置：

```bash
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY_FILE=/Users/salty/codeProject/ai/doc/deepseek-apikey.txt
LLM_API_KEY=
LLM_MODEL=deepseek-v4-flash
LLM_DAILY_CALL_LIMIT=100
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY_FILE=/Users/salty/codeProject/ai/doc/qwen-apikey.txt
QWEN_API_KEY=
QWEN_QUESTION_ROUTER_MODEL=deepseek-v4-flash
```

问答页面使用流式响应，输入框按 Enter 发送，Shift+Enter 换行，并支持选择 `deepseek-v4-flash`、`deepseek-v4-pro` 或 `qwen3.6-flash`，默认 DeepSeek Flash；预设问题点击后会直接发送。空会话展示结构化投研场景预设问题，便于直接触发数据路由和按需补数。外部模型主调用会按项目维度做日限流，默认每天 100 次，统计范围包括 DeepSeek Flash 前置路由、SQL 生成/修复和最终回答调用，不包含首包耗时、SQL 执行和总耗时等内部指标。若页面一直没有响应，先确认后端 `/api/health` 正常，再查看后端日志中是否有 LLM 日限流、生成 SQL 字段名、前置路由或数据库执行错误。

AH 溢价、折价和套利相关问题可按前置路由补充本地候选池、市场分布和自选机会，避免只基于单行 SQL 结果作答。项目已移除自动静态投研材料注入链路和旧材料目录；银行/非银、个股报告、宏观地产金融推演等回答只基于会话历史、页面上下文、结构化市场观察、按需补数结果和模型自身金融知识组织。回答提示词要求 LLM 给出评级口径、配置倾向、优先级、仓位思路、阈值和触发条件，并避免输出模板化免责句。

## 15. 当前验证状态

已验证：

- `./scripts/bootstrap.sh`
- `./scripts/check.sh`
- `./scripts/init-db.sh`
- `./scripts/start-backend.sh`：已用 `BACKEND_PORT=18000` 验证启动诊断和 `/api/health`。
- `./scripts/start-frontend.sh`：已用 `FRONTEND_PORT=15173` 验证启动诊断。
- `./scripts/restart.sh`：已用 `BACKEND_PORT=18000 FRONTEND_PORT=15173` 验证整项目后台重启。
- `./scripts/stop.sh`：已用非默认端口验证停止诊断。
- `bash -n scripts/*.sh`：启动、停止、重启脚本语法检查通过。
- 本地 MySQL `stock_ah_ai` 表和视图创建
- 本地 MySQL 已执行 `alembic upgrade head`，应用到 `20260505_0015`。
- Tushare 中转 SDK 最大范围同步：A 股基础、港股基础、交易日历、官方 AH 比价、港股通名单、A 股日线
- Tushare 中转 SDK `stock_basic limit=1` 最小连通性，不落库

未验证：

- `hk_daily`：当前 token 无法请求，已禁用
- LLM 真实问答
- 真实行情数据下的端到端页面联调
