from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

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
    """Tushare HTTP API 客户端。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def query(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: list[str] | None = None,
    ) -> TushareResult:
        """调用 Tushare Pro API 并转为字典行。

        创建日期：2026-05-04
        author: sunshengxian
        """

        token = self.settings.resolve_tushare_token()
        if not token:
            raise TushareError("Tushare Token 未配置，请设置 TUSHARE_TOKEN 或 TUSHARE_TOKEN_FILE")
        payload = {
            "api_name": api_name,
            "token": token,
            "params": params or {},
            "fields": ",".join(fields or []),
        }
        with httpx.Client(timeout=self.settings.tushare_timeout_seconds) as client:
            response = client.post(self.settings.tushare_api_url, json=payload)
        response.raise_for_status()
        body = response.json()
        code = body.get("code")
        if code != 0:
            msg = body.get("msg") or "Tushare API 调用失败"
            if code == 2002:
                raise TushareError(f"Tushare 权限不足：{msg}")
            raise TushareError(str(msg))
        data = body.get("data") or {}
        result_fields = list(data.get("fields") or [])
        items = data.get("items") or []
        rows = [dict(zip(result_fields, item, strict=False)) for item in items]
        return TushareResult(fields=result_fields, rows=rows)
