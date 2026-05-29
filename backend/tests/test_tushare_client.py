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


class FlakyPro(FakePro):
    """第一次请求模拟中转断流，第二次恢复正常。

    创建日期：2026-05-30
    author: sunshengxian
    """

    def query(self, api_name: str, fields: str = "", **kwargs: str) -> pd.DataFrame:
        """覆盖请求行为，用于验证客户端会自动重试可恢复网络错误。

        创建日期：2026-05-30
        author: sunshengxian
        """

        self.calls.append((api_name, fields, kwargs))
        if len(self.calls) == 1:
            raise RuntimeError("SSLEOFError: UNEXPECTED_EOF_WHILE_READING")
        return pd.DataFrame([{"ts_code": "000001.SZ", "close": 12.34}])


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
        tushare_token_file=None,
        tushare_api_url="https://tt.xiaodefa.cn/",
        tushare_timeout_seconds=12.0,
        tushare_request_interval_seconds=0,
    )

    result = TushareClient(settings).query(
        "stock_basic",
        params={"list_status": "L"},
        fields=["ts_code", "name", "close"],
    )

    assert pro_api_calls == [("local-token", 12.0)]
    assert fake_pro._DataApi__http_url == "https://tt.xiaodefa.cn"
    assert fake_pro.calls == [
        ("stock_basic", "ts_code,name,close", {"list_status": "L"}),
    ]
    assert result.fields == ["ts_code", "name", "close"]
    assert result.rows == [
        {"ts_code": "000001.SZ", "name": "平安银行", "close": 12.34},
        {"ts_code": "000002.SZ", "name": "万科A", "close": None},
    ]


def test_tushare_client_retries_retryable_network_error(monkeypatch) -> None:
    """确认中转服务断流类错误会重试，不会直接打断长批次同步。

    创建日期：2026-05-30
    author: sunshengxian
    """

    fake_pro = FlakyPro()
    pro_api_calls: list[tuple[str, float]] = []
    sleeps: list[float] = []

    def fake_pro_api(token: str, timeout: float) -> FlakyPro:
        pro_api_calls.append((token, timeout))
        return fake_pro

    monkeypatch.setattr("app.services.tushare_client.ts.pro_api", fake_pro_api)
    monkeypatch.setattr("app.services.tushare_client.sleep", lambda seconds: sleeps.append(seconds))
    settings = Settings(
        tushare_token="local-token",
        tushare_token_file=None,
        tushare_request_interval_seconds=0,
        tushare_request_max_attempts=2,
        tushare_retry_backoff_seconds=0.5,
    )

    result = TushareClient(settings).query(
        "daily",
        params={"trade_date": "20190801"},
        fields=["ts_code", "close"],
    )

    assert len(fake_pro.calls) == 2
    assert len(pro_api_calls) == 2
    assert sleeps == [0.5]
    assert result.rows == [{"ts_code": "000001.SZ", "close": 12.34}]


def test_tushare_token_file_overrides_env(tmp_path) -> None:
    """确认本机 token 文件优先级高于旧环境变量。

    创建日期：2026-05-04
    author: sunshengxian
    """

    token_file = tmp_path / "tushare-token.txt"
    token_file.write_text("file-token\n", encoding="utf-8")

    settings = Settings(tushare_token="env-token", tushare_token_file=token_file)

    assert settings.resolve_tushare_token() == "file-token"
