# QMT 实盘复盘看板 · 开发方案与计划（前端 + 只读 API）

文档日期：2026-06-14

> 本方案聚焦**「看板」本身**（前端页面 + 只读查询 API + 权限），**数据口径/公式不重新设计**，一律沿用既有：
> - [`qmt-trade-review-board-design.md`](qmt-trade-review-board-design.md)：数据模型、收益/盈亏口径（当日盈亏剔出入金、Modified Dietz、TWR 净值、夏普/索提诺/卡玛、FIFO 撮合、成功率/买不进/滑点）、`/api/review/*` 端点、当日/历史 Tab。
> - [`qmt-trade-review-closed-loop-attribution-design.md`](qmt-trade-review-closed-loop-attribution-design.md)：计划→执行→结果闭环归因（漏斗、逆向选择、先验校准、滑点拆解、空仓闸门反事实）。
> 本方案在其上：① 把页面信息架构扩成「1 菜单 + 多 Tab」并细化 UI/交互；② 落实「默认只给 admin」的菜单权限；③ 给出前端为主的分阶段落地计划。

---

## 0. 现状结论（先回答「建了没」）

| 部分 | 状态 |
|---|---|
| QMT 四表 `qmt_trade`/`qmt_order`/`qmt_position_snapshot`/`qmt_account_daily` + ORM + 迁移 | ✅ 已建 |
| 执行侧回流写接口 `POST /api/internal/qmt/ingest`（幂等 upsert） | ✅ 已建 |
| **复盘看板只读 API（`/api/review/*`）** | ⛔ **完全未建** |
| **复盘看板前端页面**（交易明细 / 收益统计 / 持仓 / 净值 / 归因） | ⛔ **完全未建（0 个页面）** |
| 净值/盈亏回填、TWR/风险指标/FIFO 计算服务、只读视图、SQL Guard 白名单 | ⛔ 未建 |
| 闭环归因物化表与计算 | ⛔ 未建 |
| 出入金台账 `qmt_cash_flow`、账户↔用户映射 `qmt_account` 与鉴权隔离 | ⛔ 未建 |

**一句话：数据进来了（回流落库 OK），但「给人看」的那一层（API + 页面）一行没写。本方案就是补这一层。**

---

## 1. 范围与目标

- **目标**：在现有信号侧前端（React18 + Vite + TS + **Ant Design 5** + **ECharts 5** + React Query）里新增一个**「实盘复盘」菜单（默认仅 admin 可见）**，让管理员能看：当日交易明细与盈亏、历史净值与风险、当前持仓与浮亏、信号→执行→结果闭环归因。
- **不做**：不改数据口径/公式（沿用既有设计）；前端**不做任何盈亏二次推算**，只展示后端只读视图算好的值（口径单一来源）。
- **技术约束（沿用现状）**：无 React Router，菜单走 `App.tsx` 的 `allMenuItems` + URL `?page=`；图表用 `echarts-for-react`；服务端状态用 `@tanstack/react-query`；时间一律 `formatEast8DateTime`（东八区，不在前端 ±8h）。

---

## 2. 信息架构（IA）：1 个菜单 + 5 个 Tab

**菜单**：`实盘复盘`（key=`qmt_review`，**admin-only**）。单菜单单权限位，开关整个看板，最简洁（需要更细粒度再拆多菜单，见 §5）。

顶部全局控件（5 个 Tab 共用）：**账户切换**（Select，多账户）+ **日期/区间选择**（DatePicker / RangePicker，默认最新交易日 / 近 N 交易日，经 `a_trade_calendar` 限定交易日）+ **刷新**。

| Tab | 内容 | 主数据源 API |
|---|---|---|
| **① 当日复盘** | 当日盈亏卡组 + 今日成交清单 + 当日持仓 + 战法/题材/情绪分布 | `/api/review/daily` `/trades` `/positions` |
| **② 历史净值** | TWR 净值曲线 + 回撤 + 绩效指标卡组 + 月/周周期统计 | `/api/review/history` `/history/periodic` |
| **③ 交易质量** | 单票胜率盈亏比散点 + 持有天数分布 + 滑点分布 + 成功率/买不进下钻 | `/api/review/history/trades-stats` `/orders` |
| **④ 闭环归因** | 计划→挂单→成交漏斗 + 逆向选择 + 先验校准曲线 + 空仓闸门反事实 | `/api/review/funnel` `/attribution`（归因设计） |
| **⑤ 账户/出入金** | 账户↔用户绑定（admin）+ 出入金台账录入（净值剔出入金的前置） | `/api/review/accounts` `/cashflow`（新增） |

> ⑤ 是净值/收益率口径正确的**前置**（不录出入金，TWR/当日收益率会被现金流污染）；放在看板内由 admin 维护。

---

## 3. 前端 UI / 交互设计（逐 Tab）

页面 `frontend/src/pages/QmtReviewPage.tsx`，内部 antd `Tabs`（受控，Tab key 同步进 URL `?page=qmt_review&tab=daily` 便于分享/刷新保位）。统一视觉口径：**红涨绿跌（A 股习惯，不用默认绿涨红跌）**；每个盈亏/收益率卡片右上角 `Tooltip` 标口径（TWR/是否含出入金/FIFO/滑点基准）；所有数据态走 React Query 的 `isLoading→Skeleton`、`isError→Result+重试`、空集→`Empty`。

### ① 当日复盘 Tab
- **盈亏卡组**（antd `Row`+`Col`+`Statistic`）：当日总盈亏 / 已实现 / 浮动盈亏（三卡，红绿+箭头）、当日收益率（Modified Dietz）、下单成功率、买不进只数。`Statistic` 用 `valueStyle` 着色、`precision`、`prefix` 箭头。
- **今日成交清单**（antd `Table`，行级）：方向 `Tag`（买红/卖绿）、代码+名称、成交价/量/额、`traded_time`、**回挂信号**列（战法/题材/`market_state`/角色 `Tag` 组）。列可排序、可按方向 `Filter`、`size="small"`、`scroll.x` 横向滚动、分页。点行 → 抽屉 `Drawer` 看该票当日全部成交+对应委托（下钻）。
- **当日持仓**（antd `Table`）：代码名称、持仓/可卖（T+1）、成本/现价、浮动盈亏/浮亏率（红绿）。
- **当日分布**（echarts）：按战法/题材/情绪周期的**笔数 vs 盈亏**双视角（antd `Segmented` 切换），饼图（占比）+ 柱状（盈亏）。

### ② 历史净值 Tab
- **净值曲线**（echarts `line`）：归一 NAV（TWR，已剔出入金）+ **回撤面积**（次坐标 `yAxisIndex=1`，`areaStyle`）+ 出入金切段 `markPoint`；`dataZoom` 缩放、`tooltip` 跨系列、`legend` 切换 NAV/回撤。
- **绩效指标卡组**（`Statistic` + `Descriptions`）：累计/年化收益、最大回撤（+回撤时长/恢复天数）、夏普、索提诺、卡玛、日胜率。
- **周期统计**（antd `Table` + echarts `bar`）：月/周收益、胜率、笔数、换手；柱状红绿按月收益正负。

### ③ 交易质量 Tab
- **单票胜率盈亏比散点**（echarts `scatter`）：x=胜率、y=盈亏比、气泡大小=笔数、颜色=累计盈亏正负；`tooltip` 显个股；点散点 → 下钻该票成交流水。
- **持有天数分布**（echarts `bar` 直方图）。
- **滑点分布**（两张 `bar` 直方图并列）：信号链路滑点 vs 执行质量滑点（口径分开，对应归因设计 §4）。
- **成功率/买不进下钻**（antd `Table`）：按战法/情绪分组的下单成功率、买不进（一字/秒封/排队未成）构成。

### ④ 闭环归因 Tab（建在 attribution-design §7）
- **执行漏斗**（echarts `funnel`）：计划数→挂单数→成交数，旁列各级流失率 + **逆向选择**指标（"最强的票买到没"，对应归因 §2.2）。可按 `tradable_flag`/`market_state`/战法分组。
- **先验校准**（echarts `line`，可靠性曲线）：续板/隔日溢价**先验档位（高/中/低/极低）vs 实际兑现率**，对角线为完美校准（对应归因 §3）。
- **分组对照表**（antd `Table`）：role/战法/情绪分组的实盘盈亏 vs 回测预期。
- **空仓闸门反事实**（`Statistic` + 小 `line`）：空仓日「若开仓会怎样」的反事实收益（对应归因 §5）。

### ⑤ 账户/出入金 Tab（admin）
- **账户绑定**（antd `Table` + `Modal`）：`qmt_account` 账户↔登录用户映射的增删（决定谁能看哪个账户）。
- **出入金录入**（antd `Form` + `Table`）：`qmt_cash_flow` 出入金台账（日期/金额/方向/备注），是 TWR/当日收益率剔现金流的依据；录入即影响净值重算。

---

## 4. 后端只读 API（建在 board-design §5.1，补齐缺口）

沿用既有 `/api/review/*` 端点设计（accounts/daily/trades/positions/orders/history/history-trades-stats/history-periodic/funnel），**全部挂 `CurrentUser` + `qmt_review` 权限校验 + 账户隔离**（只返回该用户经 `qmt_account` 绑定的账户）。本方案新增/明确：

- 新增 `GET /api/review/attribution`：闭环归因（漏斗+逆向选择+先验校准+空仓闸门），读归因物化表 `qmt_signal_attribution_daily`。
- 新增 `POST /api/review/accounts`（账户绑定，admin）、`GET/POST /api/review/cashflow`（出入金台账，admin）。
- 路由文件：`app/api/routes_review.py`（新建，前缀 `/api/review`，全挂鉴权）。
- 服务层：`app/services/review_service.py`（新建）——FIFO 撮合、TWR/Modified Dietz、风险指标、漏斗/归因聚合；前端零计算，口径单一来源。
- 只读 SQL 经 `sql_guard_service` 白名单（新增 `v_qmt_*` 视图到白名单）。
- 公共参数：`account_id`（缺省默认账户）、`trade_date` 或 `start/end`、`group_by`；日期经 `a_trade_calendar` 校验。

---

## 5. 权限设计（默认只给 admin）

**单菜单单权限位 `qmt_review`，落地三处：**

1. **后端枚举**（`app/services/auth_service.py`）：`ALL_MENU_PERMISSIONS` 加 `"qmt_review": "实盘复盘"`；`DEFAULT_ROLE_PERMISSIONS[ROLE_ADMIN]` 加 `qmt_review`，**`ROLE_USER` 不加** → 新注册普通用户默认看不到，仅 admin 默认有。
2. **后端 API 守卫**：`routes_review.py` 每个端点 `Depends(require_permission("qmt_review"))`（与现有 `query`/`sync` 等同款），并叠加**账户隔离**（非绑定账户 403）。
3. **前端菜单**（`frontend/src/App.tsx`）：`PageKey` 加 `qmt_review`；`allMenuItems` 加 `{key:"qmt_review", icon:<FundOutlined/>, label:"实盘复盘"}`；`pages` 加渲染 `<QmtReviewPage/>`。现有的 `UserInfo.permissions` Set 过滤逻辑会**自动**让非 admin 看不到该菜单——无需额外前端改动。
4. **存量用户**：迁移/管理后台不主动给老 USER 加；admin 可在现有 `UserAdminPage` 手动按需授权个别用户（沿用现有权限分配 UI）。

> 若日后要更细（如「只读复盘」vs「出入金管理」分权），把 ⑤ 账户/出入金拆成第二个菜单/权限位 `qmt_review_admin`，其余不变。

---

## 6. 数据/计算前置（API 之前必须先有）

看板要的很多字段是**回填/计算**出来的，API 之前要先把这层补上（对应 board-design §3–4）：

- 回填：`qmt_account_daily.prev_total_asset/daily_pnl/daily_return`、`qmt_position_snapshot.last_price/float_profit/profit_rate`（盯市价取 `realtime_quote_snapshot`/收盘价）。
- 新表：`qmt_cash_flow`（出入金台账，TWR 切段依据）、`qmt_account`（账户↔用户绑定）、`qmt_signal_attribution_daily`（归因物化表）。
- 计算服务：FIFO 撮合（交易级盈亏/持有天数/滑点）、TWR 净值、风险指标、漏斗/归因聚合 → 收盘后批处理（APScheduler 任务）+ 只读视图 `v_qmt_daily_pnl`/`v_qmt_trade_with_signal`/`v_qmt_fill_funnel`。

---

## 7. 开发计划（分阶段 · 验收标准 · 依赖顺序；不含工期）

> 阶段间严格按依赖；每阶段独立可验收。前端阶段在对应后端阶段之后即可并行推进其它 Tab。

**阶段 A — 数据/计算底座（后端前置）**
- 任务：回填 daily_pnl/净值/浮动盈亏字段；建 `qmt_cash_flow`/`qmt_account`/`qmt_signal_attribution_daily` 表 + 迁移；FIFO/TWR/风险指标/漏斗/归因计算服务 + 收盘批处理 + 只读视图 + SQL Guard 白名单。
- 验收：给定一段回流数据，批处理能算出每日 daily_pnl、TWR 净值点列、单票 FIFO 盈亏、漏斗四级数、归因物化行，且口径与 board-design §4 / 归因 §2–5 公式逐一对得上。

**阶段 B — 只读 API + 权限位（后端）**
- 任务：`routes_review.py` 全部 `/api/review/*` 端点 + `review_service` 聚合查询；`auth_service` 加 `qmt_review` 权限位（admin 默认有、user 没有）；每端点挂权限 + 账户隔离。
- 验收：admin token 能拉到各端点正确数据；普通 user token 访问 → 403；跨账户访问非绑定账户 → 403；日期非交易日报错。

**阶段 C — 前端骨架 + 菜单 + 权限（前端）**
- 任务：`App.tsx` 接 `qmt_review` 菜单/路由/页面；`api/qmt.ts` 封装端点 + React Query hooks；`QmtReviewPage` 框架（账户/日期全局控件 + 5 Tab 壳 + Tab↔URL 同步）；`types/domain.ts` 扩 QMT 类型。
- 验收：admin 登录见「实盘复盘」菜单、普通 user 不见；Tab 切换 URL 保位；加载/错误/空态完整。

**阶段 D — 当日复盘 Tab（前端，依赖 B）**
- 任务：盈亏卡组 + 今日成交清单（含信号回挂 + 行下钻 Drawer）+ 当日持仓 + 分布图。
- 验收：当日盈亏/成功率/买不进与后端一致；成交清单可排序/筛选/下钻；红涨绿跌；时间东八区。

**阶段 E — 历史净值 Tab（前端，依赖 B）**
- 任务：净值曲线（NAV+回撤+出入金标记+dataZoom）+ 绩效卡组 + 周期统计。
- 验收：净值/回撤/夏普等与后端一致；曲线可缩放；卡片 tooltip 标口径。

**阶段 F — 交易质量 Tab（前端，依赖 B）**
- 任务：胜率盈亏比散点（可下钻）+ 持有天数/滑点直方图 + 成功率/买不进下钻表。

**阶段 G — 闭环归因 Tab（前端，依赖 A 归因物化 + B `/attribution`）**
- 任务：执行漏斗 + 逆向选择 + 先验校准可靠性曲线 + 分组对照 + 空仓闸门反事实。
- 验收：漏斗四级与归因物化一致；校准曲线对角线参照清晰；可按 tradable_flag/战法分组。

**阶段 H — 账户/出入金 Tab + 鉴权隔离回归（前端+后端）**
- 任务：账户绑定 + 出入金录入 UI；录入触发净值重算；多账户/多用户隔离端到端回归。
- 验收：录出入金后 TWR 净值不被现金流污染；A 用户绝对看不到 B 账户数据；admin 能管全部。

---

## 8. 验收标准（总）

1. **口径单一来源**：前端零盈亏推算，所有数值来自后端只读视图/服务，且每个收益/盈亏 UI 都有 tooltip 注明口径（与 board-design §4、归因 §2–5 对齐）。
2. **权限**：`qmt_review` 默认仅 admin；user 看不到菜单、API 403；账户隔离严格。
3. **时间口径**：全部经 `formatEast8DateTime`，无 ±8h；日期经交易日历校验。
4. **UI 质量**：antd + echarts 一致视觉（红涨绿跌、加载/空/错态完整、移动端可读、关键表可下钻），交互流畅。
5. **闭环可验证**：能从「信号(limit_up_selected_stock) → 执行(qmt_trade/order) → 结果(隔日行情)」端到端看出漏斗、逆向选择、先验校准、滑点、空仓闸门有效性。

---

## 9. 与既有设计文档的关系

- **数据模型/收益口径/原始 API 端点/当日·历史 Tab** → 以 [`qmt-trade-review-board-design.md`](qmt-trade-review-board-design.md) 为准（本方案不重定义）。
- **闭环归因（漏斗/逆向选择/校准/滑点/空仓闸门）** → 以 [`qmt-trade-review-closed-loop-attribution-design.md`](qmt-trade-review-closed-loop-attribution-design.md) 为准。
- **本方案的增量** = ① IA 扩成 1 菜单 5 Tab；② admin-only 菜单权限三处落地；③ 前端 UI/交互细化（antd 组件 + echarts 图 + 下钻/状态）；④ 前端为主的分阶段计划。

---

## 10. 实施进度（2026-06-14 首版落地）

> 本节记录本方案**已落地**与**有意延后**的部分；口径与公式仍以 §9 两份设计文档为准。

### 已完成（可用）

**后端只读 API（信号侧 `backend/`）：**
- 权限：`auth_service.ALL_MENU_PERMISSIONS` 新增 `qmt_review=实盘复盘`，仅加入 `DEFAULT_ROLE_PERMISSIONS[ADMIN]`（user 不含）→ 默认仅 admin 可见。
- Schema：`app/schemas/qmt_review.py`（账户/当日汇总/成交/持仓/净值响应模型）。
- 服务：`app/services/qmt_review_service.py`，对 `qmt_*` 四表只读聚合：
  - 当日汇总：当日盈亏（优先 `qmt_account_daily.daily_pnl`，缺则 `total_asset−prev−net_cash_flow` 现算，剔出入金）、浮动盈亏（CLOSE 持仓 `float_profit` 求和）、已实现盈亏**近似**（总−浮动）、成交笔数/额、下单成功率/买不进（基于 `qmt_order` BUY 终态）。
  - 成交明细：分页 + 按 `(signal_trade_date, ts_code)` join `limit_up_selected_stock` 回挂战法/形态/角色/情绪 + `a_stock_basic` 兜底名称。
  - 持仓：指定日 CLOSE 快照（无则回退 ≤该日 最近 CLOSE 日）。
  - 历史净值：CLOSE `total_asset` 序列 → 归一净值 + 回撤 + 累计/年化收益 + 夏普（日频年化 rf=0）+ 日胜率。
- 路由：`app/api/routes_qmt_review.py`（`/api/review/accounts|daily|trades|positions|history`，整组挂 `require_permission("qmt_review")`），已在 `main.py` 注册。
- 测试：`tests/test_qmt_review.py` 10 用例（user 403 / admin 200 / 当日口径 / 信号 join / 持仓回退 / 历史绩效）全绿。

**前端（信号侧 `frontend/`）：**
- API 客户端 `src/api/qmt.ts`（含类型）。
- 页面 `src/pages/QmtReviewPage.tsx`：账户/日期控制条 + 4 Tab（**当日复盘 / 历史净值 / 持仓明细 / 交易质量**），KPI 卡组（红涨绿跌）、成交明细表（方向分段筛选 + 回挂信号 Tag）、持仓表、ECharts 净值+回撤双轴曲线；空库/空日空态完整；口径 tooltip 注明。
- 接入 `App.tsx`：`PageKey`/`allMenuItems`/`pages` 三处加 `qmt_review`（`LineChart` 图标），权限自动过滤（仅 admin 出菜单）。
- 样式 `src/styles/global.css` 追加 `qmt-*` 命名块（KPI 网格、红涨绿跌、信号 Tag、双行单元格等）。
- `tsc --noEmit` 与 `vite build` 均通过；dev server 启动无控制台报错。

### 口径简化与延后（诚实标注，落地时已在 UI/注释标明）

- **已实现盈亏**：当前用「当日盈亏−浮动盈亏」近似；**精确 FIFO 交易级盈亏**待「数据底座」阶段（委托-成交配对 + 持有时长）补。
- **历史净值**：当前用 `total_asset` 简单归一（`nav_method=SIMPLE_NORMALIZED`），**未剔出入金**；精确 TWR 待出入金台账 `qmt_cash_flow` 落地后重算。
- **交易质量 Tab**：当前仅呈现已可得真实指标（下单成功率/买不进/成交笔额）；**滑点、FIFO 撮合质量、买不进归因**待数据底座，UI 已用 Alert 标注出处，未造假数据。
- **闭环归因 Tab（原 §IA ④）**：本版未单列；信号→执行的关联已在「当日成交明细」以回挂 Tag 呈现，深度漏斗/逆向选择/先验校准物化延后。
- **账户/出入金 Tab（原 §IA ⑤）+ 多账户隔离**：未建；当前 admin 可见全部账户（`qmt_account` 绑定表与 per-account 鉴权隔离延后）。出入金录入 UI 同延后。

> 上述延后项均依赖新表/新数据（`qmt_cash_flow`、`qmt_account`、归因物化表）或委托-成交配对计算，需真实回流数据校验，已登记到 `astock-quant-ai/doc/待办与上线验证清单.md`。
