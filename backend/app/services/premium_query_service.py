from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from sqlalchemy import asc, desc, exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.market import (
    ATradeCalendar,
    HKTradeCalendar,
    HsgtConstituent,
    OfficialAHComparison,
    WatchlistStock,
)
from app.schemas.market import (
    PremiumListResponse,
    PremiumOfficialTrendPoint,
    PremiumPairOption,
    PremiumQueryResponse,
    PremiumSummaryResponse,
)
from app.services.decimal_utils import quantize_decimal

CONNECT_TYPES = ("SH_HK", "SZ_HK")
DEFAULT_METRIC_DIRECTION = "HA"
NEAR_TARGET_DISTANCE_PCT = Decimal("3")
ROLLING_WINDOWS = (20, 60, 120)
EX_RIGHT_PREFIXES = ("XD", "XR", "DR")


@dataclass(frozen=True)
class PremiumQueryFilters:
    """官方 AH 溢价查询条件。

    创建日期：2026-05-04
    author: sunshengxian
    """

    trade_date: date | None = None
    keyword: str | None = None
    channel: str | None = None
    min_premium: Decimal | None = None
    max_premium: Decimal | None = None
    min_ha_premium: Decimal | None = None
    max_ha_premium: Decimal | None = None
    direction: str = DEFAULT_METRIC_DIRECTION
    only_hk_connect: bool = False
    only_watchlist: bool = False


@dataclass(frozen=True)
class PremiumMetricBundle:
    """单只股票的溢价决策指标。

    创建日期：2026-05-04
    author: sunshengxian
    """

    metric_direction: str
    metric_premium_pct: Decimal | None
    premium_avg_20: Decimal | None
    premium_avg_60: Decimal | None
    premium_avg_120: Decimal | None
    premium_median_60: Decimal | None
    premium_p20_60: Decimal | None
    premium_p80_60: Decimal | None
    premium_percentile_60: Decimal | None
    premium_deviation_from_60d_avg: Decimal | None


class PremiumQueryService:
    """官方 AH 溢价查询和决策指标服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._connect_cache: dict[str, str | None] = {}
        self._latest_connect_date: date | None = None
        self._metric_cache: dict[tuple[str, str, date, str], PremiumMetricBundle] = {}

    def list_premiums(
        self,
        filters: PremiumQueryFilters,
        page: int,
        page_size: int,
        user_id: int | None = None,
    ) -> PremiumListResponse:
        """分页查询官方 AH 溢价。

        创建日期：2026-05-04
        author: sunshengxian
        """

        rows = self._query_rows(filters)
        watchlist_map = self._watchlist_map(user_id)
        if filters.only_watchlist:
            rows = [
                item
                for item in rows
                if (item.a_ts_code, item.hk_ts_code) in watchlist_map
            ]
        rows = [item for item in rows if self._matches_connect_filter(item, filters)]
        rows = sorted(
            rows,
            key=lambda item: self._metric_value(item, filters.direction) or Decimal("-999999"),
            reverse=True,
        )
        total = len(rows)
        start = (page - 1) * page_size
        items = [
            self.to_response(
                item,
                filters.direction,
                watchlist_map.get((item.a_ts_code, item.hk_ts_code)),
            )
            for item in rows[start : start + page_size]
        ]
        return PremiumListResponse(total=total, items=items)

    def summary(self, user_id: int | None = None) -> PremiumSummaryResponse:
        """获取最新交易日官方 AH 溢价总览。

        创建日期：2026-05-04
        author: sunshengxian
        """

        latest_trade_date = self.latest_trade_date()
        if latest_trade_date is None:
            return PremiumSummaryResponse(latest_trade_date=None, calculated_count=0, issue_count=0)
        base_filters = PremiumQueryFilters(trade_date=latest_trade_date, only_hk_connect=True)
        rows = self._query_rows(base_filters)
        hk_connect_rows = [
            item
            for item in rows
            if self._connect_channels(item.trade_date, item.hk_ts_code)
        ]
        calculated_count = self.db.scalar(
            select(func.count(OfficialAHComparison.id)).where(
                OfficialAHComparison.trade_date == latest_trade_date
            )
        ) or 0
        issue_count = self.db.scalar(
            select(func.count(OfficialAHComparison.id)).where(
                OfficialAHComparison.trade_date == latest_trade_date,
                OfficialAHComparison.is_realtime.is_(True),
            )
        ) or 0
        watchlist_map = self._watchlist_map(user_id)
        top = sorted(
            hk_connect_rows,
            key=lambda item: item.ah_premium or Decimal("-999999"),
            reverse=True,
        )[:10]
        bottom = sorted(
            hk_connect_rows,
            key=lambda item: item.ah_premium or Decimal("999999"),
        )[:10]
        return PremiumSummaryResponse(
            latest_trade_date=latest_trade_date,
            calculated_count=calculated_count,
            issue_count=issue_count,
            hk_connect_count=len(hk_connect_rows),
            watchlist_count=self._active_watchlist_count(user_id),
            top_premiums=[
                self.to_response(item, "AH", watchlist_map.get((item.a_ts_code, item.hk_ts_code)))
                for item in top
            ],
            bottom_premiums=[
                self.to_response(item, "AH", watchlist_map.get((item.a_ts_code, item.hk_ts_code)))
                for item in bottom
            ],
        )

    def list_pairs(self, keyword: str | None = None, limit: int = 80) -> list[PremiumPairOption]:
        """查询可展示趋势的 AH 配对。

        创建日期：2026-05-04
        author: sunshengxian
        """

        statement = select(
            OfficialAHComparison.a_ts_code,
            OfficialAHComparison.hk_ts_code,
            OfficialAHComparison.a_name,
            OfficialAHComparison.hk_name,
            OfficialAHComparison.trade_date,
        ).where(self._joint_trade_date_filter())
        if keyword:
            like = f"%{keyword.strip()}%"
            statement = statement.where(
                or_(
                    OfficialAHComparison.a_ts_code.like(like),
                    OfficialAHComparison.hk_ts_code.like(like),
                    OfficialAHComparison.a_name.like(like),
                    OfficialAHComparison.hk_name.like(like),
                )
            )
        rows = self.db.execute(
            statement.order_by(
                desc(OfficialAHComparison.trade_date),
                OfficialAHComparison.a_ts_code,
                OfficialAHComparison.hk_ts_code,
            )
        ).all()
        pair_map: dict[tuple[str, str], dict[str, object]] = {}
        for row in rows:
            key = (row.a_ts_code, row.hk_ts_code)
            current = pair_map.get(key)
            if current is None:
                pair_map[key] = {
                    "a_ts_code": row.a_ts_code,
                    "hk_ts_code": row.hk_ts_code,
                    "a_name": row.a_name,
                    "hk_name": row.hk_name,
                    "latest_trade_date": row.trade_date,
                }
                continue
            if self._prefer_display_name(current.get("a_name"), row.a_name):
                current["a_name"] = row.a_name
            if current.get("hk_name") is None and row.hk_name is not None:
                current["hk_name"] = row.hk_name
        return [
            PremiumPairOption(**value)
            for value in sorted(
                pair_map.values(),
                key=lambda item: item["latest_trade_date"] or date.min,
                reverse=True,
            )[:limit]
        ]

    def trend(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        direction: str = DEFAULT_METRIC_DIRECTION,
        user_id: int | None = None,
    ) -> list[PremiumQueryResponse]:
        """查询单个 AH 配对官方溢价趋势。

        创建日期：2026-05-04
        author: sunshengxian
        """

        statement = select(OfficialAHComparison).where(
            OfficialAHComparison.a_ts_code == a_ts_code,
            OfficialAHComparison.hk_ts_code == hk_ts_code,
            self._joint_trade_date_filter(),
        )
        if start_date:
            statement = statement.where(OfficialAHComparison.trade_date >= start_date)
        if end_date:
            statement = statement.where(OfficialAHComparison.trade_date <= end_date)
        rows = list(self.db.scalars(statement.order_by(OfficialAHComparison.trade_date)).all())
        watchlist = self._watchlist_map(user_id).get((a_ts_code, hk_ts_code))
        metrics = self._rolling_metrics(rows, direction)
        return [
            self.to_response(item, direction, watchlist, metric_override=metrics[index])
            for index, item in enumerate(rows)
        ]

    def official_trend_points(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        direction: str = DEFAULT_METRIC_DIRECTION,
    ) -> list[PremiumOfficialTrendPoint]:
        """查询官方 AH/H/A 溢价趋势点。

        创建日期：2026-05-04
        author: sunshengxian
        """

        rows = self.trend(a_ts_code, hk_ts_code, start_date, end_date, direction)
        return [
            PremiumOfficialTrendPoint(
                trade_date=item.trade_date,
                a_ts_code=item.a_ts_code,
                hk_ts_code=item.hk_ts_code,
                a_name=item.a_name,
                hk_name=item.hk_name,
                ah_ratio=item.ah_ratio,
                ah_premium_pct=item.ah_premium_pct,
                ha_ratio=item.ha_ratio,
                ha_premium_pct=item.ha_premium_pct,
                metric_direction=item.metric_direction,
                metric_premium_pct=item.metric_premium_pct,
                premium_avg_20=item.premium_avg_20,
                premium_avg_60=item.premium_avg_60,
                premium_avg_120=item.premium_avg_120,
                premium_median_60=item.premium_median_60,
                premium_p20_60=item.premium_p20_60,
                premium_p80_60=item.premium_p80_60,
                premium_percentile_60=item.premium_percentile_60,
                is_realtime=item.is_realtime,
            )
            for item in rows
        ]

    def latest_trade_date(self, include_realtime: bool = False) -> date | None:
        """查询官方 AH 比价最新交易日。

        创建日期：2026-05-04
        author: sunshengxian
        """

        filters = [self._joint_trade_date_filter()]
        if not include_realtime:
            filters.append(OfficialAHComparison.is_realtime.is_(False))
        return self.db.scalar(
            select(func.max(OfficialAHComparison.trade_date)).where(*filters)
        )

    def latest_pair_row(self, a_ts_code: str, hk_ts_code: str) -> OfficialAHComparison | None:
        """查询单个配对最新官方记录。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return self.db.scalar(
            select(OfficialAHComparison)
            .where(
                OfficialAHComparison.a_ts_code == a_ts_code,
                OfficialAHComparison.hk_ts_code == hk_ts_code,
                self._joint_trade_date_filter(),
            )
            .order_by(desc(OfficialAHComparison.trade_date))
            .limit(1)
        )

    def to_response(
        self,
        item: OfficialAHComparison,
        direction: str = DEFAULT_METRIC_DIRECTION,
        watchlist: WatchlistStock | None = None,
        metric_override: PremiumMetricBundle | None = None,
    ) -> PremiumQueryResponse:
        """将官方 AH 比价行转为前端响应。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized_direction = self._normalize_direction(
            watchlist.preferred_direction if watchlist else direction
        )
        metric = metric_override or self._metric_bundle(item, normalized_direction)
        connect_channels = self._connect_channels(item.trade_date, item.hk_ts_code)
        target = watchlist.target_premium_pct if watchlist else None
        distance = (
            quantize_decimal(target - metric.metric_premium_pct)
            if target is not None and metric.metric_premium_pct is not None
            else None
        )
        return PremiumQueryResponse(
            trade_date=item.trade_date,
            a_ts_code=item.a_ts_code,
            hk_ts_code=item.hk_ts_code,
            a_name=item.a_name,
            hk_name=item.hk_name,
            a_close=item.a_close,
            a_pct_chg=item.a_pct_chg,
            hk_close=item.hk_close,
            hk_pct_chg=item.hk_pct_chg,
            ah_ratio=item.ah_comparison,
            ah_premium_pct=item.ah_premium,
            ha_ratio=item.ha_comparison,
            ha_premium_pct=item.ha_premium,
            is_hk_connect=bool(connect_channels),
            connect_channels=connect_channels,
            metric_direction=metric.metric_direction,
            metric_premium_pct=metric.metric_premium_pct,
            premium_avg_20=metric.premium_avg_20,
            premium_avg_60=metric.premium_avg_60,
            premium_avg_120=metric.premium_avg_120,
            premium_median_60=metric.premium_median_60,
            premium_p20_60=metric.premium_p20_60,
            premium_p80_60=metric.premium_p80_60,
            premium_percentile_60=metric.premium_percentile_60,
            premium_deviation_from_60d_avg=metric.premium_deviation_from_60d_avg,
            watchlist_id=watchlist.id if watchlist else None,
            is_watchlist=watchlist is not None,
            watchlist_display_name=watchlist.display_name if watchlist else None,
            preferred_direction=watchlist.preferred_direction if watchlist else None,
            target_premium_pct=target,
            push_enabled=watchlist.push_enabled if watchlist else None,
            a_price_alert_enabled=watchlist.a_price_alert_enabled if watchlist else None,
            a_price_alert_operator=watchlist.a_price_alert_operator if watchlist else None,
            a_price_alert_target_price=watchlist.a_price_alert_target_price if watchlist else None,
            h_price_alert_enabled=watchlist.h_price_alert_enabled if watchlist else None,
            h_price_alert_operator=watchlist.h_price_alert_operator if watchlist else None,
            h_price_alert_target_price=watchlist.h_price_alert_target_price if watchlist else None,
            holding_market=watchlist.holding_market if watchlist else None,
            distance_to_target_pct=distance,
            opportunity_status=self._opportunity_status(
                metric.metric_premium_pct,
                distance,
                bool(connect_channels),
            ),
            is_realtime=item.is_realtime,
            data_source=item.data_source,
            source_updated_at=item.source_updated_at,
        )

    def _query_rows(self, filters: PremiumQueryFilters) -> list[OfficialAHComparison]:
        trade_date = filters.trade_date or self.latest_trade_date()
        if trade_date is None:
            return []
        statement = select(OfficialAHComparison).where(
            OfficialAHComparison.trade_date == trade_date,
            self._joint_trade_date_filter(),
        )
        if filters.keyword:
            like = f"%{filters.keyword.strip()}%"
            statement = statement.where(
                or_(
                    OfficialAHComparison.a_ts_code.like(like),
                    OfficialAHComparison.hk_ts_code.like(like),
                    OfficialAHComparison.a_name.like(like),
                    OfficialAHComparison.hk_name.like(like),
                )
            )
        if filters.min_premium is not None:
            statement = statement.where(OfficialAHComparison.ah_premium >= filters.min_premium)
        if filters.max_premium is not None:
            statement = statement.where(OfficialAHComparison.ah_premium <= filters.max_premium)
        if filters.min_ha_premium is not None:
            statement = statement.where(OfficialAHComparison.ha_premium >= filters.min_ha_premium)
        if filters.max_ha_premium is not None:
            statement = statement.where(OfficialAHComparison.ha_premium <= filters.max_ha_premium)
        return list(self.db.scalars(statement.order_by(asc(OfficialAHComparison.a_ts_code))).all())

    def _matches_connect_filter(
        self,
        item: OfficialAHComparison,
        filters: PremiumQueryFilters,
    ) -> bool:
        channels = self._connect_channels(item.trade_date, item.hk_ts_code)
        if filters.only_hk_connect and not channels:
            return False
        if filters.channel and filters.channel not in (channels or "").split(","):
            return False
        return True

    def _connect_channels(self, trade_date: date, hk_ts_code: str) -> str | None:
        _ = trade_date
        if hk_ts_code in self._connect_cache:
            return self._connect_cache[hk_ts_code]
        latest_connect_date = self._latest_hsgt_date()
        if latest_connect_date is None:
            self._connect_cache[hk_ts_code] = None
            return None
        channels = list(
            self.db.scalars(
                select(HsgtConstituent.connect_type)
                .where(
                    HsgtConstituent.trade_date == latest_connect_date,
                    HsgtConstituent.ts_code == hk_ts_code,
                    HsgtConstituent.connect_type.in_(CONNECT_TYPES),
                )
                .order_by(HsgtConstituent.connect_type)
            ).all()
        )
        value = ",".join(channels) if channels else None
        self._connect_cache[hk_ts_code] = value
        return value

    def _latest_hsgt_date(self) -> date | None:
        if self._latest_connect_date is None:
            self._latest_connect_date = self.db.scalar(select(func.max(HsgtConstituent.trade_date)))
        return self._latest_connect_date

    def _watchlist_map(self, user_id: int | None = None) -> dict[tuple[str, str], WatchlistStock]:
        statement = select(WatchlistStock).where(WatchlistStock.is_active.is_(True))
        if user_id is not None:
            statement = statement.where(WatchlistStock.user_id == user_id)
        rows = list(
            self.db.scalars(
                statement.order_by(WatchlistStock.sort_order, WatchlistStock.id)
            ).all()
        )
        # 官方 AH 表只能和成对关注项合并；单 A/单 H 自选留在自选接口中展示股价提醒状态。
        return {
            (item.a_ts_code, item.hk_ts_code): item
            for item in rows
            if item.target_type == "PAIR" and item.a_ts_code and item.hk_ts_code
        }

    def _active_watchlist_count(self, user_id: int | None = None) -> int:
        statement = select(func.count(WatchlistStock.id)).where(WatchlistStock.is_active.is_(True))
        if user_id is not None:
            statement = statement.where(WatchlistStock.user_id == user_id)
        return self.db.scalar(statement) or 0

    def _metric_bundle(
        self,
        item: OfficialAHComparison,
        direction: str,
    ) -> PremiumMetricBundle:
        normalized_direction = self._normalize_direction(direction)
        cache_key = (item.a_ts_code, item.hk_ts_code, item.trade_date, normalized_direction)
        if cache_key in self._metric_cache:
            return self._metric_cache[cache_key]
        history = list(
            self.db.scalars(
                select(OfficialAHComparison)
                .where(
                    OfficialAHComparison.a_ts_code == item.a_ts_code,
                    OfficialAHComparison.hk_ts_code == item.hk_ts_code,
                    OfficialAHComparison.trade_date <= item.trade_date,
                    self._joint_trade_date_filter(),
                )
                .order_by(desc(OfficialAHComparison.trade_date))
                .limit(max(ROLLING_WINDOWS))
            ).all()
        )
        history = list(reversed(history))
        metric = (
            self._rolling_metrics(history, normalized_direction)[-1]
            if history
            else self._empty_metric(normalized_direction)
        )
        self._metric_cache[cache_key] = metric
        return metric

    def _rolling_metrics(
        self,
        rows: list[OfficialAHComparison],
        direction: str,
    ) -> list[PremiumMetricBundle]:
        normalized_direction = self._normalize_direction(direction)
        values = [self._metric_value(item, normalized_direction) for item in rows]
        metrics: list[PremiumMetricBundle] = []
        for index, current in enumerate(values):
            avg_values: dict[int, Decimal | None] = {}
            for window in ROLLING_WINDOWS:
                window_values = values[max(0, index - window + 1) : index + 1]
                avg_values[window] = self._average(
                    [value for value in window_values if value is not None]
                )
            percentile_window = [
                value
                for value in values[max(0, index - 59) : index + 1]
                if value is not None
            ]
            percentile = self._percentile(current, percentile_window)
            median_60 = self._quantile(percentile_window, Decimal("0.5"))
            p20_60 = self._quantile(percentile_window, Decimal("0.2"))
            p80_60 = self._quantile(percentile_window, Decimal("0.8"))
            deviation = (
                quantize_decimal(current - avg_values[60])
                if current is not None and avg_values[60] is not None
                else None
            )
            metrics.append(
                PremiumMetricBundle(
                    metric_direction=normalized_direction,
                    metric_premium_pct=current,
                    premium_avg_20=avg_values[20],
                    premium_avg_60=avg_values[60],
                    premium_avg_120=avg_values[120],
                    premium_median_60=median_60,
                    premium_p20_60=p20_60,
                    premium_p80_60=p80_60,
                    premium_percentile_60=percentile,
                    premium_deviation_from_60d_avg=deviation,
                )
            )
        return metrics

    def _empty_metric(self, direction: str) -> PremiumMetricBundle:
        return PremiumMetricBundle(
            metric_direction=direction,
            metric_premium_pct=None,
            premium_avg_20=None,
            premium_avg_60=None,
            premium_avg_120=None,
            premium_median_60=None,
            premium_p20_60=None,
            premium_p80_60=None,
            premium_percentile_60=None,
            premium_deviation_from_60d_avg=None,
        )

    def _metric_value(self, item: OfficialAHComparison, direction: str) -> Decimal | None:
        return item.ah_premium if self._normalize_direction(direction) == "AH" else item.ha_premium

    def _joint_trade_date_filter(self):
        """过滤为 A 股和港股同时开市的官方溢价日期。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return (
            exists(
                select(1).where(
                    ATradeCalendar.exchange == "SSE",
                    ATradeCalendar.cal_date == OfficialAHComparison.trade_date,
                    ATradeCalendar.is_open == 1,
                )
            )
            & exists(
                select(1).where(
                    HKTradeCalendar.cal_date == OfficialAHComparison.trade_date,
                    HKTradeCalendar.is_open == 1,
                )
            )
        )

    def _normalize_direction(self, value: str | None) -> str:
        return "AH" if str(value or "").upper() == "AH" else "HA"

    def _prefer_display_name(self, current: object, candidate: str | None) -> bool:
        if not candidate:
            return False
        if not current:
            return True
        return self._is_ex_right_name(str(current)) and not self._is_ex_right_name(candidate)

    def _is_ex_right_name(self, value: str) -> bool:
        return value.strip().upper().startswith(EX_RIGHT_PREFIXES)

    def _average(self, values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return quantize_decimal(sum(values) / Decimal(len(values)))

    def _quantile(self, values: list[Decimal], ratio: Decimal) -> Decimal | None:
        if not values:
            return None
        sorted_values = sorted(values)
        position = Decimal(len(sorted_values) - 1) * ratio
        lower_index = int(position.to_integral_value(rounding=ROUND_FLOOR))
        upper_index = int(position.to_integral_value(rounding=ROUND_CEILING))
        if lower_index == upper_index:
            return quantize_decimal(sorted_values[lower_index])
        weight = position - Decimal(lower_index)
        return quantize_decimal(
            sorted_values[lower_index]
            + (sorted_values[upper_index] - sorted_values[lower_index]) * weight
        )

    def _percentile(self, current: Decimal | None, values: list[Decimal]) -> Decimal | None:
        if current is None or not values:
            return None
        below_or_equal = sum(1 for value in values if value <= current)
        return quantize_decimal(Decimal(below_or_equal) * Decimal("100") / Decimal(len(values)))

    def _opportunity_status(
        self,
        current: Decimal | None,
        distance: Decimal | None,
        is_hk_connect: bool,
    ) -> str:
        if current is None:
            return "DATA_ISSUE"
        if not is_hk_connect:
            return "NOT_CONNECT"
        if distance is None:
            return "WATCH"
        if distance <= Decimal("0"):
            return "REACHED"
        if distance <= NEAR_TARGET_DISTANCE_PCT:
            return "NEAR"
        return "WATCH"
