from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.market import (
    ADailyQuote,
    AStockBasic,
    ATradeCalendar,
    FxRateDaily,
    HKDailyQuote,
    HKStockBasic,
    HKTradeCalendar,
    HsgtConstituent,
    OfficialAHComparison,
)
from app.db.models.sync import SyncCheckpoint, SyncRun
from app.services.date_utils import format_tushare_date, parse_tushare_date
from app.services.decimal_utils import to_decimal
from app.services.repository import UpsertRepository
from app.services.tushare_client import TushareClient


@dataclass(frozen=True)
class DatasetSpec:
    """同步数据集规格。

    创建日期：2026-05-04
    author: sunshengxian
    """

    name: str
    label: str
    api_name: str
    fields: list[str]
    model: type
    date_fields: tuple[str, ...] = ()
    decimal_fields: tuple[str, ...] = ()
    rename_map: dict[str, str] | None = None
    default_params: dict[str, Any] | None = None
    description: str = ""


DATASET_SPECS: dict[str, DatasetSpec] = {
    "stock_basic": DatasetSpec(
        name="stock_basic",
        label="A 股基础信息",
        api_name="stock_basic",
        fields=[
            "ts_code",
            "symbol",
            "name",
            "area",
            "industry",
            "fullname",
            "market",
            "exchange",
            "curr_type",
            "list_status",
            "list_date",
            "delist_date",
            "is_hs",
        ],
        model=AStockBasic,
        date_fields=("list_date", "delist_date"),
        default_params={"exchange": "", "list_status": "L"},
        description="同步 A 股基础资料。",
    ),
    "trade_cal": DatasetSpec(
        name="trade_cal",
        label="A 股交易日历",
        api_name="trade_cal",
        fields=["exchange", "cal_date", "is_open", "pretrade_date"],
        model=ATradeCalendar,
        date_fields=("cal_date", "pretrade_date"),
        default_params={"exchange": "SSE"},
        description="同步 A 股交易日历。",
    ),
    "a_daily": DatasetSpec(
        name="a_daily",
        label="A 股日线行情",
        api_name="daily",
        fields=[
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ],
        model=ADailyQuote,
        date_fields=("trade_date",),
        decimal_fields=(
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change_amount",
            "pct_chg",
            "vol",
            "amount",
        ),
        rename_map={"change": "change_amount"},
        description="同步 A 股未复权日线行情。",
    ),
    "hk_basic": DatasetSpec(
        name="hk_basic",
        label="港股基础信息",
        api_name="hk_basic",
        fields=[
            "ts_code",
            "name",
            "fullname",
            "enname",
            "cn_spell",
            "market",
            "list_status",
            "list_date",
            "delist_date",
            "trade_unit",
            "isin",
            "curr_type",
        ],
        model=HKStockBasic,
        date_fields=("list_date", "delist_date"),
        decimal_fields=("trade_unit",),
        default_params={"list_status": "L"},
        description="同步港股基础资料。",
    ),
    "hk_tradecal": DatasetSpec(
        name="hk_tradecal",
        label="港股交易日历",
        api_name="hk_tradecal",
        fields=["cal_date", "is_open", "pretrade_date"],
        model=HKTradeCalendar,
        date_fields=("cal_date", "pretrade_date"),
        description="同步港股交易日历。",
    ),
    "hk_daily": DatasetSpec(
        name="hk_daily",
        label="港股日线行情",
        api_name="hk_daily",
        fields=[
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ],
        model=HKDailyQuote,
        date_fields=("trade_date",),
        decimal_fields=(
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change_amount",
            "pct_chg",
            "vol",
            "amount",
        ),
        rename_map={"change": "change_amount"},
        description="同步港股日线行情。",
    ),
    "stock_hsgt": DatasetSpec(
        name="stock_hsgt",
        label="沪深港通名单",
        api_name="stock_hsgt",
        fields=["ts_code", "trade_date", "type", "name", "type_name"],
        model=HsgtConstituent,
        date_fields=("trade_date",),
        rename_map={"type": "connect_type"},
        description="同步沪股通、深股通、港股通名单。",
    ),
    "fx_daily": DatasetSpec(
        name="fx_daily",
        label="外汇日线",
        api_name="fx_daily",
        fields=["ts_code", "trade_date", "bid_close", "ask_close", "exchange"],
        model=FxRateDaily,
        date_fields=("rate_date",),
        decimal_fields=("bid_close", "ask_close", "mid_rate"),
        rename_map={"trade_date": "rate_date", "ts_code": "raw_ts_code"},
        default_params={"exchange": "FXCM"},
        description="同步外汇日线，默认使用 FXCM。",
    ),
    "ah_comparison": DatasetSpec(
        name="ah_comparison",
        label="官方 AH 比价",
        api_name="stk_ah_comparison",
        fields=[
            "hk_code",
            "ts_code",
            "trade_date",
            "hk_name",
            "hk_pct_chg",
            "hk_close",
            "name",
            "close",
            "pct_chg",
            "ah_comparison",
            "ah_premium",
        ],
        model=OfficialAHComparison,
        date_fields=("trade_date",),
        decimal_fields=(
            "a_close",
            "a_pct_chg",
            "hk_close",
            "hk_pct_chg",
            "ah_comparison",
            "ah_premium",
        ),
        rename_map={
            "hk_code": "hk_ts_code",
            "ts_code": "a_ts_code",
            "name": "a_name",
            "close": "a_close",
            "pct_chg": "a_pct_chg",
        },
        description="同步 Tushare 官方 AH 比价，用于配对和校验。",
    ),
}

HSGT_TYPES = ("SH_HK", "SZ_HK", "HK_SH", "HK_SZ")
DEFAULT_FX_CODES = ("USDCNH.FXCM", "USDHKD.FXCM", "HKDCNH.FXCM", "HKDCNY.FXCM")


class SyncService:
    """数据同步服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = UpsertRepository(db)
        self.client = TushareClient(get_settings())

    def list_datasets(self) -> list[dict[str, str]]:
        """列出可同步数据集。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return [
            {"name": spec.name, "label": spec.label, "description": spec.description}
            for spec in DATASET_SPECS.values()
        ]

    def run_sync(self, dataset: str, params: dict[str, Any]) -> SyncRun:
        """执行同步任务并记录运行状态。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if dataset not in DATASET_SPECS:
            raise ValueError(f"不支持的数据集：{dataset}")
        spec = DATASET_SPECS[dataset]
        run = SyncRun(
            dataset=dataset,
            params_json=json.dumps(params, ensure_ascii=False, default=str),
            status="RUNNING",
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        try:
            row_count = self._sync_spec(spec, params)
            run.status = "SUCCESS"
            run.row_count = row_count
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            self._update_checkpoint(dataset, params, run.id)
            self.db.commit()
            self.db.refresh(run)
            return run
        except Exception as exc:
            run.status = "FAILED"
            run.error_message = str(exc)
            run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            self.db.commit()
            self.db.refresh(run)
            return run

    def _sync_spec(self, spec: DatasetSpec, params: dict[str, Any]) -> int:
        merged_params = self._build_params(spec, params)
        if spec.name == "stock_hsgt" and "type" not in merged_params:
            return sum(self._sync_spec(spec, {**params, "type": item}) for item in HSGT_TYPES)
        if spec.name == "fx_daily" and "ts_code" not in merged_params:
            return sum(
                self._sync_spec(spec, {**params, "ts_code": item})
                for item in DEFAULT_FX_CODES
            )

        result = self.client.query(spec.api_name, params=merged_params, fields=spec.fields)
        rows = [self._normalize_row(spec, row) for row in result.rows]
        rows = [row for row in rows if row]
        row_count = self.repository.upsert_many(spec.model, rows)
        if spec.name == "ah_comparison":
            from app.services.ah_pair_service import AHPairService

            AHPairService(self.db).upsert_from_official_rows(rows)
        self.db.commit()
        return row_count

    def _build_params(self, spec: DatasetSpec, params: dict[str, Any]) -> dict[str, Any]:
        api_params = dict(spec.default_params or {})
        for key, value in params.items():
            if value is None or value == "":
                continue
            if key in {"start_date", "end_date", "trade_date"}:
                api_params[key] = format_tushare_date(value)
            else:
                api_params[key] = value
        return api_params

    def _normalize_row(self, spec: DatasetSpec, row: dict[str, Any]) -> dict[str, Any]:
        rename_map = spec.rename_map or {}
        normalized = {rename_map.get(key, key): value for key, value in row.items()}
        if spec.name == "fx_daily":
            self._normalize_fx_row(normalized)
        for field in spec.date_fields:
            normalized[field] = parse_tushare_date(normalized.get(field))
        for field in spec.decimal_fields:
            normalized[field] = to_decimal(normalized.get(field))
        model_columns = set(spec.model.__table__.columns.keys())
        return {key: value for key, value in normalized.items() if key in model_columns}

    def _normalize_fx_row(self, row: dict[str, Any]) -> None:
        raw_ts_code = row.get("raw_ts_code") or ""
        pair = raw_ts_code.split(".", maxsplit=1)[0].upper()
        base_ccy = pair[:3] if len(pair) >= 6 else ""
        quote_ccy = pair[3:6] if len(pair) >= 6 else ""
        bid_close = to_decimal(row.get("bid_close"))
        ask_close = to_decimal(row.get("ask_close"))
        row["rate_pair"] = f"{base_ccy}_{quote_ccy}" if base_ccy and quote_ccy else pair
        row["base_ccy"] = base_ccy
        row["quote_ccy"] = quote_ccy
        row["source"] = "TUSHARE_FXCM"
        row["is_cross_rate"] = False
        row["mid_rate"] = (
            (bid_close + ask_close) / 2
            if bid_close is not None and ask_close is not None
            else bid_close
        )

    def _update_checkpoint(self, dataset: str, params: dict[str, Any], run_id: int) -> None:
        trade_date = parse_tushare_date(params.get("trade_date")) or parse_tushare_date(
            params.get("end_date")
        )
        scope_key = str(params.get("ts_code") or params.get("type") or "default")
        checkpoint = self.db.get(SyncCheckpoint, {"dataset": dataset, "scope_key": scope_key})
        if checkpoint is None:
            checkpoint = SyncCheckpoint(dataset=dataset, scope_key=scope_key)
            self.db.add(checkpoint)
        checkpoint.last_success_date = trade_date or date.today()
        checkpoint.last_run_id = run_id
