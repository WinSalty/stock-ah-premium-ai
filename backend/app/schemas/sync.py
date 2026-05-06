from __future__ import annotations

from datetime import date, datetime
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


class EastmoneyUnadjustedSyncBatchCreate(BaseModel):
    """东方财富不复权补数一键同步请求。

    创建日期：2026-05-06
    author: sunshengxian
    """

    start_date: date | None = None
    end_date: date | None = None


class EastmoneyUnadjustedSyncBatchResponse(BaseModel):
    """东方财富不复权补数一键同步响应。

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
