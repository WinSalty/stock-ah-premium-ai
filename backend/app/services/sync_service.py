from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
from app.services.decimal_utils import quantize_decimal, to_decimal
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
    supports_date_range: bool = False
    split_by_trade_date: bool = False
    full_start_date: date | None = None
    full_end_offset_days: int = 0
    incremental_overlap_days: int = 2


AH_HISTORY_START = date(2025, 8, 12)
CALENDAR_HISTORY_START = date(2025, 1, 1)
CALENDAR_FUTURE_DAYS = 370
CONTROL_PARAM_KEYS = {"mode"}
CORE_SYNC_PLAN: tuple[tuple[str, dict[str, Any]], ...] = (
    ("stock_basic", {}),
    ("hk_basic", {}),
    ("trade_cal", {}),
    ("hk_tradecal", {}),
    ("ah_comparison", {}),
    ("stock_hsgt", {"type": "SH_HK"}),
    ("stock_hsgt", {"type": "SZ_HK"}),
    ("a_daily", {}),
    ("fx_daily", {}),
)
DISABLED_INTERFACE_DATASETS = {"hk_daily"}


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
        supports_date_range=True,
        full_start_date=CALENDAR_HISTORY_START,
        full_end_offset_days=CALENDAR_FUTURE_DAYS,
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
        supports_date_range=True,
        split_by_trade_date=True,
        full_start_date=AH_HISTORY_START,
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
        supports_date_range=True,
        full_start_date=CALENDAR_HISTORY_START,
        full_end_offset_days=CALENDAR_FUTURE_DAYS,
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
        supports_date_range=True,
        split_by_trade_date=True,
        full_start_date=AH_HISTORY_START,
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
        supports_date_range=True,
        split_by_trade_date=True,
        full_start_date=AH_HISTORY_START,
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
        supports_date_range=True,
        full_start_date=AH_HISTORY_START,
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
            "ha_comparison",
            "ha_premium",
        ),
        rename_map={
            "hk_code": "hk_ts_code",
            "ts_code": "a_ts_code",
            "name": "a_name",
            "close": "a_close",
            "pct_chg": "a_pct_chg",
        },
        description="同步 Tushare 官方 AH 比价，用于配对和校验。",
        supports_date_range=True,
        split_by_trade_date=True,
        full_start_date=AH_HISTORY_START,
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

    def list_datasets(self) -> list[dict[str, Any]]:
        """列出可同步数据集。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return [
            self._dataset_info(spec)
            for spec in DATASET_SPECS.values()
        ]

    def run_sync(self, dataset: str, params: dict[str, Any]) -> SyncRun:
        """执行同步任务并记录运行状态。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if dataset not in DATASET_SPECS:
            raise ValueError(f"不支持的数据集：{dataset}")
        if dataset in DISABLED_INTERFACE_DATASETS:
            raise ValueError("当前 token 无法请求 hk_daily，已按要求禁用该接口同步。")
        spec = DATASET_SPECS[dataset]
        params = self._resolve_mode_params(spec, params)
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

    def run_core_plan(
        self,
        mode: str = "incremental",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[SyncRun]:
        """按 AH 溢价分析所需数据集执行一键同步。

        创建日期：2026-05-04
        author: sunshengxian
        """

        runs: list[SyncRun] = []
        base_params = {"mode": mode, "start_date": start_date, "end_date": end_date}
        for dataset, dataset_params in CORE_SYNC_PLAN:
            params = {**base_params, **dataset_params}
            params = {key: value for key, value in params.items() if value is not None}
            runs.append(self.run_sync(dataset, params))
        return runs

    def _sync_spec(self, spec: DatasetSpec, params: dict[str, Any]) -> int:
        merged_params = self._build_params(spec, params)
        if spec.name == "stock_hsgt" and "type" not in merged_params:
            return sum(self._sync_spec(spec, {**params, "type": item}) for item in HSGT_TYPES)
        if spec.name == "fx_daily" and "ts_code" not in merged_params:
            return sum(
                self._sync_spec(spec, {**params, "ts_code": item})
                for item in DEFAULT_FX_CODES
            )
        if self._should_split_by_trade_date(spec, params):
            return sum(
                self._sync_spec(spec, {**self._without_range_params(params), "trade_date": item})
                for item in self._iter_dates(
                    self._coerce_date(params.get("start_date")),
                    self._coerce_date(params.get("end_date")),
                )
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
            if key in CONTROL_PARAM_KEYS:
                continue
            if key in {"start_date", "end_date", "trade_date"}:
                api_params[key] = format_tushare_date(value)
            else:
                api_params[key] = value
        return api_params

    def _resolve_mode_params(self, spec: DatasetSpec, params: dict[str, Any]) -> dict[str, Any]:
        params = {key: value for key, value in params.items() if value is not None and value != ""}
        mode = str(params.get("mode") or "manual")
        params["mode"] = mode
        if mode == "manual":
            return params
        if mode == "full":
            return self._resolve_full_params(spec, params)
        if mode == "incremental":
            return self._resolve_incremental_params(spec, params)
        raise ValueError(f"不支持的同步模式：{mode}")

    def _resolve_full_params(self, spec: DatasetSpec, params: dict[str, Any]) -> dict[str, Any]:
        if not spec.supports_date_range:
            return self._without_range_params(params)
        params = dict(params)
        params["start_date"] = self._coerce_date(params.get("start_date")) or spec.full_start_date
        params["end_date"] = self._coerce_date(params.get("end_date")) or self._default_end_date(
            spec
        )
        params.pop("trade_date", None)
        return params

    def _resolve_incremental_params(
        self, spec: DatasetSpec, params: dict[str, Any]
    ) -> dict[str, Any]:
        if not spec.supports_date_range:
            return self._without_range_params(params)
        params = dict(params)
        requested_start = self._coerce_date(params.get("start_date"))
        requested_end = self._coerce_date(params.get("end_date")) or self._default_end_date(spec)
        checkpoint = self._get_checkpoint(spec.name, self._scope_key(params))
        checkpoint_start = None
        if checkpoint and checkpoint.last_success_date:
            checkpoint_start = checkpoint.last_success_date - timedelta(
                days=spec.incremental_overlap_days
            )
        params["start_date"] = requested_start or checkpoint_start or spec.full_start_date
        params["end_date"] = requested_end
        params.pop("trade_date", None)
        return params

    def _sync_strategy_text(self, spec: DatasetSpec) -> str:
        if not spec.supports_date_range:
            return "基础清单接口不带日期范围，增量和全量都会刷新当前全表。"
        start = spec.full_start_date.isoformat() if spec.full_start_date else "自定义起点"
        if spec.split_by_trade_date:
            return f"支持日期范围；全量默认从 {start} 起按交易日拆分请求，避免触发单次返回上限。"
        return f"支持日期范围；全量默认从 {start} 起按接口范围参数请求。"

    def _dataset_info(self, spec: DatasetSpec) -> dict[str, Any]:
        disabled = spec.name in DISABLED_INTERFACE_DATASETS
        if disabled:
            return {
                "name": spec.name,
                "label": spec.label,
                "description": "当前 token 无法请求，已禁用接口同步。",
                "supports_date_range": False,
                "supports_incremental": False,
                "supports_full_sync": False,
                "default_full_start_date": None,
                "sync_strategy": "已按要求禁用，不会在一键同步中请求 hk_daily。",
            }
        return {
            "name": spec.name,
            "label": spec.label,
            "description": spec.description,
            "supports_date_range": spec.supports_date_range,
            "supports_incremental": True,
            "supports_full_sync": True,
            "default_full_start_date": spec.full_start_date.isoformat()
            if spec.full_start_date
            else None,
            "sync_strategy": self._sync_strategy_text(spec),
        }

    def _get_checkpoint(self, dataset: str, scope_key: str) -> SyncCheckpoint | None:
        return self.db.get(SyncCheckpoint, {"dataset": dataset, "scope_key": scope_key})

    def _scope_key(self, params: dict[str, Any]) -> str:
        return str(params.get("ts_code") or params.get("type") or "default")

    def _default_end_date(self, spec: DatasetSpec) -> date:
        return date.today() + timedelta(days=spec.full_end_offset_days)

    def _without_range_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in params.items()
            if key not in {"start_date", "end_date", "trade_date"}
        }

    def _should_split_by_trade_date(self, spec: DatasetSpec, params: dict[str, Any]) -> bool:
        if not spec.split_by_trade_date or params.get("trade_date"):
            return False
        start_date = self._coerce_date(params.get("start_date"))
        end_date = self._coerce_date(params.get("end_date"))
        if start_date is None or end_date is None:
            return False
        return not (spec.name in {"a_daily", "hk_daily"} and params.get("ts_code"))

    def _iter_dates(self, start_date: date | None, end_date: date | None) -> list[date]:
        if start_date is None or end_date is None or start_date > end_date:
            return []
        days = (end_date - start_date).days
        return [start_date + timedelta(days=offset) for offset in range(days + 1)]

    def _coerce_date(self, value: date | str | None) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        return parse_tushare_date(value.replace("-", ""))

    def _normalize_row(self, spec: DatasetSpec, row: dict[str, Any]) -> dict[str, Any]:
        rename_map = spec.rename_map or {}
        normalized = {rename_map.get(key, key): value for key, value in row.items()}
        if spec.name == "fx_daily":
            self._normalize_fx_row(normalized)
        for field in spec.date_fields:
            normalized[field] = parse_tushare_date(normalized.get(field))
        for field in spec.decimal_fields:
            normalized[field] = to_decimal(normalized.get(field))
        if spec.name == "ah_comparison":
            self._normalize_official_ha_row(normalized)
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

    def _normalize_official_ha_row(self, row: dict[str, Any]) -> None:
        ah_ratio = row.get("ah_comparison")
        ha_ratio = self._reverse_ratio(ah_ratio)
        if row.get("ah_premium") is None and ah_ratio is not None:
            row["ah_premium"] = quantize_decimal((ah_ratio - Decimal("1")) * Decimal("100"))
        row["ha_comparison"] = ha_ratio
        row["ha_premium"] = (
            quantize_decimal((ha_ratio - Decimal("1")) * Decimal("100"))
            if ha_ratio is not None
            else None
        )
        row["is_realtime"] = False
        row["data_source"] = "TUSHARE_OFFICIAL"
        row["source_updated_at"] = datetime.now(UTC).replace(tzinfo=None)

    def _reverse_ratio(self, value: Decimal | None) -> Decimal | None:
        if value is None or value == Decimal("0"):
            return None
        return quantize_decimal(Decimal("1") / value)

    def _update_checkpoint(self, dataset: str, params: dict[str, Any], run_id: int) -> None:
        trade_date = parse_tushare_date(params.get("trade_date")) or parse_tushare_date(
            params.get("end_date")
        )
        scope_key = self._scope_key(params)
        checkpoint = self._get_checkpoint(dataset, scope_key)
        if checkpoint is None:
            checkpoint = SyncCheckpoint(dataset=dataset, scope_key=scope_key)
            self.db.add(checkpoint)
        checkpoint.last_success_date = trade_date or date.today()
        checkpoint.last_run_id = run_id
