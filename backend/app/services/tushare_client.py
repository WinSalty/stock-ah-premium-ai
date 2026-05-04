from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any

import pandas as pd
import tushare as ts

from app.core.config import Settings


class TushareError(RuntimeError):
    """Tushare 调用异常。

    创建日期：2026-05-04
    author: sunshengxian
    """


@dataclass(frozen=True)
class TushareResult:
    """标准化后的 Tushare 返回数据。

    创建日期：2026-05-04
    author: sunshengxian
    """

    fields: list[str]
    rows: list[dict[str, Any]]


class TushareClient:
    """Tushare SDK API 客户端。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pro: Any | None = None
        self._token: str | None = None
        self._last_request_at = 0.0

    def query(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: list[str] | None = None,
    ) -> TushareResult:
        """通过 Tushare Python SDK 调用接口并转为字典行。

        创建日期：2026-05-04
        author: sunshengxian
        """

        token = self.settings.resolve_tushare_token()
        if not token:
            raise TushareError("Tushare Token 未配置，请设置 TUSHARE_TOKEN 或 TUSHARE_TOKEN_FILE")
        self._wait_for_rate_limit()
        try:
            frame = self._get_pro(token).query(
                api_name,
                fields=",".join(fields or []),
                **(params or {}),
            )
        except Exception as exc:
            raise TushareError(self._format_error(exc)) from exc
        if frame is None:
            return TushareResult(fields=fields or [], rows=[])
        if not isinstance(frame, pd.DataFrame):
            raise TushareError(f"Tushare SDK 返回格式异常：{type(frame).__name__}")
        result_fields = list(frame.columns)
        rows = (
            frame.astype(object)
            .where(pd.notna(frame), None)
            .to_dict(orient="records")
        )
        return TushareResult(fields=result_fields, rows=rows)

    def _get_pro(self, token: str) -> Any:
        if self._pro is not None and self._token == token:
            return self._pro
        pro = ts.pro_api(token, timeout=self.settings.tushare_timeout_seconds)
        # 中转版 Tushare 要求使用官方 SDK，并把 SDK 内部请求地址切到代理服务。
        pro._DataApi__http_url = self.settings.tushare_api_url.rstrip("/")
        self._pro = pro
        self._token = token
        return pro

    def _wait_for_rate_limit(self) -> None:
        interval = max(self.settings.tushare_request_interval_seconds, 0)
        if interval == 0:
            return
        elapsed = monotonic() - self._last_request_at
        if elapsed < interval:
            sleep(interval - elapsed)
        self._last_request_at = monotonic()

    def _format_error(self, exc: Exception) -> str:
        msg = str(exc) or "Tushare API 调用失败"
        if "权限" in msg or "permission" in msg.lower() or "2002" in msg:
            return f"Tushare 权限不足：{msg}"
        if "超时" in msg or "timeout" in msg.lower():
            return f"Tushare 调用超时，可能触发了中转服务冷却或网络较慢：{msg}"
        return msg
