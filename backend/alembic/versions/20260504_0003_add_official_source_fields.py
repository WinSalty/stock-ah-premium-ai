from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0003"
down_revision = "20260504_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "official_ah_comparison",
        sa.Column("is_realtime", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "official_ah_comparison",
        sa.Column(
            "data_source",
            sa.String(length=32),
            nullable=False,
            server_default="TUSHARE_OFFICIAL",
        ),
    )
    op.add_column(
        "official_ah_comparison",
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        """
        UPDATE official_ah_comparison
        SET
          is_realtime = 0,
          data_source = 'TUSHARE_OFFICIAL',
          source_updated_at = updated_at
        """
    )


def downgrade() -> None:
    op.drop_column("official_ah_comparison", "source_updated_at")
    op.drop_column("official_ah_comparison", "data_source")
    op.drop_column("official_ah_comparison", "is_realtime")
