from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0002"
down_revision = "20260504_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "official_ah_comparison",
        sa.Column("ha_comparison", sa.DECIMAL(20, 8), nullable=True),
    )
    op.add_column(
        "official_ah_comparison",
        sa.Column("ha_premium", sa.DECIMAL(20, 8), nullable=True),
    )
    op.add_column("ah_premium_daily", sa.Column("ha_ratio", sa.DECIMAL(20, 8), nullable=True))
    op.add_column("ah_premium_daily", sa.Column("ha_premium_pct", sa.DECIMAL(20, 8), nullable=True))
    op.add_column(
        "ah_premium_daily",
        sa.Column("official_ha_ratio", sa.DECIMAL(20, 8), nullable=True),
    )
    op.add_column(
        "ah_premium_daily",
        sa.Column("official_ha_premium_pct", sa.DECIMAL(20, 8), nullable=True),
    )
    op.add_column(
        "ah_premium_daily",
        sa.Column("diff_from_official_ha_pct", sa.DECIMAL(20, 8), nullable=True),
    )
    op.execute(
        """
        UPDATE official_ah_comparison
        SET
          ha_comparison = CASE
            WHEN ah_comparison IS NULL OR ah_comparison = 0 THEN NULL
            ELSE ROUND(1 / ah_comparison, 8)
          END,
          ha_premium = CASE
            WHEN ah_comparison IS NULL OR ah_comparison = 0 THEN NULL
            ELSE ROUND((1 / ah_comparison - 1) * 100, 8)
          END
        """
    )
    op.execute(
        """
        UPDATE ah_premium_daily
        SET
          ha_ratio = CASE
            WHEN ah_ratio IS NULL OR ah_ratio = 0 THEN NULL
            ELSE ROUND(1 / ah_ratio, 8)
          END,
          ha_premium_pct = CASE
            WHEN ah_ratio IS NULL OR ah_ratio = 0 THEN NULL
            ELSE ROUND((1 / ah_ratio - 1) * 100, 8)
          END,
          official_ha_ratio = CASE
            WHEN official_ah_ratio IS NULL OR official_ah_ratio = 0 THEN NULL
            ELSE ROUND(1 / official_ah_ratio, 8)
          END,
          official_ha_premium_pct = CASE
            WHEN official_ah_ratio IS NULL OR official_ah_ratio = 0 THEN NULL
            ELSE ROUND((1 / official_ah_ratio - 1) * 100, 8)
          END
        """
    )
    op.execute(
        """
        UPDATE ah_premium_daily
        SET diff_from_official_ha_pct = CASE
          WHEN ha_premium_pct IS NULL OR official_ha_premium_pct IS NULL THEN NULL
          ELSE ROUND(ha_premium_pct - official_ha_premium_pct, 8)
        END
        """
    )


def downgrade() -> None:
    op.drop_column("ah_premium_daily", "diff_from_official_ha_pct")
    op.drop_column("ah_premium_daily", "official_ha_premium_pct")
    op.drop_column("ah_premium_daily", "official_ha_ratio")
    op.drop_column("ah_premium_daily", "ha_premium_pct")
    op.drop_column("ah_premium_daily", "ha_ratio")
    op.drop_column("official_ah_comparison", "ha_premium")
    op.drop_column("official_ah_comparison", "ha_comparison")
