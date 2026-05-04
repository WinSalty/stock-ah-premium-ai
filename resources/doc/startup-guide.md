# 项目启动手册

更新日期：2026-05-04

## 1. 目录与端口

项目根目录：

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai
```

默认端口：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`
- MySQL：`127.0.0.1:3306`

## 2. 环境要求

- Python：3.11+，本机已验证 `/opt/homebrew/bin/python3.13`。
- Node.js：支持 Vite 5 的版本。
- MySQL：本机 MySQL 5.7，连接说明见 `/Users/salty/codeProject/ai/doc/mysqluse.md`。
- Tushare：使用 Python `tushare` SDK，默认中转地址 `http://tsy.xiaodefa.cn`，同步接口运行时优先读取本机文件 `/Users/salty/codeProject/ai/doc/tushare-token.txt`，环境变量 `TUSHARE_TOKEN` 作为兜底。
- LLM：运行智能问答时需要 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。

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
TUSHARE_API_URL=http://tsy.xiaodefa.cn
TUSHARE_REQUEST_INTERVAL_SECONDS=0.6
SYNC_SCHEDULER_ENABLED=true
SYNC_SCHEDULER_TIMEZONE=Asia/Shanghai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=
APP_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

不要把真实 Token、数据库密码或 LLM Key 写入仓库。若 shell 中残留旧 `TUSHARE_TOKEN`，项目仍会优先使用 `TUSHARE_TOKEN_FILE` 指向的文件，避免误用旧 token。

Tushare 中转服务文档见 `http://tsy.xiaodefa.cn/docs`。项目后端已按其 SDK 方式设置。文档示例使用 `ts.set_token(token)`，项目实现采用 `ts.pro_api(token, timeout=...)` 直接传入 token，避免 SDK 把 token 额外写到用户目录缓存文件：

```python
import tushare as ts

pro = ts.pro_api(token, timeout=30)
pro._DataApi__http_url = "http://tsy.xiaodefa.cn"
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

浏览器访问：

```text
http://127.0.0.1:5173
```

## 8. 常用命令

```bash
make bootstrap
make check
make init-db
make backend
make frontend
```

等价脚本：

```bash
./scripts/bootstrap.sh
./scripts/check.sh
./scripts/init-db.sh
./scripts/start-backend.sh
./scripts/start-frontend.sh
```

## 9. 非外部依赖检查

```bash
./scripts/check.sh
```

检查内容：

- 后端 `ruff check app tests`。
- 后端 `pytest`。
- 前端 `npm run build`。
- 前端 `npm audit --omit=dev`。

该命令不调用 Tushare、不调用 LLM、不执行真实数据同步。

## 10. 低权限兜底导入

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

## 11. 数据同步顺序

同步入口在前端“数据同步 / 接口同步”页。

溢价页面以 `official_ah_comparison` 为展示主表。官方 `ah_comparison` 每天盘后更新；日间如果需要刷新当前日计算结果，可在“AH 官方比价”页点击“刷新实时”，结果会写回官方 AH 比价表并通过 `is_realtime` 标记来源。

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

## 12. 页面显示规则

- 时间字段统一按东八区 `yyyy-MM-dd HH:mm:ss` 展示；纯日期字段保持 `yyyy-MM-dd`。
- 同步任务、统一查询、智能问答结果和溢价表格中的长字段会单行省略，悬浮展示完整内容。
- 错误信息过长时，可在同步任务记录中悬浮查看完整错误，也可以点击“查看”打开详情弹窗。
- 日期类表格列已适当加宽，避免固定长度字段被换行挤压。

## 13. 常见问题

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

### LLM 问答返回未配置

确认 `backend/.env` 中已经配置：

```bash
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
```

## 14. 当前验证状态

已验证：

- `./scripts/bootstrap.sh`
- `./scripts/check.sh`
- `./scripts/init-db.sh`
- 本地 MySQL `stock_ah_ai` 表和视图创建
- Tushare 中转 SDK 最大范围同步：A 股基础、港股基础、交易日历、官方 AH 比价、港股通名单、A 股日线
- Tushare 中转 SDK `stock_basic limit=1` 最小连通性，不落库

未验证：

- `hk_daily`：当前 token 无法请求，已禁用
- LLM 真实问答
- 真实行情数据下的端到端页面联调
