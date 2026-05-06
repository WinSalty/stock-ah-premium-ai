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

EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_HK_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
EASTMONEY_FIELDS1 = "f1,f2,f3,f4,f5,f6"
EASTMONEY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
EASTMONEY_KLT_DAILY = "101"
EASTMONEY_FQT_UNADJUSTED = "0"
TENCENT_HK_MAX_ROWS_PER_REQUEST = 1000
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 0.8
DEFAULT_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


@dataclass(frozen=True)
class EastmoneyKlineRow:
    """东方财富不复权日 K 单行结构。

    创建日期：2026-05-06
    author: sunshengxian
    """

    market: str
    ts_code: str
    eastmoney_secid: str
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

    def to_model_row(self, data_source: str = "EASTMONEY_KLINE") -> dict[str, Any]:
        """转为数据库 upsert 行，固定写入不复权口径和东方财富来源标记。

        创建日期：2026-05-06
        author: sunshengxian
        """

        return {
            "market": self.market,
            "ts_code": self.ts_code,
            "eastmoney_secid": self.eastmoney_secid,
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
            "data_source": data_source,
            "raw_payload_json": self.raw_payload_json,
        }


class EastmoneyKlineService:
    """东方财富历史 K 线客户端。

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
    ) -> list[EastmoneyKlineRow]:
        """拉取单只股票不复权日线。

        创建日期：2026-05-06
        author: sunshengxian
        """

        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        market = self.to_market(ts_code)
        secid = self.to_eastmoney_secid(ts_code)
        params = {
            "secid": secid,
            "klt": EASTMONEY_KLT_DAILY,
            "fqt": EASTMONEY_FQT_UNADJUSTED,
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
            "fields1": EASTMONEY_FIELDS1,
            "fields2": EASTMONEY_FIELDS2,
        }
        try:
            payload = self._request(EASTMONEY_KLINE_URL, params)
        except RuntimeError:
            if market != "HK":
                raise
            logger.warning("东方财富港股日线失败，启用腾讯港股未复权降级 ts_code=%s", ts_code)
            return self._fetch_tencent_hk_unadjusted_daily(ts_code, secid, start_date, end_date)
        klines = ((payload.get("data") or {}).get("klines")) or []
        rows: list[EastmoneyKlineRow] = []
        for raw_line in klines:
            row = self._parse_kline_line(market, ts_code.upper(), secid, str(raw_line))
            if row is not None and start_date <= row.trade_date <= end_date:
                rows.append(row)
        return rows

    def to_eastmoney_secid(self, ts_code: str) -> str:
        """将项目标准代码转换为东方财富 secid。

        创建日期：2026-05-06
        author: sunshengxian
        """

        normalized = ts_code.strip().upper()
        if normalized.endswith(".SH"):
            return f"1.{normalized.split('.', maxsplit=1)[0]}"
        if normalized.endswith(".SZ"):
            return f"0.{normalized.split('.', maxsplit=1)[0]}"
        if normalized.endswith(".HK"):
            code = normalized.split(".", maxsplit=1)[0].zfill(5)
            return f"116.{code}"
        raise ValueError(f"不支持的东方财富股票代码：{ts_code}")

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

    def _request(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        # 东方财富公开接口按低频批量拉取使用，保留请求间隔以降低公开端点限流和失败概率。
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_interval_seconds:
            time.sleep(self.request_interval_seconds - elapsed)
        try:
            with httpx.Client(timeout=self.timeout_seconds, headers=DEFAULT_HEADERS) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                self._last_request_time = time.monotonic()
                payload = response.json()
        except Exception as exc:
            logger.error("东方财富不复权日线请求失败 secid=%s", params.get("secid"))
            raise RuntimeError(f"东方财富不复权日线请求失败：{exc}") from exc
        if not isinstance(payload, dict) or payload.get("data") is None:
            raise RuntimeError(f"东方财富不复权日线响应缺少 data：{params.get('secid')}")
        return payload

    def _fetch_tencent_hk_unadjusted_daily(
        self,
        ts_code: str,
        eastmoney_secid: str,
        start_date: date,
        end_date: date,
    ) -> list[EastmoneyKlineRow]:
        """用腾讯港股日 K 作为东方财富港股历史 K 线的降级数据源。

        创建日期：2026-05-06
        author: sunshengxian
        """

        rows_by_date: dict[date, EastmoneyKlineRow] = {}
        for period_start, period_end in self._split_year_ranges(start_date, end_date):
            # 腾讯港股接口单次返回行数有限，按自然年切段后再按日期去重，
            # 既避免 2018 年以来长窗口被截断，也保证接口重跑仍按交易日幂等覆盖。
            for raw_line in self._request_tencent_hk_lines(ts_code, period_start, period_end):
                row = self._parse_tencent_hk_line(ts_code, eastmoney_secid, raw_line)
                if row is not None and start_date <= row.trade_date <= end_date:
                    rows_by_date[row.trade_date] = row
        if not rows_by_date:
            raise RuntimeError(f"腾讯港股不复权日线响应为空：{ts_code}")
        return [rows_by_date[item] for item in sorted(rows_by_date)]

    def _request_tencent_hk_lines(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
    ) -> list[list[Any]]:
        hk_code = ts_code.strip().upper().split(".", maxsplit=1)[0].zfill(5)
        params = {
            "param": ",".join(
                [
                    f"hk{hk_code}",
                    "day",
                    start_date.isoformat(),
                    end_date.isoformat(),
                    str(TENCENT_HK_MAX_ROWS_PER_REQUEST),
                ]
            )
        }
        payload = self._request(TENCENT_HK_KLINE_URL, params)
        data = payload.get("data")
        symbol_payload = data.get(f"hk{hk_code}") if isinstance(data, dict) else None
        lines = symbol_payload.get("day") if isinstance(symbol_payload, dict) else None
        if not isinstance(lines, list):
            raise RuntimeError(f"腾讯港股不复权日线响应缺少 day：{ts_code}")
        return [item for item in lines if isinstance(item, list)]

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

    def _parse_tencent_hk_line(
        self,
        ts_code: str,
        eastmoney_secid: str,
        raw_line: list[Any],
    ) -> EastmoneyKlineRow | None:
        # 腾讯港股 day 行至少包含日期、开盘、收盘、最高、最低、成交量；
        # 分红除权说明会追加在第 7 列，解析时保留原始行但不参与价格字段计算。
        if len(raw_line) < 6:
            logger.error("腾讯港股不复权日线字段不足 ts_code=%s raw=%s", ts_code, raw_line)
            return None
        trade_date = parse_tushare_date(str(raw_line[0]).replace("-", ""))
        close = to_decimal(raw_line[2])
        if trade_date is None or close is None:
            logger.error("腾讯港股不复权日线日期或收盘价无效 ts_code=%s raw=%s", ts_code, raw_line)
            return None
        return EastmoneyKlineRow(
            market="HK",
            ts_code=ts_code.upper(),
            eastmoney_secid=eastmoney_secid,
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
                {
                    "secid": eastmoney_secid,
                    "fallback_source": "TENCENT_HK_KLINE",
                    "kline": raw_line,
                },
                ensure_ascii=False,
                default=str,
            ),
        )

    def _parse_kline_line(
        self,
        market: str,
        ts_code: str,
        secid: str,
        raw_line: str,
    ) -> EastmoneyKlineRow | None:
        # klines 固定为 11 列；列数不完整或收盘价无效时跳过，避免错误行情进入补数链路。
        parts = raw_line.split(",")
        if len(parts) < 11:
            logger.error("东方财富不复权日线字段不足 ts_code=%s raw=%s", ts_code, raw_line)
            return None
        trade_date = parse_tushare_date(parts[0].replace("-", ""))
        close = to_decimal(parts[2])
        if trade_date is None or close is None:
            logger.error("东方财富不复权日线日期或收盘价无效 ts_code=%s raw=%s", ts_code, raw_line)
            return None
        return EastmoneyKlineRow(
            market=market,
            ts_code=ts_code,
            eastmoney_secid=secid,
            trade_date=trade_date,
            open=to_decimal(parts[1]),
            close=close,
            high=to_decimal(parts[3]),
            low=to_decimal(parts[4]),
            volume=to_decimal(parts[5]),
            amount=to_decimal(parts[6]),
            amplitude=to_decimal(parts[7]),
            pct_chg=to_decimal(parts[8]),
            change_amount=to_decimal(parts[9]),
            turnover_rate=to_decimal(parts[10]),
            raw_payload_json=json.dumps(
                {"secid": secid, "kline": raw_line},
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
