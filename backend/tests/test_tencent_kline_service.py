from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.tencent_kline_service import TencentKlineService


def test_tencent_symbol_conversion() -> None:
    """确认项目标准代码可转换为腾讯 symbol。

    创建日期：2026-05-06
    author: sunshengxian
    """

    service = TencentKlineService(timeout_seconds=1, request_interval_seconds=0)

    assert service.to_tencent_symbol("600036.SH") == "sh600036"
    assert service.to_tencent_symbol("000001.SZ") == "sz000001"
    assert service.to_tencent_symbol("03968.HK") == "hk03968"


def test_parse_tencent_line() -> None:
    """确认腾讯日线行按不复权日线口径解析并保留来源标记。

    创建日期：2026-05-06
    author: sunshengxian
    """

    service = TencentKlineService(timeout_seconds=1, request_interval_seconds=0)
    row = service._parse_line(
        "HK",
        "03968.HK",
        "hk03968",
        ["2025-08-11", "50.800", "49.780", "50.800", "49.560", "14293571.000"],
    )

    assert row is not None
    assert row.market == "HK"
    assert row.trade_date == date(2025, 8, 11)
    assert row.close == Decimal("49.780")
    assert row.to_model_row()["data_source"] == "TENCENT_KLINE"
    assert "hk03968" in row.raw_payload_json


def test_split_year_ranges() -> None:
    """确认长周期同步按自然年分段，避免腾讯港股接口单次条数截断。

    创建日期：2026-05-06
    author: sunshengxian
    """

    service = TencentKlineService(timeout_seconds=1, request_interval_seconds=0)

    assert service._split_year_ranges(date(2024, 11, 3), date(2026, 5, 6)) == [
        (date(2024, 11, 3), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 5, 6)),
    ]
