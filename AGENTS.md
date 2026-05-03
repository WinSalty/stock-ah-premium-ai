# Stock AH Premium AI Project Rules

本项目是 `/Users/salty/codeProject/ai/coding` 下的前后端混合正式编码项目。

## 规则继承

- 项目整体遵守 `/Users/salty/codeProject/ai/coding/AGENTS.md`。
- `backend/` 后端代码遵守 `/Users/salty/codeProject/ai/coding/back/AGENTS.md`。
- `frontend/` 前端代码遵守 `/Users/salty/codeProject/ai/coding/front/AGENTS.md`。
- `resources/doc/` 存放正式设计文档、开发进度和验收说明。
- `resources/sql/` 存放数据库初始化、只读视图和补充 SQL。

## 项目约束

- 不提交 Tushare Token、LLM API Key、数据库密码等敏感信息。
- 本机 Tushare Token 文件仅在运行时由后端读取，路径通过配置控制。
- 本机 MySQL 连接信息按需参考 `/Users/salty/codeProject/ai/doc/mysqluse.md`。
- 功能测试需要真实 Tushare 权限、LLM Key 和 MySQL 环境时，必须由用户确认后再执行。
