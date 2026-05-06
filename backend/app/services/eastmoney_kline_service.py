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
EASTMONEY_FIELDS1 = "f1,f2,f3,f4,f5,f6"
EASTMONEY_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
EASTMONEY_KLT_DAILY = "101"
EASTMONEY_FQT_UNADJUSTED = "0"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_REQUEST_INTERVAL_SECONDS = 0.8


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

    def to_model_row(self) -> dict[str, Any]:
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
            "data_source": "EASTMONEY_KLINE",
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
        payload = self._request(params)
        klines = ((payload.get("data") or {}).get("klines")) or []
        rows: list[EastmoneyKlineRow] = []
        for raw_line in klines:
            row = self._parse_kline_line(market, ts_code.upper(), secid, str(raw_line))
            if row is not None:
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

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        # 东方财富公开接口按低频批量拉取使用，保留请求间隔以降低公开端点限流和失败概率。
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.request_interval_seconds:
            time.sleep(self.request_interval_seconds - elapsed)
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(EASTMONEY_KLINE_URL, params=params)
                response.raise_for_status()
                self._last_request_time = time.monotonic()
                payload = response.json()
        except Exception as exc:
            logger.error("东方财富不复权日线请求失败 secid=%s", params.get("secid"))
            raise RuntimeError(f"东方财富不复权日线请求失败：{exc}") from exc
        if not isinstance(payload, dict) or payload.get("data") is None:
            raise RuntimeError(f"东方财富不复权日线响应缺少 data：{params.get('secid')}")
        return payload

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
