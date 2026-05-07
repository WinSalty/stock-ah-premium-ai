from __future__ import annotations

from alembic import op

revision = "20260507_0025"
down_revision = "20260506_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 腾讯不复权补数早期只写代码和比价，未写 A/H 名称；数据查询页按中文名搜索时
    # 只匹配 a_name/hk_name，因此这里用 AH 配对表优先回填，保证已补历史行能被名称检索。
    op.execute(
        """
        UPDATE official_ah_comparison o
        JOIN ah_stock_pair p
          ON p.a_ts_code = o.a_ts_code
         AND p.hk_ts_code = o.hk_ts_code
        SET
          o.a_name = COALESCE(NULLIF(o.a_name, ''), p.a_name),
          o.hk_name = COALESCE(NULLIF(o.hk_name, ''), p.hk_name)
        WHERE o.data_source = 'TENCENT_UNADJUSTED_BACKFILL'
          AND (o.a_name IS NULL OR o.a_name = '' OR o.hk_name IS NULL OR o.hk_name = '')
          AND (p.a_name IS NOT NULL OR p.hk_name IS NOT NULL)
        """
    )
    # 个别环境可能还没有维护 ah_stock_pair 名称，但 Tushare 官方行已经带名称；
    # 再从同股票对最近的非空官方主表记录兜底回填，重跑迁移时不会覆盖已有非空名称。
    op.execute(
        """
        UPDATE official_ah_comparison o
        JOIN (
          SELECT n.a_ts_code, n.hk_ts_code, n.a_name, n.hk_name
          FROM official_ah_comparison n
          JOIN (
            SELECT a_ts_code, hk_ts_code, MAX(trade_date) AS trade_date
            FROM official_ah_comparison
            WHERE data_source <> 'TENCENT_UNADJUSTED_BACKFILL'
              AND (a_name IS NOT NULL OR hk_name IS NOT NULL)
            GROUP BY a_ts_code, hk_ts_code
          ) latest
            ON latest.a_ts_code = n.a_ts_code
           AND latest.hk_ts_code = n.hk_ts_code
           AND latest.trade_date = n.trade_date
          WHERE n.data_source <> 'TENCENT_UNADJUSTED_BACKFILL'
            AND (n.a_name IS NOT NULL OR n.hk_name IS NOT NULL)
        ) names
          ON names.a_ts_code = o.a_ts_code
         AND names.hk_ts_code = o.hk_ts_code
        SET
          o.a_name = COALESCE(NULLIF(o.a_name, ''), names.a_name),
          o.hk_name = COALESCE(NULLIF(o.hk_name, ''), names.hk_name)
        WHERE o.data_source = 'TENCENT_UNADJUSTED_BACKFILL'
          AND (o.a_name IS NULL OR o.a_name = '' OR o.hk_name IS NULL OR o.hk_name = '')
        """
    )


def downgrade() -> None:
    # 这是数据修复迁移，回退时不清空名称，避免误删迁移后由同步任务写入或人工维护的有效名称。
    pass
