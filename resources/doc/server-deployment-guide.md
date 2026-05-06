# 单机服务器部署记录

更新日期：2026-05-06

本文记录项目首次部署到单台云服务器时的实际方案和排障结论。敏感连接信息、数据库密码、Token 和 API Key 不写入仓库，按需维护在工作区未入库文档或服务器本机配置中。

## 1. 部署口径

- 部署形态：前端、后端、MySQL 同机部署。
- 反向代理：当前不使用 Nginx。前端直接暴露 `5173`，后端直接暴露 `8000`。
- 数据库访问：MySQL 与后端同机，后端继续使用 `127.0.0.1:3306` 直连。
- 数据来源：不迁移本地数据库，不使用 `mysqldump` 或复制数据文件；服务器空库初始化后，通过应用内 Tushare 同步功能重新拉取数据。
- 管理员：初始化环境只保留一个管理员账号。账号和初始密码通过后端环境变量配置，首次登录或初始化接口创建。

## 2. 服务器基础环境

已验证的部署环境为 Ubuntu 24.04。建议安装：

- Python 3.11+ 和 `venv`
- Node.js 18+ 与 npm
- MySQL 8
- OpenJDK 8 运行环境，并配置 `JAVA_HOME`、`PATH`

JDK 8 不是当前 FastAPI/React 主链路必需依赖，但属于服务器运行环境要求，应随部署一起安装并在登录 shell 和 systemd 环境中可见。

## 3. 目录与服务

推荐服务器目录：

```text
/home/ubuntu/stock-ah-premium-ai
```

推荐 systemd 服务：

```text
stock-ah-backend
stock-ah-frontend
mysql
```

后端服务示例：

```bash
cd /home/ubuntu/stock-ah-premium-ai/backend
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

前端生产预览服务示例：

```bash
cd /home/ubuntu/stock-ah-premium-ai/frontend
npm run preview -- --host 0.0.0.0 --port 5173 --strictPort
```

若后续改为正式静态文件服务或同源部署，可再调整；当前单机无 Nginx 方案要求浏览器能直接访问 `5173` 和 `8000` 两个端口。

## 4. 后端环境变量

服务器后端 `.env` 应放在：

```text
/home/ubuntu/stock-ah-premium-ai/backend/.env
```

关键配置项：

```bash
STOCK_AH_DB_URL=mysql+pymysql://<user>:<url-encoded-password>@127.0.0.1:3306/stock_ah_ai?charset=utf8mb4
TUSHARE_TOKEN_FILE=/home/ubuntu/stock-ah-premium-ai/secrets/tushare-token.txt
LLM_API_KEY_FILE=/home/ubuntu/stock-ah-premium-ai/secrets/deepseek-apikey.txt
QWEN_API_KEY_FILE=/home/ubuntu/stock-ah-premium-ai/secrets/qwen-apikey.txt
PUSHPLUS_CONFIG_FILE=/home/ubuntu/stock-ah-premium-ai/secrets/pushplus.txt
APP_CORS_ORIGINS=["http://<server-ip>:5173","http://<server-ip>:8000","http://localhost:5173","http://127.0.0.1:5173"]
DEFAULT_ADMIN_USERNAME=<admin-user>
DEFAULT_ADMIN_PASSWORD=<admin-password>
```

注意事项：

- 数据库密码如果包含 `@`、`#`、`:` 等特殊字符，必须在 URL 中编码，例如 `@` 写成 `%40`。
- 密钥文件建议统一放在服务器项目目录的 `secrets/` 下，权限设置为 `600`。
- `APP_CORS_ORIGINS` 在 Pydantic JSON 解析下可以使用 JSON 数组形式，服务器公网前端地址必须在列表中。

## 5. 数据库初始化

初始化顺序：

1. 创建数据库 `stock_ah_ai`。
2. 配置后端 `.env` 的 `STOCK_AH_DB_URL`。
3. 安装后端依赖并执行 Alembic 迁移到 `head`。
4. 执行只读视图 SQL：`resources/sql/01_readonly_views.sql`。
5. 启动后端，确认 `/api/health` 正常。

首次部署遇到过 MySQL 8 兼容和视图依赖问题：

- MySQL 8 upsert 不应依赖 `VALUES()` 旧写法或不存在的稀疏字段；当前代码已修复为只更新实际出现的字段。
- 某些迁移会依赖只读视图。若空库迁移提示视图不存在，应先补齐基础只读视图，再重跑迁移和完整视图 SQL。
- 视图最终以 `resources/sql/01_readonly_views.sql` 为准；迁移完成后应重新执行一次该 SQL，确保 LLM 只读查询视图为最新版本。

## 6. 前端构建与 API 地址

无 Nginx 反代时，前端构建应明确后端公网地址：

```bash
cd /home/ubuntu/stock-ah-premium-ai/frontend
VITE_API_BASE_URL=http://<server-ip>:8000 npm run build
```

然后使用 `npm run preview -- --host 0.0.0.0 --port 5173 --strictPort` 提供访问。

这种模式下，浏览器访问：

```text
http://<server-ip>:5173
```

前端会跨源请求：

```text
http://<server-ip>:8000/api/...
```

因此后端 CORS 配置和云服务器安全组必须同时正确。只放行 `5173` 不够，浏览器仍然无法访问后端接口。

## 7. 云防火墙与 CORS 排障

首次部署登录页出现过类似错误：

```text
Access to fetch at 'http://<server-ip>:8000/api/auth/login' from origin 'http://<server-ip>:5173' has been blocked by CORS policy
No 'Access-Control-Allow-Origin' header is present on the requested resource
```

服务端本机测试 CORS 成功，但本地浏览器仍失败时，优先检查云服务器安全组或云防火墙，而不是只改后端代码。

推荐排查顺序：

```bash
ssh ubuntu@<server-ip> 'systemctl is-active stock-ah-backend stock-ah-frontend mysql'
ssh ubuntu@<server-ip> 'ss -ltnp | grep -E ":(8000|5173)"'
ssh ubuntu@<server-ip> 'sudo ufw status'
```

服务器本机验证后端和 CORS：

```bash
ssh ubuntu@<server-ip> 'curl -i -s -X OPTIONS http://127.0.0.1:8000/api/auth/login \
  -H "Origin: http://<server-ip>:5173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"'
```

本地网络验证后端公网端口：

```bash
curl --noproxy '*' --max-time 8 -i http://<server-ip>:8000/api/health
```

判断标准：

- 服务器本机 `127.0.0.1:8000` 正常、本地访问 `<server-ip>:8000` 超时：通常是云安全组或云防火墙未放行 `8000`。
- 本地访问返回 502 或代理错误：先排查本机代理环境，使用 `--noproxy '*'` 复测。
- `OPTIONS` 响应中没有 `access-control-allow-origin`：检查 `APP_CORS_ORIGINS` 是否包含准确的前端 origin，协议、IP、端口必须完全一致。

当前无 Nginx 方案至少需要放行：

```text
TCP 5173
TCP 8000
```

MySQL `3306` 不需要对公网开放，后端本机直连即可。

## 8. 股票数据同步

服务器初始化不复制本地数据。数据同步应通过应用接口或前端“数据同步”页面发起，确保 `sync_run`、checkpoint 和业务 upsert 逻辑都正常运行。

推荐流程：

1. 初始化数据库结构和只读视图。
2. 启动后端和前端。
3. 使用管理员账号登录。
4. 在“数据同步”页执行一键全量重跑。
5. 执行 A 股选股因子同步。
6. 等待同步任务完成后，再进行最终重启或验收。

验收时可以用本地开发环境行数作为覆盖范围参照，但不要通过数据库迁移来达成。首次服务器同步完成后，已验证核心表量级包括：

| 表 | 验收口径 |
| --- | --- |
| `app_user` | 仅 1 个管理员 |
| `a_stock_basic` | A 股基础清单已完整刷新 |
| `hk_stock_basic` | 港股基础清单已完整刷新 |
| `a_trade_calendar` / `hk_trade_calendar` | 已覆盖当前和未来窗口 |
| `official_ah_comparison` | 官方 AH 比价按交易日同步 |
| `ah_stock_pair` | 由官方 AH 比价维护配对 |
| `hsgt_constituent` | 仅保留最新生效日期名单 |
| `a_daily_quote` | A 股日线达到本地开发环境同量级 |
| `stock_selection_factor_snapshot` | A 股候选因子快照已生成 |

`fx_rate_daily` 可能因当前 Tushare 权限或接口返回为 0 行；只要任务状态和错误信息可读，属于已知外部数据可用性问题。

## 9. 验收检查

服务状态：

```bash
ssh ubuntu@<server-ip> 'systemctl is-active stock-ah-backend stock-ah-frontend mysql'
```

后端健康：

```bash
curl --noproxy '*' http://<server-ip>:8000/api/health
```

前端访问：

```text
http://<server-ip>:5173
```

登录验收：

- 使用初始化管理员账号登录。
- 浏览器控制台无 CORS、`ERR_FAILED` 或后端连接超时。
- 登录后能看到管理员菜单和数据同步任务记录。

数据验收：

- `sync_run` 中关键任务存在后续成功记录。
- 一次历史失败记录不代表当前不可用，重点看同一数据集是否已有后续 `SUCCESS`。
- 统一查询页能查看基础清单、交易日历、官方 AH 比价、A 股日线和同步任务。

