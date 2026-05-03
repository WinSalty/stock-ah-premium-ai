from __future__ import annotations

from decimal import Decimal


def test_ah_premium_formula() -> None:
    a_close_cny = Decimal("10.00")
    h_close_hkd = Decimal("8.00")
    hkd_cny = Decimal("0.92")
    h_close_cny = h_close_hkd * hkd_cny
    ah_ratio = a_close_cny / h_close_cny
    premium_pct = (ah_ratio - Decimal("1")) * Decimal("100")
    assert premium_pct.quantize(Decimal("0.01")) == Decimal("35.87")
