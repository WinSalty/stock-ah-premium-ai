"""创建 QMT 执行侧决策明细表 qmt_decision_log。

业务意图：执行侧在各决策点（信号达标判定 / 下单 / 卖出 / 各类拦截）用 best-effort 旁路采集结构化
    决策事件，盘后经 `POST /api/internal/qmt/ingest` 回流到本表，供「决策流水/闭环」看板把
    信号达标→下单/未买→卖出 串成可读时间线。本表是**复盘用**事实源，与交易热路径解耦、可丢失。

唯一键口径（加固）：decision_id 纳入 trade_date，防执行侧决策编号跨日复用串号；幂等 upsert 以此定位同一行。

幂等：建表由 Alembic 版本串联保证唯一执行；本迁移仅建表不灌数。

创建日期：2026-06-14
author: claude
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260614_0055"
down_revision = "20260614_0054"
branch_labels = None
depends_on = None

_CHARSET_KW = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    """建决策明细表 + 加固唯一键 + 复盘/闭环 join 索引。"""

    op.create_table(
        "qmt_decision_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("account_id", sa.String(32), nullable=False, comment="QMT 资金账号"),
        sa.Column(
            "trade_date", sa.Date(), nullable=False, comment="决策发生交易日（东八区）"
        ),
        sa.Column(
            "decision_id", sa.String(64), nullable=False, comment="执行侧决策编号，去重最小单位"
        ),
        sa.Column(
            "signal_trade_date", sa.Date(), nullable=True,
            comment="关联信号日 T（回填，join limit_up_selected_stock，COALESCE 不被空覆盖）",
        ),
        sa.Column("ts_code", sa.String(16), nullable=True, comment="标准证券代码；全局闸门类可空"),
        sa.Column(
            "decision_type", sa.String(32), nullable=False,
            comment="决策类型：SIGNAL_QUALIFIED/BUY_SUBMIT/BUY_MISS/SELL_SUBMIT/SELL_HOLD/"
            "SKIP_GLOBAL/SKIP_STRATEGY/SKIP_ORCHESTRATION/SKIP_ORDER",
        ),
        sa.Column(
            "decision_stage", sa.String(32), nullable=True,
            comment="决策分层：GLOBAL_GATE/STRATEGY/ORCHESTRATION/ORDER/SELL",
        ),
        sa.Column("action", sa.String(32), nullable=True, comment="战法/动作"),
        sa.Column("strategy_family", sa.String(16), nullable=True, comment="战法族 DABAN/BANLU/DIXI/SELL"),
        sa.Column("order_phase", sa.String(16), nullable=True, comment="下单时段 AUCTION/OPENING/INTRADAY"),
        sa.Column("reason", sa.String(255), nullable=True, comment="触发/拦截原因（人读）"),
        sa.Column("reason_code", sa.String(64), nullable=True, comment="机器可读原因码（可筛可统计）"),
        sa.Column("factors_snapshot", sa.JSON(), nullable=True, comment="关键因子/阈值快照"),
        sa.Column("limit_price", sa.DECIMAL(20, 8), nullable=True, comment="决策挂价/参考价"),
        sa.Column("plan_volume", sa.BigInteger(), nullable=True, comment="计划数量（股）"),
        sa.Column(
            "order_id", sa.BigInteger(), nullable=True,
            comment="关联券商订单编号（仅 *_SUBMIT 有，串联 qmt_order/qmt_trade）",
        ),
        sa.Column("biz_order_no", sa.String(64), nullable=True, comment="执行侧业务单号（COALESCE 不被空覆盖）"),
        sa.Column(
            "decided_time", sa.DateTime(), nullable=False,
            comment="决策时刻（UTC naive，前端 formatEast8DateTime 展示）",
        ),
        sa.Column(
            "decided_time_east8", sa.DateTime(), nullable=True,
            comment="决策时刻（东八区 naive 原值，看板默认展示，COALESCE 不被空覆盖）",
        ),
        sa.Column(
            "data_source", sa.String(24), nullable=False, server_default="EMITTER",
            comment="数据来源：EMITTER 执行侧决策发射器",
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"), comment="记录创建时间（DB 生成）",
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="记录更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "trade_date", "decision_id", name="uk_qmt_decision_acct_date_did"
        ),
        comment="QMT 执行侧决策明细（信号达标→下单/未买→卖出 可读链路；复盘用、可丢失、不参与对账）",
        **_CHARSET_KW,
    )
    op.create_index("idx_qmt_decision_date_code", "qmt_decision_log", ["trade_date", "ts_code"])
    op.create_index("idx_qmt_decision_signal", "qmt_decision_log", ["signal_trade_date", "ts_code"])
    op.create_index("idx_qmt_decision_date_type", "qmt_decision_log", ["trade_date", "decision_type"])


def downgrade() -> None:
    """回滚：独立表无外键被依赖，直接 drop。"""
    op.drop_table("qmt_decision_log")
