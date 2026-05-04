from __future__ import annotations

from sqlalchemy import UniqueConstraint

from alembic import op
from app.db.models.tushare_stock_data import TUSHARE_STOCK_TABLES

revision = "20260504_0005"
down_revision = "20260504_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in TUSHARE_STOCK_TABLES.values():
        unique_constraints = [
            constraint.copy()
            for constraint in list(table.constraints)
            if isinstance(constraint, UniqueConstraint)
        ]
        op.create_table(
            table.name,
            *[column.copy() for column in table.columns],
            *unique_constraints,
            comment=table.comment,
        )
        for index in table.indexes:
            op.create_index(
                index.name,
                table.name,
                [column.name for column in index.columns],
                unique=index.unique,
            )


def downgrade() -> None:
    for table in reversed(list(TUSHARE_STOCK_TABLES.values())):
        op.drop_table(table.name)
