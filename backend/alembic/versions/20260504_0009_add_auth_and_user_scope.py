from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0009"
down_revision = "20260504_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="USER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uk_app_user_username"),
    )
    op.create_table(
        "invitation_code",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("used_by_user_id", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uk_invitation_code"),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("user_id", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "llm_chat_session",
        sa.Column("user_id", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_constraint("uk_watchlist_stock_pair", "watchlist_stock", type_="unique")
    op.create_unique_constraint(
        "uk_watchlist_user_pair",
        "watchlist_stock",
        ["user_id", "a_ts_code", "hk_ts_code"],
    )
    op.create_index("idx_llm_chat_session_user", "llm_chat_session", ["user_id"])
    op.execute(
        """
        CREATE OR REPLACE VIEW v_watchlist_opportunity AS
        SELECT
          w.id AS watchlist_id,
          w.user_id,
          w.a_ts_code,
          w.hk_ts_code,
          COALESCE(w.display_name, p.a_name, w.a_ts_code) AS display_name,
          w.preferred_direction,
          w.target_premium_pct,
          w.holding_market,
          w.sort_order,
          w.note,
          p.trade_date,
          p.a_name,
          p.hk_name,
          p.ah_ratio,
          p.ah_premium_pct,
          p.ha_ratio,
          p.ha_premium_pct,
          CASE
            WHEN w.preferred_direction = 'AH' THEN p.ah_premium_pct
            ELSE p.ha_premium_pct
          END AS metric_premium_pct,
          CASE
            WHEN w.target_premium_pct IS NULL THEN NULL
            WHEN w.preferred_direction = 'AH' THEN w.target_premium_pct - p.ah_premium_pct
            ELSE w.target_premium_pct - p.ha_premium_pct
          END AS distance_to_target_pct,
          (
            SELECT ROUND(
              SUM(
                CASE
                  WHEN (
                    CASE WHEN w.preferred_direction = 'AH' THEN h.ah_premium ELSE h.ha_premium END
                  ) <= (
                    CASE WHEN w.preferred_direction = 'AH' THEN p.ah_premium_pct ELSE p.ha_premium_pct END
                  )
                  THEN 1 ELSE 0
                END
              ) * 100 / COUNT(*),
              8
            )
            FROM official_ah_comparison h
            WHERE h.a_ts_code = w.a_ts_code
              AND h.hk_ts_code = w.hk_ts_code
              AND h.trade_date <= p.trade_date
              AND (CASE WHEN w.preferred_direction = 'AH' THEN h.ah_premium ELSE h.ha_premium END) IS NOT NULL
              AND (
                SELECT COUNT(*)
                FROM official_ah_comparison h2
                WHERE h2.a_ts_code = w.a_ts_code
                  AND h2.hk_ts_code = w.hk_ts_code
                  AND h2.trade_date <= p.trade_date
                  AND h2.trade_date >= h.trade_date
                  AND (CASE WHEN w.preferred_direction = 'AH' THEN h2.ah_premium ELSE h2.ha_premium END) IS NOT NULL
              ) <= 60
          ) AS premium_percentile_60,
          p.is_hk_connect,
          p.connect_channels,
          p.data_source,
          p.source_updated_at,
          CASE
            WHEN p.trade_date IS NULL THEN 'DATA_ISSUE'
            WHEN p.is_hk_connect = 0 THEN 'NOT_CONNECT'
            WHEN w.target_premium_pct IS NULL THEN 'WATCH'
            WHEN (
              CASE
                WHEN w.preferred_direction = 'AH' THEN w.target_premium_pct - p.ah_premium_pct
                ELSE w.target_premium_pct - p.ha_premium_pct
              END
            ) <= 0 THEN 'REACHED'
            WHEN (
              CASE
                WHEN w.preferred_direction = 'AH' THEN w.target_premium_pct - p.ah_premium_pct
                ELSE w.target_premium_pct - p.ha_premium_pct
              END
            ) <= 3 THEN 'NEAR'
            ELSE 'WATCH'
          END AS opportunity_status,
          w.updated_at
        FROM watchlist_stock w
        LEFT JOIN v_latest_official_ah_premium p
          ON p.a_ts_code = w.a_ts_code AND p.hk_ts_code = w.hk_ts_code
        WHERE w.is_active = 1
        """
    )


def downgrade() -> None:
    op.drop_index("idx_llm_chat_session_user", table_name="llm_chat_session")
    op.drop_constraint("uk_watchlist_user_pair", "watchlist_stock", type_="unique")
    op.create_unique_constraint(
        "uk_watchlist_stock_pair",
        "watchlist_stock",
        ["a_ts_code", "hk_ts_code"],
    )
    op.drop_column("llm_chat_session", "user_id")
    op.drop_column("watchlist_stock", "user_id")
    op.drop_table("invitation_code")
    op.drop_table("app_user")
