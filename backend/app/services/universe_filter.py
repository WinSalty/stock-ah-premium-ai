"""可交易股票池过滤（universe_filter）。

业务意图：统一"哪些股票可参与"的口径，三处复用同一实现——信号侧落表前过滤、回测样本
    构建、QMT 下单前兜底——保证口径一致。只参与主板+创业板，排除 ST/*ST/退市整理、科创、
    北交、新三板与上市初期次新。
设计要点：
    - 纯判定核心 ``evaluate_universe`` 无 IO，全部数据由入参注入，便于单测与回测批量复用；
    - ``filter_for_trade_date`` / ``build_universe_context`` 负责查库后调核心；
    - ST 严格按"信号日 T 当日"(as_of_date) 判定，避免用"当前是否 ST"造成回测前视偏差。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.market import AStockBasic, AStockSt, ATradeCalendar

# 板块枚举：MAIN=主板(±10%)，GEM=创业板(±20%)。
Board = Literal["MAIN", "GEM"]

# 主板前缀：沪市 600/601/603/605，深市 000/001/002/003（原中小板 002/003 已并入主板）。
_MAIN_PREFIXES = frozenset({"600", "601", "603", "605", "000", "001", "002", "003"})
# 创业板前缀：300/301。
_GEM_PREFIXES = frozenset({"300", "301"})
# 白名单（保留集逻辑：未知前缀默认落选，对未来新增号段天然安全，不会误纳科创/北交）。
WHITELIST_PREFIXES = _MAIN_PREFIXES | _GEM_PREFIXES

# 次新过滤默认阈值（交易日）；与 config.limit_up_universe_new_listing_min_days 同义。
DEFAULT_NEW_LISTING_MIN_DAYS = 6

# a_trade_calendar 中 A 股交易日历的交易所口径（与 trade_cal 同步 default_params 对齐）。
_DEFAULT_EXCHANGE = "SSE"


@dataclass(frozen=True)
class UniverseVerdict:
    """股票池判定结果。

    reason 取值：OK / NOT_WHITELIST / ST / SUSPECT_ST / NO_LIST_DATE / NEW_LISTING。
    board：命中白名单时为 MAIN/GEM；NOT_WHITELIST 时为 None。
    """

    passed: bool
    reason: str
    board: Board | None


def _board_of(ts_code: str) -> Board | None:
    """按代码前 3 位判定板块；非白名单返回 None。"""

    prefix = ts_code[:3]
    if prefix in _GEM_PREFIXES:
        return "GEM"
    if prefix in _MAIN_PREFIXES:
        return "MAIN"
    return None


def looks_like_st(name: str | None) -> bool:
    """名称是否疑似 ST/退市（兜底判据，保守口径，宁可错杀边界票）。"""

    if not name:
        return False
    return "ST" in name.upper() or "退" in name


def evaluate_universe(
    ts_code: str,
    name: str | None,
    as_of_date: date,
    *,
    is_st_on_date: bool,
    list_date: date | None,
    trade_days_since_list: int | None,
    new_listing_min_days: int = DEFAULT_NEW_LISTING_MIN_DAYS,
) -> UniverseVerdict:
    """纯判定核心：无 IO，全部数据由入参注入。

    顺序短路：L1 前缀白名单 → L2 ST（含名称兜底）→ L3 次新；任一层落选即返回。
    非白名单先返回，确保不因 ST/次新数据缺失而报错。

    创建日期：2026-06-13
    author: claude
    """

    # L1 前缀白名单：先判，非白名单不再依赖 ST/次新数据
    board = _board_of(ts_code)
    if board is None:
        return UniverseVerdict(False, "NOT_WHITELIST", None)

    # L2 ST：按 as_of_date 当日状态（point-in-time），避免用当前状态造成未来函数
    if is_st_on_date:
        return UniverseVerdict(False, "ST", board)
    # 名称兜底：a_stock_st 未命中但名称含 ST/退（防同步滞后），按疑似 ST 落选
    if looks_like_st(name):
        return UniverseVerdict(False, "SUSPECT_ST", board)

    # L3 次新：list_date 缺失保守落选；上市未满阈值个交易日落选
    if list_date is None or trade_days_since_list is None:
        return UniverseVerdict(False, "NO_LIST_DATE", board)
    if trade_days_since_list < new_listing_min_days:
        return UniverseVerdict(False, "NEW_LISTING", board)

    return UniverseVerdict(True, "OK", board)


def _to_decimal(value: Decimal | float | int | str) -> Decimal:
    """统一转 Decimal（用 str 入参避免 float 二进制误差）。"""

    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round2(value: Decimal) -> Decimal:
    """四舍五入到分（ROUND_HALF_UP，与交易所一致，避免一字判定精度错配）。"""

    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _limit_rate(board: Board) -> Decimal:
    """板块涨跌幅档位：创业板 0.20(20cm)，主板 0.10。单一出处，避免两函数不同步。"""

    return Decimal("0.20") if board == "GEM" else Decimal("0.10")


def limit_up_price(pre_close: Decimal | float | int | str, board: Board) -> Decimal:
    """涨停价：主板 pre_close×1.10、创业板 ×1.20，四舍五入到分。"""

    return _round2(_to_decimal(pre_close) * (Decimal("1") + _limit_rate(board)))


def limit_down_price(pre_close: Decimal | float | int | str, board: Board) -> Decimal:
    """跌停价：主板 pre_close×0.90、创业板 ×0.80，四舍五入到分。"""

    return _round2(_to_decimal(pre_close) * (Decimal("1") - _limit_rate(board)))


@dataclass(frozen=True)
class UniverseContext:
    """批量判定上下文：回测一次性预取当日 ST 集合 + 上市日 + 交易日历，逐票判定不再查库。"""

    as_of_date: date
    st_codes: frozenset[str]
    list_dates: dict[str, date | None]
    # is_open=1 且 cal_date<=as_of_date 的交易日，升序
    open_dates_asc: tuple[date, ...]

    def trade_days_since_list(self, list_date: date | None) -> int | None:
        """上市日到 as_of_date 之间的开市交易日数（含上市日为第 1 日）。"""

        if list_date is None:
            return None
        # open_dates_asc 全部 <= as_of_date，统计 >= list_date 的个数
        idx = bisect.bisect_left(self.open_dates_asc, list_date)
        return len(self.open_dates_asc) - idx

    def evaluate(
        self,
        ts_code: str,
        name: str | None,
        *,
        new_listing_min_days: int = DEFAULT_NEW_LISTING_MIN_DAYS,
    ) -> UniverseVerdict:
        """用预取上下文判定单票，结果与 filter_for_trade_date 等价。

        注意：批量路径不回查证券简称，调用方须传入真实 name，否则 L2 名称兜底
        （SUSPECT_ST）会失效；落表/回测调用方均持有候选股名称，满足该前提。
        """

        list_date = self.list_dates.get(ts_code)
        return evaluate_universe(
            ts_code,
            name,
            self.as_of_date,
            is_st_on_date=ts_code in self.st_codes,
            list_date=list_date,
            trade_days_since_list=self.trade_days_since_list(list_date),
            new_listing_min_days=new_listing_min_days,
        )


def build_universe_context(
    db: Session,
    as_of_date: date,
    *,
    exchange: str = _DEFAULT_EXCHANGE,
) -> UniverseContext:
    """一次性预取 as_of_date 的 ST 集合、全市场上市日、交易日历，供批量判定。"""

    st_codes = frozenset(
        db.execute(
            select(AStockSt.ts_code).where(AStockSt.trade_date == as_of_date)
        ).scalars()
    )
    list_dates: dict[str, date | None] = dict(
        db.execute(select(AStockBasic.ts_code, AStockBasic.list_date)).all()
    )
    open_dates = (
        db.execute(
            select(ATradeCalendar.cal_date)
            .where(
                ATradeCalendar.exchange == exchange,
                ATradeCalendar.is_open == 1,
                ATradeCalendar.cal_date <= as_of_date,
            )
            .order_by(ATradeCalendar.cal_date)
        )
        .scalars()
        .all()
    )
    return UniverseContext(as_of_date, st_codes, list_dates, tuple(open_dates))


def filter_for_trade_date(
    db: Session,
    ts_code: str,
    name: str | None,
    as_of_date: date,
    *,
    new_listing_min_days: int = DEFAULT_NEW_LISTING_MIN_DAYS,
    exchange: str = _DEFAULT_EXCHANGE,
) -> UniverseVerdict:
    """单票便捷封装：查 a_stock_st / a_stock_basic / a_trade_calendar 后调核心。

    创建日期：2026-06-13
    author: claude
    """

    is_st = (
        db.execute(
            select(AStockSt.id)
            .where(AStockSt.ts_code == ts_code, AStockSt.trade_date == as_of_date)
            .limit(1)
        ).first()
        is not None
    )
    list_date = db.execute(
        select(AStockBasic.list_date).where(AStockBasic.ts_code == ts_code)
    ).scalar_one_or_none()
    if name is None:
        name = db.execute(
            select(AStockBasic.name).where(AStockBasic.ts_code == ts_code)
        ).scalar_one_or_none()

    trade_days_since_list: int | None = None
    if list_date is not None:
        # 统计 [list_date, as_of_date] 之间的开市交易日数（含上市日）
        trade_days_since_list = db.execute(
            select(func.count())
            .select_from(ATradeCalendar)
            .where(
                ATradeCalendar.exchange == exchange,
                ATradeCalendar.is_open == 1,
                ATradeCalendar.cal_date >= list_date,
                ATradeCalendar.cal_date <= as_of_date,
            )
        ).scalar_one()

    return evaluate_universe(
        ts_code,
        name,
        as_of_date,
        is_st_on_date=is_st,
        list_date=list_date,
        trade_days_since_list=trade_days_since_list,
        new_listing_min_days=new_listing_min_days,
    )
