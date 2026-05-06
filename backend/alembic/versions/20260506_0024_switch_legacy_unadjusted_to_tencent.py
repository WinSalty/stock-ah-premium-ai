from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260506_0024"
down_revision = "20260506_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 已部署环境可能已经创建过旧东方财富表；本迁移只做幂等改名和来源标记切换，
    # 避免重建表导致已经补入的不复权日线丢失。
    connection = op.get_bind()
    existing_tables = set(connection.dialect.get_table_names(connection))
    if "eastmoney_unadjusted_daily_quote" in existing_tables:
        op.rename_table("eastmoney_unadjusted_daily_quote", "tencent_unadjusted_daily_quote")
        existing_tables.remove("eastmoney_unadjusted_daily_quote")
        existing_tables.add("tencent_unadjusted_daily_quote")
    if "tencent_unadjusted_daily_quote" in existing_tables:
        columns = {
            column["name"]
            for column in connection.dialect.get_columns(connection, "tencent_unadjusted_daily_quote")
        }
        if "eastmoney_secid" in columns and "tencent_symbol" not in columns:
            op.alter_column(
                "tencent_unadjusted_daily_quote",
                "eastmoney_secid",
                new_column_name="tencent_symbol",
                existing_type=sa.String(length=32),
                existing_nullable=False,
                comment="腾讯 symbol，如 sh600036、hk03968",
            )
        _replace_data_source(connection, "EASTMONEY_KLINE", "TENCENT_KLINE")
    _replace_data_source(connection, "EASTMONEY_UNADJUSTED_BACKFILL", "TENCENT_UNADJUSTED_BACKFILL")
    _replace_sync_dataset(connection, "eastmoney_unadjusted_backfill", "tencent_unadjusted_backfill")


def downgrade() -> None:
    connection = op.get_bind()
    existing_tables = set(connection.dialect.get_table_names(connection))
    if "tencent_unadjusted_daily_quote" in existing_tables:
        columns = {
            column["name"]
            for column in connection.dialect.get_columns(connection, "tencent_unadjusted_daily_quote")
        }
        if "tencent_symbol" in columns and "eastmoney_secid" not in columns:
            op.alter_column(
                "tencent_unadjusted_daily_quote",
                "tencent_symbol",
                new_column_name="eastmoney_secid",
                existing_type=sa.String(length=32),
                existing_nullable=False,
                comment="东方财富 secid，如 1.600036、116.03968",
            )
        op.rename_table("tencent_unadjusted_daily_quote", "eastmoney_unadjusted_daily_quote")
    _replace_data_source(connection, "TENCENT_KLINE", "EASTMONEY_KLINE")
    _replace_data_source(connection, "TENCENT_UNADJUSTED_BACKFILL", "EASTMONEY_UNADJUSTED_BACKFILL")
    _replace_sync_dataset(connection, "tencent_unadjusted_backfill", "eastmoney_unadjusted_backfill")


def _replace_data_source(connection, old: str, new: str) -> None:
    # 来源标记参与追跑幂等判断，切换行情源后要把历史运行记录和主表来源同步改名。
    existing_tables = set(connection.dialect.get_table_names(connection))
    for table in (
        "tencent_unadjusted_daily_quote",
        "eastmoney_unadjusted_daily_quote",
        "historical_ah_unadjusted_backfill_run",
        "official_ah_comparison",
    ):
        if table in existing_tables:
            connection.execute(
                sa.text(f"UPDATE {table} SET data_source = :new WHERE data_source = :old"),
                {"new": new, "old": old},
            )


def _replace_sync_dataset(connection, old: str, new: str) -> None:
    # sync_run 只用于同步页展示执行历史，数据集名改为腾讯后同步替换旧记录，避免页面筛选混乱。
    if "sync_run" not in set(connection.dialect.get_table_names(connection)):
        return
    connection.execute(
        sa.text("UPDATE sync_run SET dataset = :new WHERE dataset = :old"),
        {"new": new, "old": old},
    )
