from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from app.schemas.imports import ManualAHPairImportRow, ManualFxRateImportRow
from app.services.manual_import_service import ManualImportService


def test_manual_ah_pair_import_normalizes_codes() -> None:
    db = Mock()
    service = ManualImportService(db)
    service.repository = Mock()
    service.repository.upsert_many.return_value = 1

    count = service.import_ah_pairs(
        [
            ManualAHPairImportRow(
                a_ts_code="600000.sh",
                hk_ts_code="00005.hk",
                a_name="浦发银行",
                hk_name="汇丰控股",
            )
        ]
    )

    assert count == 1
    rows = service.repository.upsert_many.call_args.args[1]
    assert rows[0]["a_ts_code"] == "600000.SH"
    assert rows[0]["hk_ts_code"] == "00005.HK"
    assert rows[0]["source"] == "MANUAL"


def test_manual_fx_import_splits_rate_pair() -> None:
    db = Mock()
    service = ManualImportService(db)
    service.repository = Mock()
    service.repository.upsert_many.return_value = 1

    count = service.import_fx_rates(
        [
            ManualFxRateImportRow(
                rate_pair="hkd/cny",
                rate_date=date(2026, 5, 4),
                mid_rate=Decimal("0.9200"),
            )
        ]
    )

    assert count == 1
    rows = service.repository.upsert_many.call_args.args[1]
    assert rows[0]["rate_pair"] == "HKD_CNY"
    assert rows[0]["base_ccy"] == "HKD"
    assert rows[0]["quote_ccy"] == "CNY"


def test_manual_ah_pair_csv_import() -> None:
    db = Mock()
    service = ManualImportService(db)
    service.repository = Mock()
    service.repository.upsert_many.return_value = 1

    count = service.import_ah_pairs_csv(
        "a_ts_code,hk_ts_code,a_name,hk_name\n600000.SH,00005.HK,浦发银行,汇丰控股\n"
    )

    assert count == 1
    rows = service.repository.upsert_many.call_args.args[1]
    assert rows[0]["a_ts_code"] == "600000.SH"


def test_manual_fx_rate_csv_import() -> None:
    db = Mock()
    service = ManualImportService(db)
    service.repository = Mock()
    service.repository.upsert_many.return_value = 1

    count = service.import_fx_rates_csv("rate_pair,rate_date,mid_rate\nHKD_CNY,2026-05-04,0.9200\n")

    assert count == 1
    rows = service.repository.upsert_many.call_args.args[1]
    assert rows[0]["rate_pair"] == "HKD_CNY"
