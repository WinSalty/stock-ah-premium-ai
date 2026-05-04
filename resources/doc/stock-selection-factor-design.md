# A 股选股因子宽表方案

更新日期：2026-05-04

## 目标

为 LLM 选股提供一张可解释、可筛选的核心宽表，避免全量同步 Tushare 股票目录原始数据。当前落地表为 `stock_selection_factor_snapshot`，只保存经过联网筛选后的几十只蓝筹、低估值和红利候选股。

## 筛选口径

参考官方指数编制思路：

- 蓝筹：参考沪深300、上证50的大市值、流动性和代表性成分股口径。
- 低估值：参考沪深300价值指数，从沪深300样本中偏向股息收益率、每股净资产/价格、每股收益/价格等价值因子。
- 红利：参考中证红利、上证红利、深证红利的连续分红、较高股息率、规模和流动性口径。

当前实现使用 Tushare 联网数据：

- `daily_basic`：最新交易日估值、股息率、市值和换手率。
- `index_weight`：沪深300、上证50、沪深300价值、中证红利、上证红利、深证红利成分。
- `fina_indicator`：最近报告期 ROE、毛利率、净利率、资产负债率、收入同比。
- `daily`：近 20/60/120 个交易日涨跌幅。
- `dividend`：最近分红年度、现金分红和分红进度。
- `forecast`：最近业绩预告类型和摘要。

## 表和视图

- 表：`stock_selection_factor_snapshot`
- 最新视图：`v_stock_selection_latest`
- 历史视图：`v_stock_selection_history`
- 指标字典：`v_stock_factor_dictionary`

## 同步入口

- 后端同步数据集：`stock_selection_factors`
- API：`POST /api/sync/batches/stock-selection-factors`
- 本地脚本初始化：`./scripts/init-db.sh`

当前快照已同步 60 只候选股票，因子日期为 `2026-04-30`。

## 使用建议

LLM 问答中涉及“蓝筹、低估值、红利、ROE、PE、PB、股息率、近 60 日表现”等选股问题时，优先查询 `v_stock_selection_latest`。需要解释指标含义时查询 `v_stock_factor_dictionary`。

该表用于数据分析和候选池生成；实际使用时仍需结合风险承受能力、行业周期、财报质量和交易纪律。
