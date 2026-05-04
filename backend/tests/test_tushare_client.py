from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.services.tushare_client import TushareClient


class FakePro:
    """测试用 Tushare Pro SDK 对象。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self) -> None:
        self._DataApi__http_url = ""
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def query(self, api_name: str, fields: str = "", **kwargs: str) -> pd.DataFrame:
        self.calls.append((api_name, fields, kwargs))
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.34},
                {"ts_code": "000002.SZ", "name": "万科A", "close": None},
            ]
        )


def test_tushare_client_uses_sdk_proxy(monkeypatch) -> None:
    """确认 Tushare 客户端按中转 SDK 方式调用。

    创建日期：2026-05-04
    author: sunshengxian
    """

    fake_pro = FakePro()
    pro_api_calls: list[tuple[str, float]] = []

    def fake_pro_api(token: str, timeout: float) -> FakePro:
        pro_api_calls.append((token, timeout))
        return fake_pro

    monkeypatch.setattr("app.services.tushare_client.ts.pro_api", fake_pro_api)
    settings = Settings(
        tushare_token="local-token",
        tushare_api_url="http://tsy.xiaodefa.cn/",
        tushare_timeout_seconds=12.0,
        tushare_request_interval_seconds=0,
    )

    result = TushareClient(settings).query(
        "stock_basic",
        params={"list_status": "L"},
        fields=["ts_code", "name", "close"],
    )

    assert pro_api_calls == [("local-token", 12.0)]
    assert fake_pro._DataApi__http_url == "http://tsy.xiaodefa.cn"
    assert fake_pro.calls == [
        ("stock_basic", "ts_code,name,close", {"list_status": "L"}),
    ]
    assert result.fields == ["ts_code", "name", "close"]
    assert result.rows == [
        {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.34},
        {"ts_code": "000002.SZ", "name": "万科A", "close": None},
    ]
