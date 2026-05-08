from __future__ import annotations

from datetime import date
from unittest.mock import Mock

from app.services.tushare_stock_research_fetcher import (
    FINANCIAL_STATEMENT_PACKAGE,
    TushareStockResearchFetcher,
)


class FakeClient:
    """按接口名返回港股财务数据的测试替身。

    创建日期：2026-05-08
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], list[str]]] = []

    def query(self, api_name: str, params: dict[str, object], fields: list[str]):
        self.calls.append((api_name, params, fields))
        rows = {
            "hk_fina_indicator": [
                {
                    "ts_code": "02380.HK",
                    "name": "中国电力",
                    "end_date": "20251231",
                    "report_type": "2025年年报",
                    "std_report_date": 20251231,
                    "operate_income": 49029459000,
                    "holder_profit": 2910226000,
                    "roe_avg": 5.1266,
                    "currency": "HKD",
                }
            ],
            "hk_income": [
                {
                    "ts_code": "02380.HK",
                    "end_date": "20251231",
                    "name": "中国电力",
                    "ind_name": "营业收入",
                    "ind_value": 49029459000,
                }
            ],
            "hk_balancesheet": [
                {
                    "ts_code": "02380.HK",
                    "end_date": "20251231",
                    "name": "中国电力",
                    "ind_name": "总资产",
                    "ind_value": 367555599000,
                }
            ],
            "hk_cashflow": [
                {
                    "ts_code": "02380.HK",
                    "end_date": "20251231",
                    "name": "中国电力",
                    "ind_name": "经营活动产生的现金流量净额",
                    "ind_value": 18518055000,
                }
            ],
        }[api_name]
        return type("Result", (), {"rows": rows})()


def test_fetcher_normalizes_hk_financial_specs() -> None:
    """确认港股财务包调用 4 个白名单接口并标准化为本地字段。

    创建日期：2026-05-08
    author: sunshengxian
    """

    client = FakeClient()
    fetcher = TushareStockResearchFetcher(Mock(), client=client)  # type: ignore[arg-type]
    specs = fetcher.hk_specs[FINANCIAL_STATEMENT_PACKAGE]
    normalized_rows = []
    for spec in specs:
        params = fetcher._params_for_spec("02380.HK", spec, date(2026, 5, 8))  # noqa: SLF001
        result = client.query(spec.api_name, params=params, fields=list(spec.fields))
        normalized_rows.extend(
            fetcher._normalize_row(spec, row)  # noqa: SLF001
            for row in result.rows
        )

    indicator = next(row for row in normalized_rows if "operate_income" in row)
    statement_types = {
        row["statement_type"]
        for row in normalized_rows
        if row.get("statement_type")
    }
    assert indicator["end_date"] == date(2025, 12, 31)
    assert indicator["std_report_date"] == date(2025, 12, 31)
    assert indicator["operate_income"] is not None
    assert statement_types == {"INCOME", "BALANCE", "CASHFLOW"}
    assert [call[0] for call in client.calls] == [
        "hk_fina_indicator",
        "hk_income",
        "hk_balancesheet",
        "hk_cashflow",
    ]
