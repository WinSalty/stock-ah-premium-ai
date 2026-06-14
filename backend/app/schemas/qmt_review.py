"""QMT 实盘复盘看板只读接口的响应 Schema。

业务意图：看板前端只展示后端算好的值（口径单一来源，前端零盈亏推算），故响应字段已是
最终展示口径。时间字段一律用东八区（traded_time_east8），日期用交易日（date）。

创建日期：2026-06-14
author: claude
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class QmtAccountInfo(BaseModel):
    """可选账户（供顶部切换）。"""

    model_config = ConfigDict(from_attributes=True)

    account_id: str = Field(description="QMT 资金账号")
    latest_trade_date: date | None = Field(default=None, description="该账户已回流的最新交易日")


class QmtDailySummary(BaseModel):
    """当日复盘汇总卡片数据。"""

    trade_date: date
    has_data: bool = Field(description="该交易日是否有回流数据")
    # 盈亏（均已剔出入金口径；已实现为近似=总盈亏-浮动盈亏，待 FIFO 精算）
    daily_pnl: Decimal | None = Field(default=None, description="当日总盈亏（剔出入金）")
    float_pnl: Decimal | None = Field(default=None, description="当日浮动盈亏（持仓盯市）")
    realized_pnl_approx: Decimal | None = Field(default=None, description="已实现盈亏（近似=总-浮动）")
    daily_return: Decimal | None = Field(default=None, description="当日收益率")
    total_asset: Decimal | None = Field(default=None, description="收盘总资产")
    # 成交/委托统计
    buy_count: int = Field(default=0, description="买入成交笔数")
    sell_count: int = Field(default=0, description="卖出成交笔数")
    buy_amount: Decimal | None = Field(default=None, description="买入成交额")
    sell_amount: Decimal | None = Field(default=None, description="卖出成交额")
    order_success_rate: Decimal | None = Field(default=None, description="下单成功率(已成委托/全部委托)")
    no_fill_count: int = Field(default=0, description="买不进只数(委托完全未成)")


class QmtTradeItem(BaseModel):
    """成交明细行（含回挂信号）。"""

    model_config = ConfigDict(from_attributes=True)

    traded_id: str
    trade_date: date
    ts_code: str
    name: str | None = Field(default=None, description="证券名称(回挂信号侧)")
    trade_side: str = Field(description="BUY/SELL")
    traded_price: Decimal
    traded_volume: int
    traded_amount: Decimal | None = None
    traded_time_east8: datetime | None = Field(default=None, description="成交时间(东八区)")
    # 回挂信号侧（按 signal_trade_date + ts_code join limit_up_selected_stock）
    signal_trade_date: date | None = None
    strategy_family: str | None = None
    setup: str | None = None
    role: str | None = Field(default=None, description="角色(role_tags 首个)")
    market_state: str | None = None
    leader_strength_score: Decimal | None = None


class QmtTradesPage(BaseModel):
    """成交明细分页。"""

    items: list[QmtTradeItem]
    total: int
    page: int
    page_size: int


class QmtPositionItem(BaseModel):
    """持仓行（收盘快照）。"""

    model_config = ConfigDict(from_attributes=True)

    ts_code: str
    name: str | None = None
    volume: int
    can_use_volume: int
    avg_price: Decimal | None = None
    last_price: Decimal | None = None
    market_value: Decimal | None = None
    float_profit: Decimal | None = None
    profit_rate: Decimal | None = None


class QmtNetWorthPoint(BaseModel):
    """净值曲线一个点。"""

    trade_date: date
    nav: Decimal = Field(description="归一净值(起点=1)")
    total_asset: Decimal
    drawdown: Decimal = Field(description="相对历史峰值的回撤(<=0)")
    daily_return: Decimal | None = None


class QmtHistoryStats(BaseModel):
    """历史净值与绩效指标。"""

    start_date: date | None = None
    end_date: date | None = None
    points: list[QmtNetWorthPoint] = Field(default_factory=list)
    cumulative_return: Decimal | None = Field(default=None, description="区间累计收益率")
    annualized_return: Decimal | None = Field(default=None, description="年化收益率(×√252口径外的简单年化)")
    max_drawdown: Decimal | None = Field(default=None, description="最大回撤(<=0)")
    sharpe: Decimal | None = Field(default=None, description="夏普(日频年化, rf=0)")
    win_rate: Decimal | None = Field(default=None, description="日胜率")
    trading_days: int = 0
    # 口径说明：当前 NAV 为 total_asset 简单归一(未剔出入金)；精确 TWR 待出入金台账(阶段A)。
    nav_method: str = Field(default="SIMPLE_NORMALIZED", description="净值口径")
