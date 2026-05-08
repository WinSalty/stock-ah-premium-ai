from __future__ import annotations

from datetime import date, datetime
from typing import Any


def parse_tushare_date(value: Any) -> date | None:
    """解析 Tushare 的 YYYYMMDD 日期。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    # 港股财务指标接口部分日期会以数字返回；统一转成字符串后解析，
    # 避免按需补数因 SDK 类型差异中断，重跑时仍按同一日期幂等覆盖。
    return datetime.strptime(str(value), "%Y%m%d").date()


def format_tushare_date(value: date | str | None) -> str | None:
    """格式化为 Tushare 的 YYYYMMDD 日期。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("-", "")
    return value.strftime("%Y%m%d")
