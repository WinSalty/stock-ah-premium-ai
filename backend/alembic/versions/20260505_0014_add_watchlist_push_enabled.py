from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260505_0014"
down_revision = "20260505_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watchlist_stock",
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("watchlist_stock", "push_enabled")
