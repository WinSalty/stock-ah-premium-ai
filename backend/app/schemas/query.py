from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class QueryColumn(BaseModel):
    """查询表格列定义。

    创建日期：2026-05-04
    author: sunshengxian
    """

    key: str
    label: str
    width: int | None = None


class QueryDatasetInfo(BaseModel):
    """可查询数据集信息。

    创建日期：2026-05-04
    author: sunshengxian
    """

    name: str
    label: str
    description: str
    date_field: str | None = None
    columns: list[QueryColumn]


class DataQueryResponse(BaseModel):
    """统一数据查询响应。

    创建日期：2026-05-04
    author: sunshengxian
    """

    dataset: str
    total: int
    page: int
    page_size: int
    columns: list[QueryColumn]
    rows: list[dict[str, Any]]


class DataQueryParams(BaseModel):
    """统一数据查询参数。

    创建日期：2026-05-04
    author: sunshengxian
    """

    dataset: str
    keyword: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    page: int = 1
    page_size: int = 30
