from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260506_0021"
down_revision = "20260506_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pushplus_message_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("alert_event_id", sa.Integer(), nullable=True),
        sa.Column("recipient_type", sa.String(length=16), nullable=False),
        sa.Column("recipient_friend_id", sa.Integer(), nullable=True),
        sa.Column("recipient_name", sa.String(length=128), nullable=True),
        sa.Column("message_title", sa.String(length=128), nullable=False),
        sa.Column("message_content", sa.Text(), nullable=False),
        sa.Column("push_channel", sa.String(length=32), nullable=False, server_default="PUSHPLUS"),
        sa.Column("push_status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("push_message_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["alert_event_id"], ["alert_event.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_pushplus_message_log_user_created",
        "pushplus_message_log",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_pushplus_message_log_status_created",
        "pushplus_message_log",
        ["push_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_pushplus_message_log_status_created", table_name="pushplus_message_log")
    op.drop_index("idx_pushplus_message_log_user_created", table_name="pushplus_message_log")
    op.drop_table("pushplus_message_log")
