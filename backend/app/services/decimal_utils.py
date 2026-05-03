from __future__ import annotations

from decimal import Decimal, InvalidOperation


def to_decimal(value: object) -> Decimal | None:
    """将接口值安全转换为 Decimal。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def quantize_decimal(value: Decimal | None, scale: str = "0.00000001") -> Decimal | None:
    """按固定精度处理计算结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    if value is None:
        return None
    return value.quantize(Decimal(scale))
