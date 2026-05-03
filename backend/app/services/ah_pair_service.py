from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models.market import AHStockPair
from app.services.repository import UpsertRepository


class AHPairService:
    """AH 股票配对维护服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = UpsertRepository(db)

    def upsert_from_official_rows(self, rows: list[dict[str, Any]]) -> int:
        """从官方 AH 比价结果维护配对表。

        创建日期：2026-05-04
        author: sunshengxian
        """

        pair_rows = []
        for row in rows:
            a_ts_code = row.get("a_ts_code")
            hk_ts_code = row.get("hk_ts_code")
            if not a_ts_code or not hk_ts_code:
                continue
            pair_rows.append(
                {
                    "a_ts_code": a_ts_code,
                    "hk_ts_code": hk_ts_code,
                    "a_name": row.get("a_name"),
                    "hk_name": row.get("hk_name"),
                    "source": "TUSHARE_STK_AH",
                    "effective_start_date": row.get("trade_date"),
                    "is_active": True,
                }
            )
        return self.repository.upsert_many(AHStockPair, pair_rows)
