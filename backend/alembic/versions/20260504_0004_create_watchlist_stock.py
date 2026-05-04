from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0004"
down_revision = "20260504_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_stock",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("a_ts_code", sa.String(length=16), nullable=False),
        sa.Column("hk_ts_code", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("preferred_direction", sa.String(length=8), nullable=False, server_default="HA"),
        sa.Column("target_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("holding_market", sa.String(length=16), nullable=False, server_default="UNKNOWN"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("a_ts_code", "hk_ts_code", name="uk_watchlist_stock_pair"),
    )
    op.create_index(
        "idx_watchlist_active_order",
        "watchlist_stock",
        ["is_active", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("idx_watchlist_active_order", table_name="watchlist_stock")
    op.drop_table("watchlist_stock")
