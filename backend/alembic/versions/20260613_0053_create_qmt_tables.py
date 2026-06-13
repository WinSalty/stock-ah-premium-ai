"""创建 QMT 执行侧回流四表 qmt_trade / qmt_order / qmt_position_snapshot / qmt_account_daily。

业务意图：执行侧（Windows VPS / miniQMT）盘后经 `POST /api/internal/qmt/ingest` 把当日成交/委托/
    持仓/账户快照幂等回流到信号侧 MySQL，供复盘看板、闭环归因、只读对账消费。本迁移落地四张远端表，
    列与执行侧本机 SQLite（storage/schema.py）一一对应，便于「同 schema 搬行」。

唯一键口径（加固）：成交/委托唯一键纳入 trade_date，防 QMT 订单号/成交号跨日复用串号；与执行侧
    repository_unique_with_trade_date=True 默认一致，保证重传幂等、跨日同号不误并。

幂等：建表由 Alembic 版本串联保证唯一执行；本迁移仅建表不灌数。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260613_0053"
down_revision = "20260613_0052"
branch_labels = None
depends_on = None

# 四表通用的审计时间列（与 TimestampMixin 口径一致：DB 生成，东八区理解）。
_CHARSET_KW = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def _timestamp_columns() -> list[sa.Column]:
    """构造 created_at / updated_at 两列（DB 默认 + ON UPDATE 自动更新）。"""
    return [
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"), comment="记录创建时间（DB 生成）",
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="记录更新时间",
        ),
    ]


def upgrade() -> None:
    """建四表 + 加固唯一键 + 复盘/对账索引。"""

    # —— qmt_trade 成交明细 ——
    op.create_table(
        "qmt_trade",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("account_id", sa.String(32), nullable=False, comment="QMT 资金账号"),
        sa.Column("account_type", sa.Integer(), nullable=True, comment="QMT 账号类型枚举原值"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="成交所属交易日（东八区）"),
        sa.Column("ts_code", sa.String(16), nullable=False, comment="标准证券代码（已归一）"),
        sa.Column("qmt_stock_code", sa.String(16), nullable=False, comment="QMT 原始证券代码"),
        sa.Column("traded_id", sa.String(64), nullable=False, comment="QMT 成交编号，去重最小单位"),
        sa.Column("order_id", sa.BigInteger(), nullable=True, comment="关联委托订单编号"),
        sa.Column("order_sysid", sa.String(64), nullable=True, comment="柜台合同编号"),
        sa.Column("trade_side", sa.String(8), nullable=False, comment="买卖方向：BUY/SELL"),
        sa.Column("offset_flag", sa.Integer(), nullable=True, comment="QMT 交易操作原值"),
        sa.Column("traded_price", sa.DECIMAL(20, 8), nullable=False, comment="成交均价"),
        sa.Column("traded_volume", sa.BigInteger(), nullable=False, comment="成交数量（股）"),
        sa.Column("traded_amount", sa.DECIMAL(20, 8), nullable=True, comment="成交金额（原值）"),
        sa.Column("traded_time", sa.DateTime(), nullable=False, comment="成交时间（UTC naive）"),
        sa.Column("traded_time_east8", sa.DateTime(), nullable=True, comment="成交时间(东八区)"),
        sa.Column("strategy_name", sa.String(64), nullable=True, comment="QMT 策略名称"),
        sa.Column("order_remark", sa.String(255), nullable=True, comment="委托备注（来源标识）"),
        sa.Column("signal_trade_date", sa.Date(), nullable=True, comment="关联信号日 T（回填）"),
        sa.Column(
            "data_source", sa.String(24), nullable=False, server_default="CALLBACK",
            comment="数据来源：CALLBACK / QUERY_BACKFILL",
        ),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "trade_date", "traded_id", name="uk_qmt_trade_acct_date_traded"
        ),
        comment="QMT 成交明细表（成交回报，已实现盈亏与成交统计事实源）",
        **_CHARSET_KW,
    )
    op.create_index("idx_qmt_trade_date_code", "qmt_trade", ["trade_date", "ts_code"])
    op.create_index("idx_qmt_trade_order", "qmt_trade", ["account_id", "order_id"])
    op.create_index("idx_qmt_trade_signal", "qmt_trade", ["signal_trade_date", "ts_code"])

    # —— qmt_order 委托明细 ——
    op.create_table(
        "qmt_order",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("account_id", sa.String(32), nullable=False, comment="QMT 资金账号"),
        sa.Column("account_type", sa.Integer(), nullable=True, comment="QMT 账号类型枚举"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="委托所属交易日（东八区）"),
        sa.Column("ts_code", sa.String(16), nullable=False, comment="标准证券代码"),
        sa.Column("qmt_stock_code", sa.String(16), nullable=False, comment="QMT 原始证券代码"),
        sa.Column("order_id", sa.BigInteger(), nullable=False, comment="QMT 订单编号"),
        sa.Column("order_sysid", sa.String(64), nullable=True, comment="柜台合同编号"),
        sa.Column("trade_side", sa.String(8), nullable=False, comment="买卖方向：BUY/SELL"),
        sa.Column("offset_flag", sa.Integer(), nullable=True, comment="QMT 交易操作原值"),
        sa.Column("price_type", sa.Integer(), nullable=True, comment="QMT 报价类型枚举"),
        sa.Column("order_price", sa.DECIMAL(20, 8), nullable=True, comment="委托价格"),
        sa.Column("order_volume", sa.BigInteger(), nullable=False, comment="委托数量（股）"),
        sa.Column(
            "traded_volume", sa.BigInteger(), nullable=False, server_default="0",
            comment="已成交数量",
        ),
        sa.Column("traded_price", sa.DECIMAL(20, 8), nullable=True, comment="成交均价"),
        sa.Column(
            "order_status", sa.String(16), nullable=False,
            comment="委托状态：REPORTED/PART_TRADED/TRADED/CANCELLED/REJECTED/ERROR",
        ),
        sa.Column("status_msg", sa.String(255), nullable=True, comment="状态描述"),
        sa.Column("error_id", sa.Integer(), nullable=True, comment="下单/撤单失败错误码"),
        sa.Column("error_msg", sa.String(255), nullable=True, comment="下单/撤单失败错误描述"),
        sa.Column(
            "cancel_failed", sa.Boolean(), nullable=False, server_default="0",
            comment="是否发生撤单失败（on_cancel_error 标记）",
        ),
        sa.Column("order_time", sa.DateTime(), nullable=True, comment="报单时间（UTC naive）"),
        sa.Column("order_time_east8", sa.DateTime(), nullable=True, comment="报单时间(东八区)"),
        sa.Column("strategy_name", sa.String(64), nullable=True, comment="QMT 策略名称"),
        sa.Column("order_remark", sa.String(255), nullable=True, comment="委托备注"),
        sa.Column("signal_trade_date", sa.Date(), nullable=True, comment="关联信号日 T（回填）"),
        sa.Column(
            "data_source", sa.String(24), nullable=False, server_default="CALLBACK",
            comment="数据来源：CALLBACK / QUERY_BACKFILL",
        ),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "trade_date", "order_id", name="uk_qmt_order_acct_date_order"
        ),
        comment="QMT 委托明细表（委托终态与成交进度，成交率/撤单率事实源）",
        **_CHARSET_KW,
    )
    op.create_index("idx_qmt_order_date_code", "qmt_order", ["trade_date", "ts_code"])
    op.create_index("idx_qmt_order_status", "qmt_order", ["trade_date", "order_status"])
    op.create_index("idx_qmt_order_signal", "qmt_order", ["signal_trade_date", "ts_code"])

    # —— qmt_position_snapshot 持仓快照 ——
    op.create_table(
        "qmt_position_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("account_id", sa.String(32), nullable=False, comment="QMT 资金账号"),
        sa.Column("account_type", sa.Integer(), nullable=True, comment="QMT 账号类型枚举"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="快照所属交易日（东八区）"),
        sa.Column(
            "snapshot_type", sa.String(12), nullable=False, server_default="CLOSE",
            comment="快照类型：OPEN/INTRADAY/CLOSE（复盘只认 CLOSE）",
        ),
        sa.Column("ts_code", sa.String(16), nullable=False, comment="标准证券代码"),
        sa.Column("qmt_stock_code", sa.String(16), nullable=False, comment="QMT 原始证券代码"),
        sa.Column(
            "volume", sa.BigInteger(), nullable=False, server_default="0",
            comment="持仓数量（总持仓，含当日买入）",
        ),
        sa.Column(
            "can_use_volume", sa.BigInteger(), nullable=False, server_default="0",
            comment="可用数量（T+1 不含当日买入）",
        ),
        sa.Column("frozen_volume", sa.BigInteger(), nullable=True, comment="冻结数量"),
        sa.Column("on_road_volume", sa.BigInteger(), nullable=True, comment="在途数量"),
        sa.Column("yesterday_volume", sa.BigInteger(), nullable=True, comment="昨夜拥股"),
        sa.Column("open_price", sa.DECIMAL(20, 8), nullable=True, comment="开仓/持仓成本价"),
        sa.Column("avg_price", sa.DECIMAL(20, 8), nullable=True, comment="成本均价"),
        sa.Column("market_value", sa.DECIMAL(20, 8), nullable=True, comment="持仓市值（QMT 原值）"),
        sa.Column("last_price", sa.DECIMAL(20, 8), nullable=True, comment="盯市现价（回填）"),
        sa.Column("float_profit", sa.DECIMAL(20, 8), nullable=True, comment="浮动盈亏（回填）"),
        sa.Column("profit_rate", sa.DECIMAL(20, 8), nullable=True, comment="浮动盈亏比例（回填）"),
        sa.Column(
            "data_source", sa.String(24), nullable=False, server_default="QUERY",
            comment="数据来源：QUERY / CALLBACK",
        ),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "trade_date", "ts_code", "snapshot_type", name="uk_qmt_position_snap"
        ),
        comment="QMT 持仓快照表（按日，持仓盈亏与可卖市值复盘来源）",
        **_CHARSET_KW,
    )
    op.create_index(
        "idx_qmt_position_date_type", "qmt_position_snapshot", ["trade_date", "snapshot_type"]
    )
    op.create_index("idx_qmt_position_code", "qmt_position_snapshot", ["ts_code", "trade_date"])

    # —— qmt_account_daily 账户资产日快照 ——
    op.create_table(
        "qmt_account_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("account_id", sa.String(32), nullable=False, comment="QMT 资金账号"),
        sa.Column("account_type", sa.Integer(), nullable=True, comment="QMT 账号类型枚举"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="快照所属交易日（东八区）"),
        sa.Column(
            "snapshot_type", sa.String(12), nullable=False, server_default="CLOSE",
            comment="快照类型：INTRADAY/CLOSE（净值曲线只认 CLOSE）",
        ),
        sa.Column("total_asset", sa.DECIMAL(20, 8), nullable=False, comment="总资产（实时口径）"),
        sa.Column("cash", sa.DECIMAL(20, 8), nullable=False, comment="可用资金"),
        sa.Column(
            "frozen_cash", sa.DECIMAL(20, 8), nullable=False, server_default="0", comment="冻结资金"
        ),
        sa.Column(
            "market_value", sa.DECIMAL(20, 8), nullable=False,
            server_default="0", comment="持仓市值",
        ),
        sa.Column(
            "net_cash_flow", sa.DECIMAL(20, 8), nullable=False, server_default="0",
            comment="当日净出入金（入金正/出金负）",
        ),
        sa.Column(
            "prev_total_asset", sa.DECIMAL(20, 8), nullable=True, comment="上一交易日收盘总资产"
        ),
        sa.Column("daily_pnl", sa.DECIMAL(20, 8), nullable=True, comment="当日盈亏（已剔出入金）"),
        sa.Column("daily_return", sa.DECIMAL(20, 8), nullable=True, comment="当日收益率（回填）"),
        sa.Column("cash_flow_note", sa.String(255), nullable=True, comment="出入金备注"),
        sa.Column(
            "data_source", sa.String(24), nullable=False, server_default="QUERY",
            comment="数据来源：QUERY / CALLBACK",
        ),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "trade_date", "snapshot_type", name="uk_qmt_account_daily"
        ),
        comment="QMT 账户资产日快照表（净值曲线与账户级收益来源）",
        **_CHARSET_KW,
    )
    op.create_index("idx_qmt_account_date", "qmt_account_daily", ["trade_date"])


def downgrade() -> None:
    """回退：按建表逆序删四表（索引随表删除）。"""
    op.drop_table("qmt_account_daily")
    op.drop_table("qmt_position_snapshot")
    op.drop_table("qmt_order")
    op.drop_table("qmt_trade")
