from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0008"
down_revision = "20260504_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_chat_session", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index(
        "idx_llm_chat_session_deleted_at",
        "llm_chat_session",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_llm_chat_session_deleted_at", table_name="llm_chat_session")
    op.drop_column("llm_chat_session", "deleted_at")
