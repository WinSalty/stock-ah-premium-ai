from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260506_0020"
down_revision = "20260506_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_call_metric",
        sa.Column("conversation_title", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "llm_call_metric",
        sa.Column("user_name", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_call_metric", "user_name")
    op.drop_column("llm_call_metric", "conversation_title")
