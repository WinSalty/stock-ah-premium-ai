from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260506_0023"
down_revision = "20260506_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 腾讯不复权日线独立存储，避免历史补数口径混入 Tushare 官方日线或 Baidu 前复权数据。
    op.create_table(
        "tencent_unadjusted_daily_quote",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("market", sa.String(length=8), nullable=False, comment="市场: A、HK"),
        sa.Column("ts_code", sa.String(length=16), nullable=False, comment="项目标准代码，如 600036.SH、03968.HK"),
        sa.Column("tencent_symbol", sa.String(length=32), nullable=False, comment="腾讯 symbol，如 sh600036、hk03968"),
        sa.Column("trade_date", sa.Date(), nullable=False, comment="交易日期"),
        sa.Column("open", sa.DECIMAL(20, 6), nullable=True, comment="不复权开盘价"),
        sa.Column("close", sa.DECIMAL(20, 6), nullable=False, comment="不复权收盘价"),
        sa.Column("high", sa.DECIMAL(20, 6), nullable=True, comment="不复权最高价"),
        sa.Column("low", sa.DECIMAL(20, 6), nullable=True, comment="不复权最低价"),
        sa.Column("volume", sa.DECIMAL(24, 4), nullable=True, comment="成交量，按腾讯原始单位保存"),
        sa.Column("amount", sa.DECIMAL(24, 4), nullable=True, comment="成交额，按腾讯原始单位保存"),
        sa.Column("amplitude", sa.DECIMAL(20, 6), nullable=True, comment="振幅"),
        sa.Column("pct_chg", sa.DECIMAL(20, 6), nullable=True, comment="涨跌幅"),
        sa.Column("change_amount", sa.DECIMAL(20, 6), nullable=True, comment="涨跌额"),
        sa.Column("turnover_rate", sa.DECIMAL(20, 6), nullable=True, comment="换手率"),
        sa.Column("adjust_type", sa.String(length=16), nullable=False, server_default="NONE", comment="复权类型: NONE 不复权"),
        sa.Column("data_source", sa.String(length=32), nullable=False, server_default="TENCENT_KLINE", comment="数据来源"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="原始单行数据或摘要 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market", "ts_code", "trade_date", "adjust_type", name="uk_tencent_unadj_quote"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="腾讯不复权历史日线表",
    )
    op.create_index("idx_tencent_unadj_quote_date", "tencent_unadjusted_daily_quote", ["trade_date"])
    op.create_index(
        "idx_tencent_unadj_quote_code_date",
        "tencent_unadjusted_daily_quote",
        ["ts_code", "trade_date"],
    )

    # water-stock 写入 HKD/CNY 汇率到本项目独立表，本项目只消费该表追算历史 AH 比价。
    op.create_table(
        "waterstock_fx_rate_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("currency_pair", sa.String(length=16), nullable=False, comment="汇率对，如 HKDCNY"),
        sa.Column("rate_date", sa.Date(), nullable=False, comment="汇率日期"),
        sa.Column("open", sa.DECIMAL(20, 8), nullable=True, comment="开盘汇率"),
        sa.Column("close", sa.DECIMAL(20, 8), nullable=False, comment="收盘汇率"),
        sa.Column("high", sa.DECIMAL(20, 8), nullable=True, comment="最高汇率"),
        sa.Column("low", sa.DECIMAL(20, 8), nullable=True, comment="最低汇率"),
        sa.Column("data_source", sa.String(length=32), nullable=False, server_default="WATER_STOCK_BAIDU_FX", comment="汇率来源"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True, comment="原始响应摘要 JSON"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("currency_pair", "rate_date", "data_source", name="uk_waterstock_fx_rate"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="water-stock 历史汇率日线表",
    )
    op.create_index("idx_waterstock_fx_rate_date", "waterstock_fx_rate_daily", ["rate_date"])

    # 不复权追跑记录按 A/H 股票对和来源唯一，重跑时先看 COMPLETED 状态，避免重复追算已验证区间。
    op.create_table(
        "historical_ah_unadjusted_backfill_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="自增主键"),
        sa.Column("a_ts_code", sa.String(length=16), nullable=False, comment="A 股 Tushare 代码"),
        sa.Column("hk_ts_code", sa.String(length=16), nullable=False, comment="H 股 Tushare 代码"),
        sa.Column("data_source", sa.String(length=32), nullable=False, comment="补数来源标记"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态: RUNNING、COMPLETED、FAILED"),
        sa.Column("candidate_rows", sa.Integer(), nullable=False, server_default="0", comment="A/H/汇率三方日期交集行数"),
        sa.Column("inserted_rows", sa.Integer(), nullable=False, server_default="0", comment="写入官方 AH 主表行数"),
        sa.Column("skipped_existing_rows", sa.Integer(), nullable=False, server_default="0", comment="主表唯一键已存在跳过行数"),
        sa.Column("skipped_invalid_rows", sa.Integer(), nullable=False, server_default="0", comment="价格或汇率无效跳过行数"),
        sa.Column("first_trade_date", sa.Date(), nullable=True, comment="本轮最早日期"),
        sa.Column("last_trade_date", sa.Date(), nullable=True, comment="本轮最晚日期"),
        sa.Column("last_error", sa.String(length=512), nullable=True, comment="失败原因摘要"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="最近开始时间"),
        sa.Column("completed_at", sa.DateTime(), nullable=True, comment="最近完成时间"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False, comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("a_ts_code", "hk_ts_code", "data_source", name="uk_unadj_backfill_pair"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_comment="不复权历史 AH 比价补数执行记录表",
    )
    op.create_index(
        "idx_unadj_backfill_status",
        "historical_ah_unadjusted_backfill_run",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("idx_unadj_backfill_status", table_name="historical_ah_unadjusted_backfill_run")
    op.drop_table("historical_ah_unadjusted_backfill_run")
    op.drop_index("idx_waterstock_fx_rate_date", table_name="waterstock_fx_rate_daily")
    op.drop_table("waterstock_fx_rate_daily")
    op.drop_index("idx_tencent_unadj_quote_code_date", table_name="tencent_unadjusted_daily_quote")
    op.drop_index("idx_tencent_unadj_quote_date", table_name="tencent_unadjusted_daily_quote")
    op.drop_table("tencent_unadjusted_daily_quote")
