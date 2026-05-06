from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.date_utils import parse_tushare_date
from app.services.decimal_utils import to_decimal

logger = logging.getLogger(__name__)

TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
TENCENT_MAX_ROWS_PER_REQUEST = 1000
TENCENT_DATA_SOURCE = "TENCENT_KLINE"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 0.8
DEFAULT_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://gu.qq.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


@dataclass(frozen=True)
class TencentKlineRow:
    """腾讯未复权日 K 单行结构。

    创建日期：2026-05-06
    author: sunshengxian
    """

    market: str
    ts_code: str
    tencent_symbol: str
    trade_date: date
    open: Decimal | None
    close: Decimal
    high: Decimal | None
    low: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    amplitude: Decimal | None
    pct_chg: Decimal | None
    change_amount: Decimal | None
    turnover_rate: Decimal | None
    raw_payload_json: str

    def to_model_row(self) -> dict[str, Any]:
        """转为数据库 upsert 行，固定写入不复权口径和腾讯来源标记。

        创建日期：2026-05-06
        author: sunshengxian
        """

        return {
            "market": self.market,
            "ts_code": self.ts_code,
            "tencent_symbol": self.tencent_symbol,
            "trade_date": self.trade_date,
            "open": self.open,
            "close": self.close,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "amount": self.amount,
            "amplitude": self.amplitude,
            "pct_chg": self.pct_chg,
            "change_amount": self.change_amount,
            "turnover_rate": self.turnover_rate,
            "adjust_type": "NONE",
            "data_source": TENCENT_DATA_SOURCE,
            "raw_payload_json": self.raw_payload_json,
        }


class TencentKlineService:
    """腾讯历史 K 线客户端。

    创建日期：2026-05-06
    author: sunshengxian
    """

    def __init__(
        self,
        timeout_seconds: float | None = None,
        request_interval_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.timeout_seconds = timeout_seconds or min(
            max(settings.tushare_timeout_seconds, 1.0),
            DEFAULT_TIMEOUT_SECONDS,
        )
        self.request_interval_seconds = (
            request_interval_seconds
            if request_interval_seconds is not None
            else DEFAULT_REQUEST_INTERVAL_SECONDS
        )
        self._last_request_time = 0.0

    def fetch_unadjusted_daily(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
    ) -> list[TencentKlineRow]:
        """拉取单只股票腾讯不复权日线。

        创建日期：2026-05-06
        author: sunshengxian
        """

        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        market = self.to_market(ts_code)
        symbol = self.to_tencent_symbol(ts_code)
        rows_by_date: dict[date, TencentKlineRow] = {}
        for period_start, period_end in self._split_year_ranges(start_date, end_date):
            # 腾讯日线接口单次返回行数有限，按自然年切段后再按日期去重，
            # 避免 2018 年以来长窗口被截断；重跑时同一交易日仍只保留一行。
            for raw_line in self._request_lines(symbol, period_start, period_end):
                row = self._parse_line(market, ts_code.upper(), symbol, raw_line)
                if row is not None and start_date <= row.trade_date <= end_date:
                    rows_by_date[row.trade_date] = row
        if not rows_by_date:
            raise RuntimeError(f"腾讯不复权日线响应为空：{ts_code}")
        return [rows_by_date[item] for item in sorted(rows_by_date)]

    def to_tencent_symbol(self, ts_code: str) -> str:
        """将项目标准代码转换为腾讯行情 symbol。

        创建日期：2026-05-06
        author: sunshengxian
        """

        normalized = ts_code.strip().upper()
        code = normalized.split(".", maxsplit=1)[0]
        if normalized.endswith(".SH"):
            return f"sh{code}"
        if normalized.endswith(".SZ"):
            return f"sz{code}"
        if normalized.endswith(".HK"):
            return f"hk{code.zfill(5)}"
        raise ValueError(f"不支持的腾讯行情股票代码：{ts_code}")

    def to_market(self, ts_code: str) -> str:
        """识别 A 股或港股市场，用于独立表唯一键和查询过滤。

        创建日期：2026-05-06
        author: sunshengxian
        """

        normalized = ts_code.strip().upper()
        if normalized.endswith((".SH", ".SZ")):
            return "A"
        if normalized.endswith(".HK"):
            return "HK"
        raise ValueError(f"不支持的股票代码市场：{ts_code}")

    def _request_lines(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[list[Any]]:
        params = {
            "param": ",".join(
                [
                    symbol,
                    "day",
                    start_date.isoformat(),
                    end_date.isoformat(),
                    str(TENCENT_MAX_ROWS_PER_REQUEST),
                ]
            )
        }
        payload = self._request(params)
        data = payload.get("data")
        symbol_payload = data.get(symbol) if isinstance(data, dict) else None
        lines = symbol_payload.get("day") if isinstance(symbol_payload, dict) else None
        if not isinstance(lines, list):
            raise RuntimeError(f"腾讯不复权日线响应缺少 day：{symbol}")
        return [item for item in lines if isinstance(item, list)]

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        # 腾讯公开接口用于低频批量补历史日线，保留请求间隔以降低公开端点限流概率。
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_interval_seconds:
            time.sleep(self.request_interval_seconds - elapsed)
        try:
            with httpx.Client(timeout=self.timeout_seconds, headers=DEFAULT_HEADERS) as client:
                response = client.get(TENCENT_KLINE_URL, params=params)
                response.raise_for_status()
                self._last_request_time = time.monotonic()
                payload = response.json()
        except Exception as exc:
            logger.error("腾讯不复权日线请求失败 param=%s", params.get("param"))
            raise RuntimeError(f"腾讯不复权日线请求失败：{exc}") from exc
        if not isinstance(payload, dict) or payload.get("data") is None:
            raise RuntimeError(f"腾讯不复权日线响应缺少 data：{params.get('param')}")
        return payload

    def _split_year_ranges(self, start_date: date, end_date: date) -> list[tuple[date, date]]:
        # 以自然年切分长周期同步窗口，边界日期直接传给接口，避免跨年分段遗漏首尾交易日。
        ranges: list[tuple[date, date]] = []
        current_year = start_date.year
        while current_year <= end_date.year:
            period_start = max(start_date, date(current_year, 1, 1))
            period_end = min(end_date, date(current_year, 12, 31))
            ranges.append((period_start, period_end))
            current_year += 1
        return ranges

    def _parse_line(
        self,
        market: str,
        ts_code: str,
        symbol: str,
        raw_line: list[Any],
    ) -> TencentKlineRow | None:
        # 腾讯 day 行至少包含日期、开盘、收盘、最高、最低、成交量；
        # 分红除权说明会追加在第 7 列，解析时保留原始行但不参与价格字段计算。
        if len(raw_line) < 6:
            logger.error("腾讯不复权日线字段不足 ts_code=%s raw=%s", ts_code, raw_line)
            return None
        trade_date = parse_tushare_date(str(raw_line[0]).replace("-", ""))
        close = to_decimal(raw_line[2])
        if trade_date is None or close is None:
            logger.error("腾讯不复权日线日期或收盘价无效 ts_code=%s raw=%s", ts_code, raw_line)
            return None
        return TencentKlineRow(
            market=market,
            ts_code=ts_code,
            tencent_symbol=symbol,
            trade_date=trade_date,
            open=to_decimal(raw_line[1]),
            close=close,
            high=to_decimal(raw_line[3]),
            low=to_decimal(raw_line[4]),
            volume=to_decimal(raw_line[5]),
            amount=None,
            amplitude=None,
            pct_chg=None,
            change_amount=None,
            turnover_rate=None,
            raw_payload_json=json.dumps(
                {"symbol": symbol, "kline": raw_line},
                ensure_ascii=False,
                default=str,
            ),
        )


def parse_iso_date(value: date | str | None, default: date | None = None) -> date | None:
    """解析接口日期参数，兼容 ISO 日期和 Tushare 紧凑日期。

    创建日期：2026-05-06
    author: sunshengxian
    """

    if value is None or value == "":
        return default
    if isinstance(value, date):
        return value
    return datetime.strptime(value.replace("-", ""), "%Y%m%d").date()
