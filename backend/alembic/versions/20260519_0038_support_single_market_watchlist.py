from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260519_0038"
down_revision = "20260510_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 自选身份从固定 A/H 配对扩展为 PAIR、A_ONLY、H_ONLY 三类；旧数据全部回填为 PAIR，
    # target_key 作为统一唯一键，避免 MySQL 唯一索引遇到 NULL 单侧代码时无法去重。
    op.add_column(
        "watchlist_stock",
        sa.Column(
            "target_type",
            sa.String(length=16),
            nullable=False,
            server_default="PAIR",
        ),
    )
    op.add_column(
        "watchlist_stock",
        sa.Column("target_key", sa.String(length=40), nullable=True),
    )
    op.execute(
        """
        UPDATE watchlist_stock
        SET target_type = 'PAIR',
            target_key = CONCAT(a_ts_code, '|', hk_ts_code)
        WHERE target_key IS NULL OR target_key = ''
        """
    )
    op.alter_column(
        "watchlist_stock",
        "target_key",
        existing_type=sa.String(length=40),
        nullable=False,
    )
    op.drop_constraint("uk_watchlist_user_pair", "watchlist_stock", type_="unique")
    op.create_unique_constraint(
        "uk_watchlist_user_target",
        "watchlist_stock",
        ["user_id", "target_type", "target_key"],
    )
    op.create_index("idx_watchlist_a_code", "watchlist_stock", ["a_ts_code"])
    op.create_index("idx_watchlist_hk_code", "watchlist_stock", ["hk_ts_code"])
    op.alter_column(
        "watchlist_stock",
        "a_ts_code",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.alter_column(
        "watchlist_stock",
        "hk_ts_code",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    # 自选机会只读视图仍服务 A/H 配对机会判断；单 A/单 H 关注只进入股价提醒，
    # 因此视图显式过滤 PAIR，避免 LLM 或只读账号把单股关注误解释为价差机会。
    op.execute(
        """
        CREATE OR REPLACE VIEW v_watchlist_opportunity AS
        SELECT
          w.id AS watchlist_id,
          w.user_id,
          w.target_type,
          w.target_key,
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
                    CASE
                      WHEN w.preferred_direction = 'AH' THEN p.ah_premium_pct
                      ELSE p.ha_premium_pct
                    END
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
              AND (
                CASE
                  WHEN w.preferred_direction = 'AH' THEN h.ah_premium
                  ELSE h.ha_premium
                END
              ) IS NOT NULL
              AND (
                SELECT COUNT(*)
                FROM official_ah_comparison h2
                WHERE h2.a_ts_code = w.a_ts_code
                  AND h2.hk_ts_code = w.hk_ts_code
                  AND h2.trade_date <= p.trade_date
                  AND h2.trade_date >= h.trade_date
                  AND (
                    CASE
                      WHEN w.preferred_direction = 'AH' THEN h2.ah_premium
                      ELSE h2.ha_premium
                    END
                  ) IS NOT NULL
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
          AND w.target_type = 'PAIR'
          AND w.a_ts_code IS NOT NULL
          AND w.hk_ts_code IS NOT NULL
        """
    )


def downgrade() -> None:
    # 回滚到旧配对模型时无法保留单 A/单 H 关注；先删除单侧关注，再恢复非空配对唯一键。
    op.execute("DELETE FROM watchlist_stock WHERE target_type <> 'PAIR'")
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
                    CASE
                      WHEN w.preferred_direction = 'AH' THEN p.ah_premium_pct
                      ELSE p.ha_premium_pct
                    END
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
              AND (
                CASE
                  WHEN w.preferred_direction = 'AH' THEN h.ah_premium
                  ELSE h.ha_premium
                END
              ) IS NOT NULL
              AND (
                SELECT COUNT(*)
                FROM official_ah_comparison h2
                WHERE h2.a_ts_code = w.a_ts_code
                  AND h2.hk_ts_code = w.hk_ts_code
                  AND h2.trade_date <= p.trade_date
                  AND h2.trade_date >= h.trade_date
                  AND (
                    CASE
                      WHEN w.preferred_direction = 'AH' THEN h2.ah_premium
                      ELSE h2.ha_premium
                    END
                  ) IS NOT NULL
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
    op.alter_column(
        "watchlist_stock",
        "a_ts_code",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.alter_column(
        "watchlist_stock",
        "hk_ts_code",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.drop_index("idx_watchlist_hk_code", table_name="watchlist_stock")
    op.drop_index("idx_watchlist_a_code", table_name="watchlist_stock")
    op.drop_constraint("uk_watchlist_user_target", "watchlist_stock", type_="unique")
    op.create_unique_constraint(
        "uk_watchlist_user_pair",
        "watchlist_stock",
        ["user_id", "a_ts_code", "hk_ts_code"],
    )
    op.drop_column("watchlist_stock", "target_key")
    op.drop_column("watchlist_stock", "target_type")
