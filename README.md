# 港股通 A/H 溢价数据助手

## 项目定位

本项目用于通过 Tushare 拉取 A 股、港股通、港股行情和汇率数据，持久化到本地 MySQL，并计算港股通标的中的 A/H 溢价率。后续提供一个简洁前端页面用于查看同步状态、溢价榜单和趋势，并通过 LLM API 对本地数据进行问答分析。

当前已进入一阶段代码开发，完成后端 FastAPI 服务、数据库迁移、Tushare 同步服务、A/H 溢价计算、LLM 问答 API、React 前端页面和开发进度文档。按用户要求，暂不进行需要真实 Tushare 权限、LLM Key 或本地 MySQL 的功能测试。

## 当前产出

- 一阶段详细开发方案：[phase-1-detailed-development-plan.md](./resources/doc/phase-1-detailed-development-plan.md)
- 开发进度记录：[development-progress.md](./resources/doc/development-progress.md)
- 项目启动手册：[startup-guide.md](./resources/doc/startup-guide.md)
- 数据库初始化 SQL：[00_create_database.sql](./resources/sql/00_create_database.sql)
- LLM 只读视图 SQL：[01_readonly_views.sql](./resources/sql/01_readonly_views.sql)

## 项目目录

本项目是前后端混合 coding 项目，统一放在：

- 项目根目录：`/Users/salty/codeProject/ai/coding/stock-ah-premium-ai`
- 后端目录：`/Users/salty/codeProject/ai/coding/stock-ah-premium-ai/backend`
- 前端目录：`/Users/salty/codeProject/ai/coding/stock-ah-premium-ai/frontend`
- 正式设计文档：`/Users/salty/codeProject/ai/coding/stock-ah-premium-ai/resources/doc`

后端代码位于 `backend/`，前端代码位于 `frontend/`，项目文档和 SQL 资源分别位于 `resources/doc/`、`resources/sql/`。

## 关键约束

- 本地 MySQL 连接信息按需读取 `/Users/salty/codeProject/ai/doc/mysqluse.md`，项目文档和代码中不写入密码、Token 或 LLM API Key。
- Tushare Token、LLM API Key、数据库账号密码均通过环境变量或本机未入库配置注入。
- 一阶段目标数据库名为 `stock_ah_ai`，建库 SQL 放在 `resources/sql/00_create_database.sql`，表结构由 Alembic 迁移创建。

## 本地启动

完整启动、配置、验证和排错说明见：[项目启动手册](./resources/doc/startup-guide.md)。

快速启动顺序如下。

首次安装依赖：

```bash
cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai
./scripts/bootstrap.sh
```

执行非外部依赖检查：

```bash
./scripts/check.sh
```

后端：

```bash
cp backend/.env.example backend/.env
./scripts/start-backend.sh
```

前端：

```bash
./scripts/start-frontend.sh
```

数据库初始化：

```bash
./scripts/init-db.sh
```

也可以使用 `make bootstrap`、`make check`、`make init-db`、`make backend`、`make frontend`。
