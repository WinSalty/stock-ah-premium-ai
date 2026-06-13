from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260613_0052"
down_revision = "20260613_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新建打板回测三表：批次头 / 撮合明细 / 对照组涨停池。

    口径：T→B(买入日=T+1)→S(卖出日=B+1)经 a_trade_calendar 映射；不复权；一字/秒封不计收益
        (计入分母)；涨跌停按 board(主板±10%/创业板±20%)；空仓日收益记 0 留痕。
    幂等：run 表 run_key 唯一(同口径重跑先清同 run_id 明细再写)；对照组 (trade_date,ts_code,source) 唯一。

    创建日期：2026-06-13
    author: claude
    """

    op.create_table(
        "limit_up_backtest_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("run_key", sa.String(length=128), nullable=False, comment="口径哈希(幂等重跑键)"),
        sa.Column("start_date", sa.Date(), nullable=False, comment="回测信号区间起(trade_date)"),
        sa.Column("end_date", sa.Date(), nullable=False, comment="回测信号区间止"),
        sa.Column("exec_version", sa.String(length=32), nullable=False, comment="可成交性版本 v_exec.N"),
        sa.Column("cost_version", sa.String(length=32), nullable=False, comment="买入价+费用版本 v_cost.N"),
        sa.Column("hold_window", sa.Integer(), nullable=False, server_default="1", comment="持有窗口(交易日)"),
        sa.Column(
            "sell_price_policy",
            sa.String(length=32),
            nullable=False,
            server_default="NEXT_OPEN",
            comment="卖出价口径 NEXT_OPEN/NEXT_CLOSE/VWAP",
        ),
        sa.Column("include_fees", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否含费"),
        sa.Column(
            "control_group_source",
            sa.String(length=32),
            nullable=False,
            server_default="CACHE_POOL",
            comment="对照组源 CACHE_POOL(方案b)/LIMIT_LIST_D(方案a)",
        ),
        sa.Column(
            "params_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="完整口径快照(可复现)",
        ),
        sa.Column(
            "summary_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="汇总指标(分布/超额/分组)",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="RUNNING", comment="RUNNING/SUCCESS/FAILED"),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0", comment="信号数"),
        sa.Column("tradable_count", sa.Integer(), nullable=False, server_default="0", comment="可成交数"),
        sa.Column("empty_day_count", sa.Integer(), nullable=False, server_default="0", comment="空仓日数(留痕)"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始时间(UTC naive)"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="结束时间(UTC naive)"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uk_lub_run_key"),
        comment="打板信号回测批次头(参数快照+汇总)",
    )
    op.create_index("idx_lub_run_status_started", "limit_up_backtest_run", ["status", "started_at"])

    op.create_table(
        "limit_up_backtest_result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("run_id", sa.Integer(), nullable=False, comment="关联 limit_up_backtest_run.id"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="标的"),
        sa.Column("signal_trade_date", sa.Date(), nullable=False, comment="信号日 T"),
        sa.Column("target_trade_date", sa.Date(), nullable=True, comment="买入日 B=T+1(日历映射)"),
        sa.Column("sell_date", sa.Date(), nullable=True, comment="实际卖出日(含跌停顺延)"),
        sa.Column("hold_window", sa.Integer(), nullable=False, server_default="1", comment="持有窗口(交易日)"),
        sa.Column("board", sa.String(length=8), nullable=True, comment="MAIN/GEM(涨跌停幅度)"),
        sa.Column("limit_up_price", sa.DECIMAL(precision=12, scale=4), nullable=True, comment="B日理论涨停价(不复权)"),
        sa.Column("tradable_flag", sa.Integer(), nullable=False, server_default="1", comment="1可成交/0买不进(一字秒封)"),
        sa.Column("miss_reason", sa.String(length=32), nullable=True, comment="ONE_WORD/SECONDS_SEAL/NO_QUOTE/EMPTY_GATE"),
        sa.Column("buy_price", sa.DECIMAL(precision=12, scale=4), nullable=True, comment="假设买入价(对账P_backtest)"),
        sa.Column("sell_price", sa.DECIMAL(precision=12, scale=4), nullable=True, comment="卖出价"),
        sa.Column("limit_down_rollover_days", sa.Integer(), nullable=False, server_default="0", comment="无量跌停顺延天数"),
        sa.Column("gross_return_pct", sa.DECIMAL(precision=12, scale=6), nullable=True, comment="毛收益率(可成交才有)"),
        sa.Column("net_return_pct", sa.DECIMAL(precision=12, scale=6), nullable=True, comment="净收益率(扣费)"),
        sa.Column("control_excess_pct", sa.DECIMAL(precision=12, scale=6), nullable=True, comment="相对对照组超额"),
        sa.Column("leader_strength_score", sa.DECIMAL(precision=8, scale=2), nullable=True, comment="龙头强度分(分组用快照)"),
        sa.Column("role", sa.String(length=32), nullable=True, comment="角色(分组用快照)"),
        sa.Column("strategy_family", sa.String(length=32), nullable=True, comment="战法族(分组用快照)"),
        sa.Column("market_state", sa.String(length=16), nullable=True, comment="情绪周期(分组用快照)"),
        sa.Column("is_empty_day", sa.Integer(), nullable=False, server_default="0", comment="空仓日留痕(收益记0)"),
        sa.Column("computed_at", sa.DateTime(), nullable=True, comment="计算时间(UTC naive)"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "ts_code", "signal_trade_date", "hold_window", name="uk_lub_result"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["limit_up_backtest_run.id"], name="fk_lub_result_run"),
        comment="打板回测撮合明细(一信号×一窗口一行)",
    )
    op.create_index("idx_lub_result_run_window", "limit_up_backtest_result", ["run_id", "hold_window"])
    op.create_index(
        "idx_lub_result_group", "limit_up_backtest_result", ["run_id", "market_state", "role"]
    )

    op.create_table(
        "limit_up_market_pool",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="涨停所属交易日 T"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="涨停标的"),
        sa.Column("name", sa.String(length=64), nullable=True, comment="名称"),
        sa.Column("board_level", sa.Integer(), nullable=True, comment="连板数(快照)"),
        sa.Column("limit_type", sa.String(length=16), nullable=True, comment="涨停类型(快照)"),
        sa.Column("theme", sa.String(length=255), nullable=True, comment="题材(快照)"),
        sa.Column("seal_ratio_pct", sa.DECIMAL(precision=12, scale=4), nullable=True, comment="封流比(快照衍生)"),
        sa.Column(
            "next_day_return_pct",
            sa.DECIMAL(precision=12, scale=6),
            nullable=True,
            comment="隔日收益(B=T+1开→S=T+2开，与信号回测同口径，作超额基准)",
        ),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="CACHE_POOL", comment="CACHE_POOL/LIMIT_LIST_D"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "ts_code", "source", name="uk_lump"),
        comment="回测对照组全市场涨停池(方案b 从报告快照抽取回填)",
    )
    op.create_index("idx_lump_date", "limit_up_market_pool", ["trade_date"])


def downgrade() -> None:
    """回滚：逆序删除回测三表(drop_table 级联清索引/外键)。

    创建日期：2026-06-13
    author: claude
    """

    op.drop_table("limit_up_market_pool")
    op.drop_table("limit_up_backtest_result")
    op.drop_table("limit_up_backtest_run")
