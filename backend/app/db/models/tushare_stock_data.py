from __future__ import annotations

from sqlalchemy import (
    DECIMAL,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

from app.db.base import Base
from app.services.tushare_stock_catalog import TUSHARE_STOCK_DATASETS

_TYPE_MAP = {
    "INT": Integer,
    "DATE": Date,
    "DATETIME": DateTime,
    "TEXT": Text,
}


def _column_type(sql_type: str):
    if sql_type == "DECIMAL(30,10)":
        return DECIMAL(30, 10)
    if sql_type.startswith("VARCHAR"):
        length = int(sql_type.removeprefix("VARCHAR(").removesuffix(")"))
        return String(length)
    return _TYPE_MAP[sql_type]


def _build_table(spec, metadata: MetaData) -> Table:
    columns = [
        Column("id", Integer, primary_key=True, autoincrement=True, comment="本地自增主键"),
        Column("sync_key", String(64), nullable=False, comment="按接口关键字段生成的同步幂等键"),
    ]
    for field in spec.fields:
        columns.append(
            Column(
                field.name,
                _column_type(field.sql_type),
                nullable=True,
                comment=field.description[:900],
            )
        )
    columns.extend(
        [
            Column(
                "created_at",
                DateTime,
                nullable=False,
                server_default=func.now(),
                comment="本地创建时间",
            ),
            Column(
                "updated_at",
                DateTime,
                nullable=False,
                server_default=func.now(),
                onupdate=func.now(),
                comment="本地更新时间",
            ),
        ]
    )
    return Table(
        spec.table_name,
        metadata,
        *columns,
        UniqueConstraint("sync_key", name=f"uk_{spec.table_name}_sync_key"),
        Index(f"idx_{spec.table_name}_sync_key", "sync_key"),
        comment=f"Tushare股票数据-{spec.menu_name}；接口 {spec.api_name}",
    )


TUSHARE_STOCK_TABLES = {
    spec.dataset_name: _build_table(spec, Base.metadata) for spec in TUSHARE_STOCK_DATASETS
}
