from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


class DatasetInfo(BaseModel):
    """可同步数据集信息。

    创建日期：2026-05-04
    author: sunshengxian
    """

    name: str
    label: str
    description: str
    supports_date_range: bool
    supports_incremental: bool
    supports_full_sync: bool
    default_full_start_date: str | None
    sync_strategy: str


class SyncMode(StrEnum):
    """同步模式。

    创建日期：2026-05-04
    author: sunshengxian
    """

    MANUAL = "manual"
    INCREMENTAL = "incremental"
    FULL = "full"


class DividendReinvestmentSyncMode(StrEnum):
    """分红再投入专用同步模式。

    创建日期：2026-06-02
    author: sunshengxian
    """

    INCREMENTAL = "incremental"
    FULL = "full"
    CALCULATE_ONLY = "calculate_only"


class SyncRunCreate(BaseModel):
    """创建同步任务请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    dataset: str
    mode: SyncMode = SyncMode.MANUAL
    start_date: date | None = None
    end_date: date | None = None
    trade_date: date | None = None
    ts_code: str | None = None
    type: str | None = Field(default=None, description="沪深港通类型")


class SyncBatchCreate(BaseModel):
    """创建一键同步请求。

    创建日期：2026-05-04
    author: sunshengxian
    """

    mode: SyncMode = SyncMode.INCREMENTAL
    start_date: date | None = None
    end_date: date | None = None


class TencentUnadjustedSyncBatchCreate(BaseModel):
    """腾讯不复权补数一键同步请求。

    创建日期：2026-05-06
    author: sunshengxian
    """

    start_date: date | None = None
    end_date: date | None = None


class DividendReinvestmentSyncBatchCreate(BaseModel):
    """分红再投入数据落地一键同步请求。

    创建日期：2026-05-29
    author: sunshengxian
    """

    mode: DividendReinvestmentSyncMode = DividendReinvestmentSyncMode.INCREMENTAL
    start_date: date | None = None
    end_date: date | None = None
    initial_amount: Decimal | None = Field(
        default=None,
        gt=0,
        description="每只股票模拟初始投入金额",
    )
    cash_div_field: str = Field(
        default="cash_div_tax",
        description="现金分红口径，支持 cash_div_tax 或 cash_div",
    )
    supplement_dividend_by_stock: bool = Field(
        default=False,
        description="是否按候选股票逐只补齐历史分红，适合修复 ex_date 全市场回补缺口",
    )
    supplement_financial_indicator_by_stock: bool = Field(
        default=False,
        description="是否按候选股票逐只补齐 A 股财务指标，适合修复 ROE 覆盖不足",
    )


class TencentUnadjustedSyncBatchResponse(BaseModel):
    """腾讯不复权补数一键同步响应。

    创建日期：2026-05-06
    author: sunshengxian
    """

    start_date: date
    end_date: date
    pending_pair_count: int
    quote_rows: int
    backfill_pair_count: int
    candidate_rows: int
    inserted_rows: int
    skipped_existing_rows: int
    replaced_baidu_rows: int
    skipped_invalid_rows: int


class SyncRunResponse(OrmModel):
    """同步任务响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    id: int
    dataset: str
    params_json: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    row_count: int
    error_message: str | None
