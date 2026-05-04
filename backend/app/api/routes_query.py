from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import require_permission
from app.db.session import get_db
from app.schemas.query import DataQueryResponse, QueryDatasetInfo
from app.services.data_query_service import DataQueryService

router = APIRouter(dependencies=[Depends(require_permission("query"))])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/query/datasets", response_model=list[QueryDatasetInfo])
def list_query_datasets(db: DbSession) -> list[QueryDatasetInfo]:
    """获取可查询数据集。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return DataQueryService(db).list_datasets()


@router.get("/query/rows", response_model=DataQueryResponse)
def query_rows(
    db: DbSession,
    dataset: Annotated[str, Query(min_length=1)],
    keyword: Annotated[str | None, Query()] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 30,
) -> DataQueryResponse:
    """查询指定数据集的同步数据。

    创建日期：2026-05-04
    author: sunshengxian
    """

    try:
        return DataQueryService(db).query(dataset, keyword, start_date, end_date, page, page_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
