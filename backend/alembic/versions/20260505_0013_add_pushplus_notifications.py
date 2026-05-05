from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260505_0013"
down_revision = "20260505_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watchlist_stock",
        sa.Column("price_alert_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("price_alert_market", sa.String(length=8), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("price_alert_operator", sa.String(length=8), nullable=False, server_default="GTE"),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("price_alert_target_price", sa.DECIMAL(20, 6), nullable=True),
    )
    op.create_table(
        "pushplus_binding",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("friend_id", sa.Integer(), nullable=False),
        sa.Column("friend_token", sa.String(length=128), nullable=False),
        sa.Column("friend_nick_name", sa.String(length=128), nullable=True),
        sa.Column("friend_remark", sa.String(length=128), nullable=True),
        sa.Column("is_follow", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("bound_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uk_pushplus_binding_user"),
    )
    op.create_index("idx_pushplus_binding_active", "pushplus_binding", ["is_active"])
    op.create_table(
        "alert_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("metric_direction", sa.String(length=8), nullable=True),
        sa.Column("metric_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("target_premium_pct", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("price_alert_market", sa.String(length=8), nullable=True),
        sa.Column("price_alert_operator", sa.String(length=8), nullable=True),
        sa.Column("price_alert_ts_code", sa.String(length=16), nullable=True),
        sa.Column("last_price", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("target_price", sa.DECIMAL(20, 6), nullable=True),
        sa.Column("message_title", sa.String(length=128), nullable=False),
        sa.Column("message_content", sa.Text(), nullable=False),
        sa.Column("push_channel", sa.String(length=32), nullable=False, server_default="PUSHPLUS"),
        sa.Column("push_status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("push_message_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlist_stock.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uk_alert_event_dedupe"),
    )
    op.create_index("idx_alert_event_user_day", "alert_event", ["user_id", "trading_day"])
    op.create_index("idx_alert_event_watchlist", "alert_event", ["watchlist_id"])


def downgrade() -> None:
    op.drop_index("idx_alert_event_watchlist", table_name="alert_event")
    op.drop_index("idx_alert_event_user_day", table_name="alert_event")
    op.drop_table("alert_event")
    op.drop_index("idx_pushplus_binding_active", table_name="pushplus_binding")
    op.drop_table("pushplus_binding")
    op.drop_column("watchlist_stock", "price_alert_target_price")
    op.drop_column("watchlist_stock", "price_alert_operator")
    op.drop_column("watchlist_stock", "price_alert_market")
    op.drop_column("watchlist_stock", "price_alert_enabled")
