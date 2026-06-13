"""QMT 执行侧回流四表 ORM（成交 / 委托 / 持仓快照 / 账户日快照）。

业务意图：执行侧（Windows VPS / miniQMT）盘后把本机 SQLite 的 qmt_* 当日数据，经
    `POST /api/internal/qmt/ingest` 幂等回流到信号侧 MySQL，供复盘看板 / 闭环归因 / 只读对账消费。
    本模块是这四张远端表的库口径单一来源，列与执行侧 storage/schema.py 对应（同 schema 搬行）。
    DDL 注释对齐 resources/doc/qmt-trade-review-design.md。

唯一键口径（加固方案，区别于设计文档原始 DDL）：成交 / 委托唯一键纳入 trade_date——
    即 (account_id, trade_date, traded_id) / (account_id, trade_date, order_id)，
    防 QMT 订单号 / 成交号跨日复用导致串号覆盖；与执行侧 `repository_unique_with_trade_date=True`
    默认口径一致，保证「同一行重传幂等、跨日同号不误并」。持仓 / 账户快照本就含 trade_date。

时间口径（与全局一致）：`*_time` 存 UTC naive（执行侧把东八区时间戳转 UTC 后回流，前端
    formatEast8DateTime 展示），`*_time_east8` 存东八区 naive 原值仅供人工核对；created_at/
    updated_at 由 DB 生成。回流 upsert 时 signal_trade_date / *_east8 走 COALESCE 不被空覆盖。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DECIMAL,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class QmtTrade(TimestampMixin, Base):
    """QMT 成交明细表（成交回报，已实现盈亏与成交统计事实源）。"""

    __tablename__ = "qmt_trade"
    __table_args__ = (
        # 加固唯一键：纳入 trade_date 防成交号跨日复用串号；幂等 upsert 以此定位同一行。
        UniqueConstraint(
            "account_id", "trade_date", "traded_id", name="uk_qmt_trade_acct_date_traded"
        ),
        Index("idx_qmt_trade_date_code", "trade_date", "ts_code"),
        Index("idx_qmt_trade_order", "account_id", "order_id"),
        Index("idx_qmt_trade_signal", "signal_trade_date", "ts_code"),
    )

    # BigInteger PK：MySQL 落 BIGINT AUTO_INCREMENT；SQLite（单测）只对 INTEGER 主键自增，
    # 故 with_variant(Integer, "sqlite") 让测试库用 INTEGER 主键正常自增。
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    account_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="QMT 资金账号")
    account_type: Mapped[int | None] = mapped_column(Integer, comment="QMT 账号类型枚举原值")
    trade_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="成交所属交易日（东八区，对齐 a_trade_calendar.cal_date）"
    )
    ts_code: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="标准证券代码（执行侧已归一）"
    )
    qmt_stock_code: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="QMT 原始证券代码（保留原值便于排查）"
    )
    traded_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="QMT 成交编号，成交去重最小单位"
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="关联委托订单编号，用于回溯委托与 FIFO 撮合"
    )
    order_sysid: Mapped[str | None] = mapped_column(String(64), comment="柜台合同编号")
    trade_side: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="买卖方向：BUY / SELL（执行侧统一映射）"
    )
    offset_flag: Mapped[int | None] = mapped_column(Integer, comment="QMT 交易操作原值（开/平等）")
    traded_price: Mapped[Decimal] = mapped_column(
        DECIMAL(20, 8), nullable=False, comment="成交均价"
    )
    traded_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="成交数量（股）")
    traded_amount: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="成交金额（QMT 原值，未必含费用）"
    )
    traded_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="成交时间（UTC naive，前端 formatEast8DateTime 展示）"
    )
    traded_time_east8: Mapped[datetime | None] = mapped_column(
        DateTime, comment="成交时间（东八区 naive 原值，仅供核对，COALESCE 不被空覆盖）"
    )
    strategy_name: Mapped[str | None] = mapped_column(String(64), comment="QMT 策略名称")
    order_remark: Mapped[str | None] = mapped_column(
        String(255), comment="委托备注（透传信号侧来源标识，便于对账）"
    )
    signal_trade_date: Mapped[date | None] = mapped_column(
        Date, comment="关联信号日 T（回填，join limit_up_selected_stock，COALESCE 不被空覆盖）"
    )
    data_source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="CALLBACK", server_default="CALLBACK",
        comment="数据来源：CALLBACK 回调 / QUERY_BACKFILL 收盘兜底补采",
    )


class QmtOrder(TimestampMixin, Base):
    """QMT 委托明细表（委托终态与成交进度，成交率/撤单率事实源）。"""

    __tablename__ = "qmt_order"
    __table_args__ = (
        # 加固唯一键：纳入 trade_date 防订单号跨日复用串号。
        UniqueConstraint(
            "account_id", "trade_date", "order_id", name="uk_qmt_order_acct_date_order"
        ),
        Index("idx_qmt_order_date_code", "trade_date", "ts_code"),
        Index("idx_qmt_order_status", "trade_date", "order_status"),
        Index("idx_qmt_order_signal", "signal_trade_date", "ts_code"),
    )

    # BigInteger PK：MySQL 落 BIGINT AUTO_INCREMENT；SQLite（单测）只对 INTEGER 主键自增，
    # 故 with_variant(Integer, "sqlite") 让测试库用 INTEGER 主键正常自增。
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    account_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="QMT 资金账号")
    account_type: Mapped[int | None] = mapped_column(Integer, comment="QMT 账号类型枚举")
    trade_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="委托所属交易日（东八区）"
    )
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False, comment="标准证券代码")
    qmt_stock_code: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="QMT 原始证券代码"
    )
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="QMT 订单编号")
    order_sysid: Mapped[str | None] = mapped_column(String(64), comment="柜台合同编号")
    trade_side: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="买卖方向：BUY / SELL"
    )
    offset_flag: Mapped[int | None] = mapped_column(Integer, comment="QMT 交易操作原值")
    price_type: Mapped[int | None] = mapped_column(
        Integer, comment="QMT 报价类型枚举（限价/市价等）"
    )
    order_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8), comment="委托价格")
    order_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="委托数量（股）")
    traded_volume: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0", comment="已成交数量"
    )
    traded_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8), comment="成交均价")
    order_status: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="委托状态：REPORTED/PART_TRADED/TRADED/CANCELLED/REJECTED/ERROR",
    )
    status_msg: Mapped[str | None] = mapped_column(
        String(255), comment="状态描述（QMT status_msg）"
    )
    error_id: Mapped[int | None] = mapped_column(Integer, comment="下单/撤单失败错误码")
    error_msg: Mapped[str | None] = mapped_column(String(255), comment="下单/撤单失败错误描述")
    cancel_failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
        comment="是否发生撤单失败（on_cancel_error 标记）",
    )
    order_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="报单时间（UTC naive，前端 formatEast8DateTime 展示）"
    )
    order_time_east8: Mapped[datetime | None] = mapped_column(
        DateTime, comment="报单时间（东八区 naive 原值，COALESCE 不被空覆盖）"
    )
    strategy_name: Mapped[str | None] = mapped_column(String(64), comment="QMT 策略名称")
    order_remark: Mapped[str | None] = mapped_column(
        String(255), comment="委托备注（透传信号侧来源标识）"
    )
    signal_trade_date: Mapped[date | None] = mapped_column(
        Date, comment="关联信号日 T（回填，COALESCE 不被空覆盖）"
    )
    data_source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="CALLBACK", server_default="CALLBACK",
        comment="数据来源：CALLBACK / QUERY_BACKFILL",
    )


class QmtPositionSnapshot(TimestampMixin, Base):
    """QMT 持仓快照表（按日，持仓盈亏与可卖市值复盘来源）。"""

    __tablename__ = "qmt_position_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "trade_date", "ts_code", "snapshot_type", name="uk_qmt_position_snap"
        ),
        Index("idx_qmt_position_date_type", "trade_date", "snapshot_type"),
        Index("idx_qmt_position_code", "ts_code", "trade_date"),
    )

    # BigInteger PK：MySQL 落 BIGINT AUTO_INCREMENT；SQLite（单测）只对 INTEGER 主键自增，
    # 故 with_variant(Integer, "sqlite") 让测试库用 INTEGER 主键正常自增。
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    account_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="QMT 资金账号")
    account_type: Mapped[int | None] = mapped_column(Integer, comment="QMT 账号类型枚举")
    trade_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="快照所属交易日（东八区）"
    )
    snapshot_type: Mapped[str] = mapped_column(
        String(12), nullable=False, default="CLOSE", server_default="CLOSE",
        comment="快照类型：OPEN/INTRADAY/CLOSE（历史净值/持仓复盘只认 CLOSE）",
    )
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False, comment="标准证券代码")
    qmt_stock_code: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="QMT 原始证券代码"
    )
    volume: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="持仓数量（总持仓，含当日买入；T+1 当日买入计入但不可卖）",
    )
    can_use_volume: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="可用数量（可卖部分，T+1 不含当日买入）",
    )
    frozen_volume: Mapped[int | None] = mapped_column(
        BigInteger, comment="冻结数量（版本不提供则空）"
    )
    on_road_volume: Mapped[int | None] = mapped_column(
        BigInteger, comment="在途数量（版本不提供则空）"
    )
    yesterday_volume: Mapped[int | None] = mapped_column(
        BigInteger, comment="昨夜拥股（版本不提供则空）"
    )
    open_price: Mapped[Decimal | None] = mapped_column(DECIMAL(20, 8), comment="开仓/持仓成本价")
    avg_price: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="成本均价（版本提供则有）"
    )
    market_value: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="持仓市值（QMT 原值）"
    )
    last_price: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="盯市现价（API 不给，由收盘价回填，用于算浮盈）"
    )
    float_profit: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="浮动盈亏=(last_price-成本)×volume（计算字段，回填）"
    )
    profit_rate: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="浮动盈亏比例=(last_price-成本)/成本（计算字段，回填）"
    )
    data_source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="QUERY", server_default="QUERY",
        comment="数据来源：QUERY 定时拉取 / CALLBACK 回调刷新",
    )


class QmtAccountDaily(TimestampMixin, Base):
    """QMT 账户资产日快照表（净值曲线与账户级收益来源）。"""

    __tablename__ = "qmt_account_daily"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "trade_date", "snapshot_type", name="uk_qmt_account_daily"
        ),
        Index("idx_qmt_account_date", "trade_date"),
    )

    # BigInteger PK：MySQL 落 BIGINT AUTO_INCREMENT；SQLite（单测）只对 INTEGER 主键自增，
    # 故 with_variant(Integer, "sqlite") 让测试库用 INTEGER 主键正常自增。
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    account_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="QMT 资金账号")
    account_type: Mapped[int | None] = mapped_column(Integer, comment="QMT 账号类型枚举")
    trade_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="快照所属交易日（东八区）"
    )
    snapshot_type: Mapped[str] = mapped_column(
        String(12), nullable=False, default="CLOSE", server_default="CLOSE",
        comment="快照类型：INTRADAY/CLOSE（历史净值曲线只认 CLOSE）",
    )
    total_asset: Mapped[Decimal] = mapped_column(
        DECIMAL(20, 8), nullable=False, comment="总资产（含当日浮动盈亏的实时口径）"
    )
    cash: Mapped[Decimal] = mapped_column(DECIMAL(20, 8), nullable=False, comment="可用资金")
    frozen_cash: Mapped[Decimal] = mapped_column(
        DECIMAL(20, 8), nullable=False, default=0, server_default="0", comment="冻结资金"
    )
    market_value: Mapped[Decimal] = mapped_column(
        DECIMAL(20, 8), nullable=False, default=0, server_default="0", comment="持仓市值"
    )
    net_cash_flow: Mapped[Decimal] = mapped_column(
        DECIMAL(20, 8), nullable=False, default=0, server_default="0",
        comment="当日净出入金（入金正/出金负；API 不提供，人工/外部录入）",
    )
    prev_total_asset: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="上一交易日收盘总资产（计算字段，回填）"
    )
    daily_pnl: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="当日盈亏=total_asset-prev_total_asset-net_cash_flow（已剔出入金）"
    )
    daily_return: Mapped[Decimal | None] = mapped_column(
        DECIMAL(20, 8), comment="当日收益率（单日 Modified Dietz，计算字段）"
    )
    cash_flow_note: Mapped[str | None] = mapped_column(String(255), comment="出入金备注")
    data_source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="QUERY", server_default="QUERY",
        comment="数据来源：QUERY 定时拉取 / CALLBACK 回调刷新",
    )
