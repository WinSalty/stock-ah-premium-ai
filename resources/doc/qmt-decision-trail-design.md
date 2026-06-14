# 信号选股 + 执行决策明细看板 · 落地设计

文档日期：2026-06-14

> 诉求：在信号侧前端「实盘复盘」页内，能看到 ①信号侧选股情况（什么信号达标了、为什么入选）；②执行侧具体交易决策明细（什么信号达标→下单了什么/卖出了什么/为什么没买），把 **信号达标 → 下单/未买 → 卖出** 串成一条可读时间线。
>
> **第一硬约束**：执行侧采集决策明细对真实交易做到**零阻塞、零影响、零异常冒泡，数据可丢失（best-effort）**。

## 0. 总纲

执行侧在已有决策点只做一次 O(1) 有界队列入队（满即丢），由独立后台线程批量写本机新表 `qmt_decision_log`（与交易事实源物理隔离），盘后旁路 best-effort 回流到信号侧已有的 `/api/internal/qmt/ingest`；信号侧把决策表与已落库的 `limit_up_selected_stock` 按 `(signal_trade_date, ts_code)` join，在复盘页新增只读 Tab 渲染时间线。**整条决策链路即使全挂，交易事实源与下单热路径完全不受影响。**

## A. 数据模型 `qmt_decision_log`

与回流四表同前缀，复用 ingest 白名单与幂等 upsert 机制。关键字段：

- 唯一键 `(account_id, trade_date, decision_id)`；
- `decision_type` 枚举：`SIGNAL_QUALIFIED` / `BUY_SUBMIT` / `BUY_MISS` / `SELL_SUBMIT` / `SELL_HOLD` / `SKIP_GLOBAL` / `SKIP_STRATEGY` / `SKIP_ORCHESTRATION` / `SKIP_ORDER`（所有 `SKIP_*`、`BUY_MISS` 即「为什么没买/没卖」的事实源）；
- `decision_stage`（GLOBAL_GATE/STRATEGY/ORCHESTRATION/ORDER/SELL）、`action`、`strategy_family`、`order_phase`；
- `reason`（人读）、`reason_code`（机器码，可筛可统计）、`factors_snapshot`（关键因子/阈值快照 JSON）；
- `limit_price` / `plan_volume`；`order_id` / `biz_order_no`（仅 SUBMIT 类有，串联 `qmt_order/qmt_trade`）；
- 时间双写：`decided_time`（UTC naive）+ `decided_time_east8`（东八区 naive，看板默认展示，**不二次 ±8h**）。
- 索引：`(trade_date,ts_code)`、`(signal_trade_date,ts_code)`、`(trade_date,decision_type)`；回填列（COALESCE 不被空覆盖）：`signal_trade_date / decided_time_east8 / order_id / biz_order_no`。

关联：`qmt_decision_log.(signal_trade_date,ts_code)` → `limit_up_selected_stock.(trade_date,ts_code)`（最新 READY 版本消歧）；`qmt_decision_log.order_id` → `qmt_order/qmt_trade`。

## B. 执行侧非阻塞采集（硬约束逐条达成）

| 约束 | 手段 |
|---|---|
| 不阻塞下单 | 决策点只 `put_nowait`（O(1) 内存），满即 `except Full: dropped+=1`，热路径无任何 IO |
| 可丢失 | 有界队列 + 满即丢 + 消费线程异常全吞 + 回流失败不重试到死 |
| 零异常冒泡 | `emit` 外层 `try/except Exception: pass`（连构造事件都不许抛） |
| 不污染交易事实源 | 决策队列/线程/SQLite 写连接与交易侧 `AsyncWriteQueue` 物理隔离 |
| 不污染对账 | `qmt_decision_log` 不加入执行侧 `QMT_TABLES`、不进 `RemoteSyncJob` 的 ok 判据 |

**埋点（精确位置见探查报告）**：买入侧核心钩子 `entry_router.py:312 _record`（现 `decision_log=[]` 是死代码，替换为 `DecisionEmitter`）；编排层 `main.py:268/427/439`；下单层 `order_executor.py:193/206/220/237/299/319/425/573/621`；卖出 `sell_decider.py:383`。手法：每处现有 `logger.info(event,...)` 旁**追加一行** `emitter.emit(...)`，不改动任何现有控制流。

**Feature flag**：`settings.decision_log_enabled`（**默认 True**，按用户决定默认开）。置 False（或缺信号回流通道）时 `DecisionEmitter` 为 no-op（不建队列、不起线程，埋点零成本），即一键回滚开关。默认开意味着真机部署即生效，故「不影响实盘下单」需真机验证（见 §E 阶段 4）。

## C. 回流链路（复用 `/api/internal/qmt/ingest`）

信号侧仅两处改动：`QMT_INGEST_TABLES` 加 `qmt_decision_log`；`_TABLE_SPEC` 加一项（model/unique/coalesce）。路由、token 鉴权、事务骨架、按 ORM 列类型反序列化全部不动即复用。执行侧回流走独立 best-effort 旁路，**不进 `RemoteSyncJob` 的 ok 对账**，失败只 warn、`synced=0` 下轮补。

## D. 信号侧只读 API + 看板（复用 `qmt_review` 权限位）

- `GET /api/review/selection?date=` —— 信号选股视图，暴露 `limit_up_selected_stock` 既有结构化字段（tier/board_level、leader_strength_score + 六维子分 strength_dim_json、role_tags、strategy_family/setup/action、tradable_flag、continuation_prob/next_day_premium_prob、boost_conditions/fail_conditions/suggested_hold_thesis、selection_reason、热字段）。**最新 READY 版本消歧**。
- `GET /api/review/decisions` —— 决策流水分页（按 account/date/decision_type/ts_code 筛）。
- `GET /api/review/decision-closeloop?date=&ts_code=` —— 单票闭环时间线（信号→决策→下单→卖出聚合，按 `decided_time_east8` 升序）。
- 前端在 `QmtReviewPage.tsx` 现有 `<Tabs>` 内新增「信号选股」「决策流水/闭环」两 Tab（闭环态用 antd `<Timeline>`）。

## E. 分阶段落地

- **阶段 1（零交易风险，无需真机）**：`/api/review/selection` + 「信号选股」Tab，暴露已落库选股决策字段。
- **阶段 2（零交易风险，构造数据验证）**：`qmt_decision_log` ORM + 迁移 `0055` + ingest 接收端（两处）+ `/review/decisions`、`/review/decision-closeloop` + 「决策流水/闭环」Tab。
- **阶段 3（需真机 miniQMT 验证）**：执行侧 `DecisionEmitter`（有界队列+消费线程+no-op 降级）+ 各埋点旁路 emit + best-effort 回流 + feature flag（**默认开**，按用户决定）。
- **阶段 4**：真机决策 → 看板闭环时间线端到端核对；prompt_version 消歧、时间双写、reason_code 映射校准。

## F. 风险与回滚

「决策采集整条挂掉，真实交易完全不受影响」保证链：①物理隔离（无共享锁/连接）；②热路径零 IO（只多一次 `put_nowait`，emit 外层吞异常）；③满即丢；④消费线程不 fail-fast（异常全吞，崩了交易照常）；⑤回流旁路（不进 ok 判据）；⑥接收端隔离（决策写失败 rollback，不影响四表回流）。回滚预案：flag 关→emit no-op / 关回流 / 白名单摘表 / 前端隐藏 Tab / 迁移 downgrade drop 表，各层独立。

## 关键改动文件

**信号侧**：`schemas/qmt_ingest.py`、`services/qmt_ingest_service.py`、`db/models/qmt.py`（新 `QmtDecisionLog`）、`alembic/versions/20260614_0055_*`、`api/routes_qmt_review.py`、`services/qmt_review_service.py`、`schemas/qmt_review.py`、`frontend/src/api/qmt.ts`、`frontend/src/pages/QmtReviewPage.tsx`、`tests/`。
**执行侧**：新建 `qmt_strategy/decision/decision_emitter.py`；改 `entry/entry_router.py`、`app/main.py`、`order/order_executor.py`、`position/sell_decider.py`、`storage/schema.py`、`storage/http_ingest_repository.py`、`storage/local_stack.py`、`app/run.py`、settings。

---

## 实施状态（2026-06-14）

- **阶段 1 ✅**（信号侧，零交易风险）：`GET /api/review/selection` +「信号选股」Tab，暴露 `limit_up_selected_stock` 决策字段（最新 READY 版本消歧）。
- **阶段 2 ✅**（信号侧，零交易风险，构造数据验证）：`qmt_decision_log` 表（迁移 `0055`）+ ingest 接收端（白名单 + `_TABLE_SPEC` + 修复 JSON 列 `_coerce_value` 双重编码）+ `GET /api/review/decisions`、`/decision-closeloop` +「决策流水/闭环」Tab（antd Timeline）。本机已迁移 + 灌演示数据，浏览器端到端验证通过。
- **阶段 3 ✅**（执行侧，`decision_log_enabled` 默认开）：`qmt_strategy/decision/decision_emitter.py`（有界队列 + 独立 daemon 线程 + best-effort 回流 + 异常全吞 + no-op 降级）+ entry_router/order_executor/sell_decider/main 编排各点埋点 + run.py 装配。全仓 444 测试通过（含 10 个采集器单测）。**与下单热路径物理隔离，整条采集崩溃也不影响交易/四表回流/对账。**
- **阶段 4 ⏳ 待真机**：默认开的采集对实盘下单零影响验证、两侧 token 部署、决策→看板闭环端到端核对、一键回滚演练。见执行侧 `doc/待办与上线验证清单.md` §F。

> 提交：信号侧 `feature/limit-up-watchlist-signal`（阶段 1-2）；执行侧 `main`（阶段 3）。
