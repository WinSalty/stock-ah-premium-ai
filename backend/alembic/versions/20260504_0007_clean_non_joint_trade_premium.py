from __future__ import annotations

from alembic import op

revision = "20260504_0007"
down_revision = "20260504_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE o
        FROM official_ah_comparison o
        LEFT JOIN a_trade_calendar a
          ON a.exchange = 'SSE'
         AND a.cal_date = o.trade_date
         AND a.is_open = 1
        LEFT JOIN hk_trade_calendar hkc
          ON hkc.cal_date = o.trade_date
         AND hkc.is_open = 1
        WHERE a.cal_date IS NULL
           OR hkc.cal_date IS NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_watchlist_opportunity AS
        SELECT
          w.id AS watchlist_id,
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
                    CASE WHEN w.preferred_direction = 'AH'
                      THEN hist.ah_premium ELSE hist.ha_premium END
                  ) <= (
                    CASE WHEN w.preferred_direction = 'AH'
                      THEN p.ah_premium_pct ELSE p.ha_premium_pct END
                  )
                  THEN 1 ELSE 0
                END
              ) * 100 / COUNT(*),
              8
            )
            FROM official_ah_comparison hist
            WHERE hist.a_ts_code = w.a_ts_code
              AND hist.hk_ts_code = w.hk_ts_code
              AND hist.trade_date <= p.trade_date
              AND (
                CASE WHEN w.preferred_direction = 'AH'
                  THEN hist.ah_premium ELSE hist.ha_premium END
              ) IS NOT NULL
              AND (
                SELECT COUNT(*)
                FROM official_ah_comparison hist2
                WHERE hist2.a_ts_code = w.a_ts_code
                  AND hist2.hk_ts_code = w.hk_ts_code
                  AND hist2.trade_date <= p.trade_date
                  AND hist2.trade_date >= hist.trade_date
                  AND (
                    CASE WHEN w.preferred_direction = 'AH'
                      THEN hist2.ah_premium ELSE hist2.ha_premium END
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


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW v_watchlist_opportunity AS
        SELECT
          w.id AS watchlist_id,
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
                    CASE WHEN w.preferred_direction = 'AH'
                      THEN p.ah_premium_pct ELSE p.ha_premium_pct END
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
              AND h.trade_date >= DATE_SUB(p.trade_date, INTERVAL 120 DAY)
              AND (
                CASE WHEN w.preferred_direction = 'AH' THEN h.ah_premium ELSE h.ha_premium END
              ) IS NOT NULL
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
