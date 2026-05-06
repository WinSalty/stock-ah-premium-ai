from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.market import AStockBasic
from app.services.data_query_service import DATA_QUERY_SPECS, DataQueryService


def test_data_query_filters_keyword_and_serializes_date() -> None:
    """确认统一查询支持关键词过滤和日期序列化。

    创建日期：2026-05-04
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                AStockBasic(
                    ts_code="000001.SZ",
                    name="平安银行",
                    industry="银行",
                    list_date=date(1991, 4, 3),
                ),
                AStockBasic(
                    ts_code="000002.SZ",
                    name="万科A",
                    industry="房地产",
                    list_date=date(1991, 1, 29),
                ),
            ]
        )
        db.commit()

        result = DataQueryService(db).query(
            dataset="a_stock_basic",
            keyword="银行",
            start_date=None,
            end_date=None,
            page=1,
            page_size=10,
        )

    assert result.total == 1
    assert result.rows[0]["ts_code"] == "000001.SZ"
    assert result.rows[0]["list_date"] == "1991-04-03"


def test_data_query_contains_unadjusted_backfill_datasets() -> None:
    """确认查询白名单包含不复权补数核验所需三张表。

    创建日期：2026-05-06
    author: sunshengxian
    """

    assert "tencent_unadjusted_daily_quote" in DATA_QUERY_SPECS
    assert "waterstock_fx_rate_daily" in DATA_QUERY_SPECS
    assert "historical_ah_unadjusted_backfill_run" in DATA_QUERY_SPECS
