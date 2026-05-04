from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.market import (
    ADailyQuote,
    AHPremiumDaily,
    AHStockPair,
    AStockBasic,
    ATradeCalendar,
    FxRateDaily,
    HKDailyQuote,
    HKStockBasic,
    HKTradeCalendar,
    HsgtConstituent,
    OfficialAHComparison,
    WatchlistStock,
)
from app.db.models.sync import SyncRun
from app.schemas.query import DataQueryResponse, QueryColumn, QueryDatasetInfo


@dataclass(frozen=True)
class QueryDatasetSpec:
    """查询数据集白名单配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    name: str
    label: str
    description: str
    model: type
    columns: tuple[QueryColumn, ...]
    keyword_fields: tuple[str, ...] = ()
    date_field: str | None = None
    default_order: tuple[tuple[str, str], ...] = ()


def col(key: str, label: str, width: int | None = None) -> QueryColumn:
    """创建列定义。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return QueryColumn(key=key, label=label, width=width)


DATA_QUERY_SPECS: dict[str, QueryDatasetSpec] = {
    "a_stock_basic": QueryDatasetSpec(
        name="a_stock_basic",
        label="A 股基础信息",
        description="已同步的 A 股股票基础资料。",
        model=AStockBasic,
        columns=(
            col("ts_code", "代码", 130),
            col("name", "名称", 130),
            col("industry", "行业", 140),
            col("area", "地区", 100),
            col("market", "市场", 100),
            col("exchange", "交易所", 100),
            col("list_status", "上市状态", 100),
            col("list_date", "上市日期", 132),
            col("is_hs", "沪深港通", 110),
        ),
        keyword_fields=("ts_code", "symbol", "name", "industry", "area"),
        default_order=(("ts_code", "asc"),),
    ),
    "hk_stock_basic": QueryDatasetSpec(
        name="hk_stock_basic",
        label="港股基础信息",
        description="已同步的港股基础资料。",
        model=HKStockBasic,
        columns=(
            col("ts_code", "代码", 130),
            col("name", "名称", 150),
            col("fullname", "全称", 220),
            col("market", "市场", 110),
            col("list_status", "上市状态", 100),
            col("list_date", "上市日期", 132),
            col("trade_unit", "交易单位", 110),
            col("curr_type", "币种", 90),
        ),
        keyword_fields=("ts_code", "name", "fullname", "enname", "cn_spell"),
        default_order=(("ts_code", "asc"),),
    ),
    "a_trade_calendar": QueryDatasetSpec(
        name="a_trade_calendar",
        label="A 股交易日历",
        description="A 股交易日历。",
        model=ATradeCalendar,
        columns=(
            col("exchange", "交易所", 100),
            col("cal_date", "日期", 132),
            col("is_open", "是否开市", 100),
            col("pretrade_date", "上一交易日", 132),
        ),
        keyword_fields=("exchange",),
        date_field="cal_date",
        default_order=(("cal_date", "desc"),),
    ),
    "hk_trade_calendar": QueryDatasetSpec(
        name="hk_trade_calendar",
        label="港股交易日历",
        description="港股交易日历。",
        model=HKTradeCalendar,
        columns=(
            col("cal_date", "日期", 132),
            col("is_open", "是否开市", 100),
            col("pretrade_date", "上一交易日", 132),
        ),
        date_field="cal_date",
        default_order=(("cal_date", "desc"),),
    ),
    "a_daily_quote": QueryDatasetSpec(
        name="a_daily_quote",
        label="A 股日线行情",
        description="已同步的 A 股日线行情。",
        model=ADailyQuote,
        columns=(
            col("trade_date", "交易日", 132),
            col("ts_code", "代码", 130),
            col("open", "开盘", 100),
            col("high", "最高", 100),
            col("low", "最低", 100),
            col("close", "收盘", 100),
            col("pct_chg", "涨跌幅", 100),
            col("vol", "成交量", 120),
            col("amount", "成交额", 120),
        ),
        keyword_fields=("ts_code",),
        date_field="trade_date",
        default_order=(("trade_date", "desc"), ("ts_code", "asc")),
    ),
    "hk_daily_quote": QueryDatasetSpec(
        name="hk_daily_quote",
        label="港股日线行情",
        description="已同步的港股日线行情。",
        model=HKDailyQuote,
        columns=(
            col("trade_date", "交易日", 132),
            col("ts_code", "代码", 130),
            col("open", "开盘", 100),
            col("high", "最高", 100),
            col("low", "最低", 100),
            col("close", "收盘", 100),
            col("pct_chg", "涨跌幅", 100),
            col("vol", "成交量", 120),
            col("amount", "成交额", 120),
        ),
        keyword_fields=("ts_code",),
        date_field="trade_date",
        default_order=(("trade_date", "desc"), ("ts_code", "asc")),
    ),
    "hsgt_constituent": QueryDatasetSpec(
        name="hsgt_constituent",
        label="沪深港通名单",
        description="沪股通、深股通、港股通名单。",
        model=HsgtConstituent,
        columns=(
            col("trade_date", "交易日", 132),
            col("connect_type", "通道", 110),
            col("ts_code", "代码", 130),
            col("name", "名称", 150),
            col("type_name", "类型名称", 140),
        ),
        keyword_fields=("ts_code", "name", "connect_type", "type_name"),
        date_field="trade_date",
        default_order=(("trade_date", "desc"), ("connect_type", "asc"), ("ts_code", "asc")),
    ),
    "fx_rate_daily": QueryDatasetSpec(
        name="fx_rate_daily",
        label="外汇日线",
        description="已同步或人工导入的外汇日线。",
        model=FxRateDaily,
        columns=(
            col("rate_date", "日期", 132),
            col("rate_pair", "汇率对", 120),
            col("mid_rate", "中间价", 120),
            col("bid_close", "买价", 120),
            col("ask_close", "卖价", 120),
            col("source", "来源", 140),
            col("raw_ts_code", "原始代码", 130),
        ),
        keyword_fields=("rate_pair", "source", "raw_ts_code"),
        date_field="rate_date",
        default_order=(("rate_date", "desc"), ("rate_pair", "asc")),
    ),
    "ah_stock_pair": QueryDatasetSpec(
        name="ah_stock_pair",
        label="AH 配对",
        description="官方比价或人工导入维护的 AH 股票配对。",
        model=AHStockPair,
        columns=(
            col("a_ts_code", "A 股代码", 130),
            col("a_name", "A 股名称", 140),
            col("hk_ts_code", "H 股代码", 130),
            col("hk_name", "H 股名称", 150),
            col("source", "来源", 140),
            col("effective_start_date", "生效开始", 132),
            col("effective_end_date", "生效结束", 132),
            col("is_active", "启用", 90),
        ),
        keyword_fields=("a_ts_code", "hk_ts_code", "a_name", "hk_name", "source"),
        default_order=(("a_ts_code", "asc"),),
    ),
    "official_ah_comparison": QueryDatasetSpec(
        name="official_ah_comparison",
        label="官方 AH 比价",
        description="Tushare 官方 AH 比价快照。",
        model=OfficialAHComparison,
        columns=(
            col("trade_date", "交易日", 132),
            col("a_ts_code", "A 股代码", 130),
            col("a_name", "A 股名称", 140),
            col("a_close", "A 股收盘", 110),
            col("hk_ts_code", "H 股代码", 130),
            col("hk_name", "H 股名称", 150),
            col("hk_close", "H 股收盘", 110),
            col("ah_comparison", "AH 比价", 120),
            col("ah_premium", "AH 溢价", 120),
            col("ha_comparison", "H/A 比价", 120),
            col("ha_premium", "H/A 溢价", 120),
            col("is_realtime", "实时", 90),
            col("data_source", "来源", 140),
            col("source_updated_at", "来源更新时间", 190),
        ),
        keyword_fields=("a_ts_code", "hk_ts_code", "a_name", "hk_name", "data_source"),
        date_field="trade_date",
        default_order=(("trade_date", "desc"), ("ah_premium", "desc")),
    ),
    "watchlist_stock": QueryDatasetSpec(
        name="watchlist_stock",
        label="自选股票",
        description="用户关注的 AH 股票和阈值配置。",
        model=WatchlistStock,
        columns=(
            col("id", "ID", 80),
            col("a_ts_code", "A 股代码", 130),
            col("hk_ts_code", "H 股代码", 130),
            col("display_name", "展示名", 160),
            col("preferred_direction", "关注方向", 110),
            col("target_premium_pct", "目标阈值", 120),
            col("holding_market", "持有侧", 100),
            col("sort_order", "排序", 90),
            col("note", "备注", 220),
            col("is_active", "启用", 90),
            col("updated_at", "更新时间", 190),
        ),
        keyword_fields=("a_ts_code", "hk_ts_code", "display_name", "preferred_direction", "note"),
        default_order=(("sort_order", "asc"), ("id", "asc")),
    ),
    "ah_premium_daily": QueryDatasetSpec(
        name="ah_premium_daily",
        label="自算 AH 溢价",
        description="项目自算的港股通 AH 溢价结果。",
        model=AHPremiumDaily,
        columns=(
            col("trade_date", "交易日", 132),
            col("a_ts_code", "A 股代码", 130),
            col("a_name", "A 股名称", 140),
            col("hk_ts_code", "H 股代码", 130),
            col("hk_name", "H 股名称", 150),
            col("ah_premium_pct", "自算溢价", 120),
            col("ha_ratio", "H/A 比价", 120),
            col("ha_premium_pct", "H/A 溢价", 120),
            col("official_ha_ratio", "官方 H/A 比价", 130),
            col("official_ha_premium_pct", "官方 H/A 溢价", 130),
            col("calc_status", "状态", 130),
            col("connect_channels", "港股通通道", 130),
            col("error_message", "错误", 220),
        ),
        keyword_fields=("a_ts_code", "hk_ts_code", "a_name", "hk_name", "calc_status"),
        date_field="trade_date",
        default_order=(("trade_date", "desc"), ("ah_premium_pct", "desc")),
    ),
    "sync_run": QueryDatasetSpec(
        name="sync_run",
        label="同步任务",
        description="同步任务运行记录。",
        model=SyncRun,
        columns=(
            col("id", "ID", 80),
            col("dataset", "数据集", 150),
            col("status", "状态", 110),
            col("row_count", "行数", 100),
            col("started_at", "开始时间", 190),
            col("finished_at", "结束时间", 190),
            col("params_json", "参数", 320),
            col("error_message", "错误", 360),
        ),
        keyword_fields=("dataset", "status", "params_json", "error_message"),
        default_order=(("id", "desc"),),
    ),
}


class DataQueryService:
    """统一数据查询服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_datasets(self) -> list[QueryDatasetInfo]:
        """列出可查询数据集。

        创建日期：2026-05-04
        author: sunshengxian
        """

        return [
            QueryDatasetInfo(
                name=spec.name,
                label=spec.label,
                description=spec.description,
                date_field=spec.date_field,
                columns=list(spec.columns),
            )
            for spec in DATA_QUERY_SPECS.values()
        ]

    def query(
        self,
        dataset: str,
        keyword: str | None,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> DataQueryResponse:
        """执行白名单表查询。

        创建日期：2026-05-04
        author: sunshengxian
        """

        spec = DATA_QUERY_SPECS.get(dataset)
        if spec is None:
            raise ValueError(f"不支持查询的数据集：{dataset}")
        filters = self._build_filters(spec, keyword, start_date, end_date)
        total_statement = select(func.count()).select_from(spec.model)
        row_statement = select(spec.model)
        if filters:
            total_statement = total_statement.where(*filters)
            row_statement = row_statement.where(*filters)
        row_statement = row_statement.order_by(*self._order_by(spec))
        row_statement = row_statement.offset((page - 1) * page_size).limit(page_size)
        total = self.db.scalar(total_statement) or 0
        rows = [self._serialize_row(spec, item) for item in self.db.scalars(row_statement).all()]
        return DataQueryResponse(
            dataset=dataset,
            total=total,
            page=page,
            page_size=page_size,
            columns=list(spec.columns),
            rows=rows,
        )

    def _build_filters(
        self,
        spec: QueryDatasetSpec,
        keyword: str | None,
        start_date: date | None,
        end_date: date | None,
    ) -> list[Any]:
        filters: list[Any] = []
        clean_keyword = (keyword or "").strip()
        if clean_keyword and spec.keyword_fields:
            pattern = f"%{clean_keyword}%"
            filters.append(
                or_(*(getattr(spec.model, field).like(pattern) for field in spec.keyword_fields))
            )
        if spec.date_field:
            column = getattr(spec.model, spec.date_field)
            if start_date:
                filters.append(column >= start_date)
            if end_date:
                filters.append(column <= end_date)
        return filters

    def _order_by(self, spec: QueryDatasetSpec) -> list[Any]:
        clauses = []
        for field, direction in spec.default_order:
            column = getattr(spec.model, field)
            clauses.append(desc(column) if direction == "desc" else asc(column))
        return clauses

    def _serialize_row(self, spec: QueryDatasetSpec, row: Any) -> dict[str, Any]:
        return {column.key: self._to_jsonable(getattr(row, column.key)) for column in spec.columns}

    def _to_jsonable(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, date | datetime):
            return value.isoformat()
        return value
