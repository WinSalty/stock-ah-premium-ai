from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260505_0015"
down_revision = "20260505_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("overview_chart_settings_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_user", "overview_chart_settings_json")
