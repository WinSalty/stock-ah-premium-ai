from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.eastmoney_kline_service import EastmoneyKlineService


def test_eastmoney_secid_conversion() -> None:
    """确认项目标准代码可转换为东方财富 secid。

    创建日期：2026-05-06
    author: sunshengxian
    """

    service = EastmoneyKlineService(timeout_seconds=1, request_interval_seconds=0)

    assert service.to_eastmoney_secid("600036.SH") == "1.600036"
    assert service.to_eastmoney_secid("000001.SZ") == "0.000001"
    assert service.to_eastmoney_secid("03968.HK") == "116.03968"


def test_parse_unadjusted_kline_line() -> None:
    """确认东方财富 klines 单行能解析成不复权日线结构。

    创建日期：2026-05-06
    author: sunshengxian
    """

    service = EastmoneyKlineService(timeout_seconds=1, request_interval_seconds=0)
    row = service._parse_kline_line(
        "A",
        "600036.SH",
        "1.600036",
        "2025-08-11,40.1,40.2,40.8,39.9,1000,2000,1.2,0.5,0.2,0.8",
    )

    assert row is not None
    assert row.trade_date == date(2025, 8, 11)
    assert row.close == Decimal("40.2")
    assert row.to_model_row()["adjust_type"] == "NONE"
