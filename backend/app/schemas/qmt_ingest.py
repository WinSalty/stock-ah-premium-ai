"""QMT 回流 ingest 接口请求/响应契约（机器对机器）。

业务意图：执行侧（QMT/Windows）盘后把本机 SQLite 的 qmt_* 当日数据，经
    `POST /api/internal/qmt/ingest` 幂等回流到信号侧。本模块定义请求/响应体——
    `records` 为「一行一记录」的列表，每条带 `table`（目标表）+ `data`（执行侧 mappers.*_to_row
    产出的列名字典，值已 JSON 友好化：Decimal→str、date/datetime→ISO、枚举→值、bool→0/1）。

设计取舍：执行侧 RemoteSyncJob 逐行 POST（records 长度=1），以复用其「单行失败保 synced=0、
    下轮重试」的幂等模型；本契约同时支持批量（records 长度 N），便于将来一次回流多行。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

# 允许回流的四张表（白名单，杜绝任意表写入）。与执行侧 storage.schema.QMT_TABLES 对齐。
QMT_INGEST_TABLES = ("qmt_trade", "qmt_order", "qmt_position_snapshot", "qmt_account_daily")


class QmtIngestRecord(BaseModel):
    """单条回流记录：目标表名 + 列名字典。"""

    table: str = Field(description="目标表（四张 qmt_* 之一，见 QMT_INGEST_TABLES）")
    data: dict[str, Any] = Field(description="列名→值字典（mappers.*_to_row 产出，JSON 友好化）")


class QmtIngestRequest(BaseModel):
    """回流请求体。account_id/trade_date 为可选审计字段，落库口径以每条 data 内的值为准。"""

    account_id: str | None = Field(default=None, description="账户（仅审计/日志，可选）")
    trade_date: date | None = Field(default=None, description="交易日（仅审计/日志，可选）")
    records: list[QmtIngestRecord] = Field(description="待回流记录列表（≥1 条）")


class QmtIngestResponse(BaseModel):
    """回流响应体：整批成功才返回（任一失败由接口以非 2xx + 明细报错，触发执行侧重试）。"""

    ok: bool = True
    total: int = Field(default=0, description="本次成功 upsert 的记录总数")
    by_table: dict[str, int] = Field(default_factory=dict, description="各表成功 upsert 行数")
