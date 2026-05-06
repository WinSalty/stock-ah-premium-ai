from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260506_0019"
down_revision = "20260505_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "a_price_alert_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "a_price_alert_operator",
            sa.String(length=8),
            nullable=False,
            server_default="GTE",
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("a_price_alert_target_price", sa.DECIMAL(20, 6), nullable=True),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "h_price_alert_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "h_price_alert_operator",
            sa.String(length=8),
            nullable=False,
            server_default="GTE",
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("h_price_alert_target_price", sa.DECIMAL(20, 6), nullable=True),
    )
    op.drop_column("watchlist_stock", "price_alert_target_price")
    op.drop_column("watchlist_stock", "price_alert_operator")
    op.drop_column("watchlist_stock", "price_alert_market")
    op.drop_column("watchlist_stock", "price_alert_enabled")


def downgrade() -> None:
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "price_alert_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "price_alert_market",
            sa.String(length=8),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "price_alert_operator",
            sa.String(length=8),
            nullable=False,
            server_default="GTE",
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("price_alert_target_price", sa.DECIMAL(20, 6), nullable=True),
    )
    op.drop_column("watchlist_stock", "h_price_alert_target_price")
    op.drop_column("watchlist_stock", "h_price_alert_operator")
    op.drop_column("watchlist_stock", "h_price_alert_enabled")
    op.drop_column("watchlist_stock", "a_price_alert_target_price")
    op.drop_column("watchlist_stock", "a_price_alert_operator")
    op.drop_column("watchlist_stock", "a_price_alert_enabled")
