from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.market import AStockBasic, StockSelectionFactorSnapshot
from app.services.date_utils import format_tushare_date, parse_tushare_date
from app.services.decimal_utils import quantize_decimal, to_decimal
from app.services.repository import UpsertRepository
from app.services.tushare_client import TushareClient

INDEX_CODES = {
    "hs300": "000300.SH",
    "sse50": "000016.SH",
    "csi300_value": "000919.CSI",
    "csi_dividend": "000922.CSI",
    "sse_dividend": "000015.SH",
    "sz_dividend": "399324.SZ",
}


@dataclass
class SelectionCandidate:
    """选股候选中间结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    ts_code: str
    score: Decimal
    tags: set[str]
    reasons: list[str]
    daily_basic: dict[str, Any]


class StockSelectionFactorService:
    """A 股选股因子宽表同步服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.client = TushareClient(get_settings())
        self.repository = UpsertRepository(db)

    def sync_curated_factors(self, max_count: int = 60) -> int:
        """联网筛选蓝筹、低估值和红利股，并同步核心宽表。

        创建日期：2026-05-04
        author: sunshengxian
        """

        trade_date, daily_rows = self._fetch_latest_daily_basic()
        stock_map = self._stock_basic_map()
        index_members = self._fetch_index_members(trade_date)
        candidates = self._select_candidates(daily_rows, index_members, max_count)
        rows = [
            self._build_factor_row(candidate, trade_date, stock_map, index_members)
            for candidate in candidates
        ]
        row_count = self.repository.upsert_many(StockSelectionFactorSnapshot, rows)
        self.db.commit()
        return row_count

    def _fetch_latest_daily_basic(self) -> tuple[date, list[dict[str, Any]]]:
        fields = [
            "ts_code",
            "trade_date",
            "close",
            "turnover_rate",
            "pe_ttm",
            "pb",
            "ps_ttm",
            "dv_ttm",
            "total_mv",
            "circ_mv",
        ]
        for offset in range(20):
            current = date.today() - timedelta(days=offset)
            result = self.client.query(
                "daily_basic",
                params={"trade_date": format_tushare_date(current)},
                fields=fields,
            )
            if result.rows:
                return current, result.rows
        raise ValueError("最近 20 天未获取到 daily_basic 数据")

    def _fetch_index_members(self, trade_date: date) -> dict[str, dict[str, Decimal]]:
        members: dict[str, dict[str, Decimal]] = {}
        for name, index_code in INDEX_CODES.items():
            result = self.client.query(
                "index_weight",
                params={
                    "index_code": index_code,
                    "trade_date": format_tushare_date(trade_date),
                },
                fields=["con_code", "weight"],
            )
            members[name] = {
                str(row["con_code"]): to_decimal(row.get("weight")) or Decimal("0")
                for row in result.rows
                if row.get("con_code")
            }
        return members

    def _stock_basic_map(self) -> dict[str, AStockBasic]:
        statement = select(AStockBasic)
        return {item.ts_code: item for item in self.db.scalars(statement).all()}

    def _select_candidates(
        self,
        daily_rows: list[dict[str, Any]],
        index_members: dict[str, dict[str, Decimal]],
        max_count: int,
    ) -> list[SelectionCandidate]:
        candidates = [
            candidate
            for row in daily_rows
            if (candidate := self._build_candidate(row, index_members)) is not None
        ]
        blue = [item for item in candidates if "BLUE_CHIP" in item.tags]
        value = [item for item in candidates if "LOW_VALUATION" in item.tags]
        dividend = [item for item in candidates if "DIVIDEND" in item.tags]
        selected: dict[str, SelectionCandidate] = {}
        for bucket, limit in [(blue, 24), (value, 24), (dividend, 24)]:
            for item in sorted(bucket, key=lambda item: item.score, reverse=True)[:limit]:
                selected[item.ts_code] = item
        for item in sorted(candidates, key=lambda item: item.score, reverse=True):
            if len(selected) >= max_count:
                break
            selected[item.ts_code] = item
        return sorted(selected.values(), key=lambda item: item.score, reverse=True)[:max_count]

    def _build_candidate(
        self,
        row: dict[str, Any],
        index_members: dict[str, dict[str, Decimal]],
    ) -> SelectionCandidate | None:
        ts_code = str(row.get("ts_code") or "")
        if not ts_code:
            return None
        pe_ttm = to_decimal(row.get("pe_ttm"))
        pb = to_decimal(row.get("pb"))
        dividend_yield = to_decimal(row.get("dv_ttm"))
        total_mv = to_decimal(row.get("total_mv"))
        if total_mv is None or total_mv < Decimal("1000000"):
            return None

        tags: set[str] = set()
        reasons: list[str] = []
        score = Decimal("0")
        if ts_code in index_members["hs300"] or ts_code in index_members["sse50"]:
            tags.add("BLUE_CHIP")
            reasons.append("核心宽基指数成分")
            score += Decimal("20")
            score += min(total_mv / Decimal("10000000"), Decimal("25"))
        if ts_code in index_members["csi300_value"] or self._is_low_value(pe_ttm, pb, total_mv):
            tags.add("LOW_VALUATION")
            reasons.append("估值处于低估值筛选区间")
            score += Decimal("20")
            score += self._valuation_score(pe_ttm, pb)
        if (
            ts_code in index_members["csi_dividend"]
            or ts_code in index_members["sse_dividend"]
            or ts_code in index_members["sz_dividend"]
            or (dividend_yield is not None and dividend_yield >= Decimal("2.5"))
        ):
            tags.add("DIVIDEND")
            reasons.append("红利指数成分或滚动股息率较高")
            score += Decimal("18")
            score += self._dividend_score(dividend_yield)
        if not tags:
            return None
        return SelectionCandidate(
            ts_code=ts_code,
            score=score,
            tags=tags,
            reasons=reasons,
            daily_basic=row,
        )

    def _is_low_value(
        self,
        pe_ttm: Decimal | None,
        pb: Decimal | None,
        total_mv: Decimal | None,
    ) -> bool:
        return (
            pe_ttm is not None
            and pb is not None
            and total_mv is not None
            and Decimal("0") < pe_ttm <= Decimal("18")
            and Decimal("0") < pb <= Decimal("2")
            and total_mv >= Decimal("3000000")
        )

    def _valuation_score(self, pe_ttm: Decimal | None, pb: Decimal | None) -> Decimal:
        score = Decimal("0")
        if pe_ttm is not None and pe_ttm > 0:
            if pe_ttm <= Decimal("10"):
                score += Decimal("20")
            elif pe_ttm <= Decimal("15"):
                score += Decimal("14")
            elif pe_ttm <= Decimal("20"):
                score += Decimal("8")
        if pb is not None and pb > 0:
            if pb <= Decimal("1"):
                score += Decimal("12")
            elif pb <= Decimal("1.5"):
                score += Decimal("8")
            elif pb <= Decimal("2"):
                score += Decimal("4")
        return score

    def _dividend_score(self, dividend_yield: Decimal | None) -> Decimal:
        if dividend_yield is None:
            return Decimal("0")
        if dividend_yield >= Decimal("5"):
            return Decimal("20")
        if dividend_yield >= Decimal("4"):
            return Decimal("16")
        if dividend_yield >= Decimal("3"):
            return Decimal("12")
        if dividend_yield >= Decimal("2"):
            return Decimal("6")
        return Decimal("0")

    def _build_factor_row(
        self,
        candidate: SelectionCandidate,
        trade_date: date,
        stock_map: dict[str, AStockBasic],
        index_members: dict[str, dict[str, Decimal]],
    ) -> dict[str, Any]:
        stock = stock_map.get(candidate.ts_code)
        fina = self._latest_fina_indicator(candidate.ts_code)
        returns = self._return_factors(candidate.ts_code, trade_date)
        dividend = self._latest_dividend(candidate.ts_code)
        forecast = self._latest_forecast(candidate.ts_code)
        score = candidate.score + self._quality_score(fina)
        tags = set(candidate.tags)
        if self._quality_score(fina) > 0:
            tags.add("QUALITY")
            candidate.reasons.append("最近报告期盈利质量指标较好")
        daily = candidate.daily_basic
        return {
            "factor_date": trade_date,
            "ts_code": candidate.ts_code,
            "symbol": stock.symbol if stock else candidate.ts_code.split(".")[0],
            "name": stock.name if stock else candidate.ts_code,
            "industry": stock.industry if stock else None,
            "area": stock.area if stock else None,
            "market": stock.market if stock else None,
            "selection_tags": ",".join(sorted(tags)),
            "selection_score": quantize_decimal(score),
            "selection_reason": "；".join(candidate.reasons),
            "is_hs300": candidate.ts_code in index_members["hs300"],
            "is_sse50": candidate.ts_code in index_members["sse50"],
            "is_csi300_value": candidate.ts_code in index_members["csi300_value"],
            "is_csi_dividend": candidate.ts_code in index_members["csi_dividend"],
            "is_sse_dividend": candidate.ts_code in index_members["sse_dividend"],
            "is_sz_dividend": candidate.ts_code in index_members["sz_dividend"],
            "close": to_decimal(daily.get("close")),
            "pct_chg": to_decimal(daily.get("pct_chg")),
            "turnover_rate": to_decimal(daily.get("turnover_rate")),
            "pe_ttm": to_decimal(daily.get("pe_ttm")),
            "pb": to_decimal(daily.get("pb")),
            "ps_ttm": to_decimal(daily.get("ps_ttm")),
            "dividend_yield_ttm": to_decimal(daily.get("dv_ttm")),
            "total_mv": to_decimal(daily.get("total_mv")),
            "circ_mv": to_decimal(daily.get("circ_mv")),
            "roe": to_decimal(fina.get("roe")),
            "grossprofit_margin": to_decimal(fina.get("grossprofit_margin")),
            "netprofit_margin": to_decimal(fina.get("netprofit_margin")),
            "debt_to_assets": to_decimal(fina.get("debt_to_assets")),
            "revenue_yoy": to_decimal(fina.get("or_yoy")),
            "latest_report_period": parse_tushare_date(fina.get("end_date")),
            "return_20d": returns.get("return_20d"),
            "return_60d": returns.get("return_60d"),
            "return_120d": returns.get("return_120d"),
            "latest_dividend_year": dividend.get("end_date"),
            "latest_cash_div_tax": to_decimal(dividend.get("cash_div_tax")),
            "latest_dividend_proc": dividend.get("div_proc"),
            "forecast_type": forecast.get("type"),
            "forecast_summary": forecast.get("summary"),
            "data_source": "TUSHARE",
            "source_trade_date": trade_date,
        }

    def _quality_score(self, fina: dict[str, Any]) -> Decimal:
        score = Decimal("0")
        roe = to_decimal(fina.get("roe"))
        debt = to_decimal(fina.get("debt_to_assets"))
        revenue_yoy = to_decimal(fina.get("or_yoy"))
        if roe is not None:
            if roe >= Decimal("15"):
                score += Decimal("10")
            elif roe >= Decimal("10"):
                score += Decimal("6")
        if debt is not None and debt <= Decimal("55"):
            score += Decimal("4")
        if revenue_yoy is not None and revenue_yoy > 0:
            score += Decimal("3")
        return score

    def _latest_fina_indicator(self, ts_code: str) -> dict[str, Any]:
        result = self.client.query(
            "fina_indicator",
            params={"ts_code": ts_code},
            fields=[
                "ts_code",
                "ann_date",
                "end_date",
                "roe",
                "grossprofit_margin",
                "netprofit_margin",
                "debt_to_assets",
                "or_yoy",
            ],
        )
        return self._latest_by_date(result.rows, "end_date")

    def _latest_dividend(self, ts_code: str) -> dict[str, Any]:
        result = self.client.query(
            "dividend",
            params={"ts_code": ts_code},
            fields=["ts_code", "end_date", "ann_date", "div_proc", "cash_div_tax"],
        )
        return self._latest_by_date(result.rows, "end_date")

    def _latest_forecast(self, ts_code: str) -> dict[str, Any]:
        result = self.client.query(
            "forecast",
            params={"ts_code": ts_code},
            fields=["ts_code", "ann_date", "end_date", "type", "summary"],
        )
        return self._latest_by_date(result.rows, "ann_date")

    def _return_factors(self, ts_code: str, trade_date: date) -> dict[str, Decimal | None]:
        start_date = trade_date - timedelta(days=220)
        result = self.client.query(
            "daily",
            params={
                "ts_code": ts_code,
                "start_date": format_tushare_date(start_date),
                "end_date": format_tushare_date(trade_date),
            },
            fields=["trade_date", "close"],
        )
        rows = sorted(
            [row for row in result.rows if row.get("close") is not None],
            key=lambda row: str(row.get("trade_date")),
        )
        if not rows:
            return {"return_20d": None, "return_60d": None, "return_120d": None}
        latest_close = to_decimal(rows[-1].get("close"))
        return {
            "return_20d": self._period_return(rows, latest_close, 20),
            "return_60d": self._period_return(rows, latest_close, 60),
            "return_120d": self._period_return(rows, latest_close, 120),
        }

    def _period_return(
        self,
        rows: list[dict[str, Any]],
        latest_close: Decimal | None,
        window: int,
    ) -> Decimal | None:
        if latest_close is None or len(rows) <= window:
            return None
        base_close = to_decimal(rows[-window - 1].get("close"))
        if base_close is None or base_close == 0:
            return None
        return quantize_decimal((latest_close / base_close - Decimal("1")) * Decimal("100"))

    def _latest_by_date(self, rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
        valid_rows = [row for row in rows if row.get(field)]
        if not valid_rows:
            return {}
        return max(valid_rows, key=lambda row: str(row.get(field)))
