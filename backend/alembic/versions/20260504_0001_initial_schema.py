from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "a_stock_basic",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("area", sa.String(length=64), nullable=True),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("fullname", sa.String(length=255), nullable=True),
        sa.Column("market", sa.String(length=64), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("curr_type", sa.String(length=16), nullable=True),
        sa.Column("list_status", sa.String(length=8), nullable=True),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("delist_date", sa.Date(), nullable=True),
        sa.Column("is_hs", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("ts_code"),
    )
    op.create_table(
        "hk_stock_basic",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("fullname", sa.String(length=255), nullable=True),
        sa.Column("enname", sa.String(length=255), nullable=True),
        sa.Column("cn_spell", sa.String(length=64), nullable=True),
        sa.Column("market", sa.String(length=64), nullable=True),
        sa.Column("list_status", sa.String(length=8), nullable=True),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("delist_date", sa.Date(), nullable=True),
        sa.Column("trade_unit", sa.DECIMAL(18, 4), nullable=True),
        sa.Column("isin", sa.String(length=32), nullable=True),
        sa.Column("curr_type", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("ts_code"),
    )
    op.create_table(
        "a_trade_calendar",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("cal_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Integer(), nullable=False),
        sa.Column("pretrade_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange", "cal_date", name="uk_a_trade_calendar"),
    )
    op.create_table(
        "hk_trade_calendar",
        sa.Column("cal_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Integer(), nullable=False),
        sa.Column("pretrade_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("cal_date"),
    )
    op.create_table(
        "a_daily_quote",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("high", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("low", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("close", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("pre_close", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("change_amount", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("pct_chg", sa.DECIMAL(12, 6), nullable=True),
        sa.Column("vol", sa.DECIMAL(24, 6), nullable=True),
        sa.Column("amount", sa.DECIMAL(24, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "trade_date", name="uk_a_daily_quote"),
    )
    op.create_index("idx_a_daily_trade_date", "a_daily_quote", ["trade_date"])
    op.create_index("idx_a_daily_ts_code", "a_daily_quote", ["ts_code"])
    op.create_table(
        "hk_daily_quote",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("high", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("low", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("close", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("pre_close", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("change_amount", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("pct_chg", sa.DECIMAL(12, 6), nullable=True),
        sa.Column("vol", sa.DECIMAL(24, 6), nullable=True),
        sa.Column("amount", sa.DECIMAL(24, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ts_code", "trade_date", name="uk_hk_daily_quote"),
    )
    op.create_index("idx_hk_daily_trade_date", "hk_daily_quote", ["trade_date"])
    op.create_index("idx_hk_daily_ts_code", "hk_daily_quote", ["ts_code"])
    op.create_table(
        "hsgt_constituent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("connect_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("type_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "ts_code", "connect_type", name="uk_hsgt_constituent"),
    )
    op.create_index("idx_hsgt_date_type", "hsgt_constituent", ["trade_date", "connect_type"])
    op.create_index("idx_hsgt_ts_code", "hsgt_constituent", ["ts_code"])
    op.create_table(
        "fx_rate_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rate_pair", sa.String(length=32), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("base_ccy", sa.String(length=8), nullable=False),
        sa.Column("quote_ccy", sa.String(length=8), nullable=False),
        sa.Column("mid_rate", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("bid_close", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("ask_close", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("raw_ts_code", sa.String(length=32), nullable=True),
        sa.Column("is_cross_rate", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rate_pair", "rate_date", "source", name="uk_fx_rate_daily"),
    )
    op.create_index("idx_fx_pair_date", "fx_rate_daily", ["rate_pair", "rate_date"])
    op.create_table(
        "ah_stock_pair",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("a_ts_code", sa.String(length=16), nullable=False),
        sa.Column("hk_ts_code", sa.String(length=16), nullable=False),
        sa.Column("a_name", sa.String(length=128), nullable=True),
        sa.Column("hk_name", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("effective_start_date", sa.Date(), nullable=True),
        sa.Column("effective_end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("a_ts_code", "hk_ts_code", name="uk_ah_stock_pair"),
    )
    op.create_index("idx_ah_pair_hk", "ah_stock_pair", ["hk_ts_code"])
    op.create_index("idx_ah_pair_a", "ah_stock_pair", ["a_ts_code"])
    op.create_table(
        "official_ah_comparison",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("a_ts_code", sa.String(length=16), nullable=False),
        sa.Column("hk_ts_code", sa.String(length=16), nullable=False),
        sa.Column("a_name", sa.String(length=128), nullable=True),
        sa.Column("hk_name", sa.String(length=128), nullable=True),
        sa.Column("a_close", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("a_pct_chg", sa.DECIMAL(12, 6), nullable=True),
        sa.Column("hk_close", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("hk_pct_chg", sa.DECIMAL(12, 6), nullable=True),
        sa.Column("ah_comparison", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("ah_premium", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "a_ts_code", "hk_ts_code", name="uk_official_ah"),
    )
    op.create_index("idx_official_ah_trade_date", "official_ah_comparison", ["trade_date"])
    op.create_table(
        "ah_premium_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("a_ts_code", sa.String(length=16), nullable=False),
        sa.Column("hk_ts_code", sa.String(length=16), nullable=False),
        sa.Column("a_name", sa.String(length=128), nullable=True),
        sa.Column("hk_name", sa.String(length=128), nullable=True),
        sa.Column("a_close_cny", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("h_close_hkd", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("hkd_cny", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("h_close_cny", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("ah_ratio", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("ah_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("is_hk_connect", sa.Boolean(), nullable=False),
        sa.Column("connect_channels", sa.String(length=64), nullable=True),
        sa.Column("rate_date", sa.Date(), nullable=True),
        sa.Column("rate_source", sa.String(length=64), nullable=True),
        sa.Column("rate_fallback", sa.Boolean(), nullable=False),
        sa.Column("calc_status", sa.String(length=32), nullable=False),
        sa.Column("official_ah_ratio", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("official_ah_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("diff_from_official_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "a_ts_code", "hk_ts_code", name="uk_ah_premium_daily"),
    )
    op.create_index("idx_ah_premium_rank", "ah_premium_daily", ["trade_date", "ah_premium_pct"])
    op.create_index("idx_ah_premium_hk", "ah_premium_daily", ["hk_ts_code", "trade_date"])
    op.create_index("idx_ah_premium_a", "ah_premium_daily", ["a_ts_code", "trade_date"])
    op.create_table(
        "sync_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sync_checkpoint",
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("last_success_date", sa.Date(), nullable=True),
        sa.Column("last_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("dataset", "scope_key"),
    )
    op.create_table(
        "data_quality_issue",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("ref_key", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "llm_chat_session",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "llm_chat_message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=True),
        sa.Column("result_preview_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["llm_chat_session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    for table in [
        "llm_chat_message",
        "llm_chat_session",
        "data_quality_issue",
        "sync_checkpoint",
        "sync_run",
        "ah_premium_daily",
        "official_ah_comparison",
        "ah_stock_pair",
        "fx_rate_daily",
        "hsgt_constituent",
        "hk_daily_quote",
        "a_daily_quote",
        "hk_trade_calendar",
        "a_trade_calendar",
        "hk_stock_basic",
        "a_stock_basic",
    ]:
        op.drop_table(table)
