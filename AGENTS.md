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

## 时间与时区口径

- 新增或修改任何时间字段时，必须先明确该字段是 `UTC naive`、`东八区 naive` 还是带时区 ISO 字符串，不能在前端或后端凭感觉手动加减 8 小时。
- 后端使用 `datetime.now(UTC).replace(tzinfo=None)` 写入的字段按 `UTC naive` 入库，前端使用 `formatEast8DateTime(value)` 展示，由工具统一转成东八区。
- 数据库 `server_default=func.now()`、MySQL `CURRENT_TIMESTAMP`、`created_at`、`updated_at` 等由数据库生成且无时区后缀的字段，在当前服务器口径下按东八区本地时间理解；前端展示必须使用 `formatEast8DateTime(value, { naiveAsEast8: true })`，避免再次按 UTC 转换导致快 8 小时。
- 如果新接口返回时间给前端，优先在 schema/注释/页面调用处标明时间来源；发现展示快 8 小时或慢 8 小时，先检查字段来源和格式化参数，不得用临时字符串拼接或硬编码偏移修补。

## Git Push 操作口径

- 本项目远端为 `https://github.com/WinSalty/stock-ah-premium-ai.git`，本机命令行 Git 使用 macOS `osxkeychain` 凭据；IDEA 推送成功通常说明 IDEA 自身登录态有效，但 Codex/终端推送可直接走同一套命令行 Git 配置。
- 完成正式编码或正式项目文档交付后，除非用户明确说“不用 push”或“只本地提交”，默认都要在 commit 后直接 push。先执行 `git -C /Users/salty/codeProject/ai/coding/stock-ah-premium-ai status --short --branch` 确认工作区状态，再通过 `zsh -lc 'cd /Users/salty/codeProject/ai/coding/stock-ah-premium-ai && git push origin main'` 执行一次 push；这样可加载本机 `~/.zprofile` 里的终端代理环境，避免 Codex 当前会话未继承代理导致 GitHub 连接超时。不要额外执行 `push --dry-run`。
- `git push origin main` 只允许尝试一次；如果失败或超时，立即停止并在交付说明中明确“本地已提交但未 push”以及失败原因，不要自动重试、不要改协议参数、不要改 Git 配置、不要切换凭据。若确需再次尝试，必须由用户重新明确要求。
- 如果 `git push origin main` 提示认证失败，再检查 `printf 'protocol=https\nhost=github.com\n\n' | git credential-osxkeychain get` 是否能返回 `username` 和已打码的 `password`；不要打印真实 token。若 keychain 没有凭据，再询问用户是否允许使用 `/Users/salty/codeProject/ai/doc/github-token.txt` 重新写入 GitHub HTTPS 凭据。
- 如果用户说“不用 push”或“只本地提交”，则保持本地提交即可，并在交付说明里明确“本地领先远端，未 push”。

## 服务器操作边界

- 默认不部署服务器；完成本地代码修改、测试、commit 和 push 后即停止，不主动执行 `rsync`、`scp`、远端构建、服务重启或生产发布。
- 服务器默认只允许做只读查询和日志排查，包括查看服务状态、健康检查、公开配置、日志、只读 SQL 查询和文件元数据检查；不得修改服务器文件、同步代码、重启服务、安装依赖、修改环境变量或改动数据库结构/数据。
- 只有用户明确要求“部署服务器”“修改服务器文件”“执行数据库迁移/写入/修复数据”等具体高影响操作时，才允许执行对应写操作；执行前必须说明将要改动的服务器范围和数据库影响。
