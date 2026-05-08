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
    AExpress,
    AFinancialAudit,
    AFinancialIndicator,
    AForecast,
    AHolderNumber,
    AIncomeStatement,
    AMainBusinessComposition,
    AMoneyflow,
    APledgeStat,
    ATop10Holder,
    HKFinancialIndicator,
    HKFinancialStatementItem,
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
BUSINESS_PROFILE_PACKAGE = "business_profile"
SHAREHOLDER_GOVERNANCE_PACKAGE = "shareholder_governance"
CAPITAL_FLOW_PACKAGE = "capital_flow_light"


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
    extra_params: dict[str, Any] | None = None
    static_fields: dict[str, Any] | None = None


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
                    "total_cogs",
                    "oper_cost",
                    "biz_tax_surchg",
                    "sell_exp",
                    "admin_exp",
                    "fin_exp",
                    "rd_exp",
                    "assets_impair_loss",
                    "credit_impa_loss",
                    "oth_income",
                    "asset_disp_income",
                    "operate_profit",
                    "non_oper_income",
                    "non_oper_exp",
                    "total_profit",
                    "income_tax",
                    "n_income",
                    "n_income_attr_p",
                    "minority_gain",
                    "invest_income",
                    "fv_value_chg_gain",
                    "ebit",
                    "ebitda",
                    "update_flag",
                ),
                date_fields=("ann_date", "f_ann_date", "end_date"),
                decimal_fields=(
                    "basic_eps",
                    "diluted_eps",
                    "total_revenue",
                    "revenue",
                    "total_cogs",
                    "oper_cost",
                    "biz_tax_surchg",
                    "sell_exp",
                    "admin_exp",
                    "fin_exp",
                    "rd_exp",
                    "assets_impair_loss",
                    "credit_impa_loss",
                    "oth_income",
                    "asset_disp_income",
                    "operate_profit",
                    "non_oper_income",
                    "non_oper_exp",
                    "total_profit",
                    "income_tax",
                    "n_income",
                    "n_income_attr_p",
                    "minority_gain",
                    "invest_income",
                    "fv_value_chg_gain",
                    "ebit",
                    "ebitda",
                ),
                default_years=8,
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
                    "lt_eqt_invest",
                    "invest_real_estate",
                    "notes_receiv",
                    "accounts_receiv",
                    "oth_receiv",
                    "inventories",
                    "fix_assets",
                    "cip",
                    "intan_assets",
                    "goodwill",
                    "total_cur_assets",
                    "total_nca",
                    "st_borr",
                    "notes_payable",
                    "acct_payable",
                    "contract_liab",
                    "lt_borr",
                    "bond_payable",
                    "total_cur_liab",
                    "total_ncl",
                    "cap_rese",
                    "surplus_rese",
                    "undistr_porfit",
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
                    "lt_eqt_invest",
                    "invest_real_estate",
                    "notes_receiv",
                    "accounts_receiv",
                    "oth_receiv",
                    "inventories",
                    "fix_assets",
                    "cip",
                    "intan_assets",
                    "goodwill",
                    "total_cur_assets",
                    "total_nca",
                    "st_borr",
                    "notes_payable",
                    "acct_payable",
                    "contract_liab",
                    "lt_borr",
                    "bond_payable",
                    "total_cur_liab",
                    "total_ncl",
                    "cap_rese",
                    "surplus_rese",
                    "undistr_porfit",
                ),
                default_years=8,
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
                    "c_paid_goods_s",
                    "c_paid_to_for_empl",
                    "c_paid_for_taxes",
                    "n_cashflow_act",
                    "c_recp_return_invest",
                    "n_recp_disp_fiolta",
                    "c_pay_acq_const_fiolta",
                    "n_cashflow_inv_act",
                    "c_recp_borrow",
                    "c_prepay_amt_borr",
                    "c_pay_dist_dpcp_int_exp",
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
                    "c_paid_goods_s",
                    "c_paid_to_for_empl",
                    "c_paid_for_taxes",
                    "n_cashflow_act",
                    "c_recp_return_invest",
                    "n_recp_disp_fiolta",
                    "c_pay_acq_const_fiolta",
                    "n_cashflow_inv_act",
                    "c_recp_borrow",
                    "c_prepay_amt_borr",
                    "c_pay_dist_dpcp_int_exp",
                    "n_cash_flows_fnc_act",
                    "n_incr_cash_cash_equ",
                    "c_cash_equ_end_period",
                ),
                default_years=8,
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
                    "roe_dt",
                    "roa",
                    "grossprofit_margin",
                    "netprofit_margin",
                    "sales_gpr",
                    "profit_to_gr",
                    "debt_to_assets",
                    "current_ratio",
                    "quick_ratio",
                    "assets_to_eqt",
                    "or_yoy",
                    "q_sales_yoy",
                    "netprofit_yoy",
                    "q_netprofit_yoy",
                    "ocf_to_revenue",
                    "ocfps",
                    "roe_yoy",
                    "bps",
                    "profit_dedt",
                    "update_flag",
                ),
                date_fields=("ann_date", "end_date"),
                decimal_fields=(
                    "eps",
                    "dt_eps",
                    "roe",
                    "roe_waa",
                    "roe_dt",
                    "roa",
                    "grossprofit_margin",
                    "netprofit_margin",
                    "sales_gpr",
                    "profit_to_gr",
                    "debt_to_assets",
                    "current_ratio",
                    "quick_ratio",
                    "assets_to_eqt",
                    "or_yoy",
                    "q_sales_yoy",
                    "netprofit_yoy",
                    "q_netprofit_yoy",
                    "ocf_to_revenue",
                    "ocfps",
                    "roe_yoy",
                    "bps",
                    "profit_dedt",
                ),
                default_years=8,
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
                default_years=8,
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
                default_years=5,
            ),
        ),
        BUSINESS_PROFILE_PACKAGE: (
            FetchApiSpec(
                package_name=BUSINESS_PROFILE_PACKAGE,
                api_name="fina_mainbz",
                model=AMainBusinessComposition,
                fields=(
                    "ts_code",
                    "end_date",
                    "bz_item",
                    "bz_sales",
                    "bz_profit",
                    "bz_cost",
                    "curr_type",
                    "update_flag",
                ),
                date_fields=("end_date",),
                decimal_fields=("bz_sales", "bz_profit", "bz_cost"),
                default_years=8,
                extra_params={"type": "P"},
                static_fields={"business_type": "PRODUCT"},
            ),
            FetchApiSpec(
                package_name=BUSINESS_PROFILE_PACKAGE,
                api_name="fina_mainbz",
                model=AMainBusinessComposition,
                fields=(
                    "ts_code",
                    "end_date",
                    "bz_item",
                    "bz_sales",
                    "bz_profit",
                    "bz_cost",
                    "curr_type",
                    "update_flag",
                ),
                date_fields=("end_date",),
                decimal_fields=("bz_sales", "bz_profit", "bz_cost"),
                default_years=8,
                extra_params={"type": "D"},
                static_fields={"business_type": "REGION"},
            ),
            FetchApiSpec(
                package_name=BUSINESS_PROFILE_PACKAGE,
                api_name="fina_audit",
                model=AFinancialAudit,
                fields=(
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "audit_result",
                    "audit_fees",
                    "audit_agency",
                    "audit_sign",
                ),
                date_fields=("ann_date", "end_date"),
                decimal_fields=("audit_fees",),
                default_years=8,
            ),
            FetchApiSpec(
                package_name=BUSINESS_PROFILE_PACKAGE,
                api_name="express",
                model=AExpress,
                fields=(
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "revenue",
                    "operate_profit",
                    "total_profit",
                    "n_income",
                    "total_assets",
                    "total_hldr_eqy_exc_min_int",
                    "diluted_eps",
                    "diluted_roe",
                    "yoy_net_profit",
                    "bps",
                    "yoy_sales",
                    "yoy_op",
                    "yoy_tp",
                    "yoy_dedu_np",
                    "yoy_eps",
                    "yoy_roe",
                    "growth_assets",
                    "yoy_equity",
                    "growth_bps",
                    "perf_summary",
                    "is_audit",
                    "remark",
                ),
                date_fields=("ann_date", "end_date"),
                decimal_fields=(
                    "revenue",
                    "operate_profit",
                    "total_profit",
                    "n_income",
                    "total_assets",
                    "total_hldr_eqy_exc_min_int",
                    "diluted_eps",
                    "diluted_roe",
                    "yoy_net_profit",
                    "bps",
                    "yoy_sales",
                    "yoy_op",
                    "yoy_tp",
                    "yoy_dedu_np",
                    "yoy_eps",
                    "yoy_roe",
                    "growth_assets",
                    "yoy_equity",
                    "growth_bps",
                ),
                default_years=5,
            ),
        ),
        SHAREHOLDER_GOVERNANCE_PACKAGE: (
            FetchApiSpec(
                package_name=SHAREHOLDER_GOVERNANCE_PACKAGE,
                api_name="top10_holders",
                model=ATop10Holder,
                fields=(
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "holder_name",
                    "hold_amount",
                    "hold_ratio",
                    "hold_float_ratio",
                    "hold_change",
                    "holder_type",
                ),
                date_fields=("ann_date", "end_date"),
                decimal_fields=("hold_amount", "hold_ratio", "hold_float_ratio", "hold_change"),
                default_years=5,
                static_fields={"holder_scope": "TOTAL"},
            ),
            FetchApiSpec(
                package_name=SHAREHOLDER_GOVERNANCE_PACKAGE,
                api_name="top10_floatholders",
                model=ATop10Holder,
                fields=(
                    "ts_code",
                    "ann_date",
                    "end_date",
                    "holder_name",
                    "hold_amount",
                    "hold_ratio",
                    "hold_float_ratio",
                    "hold_change",
                    "holder_type",
                ),
                date_fields=("ann_date", "end_date"),
                decimal_fields=("hold_amount", "hold_ratio", "hold_float_ratio", "hold_change"),
                default_years=5,
                static_fields={"holder_scope": "FLOAT"},
            ),
            FetchApiSpec(
                package_name=SHAREHOLDER_GOVERNANCE_PACKAGE,
                api_name="stk_holdernumber",
                model=AHolderNumber,
                fields=("ts_code", "ann_date", "end_date", "holder_num"),
                date_fields=("ann_date", "end_date"),
                decimal_fields=(),
                default_years=5,
            ),
            FetchApiSpec(
                package_name=SHAREHOLDER_GOVERNANCE_PACKAGE,
                api_name="pledge_stat",
                model=APledgeStat,
                fields=(
                    "ts_code",
                    "end_date",
                    "pledge_count",
                    "unrest_pledge",
                    "rest_pledge",
                    "total_share",
                    "pledge_ratio",
                ),
                date_fields=("end_date",),
                decimal_fields=("unrest_pledge", "rest_pledge", "total_share", "pledge_ratio"),
                default_years=5,
            ),
        ),
        CAPITAL_FLOW_PACKAGE: (
            FetchApiSpec(
                package_name=CAPITAL_FLOW_PACKAGE,
                api_name="moneyflow",
                model=AMoneyflow,
                fields=(
                    "ts_code",
                    "trade_date",
                    "buy_sm_vol",
                    "buy_sm_amount",
                    "sell_sm_vol",
                    "sell_sm_amount",
                    "buy_md_vol",
                    "buy_md_amount",
                    "sell_md_vol",
                    "sell_md_amount",
                    "buy_lg_vol",
                    "buy_lg_amount",
                    "sell_lg_vol",
                    "sell_lg_amount",
                    "buy_elg_vol",
                    "buy_elg_amount",
                    "sell_elg_vol",
                    "sell_elg_amount",
                    "net_mf_vol",
                    "net_mf_amount",
                ),
                date_fields=("trade_date",),
                decimal_fields=(
                    "buy_sm_vol",
                    "buy_sm_amount",
                    "sell_sm_vol",
                    "sell_sm_amount",
                    "buy_md_vol",
                    "buy_md_amount",
                    "sell_md_vol",
                    "sell_md_amount",
                    "buy_lg_vol",
                    "buy_lg_amount",
                    "sell_lg_vol",
                    "sell_lg_amount",
                    "buy_elg_vol",
                    "buy_elg_amount",
                    "sell_elg_vol",
                    "sell_elg_amount",
                    "net_mf_vol",
                    "net_mf_amount",
                ),
                default_days=60,
            ),
        ),
    }

    hk_specs: dict[str, tuple[FetchApiSpec, ...]] = {
        FINANCIAL_STATEMENT_PACKAGE: (
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="hk_fina_indicator",
                model=HKFinancialIndicator,
                fields=(
                    "ts_code",
                    "name",
                    "end_date",
                    "report_type",
                    "std_report_date",
                    "per_netcash_operate",
                    "per_oi",
                    "bps",
                    "basic_eps",
                    "diluted_eps",
                    "operate_income",
                    "operate_income_yoy",
                    "gross_profit",
                    "gross_profit_yoy",
                    "holder_profit",
                    "holder_profit_yoy",
                    "gross_profit_ratio",
                    "eps_ttm",
                    "operate_income_qoq",
                    "net_profit_ratio",
                    "roe_avg",
                    "gross_profit_qoq",
                    "roa",
                    "holder_profit_qoq",
                    "roe_yearly",
                    "roic_yearly",
                    "total_assets",
                    "total_liabilities",
                    "tax_ebt",
                    "ocf_sales",
                    "total_parent_equity",
                    "debt_asset_ratio",
                    "operate_profit",
                    "pretax_profit",
                    "netcash_operate",
                    "netcash_invest",
                    "netcash_finance",
                    "end_cash",
                    "divi_ratio",
                    "dividend_rate",
                    "current_ratio",
                    "currentdebt_debt",
                    "total_market_cap",
                    "hksk_market_cap",
                    "pe_ttm",
                    "pb_ttm",
                    "dps_hkd",
                    "start_date",
                    "fiscal_year",
                    "currency",
                    "dps_hkd_ly",
                    "org_type",
                    "equity_multiplier",
                    "equity_ratio",
                ),
                date_fields=("end_date", "std_report_date", "start_date"),
                decimal_fields=(
                    "per_netcash_operate",
                    "per_oi",
                    "bps",
                    "basic_eps",
                    "diluted_eps",
                    "operate_income",
                    "operate_income_yoy",
                    "gross_profit",
                    "gross_profit_yoy",
                    "holder_profit",
                    "holder_profit_yoy",
                    "gross_profit_ratio",
                    "eps_ttm",
                    "operate_income_qoq",
                    "net_profit_ratio",
                    "roe_avg",
                    "gross_profit_qoq",
                    "roa",
                    "holder_profit_qoq",
                    "roe_yearly",
                    "roic_yearly",
                    "total_assets",
                    "total_liabilities",
                    "tax_ebt",
                    "ocf_sales",
                    "total_parent_equity",
                    "debt_asset_ratio",
                    "operate_profit",
                    "pretax_profit",
                    "netcash_operate",
                    "netcash_invest",
                    "netcash_finance",
                    "end_cash",
                    "divi_ratio",
                    "dividend_rate",
                    "current_ratio",
                    "currentdebt_debt",
                    "total_market_cap",
                    "hksk_market_cap",
                    "pe_ttm",
                    "pb_ttm",
                    "dps_hkd",
                    "dps_hkd_ly",
                    "equity_multiplier",
                    "equity_ratio",
                ),
                default_years=8,
            ),
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="hk_income",
                model=HKFinancialStatementItem,
                fields=("ts_code", "end_date", "name", "ind_name", "ind_value"),
                date_fields=("end_date",),
                decimal_fields=("ind_value",),
                default_years=8,
                static_fields={"statement_type": "INCOME"},
            ),
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="hk_balancesheet",
                model=HKFinancialStatementItem,
                fields=("ts_code", "end_date", "name", "ind_name", "ind_value"),
                date_fields=("end_date",),
                decimal_fields=("ind_value",),
                default_years=8,
                static_fields={"statement_type": "BALANCE"},
            ),
            FetchApiSpec(
                package_name=FINANCIAL_STATEMENT_PACKAGE,
                api_name="hk_cashflow",
                model=HKFinancialStatementItem,
                fields=("ts_code", "end_date", "name", "ind_name", "ind_value"),
                date_fields=("end_date",),
                decimal_fields=("ind_value",),
                default_years=8,
                static_fields={"statement_type": "CASHFLOW"},
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

        # 港股财务接口是独立 API，字段形态也与 A 股不同；按代码后缀分流到港股白名单，
        # 保证 LLM 仍只能触发单股、固定包、固定字段的受控补数。
        spec_catalog = self.hk_specs if ts_code.upper().endswith(".HK") else self.specs
        specs = spec_catalog.get(package_name)
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
        if spec.extra_params:
            # 同一接口可能按业务口径拆分抓取，例如主营构成按产品和地区分别请求；
            # 固定参数只来自白名单配置，避免 LLM 自行扩展 Tushare 查询范围。
            params.update(spec.extra_params)
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
        if spec.static_fields:
            # Tushare 部分接口返回值不包含查询口径，本地补入固定字段；
            # 这样同一张表能区分产品/地区、全体/流通股东等不同业务口径。
            normalized.update(spec.static_fields)
        for field in spec.date_fields:
            normalized[field] = parse_tushare_date(normalized.get(field))
        for field in spec.decimal_fields:
            normalized[field] = to_decimal(normalized.get(field))
        if spec.api_name in {"income", "balancesheet", "cashflow"}:
            normalized["report_type"] = str(normalized.get("report_type") or "")
            normalized["update_flag"] = str(normalized.get("update_flag") or "")
        if spec.api_name == "hk_fina_indicator":
            normalized["report_type"] = str(normalized.get("report_type") or "")
            fiscal_year = normalized.get("fiscal_year")
            normalized["fiscal_year"] = int(fiscal_year) if fiscal_year not in (None, "") else None
        if spec.api_name in {"hk_income", "hk_balancesheet", "hk_cashflow"}:
            # 港股三大报表是“指标名/指标值”窄表，statement_type 来自白名单固定参数；
            # ind_name 为空的汇总/异常行不可复核，直接跳过，重跑仍不会产生脏数据。
            normalized["statement_type"] = str(normalized.get("statement_type") or "")
            normalized["ind_name"] = str(normalized.get("ind_name") or "")
        if spec.api_name == "dividend":
            normalized["div_proc"] = str(normalized.get("div_proc") or "")
        if spec.api_name == "forecast":
            normalized["type"] = str(normalized.get("type") or "")
        if spec.api_name == "fina_mainbz":
            normalized["business_type"] = str(normalized.get("business_type") or "")
            normalized["bz_item"] = str(normalized.get("bz_item") or "")
            normalized["update_flag"] = str(normalized.get("update_flag") or "")
        if spec.api_name in {"top10_holders", "top10_floatholders"}:
            normalized["holder_scope"] = str(normalized.get("holder_scope") or "")
            normalized["holder_name"] = str(normalized.get("holder_name") or "")
        normalized["raw_payload_json"] = json.dumps(row, ensure_ascii=False, default=str)
        model_columns = set(spec.model.__table__.columns.keys())
        filtered = {key: value for key, value in normalized.items() if key in model_columns}
        required_columns = {
            column.name
            for column in spec.model.__table__.columns
            if (
                not column.primary_key
                and not column.nullable
                and column.default is None
                and column.server_default is None
                and column.name not in {"created_at", "updated_at"}
            )
        }
        if any(filtered.get(column_name) in (None, "") for column_name in required_columns):
            return {}
        return filtered

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
