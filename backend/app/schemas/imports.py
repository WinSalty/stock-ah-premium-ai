from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ManualAHPairImportRow(BaseModel):
    """人工 AH 配对导入行。

    创建日期：2026-05-04
    author: sunshengxian
    """

    a_ts_code: str
    hk_ts_code: str
    a_name: str | None = None
    hk_name: str | None = None
    effective_start_date: date | None = None
    effective_end_date: date | None = None
    is_active: bool = True


class ManualAHPairImportRequest(BaseModel):
    """人工 AH 配对导入请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    rows: list[ManualAHPairImportRow] = Field(min_length=1)


class ManualFxRateImportRow(BaseModel):
    """人工汇率导入行。

    创建日期：2026-05-04
    author: sunshengxian
    """

    rate_pair: str = Field(description="例如 HKD_CNY、USD_CNH、USD_HKD")
    rate_date: date
    mid_rate: Decimal
    source: str = "MANUAL"
    raw_ts_code: str | None = None


class ManualFxRateImportRequest(BaseModel):
    """人工汇率导入请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    rows: list[ManualFxRateImportRow] = Field(min_length=1)


class ImportResponse(BaseModel):
    """导入响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    imported_rows: int
