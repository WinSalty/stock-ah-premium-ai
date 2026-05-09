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
- 本项目内任何代码、脚本、SQL、迁移和自动化任务的新增或修改，都必须使用中文注释写清业务意图、数据来源、过滤条件、幂等/重跑口径和异常边界；触碰到缺少中文注释的既有逻辑时，必须在本次改动范围内补齐。

## Git Push 操作口径

- 本项目远端为 `https://github.com/WinSalty/stock-ah-premium-ai.git`，本机命令行 Git 使用 macOS `osxkeychain` 凭据；IDEA 推送成功通常说明 IDEA 自身登录态有效，但 Codex/终端推送仍应先按命令行凭据单独验证。
- 用户明确要求 push 时，先执行 `git -C /Users/salty/codeProject/ai/coding/stock-ah-premium-ai status --short --branch` 和 `git -C /Users/salty/codeProject/ai/coding/stock-ah-premium-ai push --dry-run origin main`。dry-run 成功后再执行 `git -C /Users/salty/codeProject/ai/coding/stock-ah-premium-ai push origin main`。
- 如果 dry-run 提示认证失败，先检查 `printf 'protocol=https\nhost=github.com\n\n' | git credential-osxkeychain get` 是否能返回 `username` 和已打码的 `password`；不要打印真实 token。若 keychain 没有凭据，再询问用户是否允许使用 `/Users/salty/codeProject/ai/doc/github-token.txt` 重新写入 GitHub HTTPS 凭据。
- 仅在用户明确要求 push 时推送；如果用户说“不用 push”或只要求本地部署/服务器 rsync，则保持本地提交即可，并在交付说明里明确“本地领先远端，未 push”。
