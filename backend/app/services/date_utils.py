from __future__ import annotations

from datetime import date, datetime


def parse_tushare_date(value: str | date | None) -> date | None:
    """解析 Tushare 的 YYYYMMDD 日期。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y%m%d").date()


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
