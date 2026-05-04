from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260504_0006"
down_revision = "20260504_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_ah_premium_a", table_name="ah_premium_daily")
    op.drop_index("idx_ah_premium_hk", table_name="ah_premium_daily")
    op.drop_index("idx_ah_premium_rank", table_name="ah_premium_daily")
    op.drop_table("ah_premium_daily")


def downgrade() -> None:
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
        sa.Column("ha_ratio", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("ha_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("is_hk_connect", sa.Boolean(), nullable=False),
        sa.Column("connect_channels", sa.String(length=64), nullable=True),
        sa.Column("rate_date", sa.Date(), nullable=True),
        sa.Column("rate_source", sa.String(length=64), nullable=True),
        sa.Column("rate_fallback", sa.Boolean(), nullable=False),
        sa.Column("calc_status", sa.String(length=32), nullable=False),
        sa.Column("official_ah_ratio", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("official_ah_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("official_ha_ratio", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("official_ha_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("diff_from_official_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("diff_from_official_ha_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "a_ts_code", "hk_ts_code", name="uk_ah_premium_daily"),
    )
    op.create_index("idx_ah_premium_rank", "ah_premium_daily", ["trade_date", "ah_premium_pct"])
    op.create_index("idx_ah_premium_hk", "ah_premium_daily", ["hk_ts_code", "trade_date"])
    op.create_index("idx_ah_premium_a", "ah_premium_daily", ["a_ts_code", "trade_date"])
