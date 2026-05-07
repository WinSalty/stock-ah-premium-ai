from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.market import (
    ABalanceSheet,
    ACashflowStatement,
    ADailyBasic,
    ADailyQuote,
    ADividend,
    AFinancialIndicator,
    AForecast,
    AIncomeStatement,
    LlmMarketDataFetchItem,
)
from app.services.date_utils import format_tushare_date, parse_tushare_date
from app.services.decimal_utils import to_decimal
from app.services.repository import UpsertRepository
from app.services.tushare_client import TushareClient

logger = logging.getLogger(__name__)

QUOTE_VALUATION_PACKAGE = "quote_valuation"
FINANCIAL_STATEMENT_PACKAGE = "financial_statement"
DIVIDEND_FORECAST_PACKAGE = "dividend_forecast"


@dataclass(frozen=True)
class FetchApiSpec:
    """Tushare 单接口白名单描述。

    创建日期：2026-05-07
    author: sunshengxian
    """

    package_name: str
    api_name: str
    model: type
    fields: tuple[str, ...]
    date_fields: tuple[str, ...]
    decimal_fields: tuple[str, ...]
    default_days: int | None = None
    default_years: int | None = None


class TushareStockResearchFetcher:
    """个股研究数据白名单抓取器。

    创建日期：2026-05-07
    author: sunshengxian
    """

    specs: dict[str, tuple[FetchApiSpec, ...]] = {
        QUOTE_VALUATION_PACKAGE: (
            FetchApiSpec(
                package_name=QUOTE_VALUATION_PACKAGE,
                api_name="daily",
                model=ADailyQuote,
                fields=(
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
                ),
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
                default_days=180,
            ),
            FetchApiSpec(
                package_name=QUOTE_VALUATION_PACKAGE,
                api_name="daily_basic",
                model=ADailyBasic,
                fields=(
                    "ts_code",
                    "trade_date",
                    "close",
                    "turnover_rate",
                    "volume_ratio",
                    "pe",
                    "pe_ttm",
                    "pb",
                    "ps",
                    "ps_ttm",
                    "dv_ratio",
                    "dv_ttm",
                    "total_share",
                    "float_share",
                    "free_share",
                    "total_mv",
                    "circ_mv",
                ),
                date_fields=("trade_date",),
                decimal_fields=(
                    "close",
                    "turnover_rate",
                    "volume_ratio",
                    "pe",
                    "pe_ttm",
                    "pb",
                    "ps",
                    "ps_ttm",
                    "dv_ratio",
                    "dv_ttm",
                    "total_share",
                    "float_share",
                    "free_share",
                    "total_mv",
                    "circ_mv",
                ),
                default_days=180,
            ),
        ),
        FINANCIAL_STATEMENT_PACKAGE: (
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="income",
                model=AIncomeStatement,
                fields=(
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "comp_type",
                    "end_type",
                    "basic_eps",
                    "diluted_eps",
                    "total_revenue",
                    "revenue",
                    "oper_cost",
                    "sell_exp",
                    "admin_exp",
                    "fin_exp",
                    "operate_profit",
                    "total_profit",
                    "income_tax",
                    "n_income",
                    "n_income_attr_p",
                    "update_flag",
                ),
                date_fields=("ann_date", "f_ann_date", "end_date"),
                decimal_fields=(
                    "basic_eps",
                    "diluted_eps",
                    "total_revenue",
                    "revenue",
                    "oper_cost",
                    "sell_exp",
                    "admin_exp",
                    "fin_exp",
                    "operate_profit",
                    "total_profit",
                    "income_tax",
                    "n_income",
                    "n_income_attr_p",
                ),
                default_years=5,
            ),
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="balancesheet",
                model=ABalanceSheet,
                fields=(
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "comp_type",
                    "total_assets",
                    "total_liab",
                    "total_hldr_eqy_inc_min_int",
                    "total_hldr_eqy_exc_min_int",
                    "money_cap",
                    "trad_asset",
                    "notes_receiv",
                    "accounts_receiv",
                    "inventories",
                    "total_cur_assets",
                    "st_borr",
                    "lt_borr",
                    "bond_payable",
                    "total_cur_liab",
                    "update_flag",
                ),
                date_fields=("ann_date", "f_ann_date", "end_date"),
                decimal_fields=(
                    "total_assets",
                    "total_liab",
                    "total_hldr_eqy_inc_min_int",
                    "total_hldr_eqy_exc_min_int",
                    "money_cap",
                    "trad_asset",
                    "notes_receiv",
                    "accounts_receiv",
                    "inventories",
                    "total_cur_assets",
                    "st_borr",
                    "lt_borr",
                    "bond_payable",
                    "total_cur_liab",
                ),
                default_years=5,
            ),
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="cashflow",
                model=ACashflowStatement,
                fields=(
                    "ts_code",
                    "ann_date",
                    "f_ann_date",
                    "end_date",
                    "report_type",
                    "comp_type",
                    "net_profit",
                    "finan_exp",
                    "c_fr_sale_sg",
                    "n_cashflow_act",
                    "n_cashflow_inv_act",
                    "n_cash_flows_fnc_act",
                    "n_incr_cash_cash_equ",
                    "c_cash_equ_end_period",
                    "update_flag",
                ),
                date_fields=("ann_date", "f_ann_date", "end_date"),
                decimal_fields=(
                    "net_profit",
                    "finan_exp",
                    "c_fr_sale_sg",
                    "n_cashflow_act",
                    "n_cashflow_inv_act",
                    "n_cash_flows_fnc_act",
                    "n_incr_cash_cash_equ",
                    "c_cash_equ_end_period",
                ),
                default_years=5,
            ),
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="fina_indicator",
                model=AFinancialIndicator,
                fields=(
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "eps",
                    "dt_eps",
                    "roe",
                    "roe_waa",
                    "grossprofit_margin",
                    "netprofit_margin",
                    "debt_to_assets",
                    "current_ratio",
                    "quick_ratio",
                    "or_yoy",
                    "netprofit_yoy",
                    "ocf_to_revenue",
                    "roe_yoy",
                    "bps",
                    "update_flag",
                ),
                date_fields=("ann_date", "end_date"),
                decimal_fields=(
                    "eps",
                    "dt_eps",
                    "roe",
                    "roe_waa",
                    "grossprofit_margin",
                    "netprofit_margin",
                    "debt_to_assets",
                    "current_ratio",
                    "quick_ratio",
                    "or_yoy",
                    "netprofit_yoy",
                    "ocf_to_revenue",
                    "roe_yoy",
                    "bps",
                ),
                default_years=5,
            ),
        ),
        DIVIDEND_FORECAST_PACKAGE: (
            FetchApiSpec(
                package_name=DIVIDEND_FORECAST_PACKAGE,
                api_name="dividend",
                model=ADividend,
                fields=(
                    "ts_code",
                    "end_date",
                    "ann_date",
                    "div_proc",
                    "stk_div",
                    "cash_div",
                    "cash_div_tax",
                    "record_date",
                    "ex_date",
                    "pay_date",
                ),
                date_fields=("end_date", "ann_date", "record_date", "ex_date", "pay_date"),
                decimal_fields=("stk_div", "cash_div", "cash_div_tax"),
                default_years=5,
            ),
            FetchApiSpec(
                package_name=DIVIDEND_FORECAST_PACKAGE,
                api_name="forecast",
                model=AForecast,
                fields=(
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "type",
                    "p_change_min",
                    "p_change_max",
                    "net_profit_min",
                    "net_profit_max",
                    "last_parent_net",
                    "first_ann_date",
                    "summary",
                    "change_reason",
                ),
                date_fields=("ann_date", "end_date", "first_ann_date"),
                decimal_fields=(
                    "p_change_min",
                    "p_change_max",
                    "net_profit_min",
                    "net_profit_max",
                    "last_parent_net",
                ),
                default_years=3,
            ),
        ),
    }

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        client: TushareClient | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.client = client or TushareClient(self.settings)
        self.repository = UpsertRepository(db)

    def fetch_package(
        self,
        ts_code: str,
        package_name: str,
        run_id: int | None = None,
        today: date | None = None,
    ) -> int:
        """抓取一个固定数据包并写入本地表。

        创建日期：2026-05-07
        author: sunshengxian
        """

        specs = self.specs.get(package_name)
        if specs is None:
            raise ValueError(f"不支持的数据包：{package_name}")
        row_count = 0
        for spec in specs:
            row_count += self._fetch_spec(ts_code, spec, run_id, today or date.today())
        self.db.commit()
        return row_count

    def _fetch_spec(
        self,
        ts_code: str,
        spec: FetchApiSpec,
        run_id: int | None,
        today: date,
    ) -> int:
        params = self._params_for_spec(ts_code, spec, today)
        item = self._start_item(run_id, spec, params)
        started_at = perf_counter()
        try:
            result = self.client.query(spec.api_name, params=params, fields=list(spec.fields))
            rows = [self._normalize_row(spec, row) for row in result.rows]
            rows = [row for row in rows if row]
            row_count = self.repository.upsert_many(spec.model, rows)
            self._finish_item(item, "COMPLETED", row_count, started_at)
            return row_count
        except Exception as exc:
            self._finish_item(item, "FAILED", 0, started_at, str(exc)[:512])
            logger.error(
                "LLM 按需 Tushare 数据包抓取失败 api=%s ts_code=%s",
                spec.api_name,
                ts_code,
                exc_info=True,
            )
            raise

    def _params_for_spec(self, ts_code: str, spec: FetchApiSpec, today: date) -> dict[str, Any]:
        # 15000 积分权限下不做全市场扫描，只以 ts_code 加短日期窗口请求，避免误触宽接口。
        params: dict[str, Any] = {"ts_code": ts_code}
        if spec.default_days:
            start_date = today - timedelta(days=spec.default_days)
            params["start_date"] = format_tushare_date(start_date)
            params["end_date"] = format_tushare_date(today)
        elif spec.default_years:
            start_date = today - timedelta(days=365 * spec.default_years)
            params["start_date"] = format_tushare_date(start_date)
            params["end_date"] = format_tushare_date(today)
        return params

    def _normalize_row(self, spec: FetchApiSpec, row: dict[str, Any]) -> dict[str, Any]:
        # 保留原始行便于审计，同时只写模型允许字段，防止接口新增字段污染本地表结构。
        normalized = {
            "change_amount" if key == "change" else key: value
            for key, value in row.items()
        }
        for field in spec.date_fields:
            normalized[field] = parse_tushare_date(normalized.get(field))
        for field in spec.decimal_fields:
            normalized[field] = to_decimal(normalized.get(field))
        if spec.api_name in {"income", "balancesheet", "cashflow"}:
            normalized["report_type"] = str(normalized.get("report_type") or "")
            normalized["update_flag"] = str(normalized.get("update_flag") or "")
        if spec.api_name == "dividend":
            normalized["div_proc"] = str(normalized.get("div_proc") or "")
        if spec.api_name == "forecast":
            normalized["type"] = str(normalized.get("type") or "")
        normalized["raw_payload_json"] = json.dumps(row, ensure_ascii=False, default=str)
        model_columns = set(spec.model.__table__.columns.keys())
        return {key: value for key, value in normalized.items() if key in model_columns}

    def _start_item(
        self,
        run_id: int | None,
        spec: FetchApiSpec,
        params: dict[str, Any],
    ) -> LlmMarketDataFetchItem:
        item = LlmMarketDataFetchItem(
            run_id=run_id,
            package_name=spec.package_name,
            api_name=spec.api_name,
            params_json=json.dumps(params, ensure_ascii=False, default=str),
            fields_json=json.dumps(list(spec.fields), ensure_ascii=False),
            status="RUNNING",
            row_count=0,
        )
        self.db.add(item)
        self.db.flush()
        return item

    def _finish_item(
        self,
        item: LlmMarketDataFetchItem,
        status: str,
        row_count: int,
        started_at: float,
        error_message: str | None = None,
    ) -> None:
        # 明细与批次共用同一事务，调用方失败时仍可看到失败原因，便于排查接口权限或字段问题。
        item.status = status
        item.row_count = row_count
        item.elapsed_ms = int((perf_counter() - started_at) * 1000)
        item.error_message = error_message
        item.updated_at = datetime.now(UTC).replace(tzinfo=None)
