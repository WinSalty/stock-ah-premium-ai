from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.db.base import Base


class UpsertRepository:
    """MySQL 幂等写入仓储。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_many(self, model: type[Base], rows: Sequence[dict[str, Any]]) -> int:
        """批量 upsert 数据。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if not rows:
            return 0
        statement = mysql_insert(model).values(list(rows))
        update_columns = {
            column.name: statement.inserted[column.name]
            for column in model.__table__.columns
            if not column.primary_key and column.name != "created_at"
        }
        self.db.execute(statement.on_duplicate_key_update(**update_columns))
        return len(rows)
