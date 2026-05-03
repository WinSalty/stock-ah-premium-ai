from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.market import AHStockPair, FxRateDaily
from app.schemas.imports import ManualAHPairImportRow, ManualFxRateImportRow
from app.services.repository import UpsertRepository


class ManualImportService:
    """人工兜底数据导入服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = UpsertRepository(db)

    def import_ah_pairs(self, rows: list[ManualAHPairImportRow]) -> int:
        """导入人工 AH 配对。

        创建日期：2026-05-04
        author: sunshengxian
        """

        payload = [
            {
                "a_ts_code": row.a_ts_code.upper(),
                "hk_ts_code": row.hk_ts_code.upper(),
                "a_name": row.a_name,
                "hk_name": row.hk_name,
                "source": "MANUAL",
                "effective_start_date": row.effective_start_date,
                "effective_end_date": row.effective_end_date,
                "is_active": row.is_active,
            }
            for row in rows
        ]
        count = self.repository.upsert_many(AHStockPair, payload)
        self.db.commit()
        return count

    def import_fx_rates(self, rows: list[ManualFxRateImportRow]) -> int:
        """导入人工汇率。

        创建日期：2026-05-04
        author: sunshengxian
        """

        payload = []
        for row in rows:
            pair = row.rate_pair.upper().replace("/", "_")
            parts = pair.split("_", maxsplit=1)
            base_ccy = parts[0] if parts else ""
            quote_ccy = parts[1] if len(parts) > 1 else ""
            payload.append(
                {
                    "rate_pair": pair,
                    "rate_date": row.rate_date,
                    "base_ccy": base_ccy,
                    "quote_ccy": quote_ccy,
                    "mid_rate": row.mid_rate,
                    "bid_close": None,
                    "ask_close": None,
                    "source": row.source.upper(),
                    "raw_ts_code": row.raw_ts_code,
                    "is_cross_rate": False,
                }
            )
        count = self.repository.upsert_many(FxRateDaily, payload)
        self.db.commit()
        return count
