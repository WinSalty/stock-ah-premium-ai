"""短线打板信号回测引擎。

定位：项目唯一既有回测是分红再投长持(口径完全不同)，故从零新建。本引擎产出每条信号在
    不复权 T+1 行情上"按规则假设成交"的预期收益，供分布/分组评估与"实盘−回测 gap"对账。
撮合铁律(与实盘/闭环归因逐字一致)：
    - T→B(买入日=T+1)→S(卖出日=B+1)全程 a_trade_calendar 映射，禁自然日加减；
    - 不复权(tencent_unadjusted_daily_quote, adjust_type='NONE')；
    - 一字/秒封"买不进"剔除(不计收益但计入分母留痕)；涨跌停按 board(主板±10%/创业板±20%)；
    - 无量跌停卖出顺延；空仓日(market_state='空仓')收益记 0 留痕、计入分母不剔除。
对照组：默认方案 b(CACHE_POOL)——从 limit_up_analysis_cache.context_json.limit_up_stocks 抽取回填
    limit_up_market_pool，算同口径隔日收益作"全市场涨停池"超额基准。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.market import (
    ATradeCalendar,
    LimitUpBacktestResult,
    LimitUpBacktestRun,
    LimitUpMarketPool,
    TencentUnadjustedDailyQuote,
)
from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
from app.services.universe_filter import limit_up_price

logger = logging.getLogger(__name__)

_GEM_PREFIXES = frozenset({"300", "301"})
_EMPTY_MARKET_STATE = "空仓"
_CALENDAR_EXCHANGE = "SSE"
_ROLLOVER_CAP = 5  # 无量跌停卖出顺延上限(交易日)
_PRICE_EPS = 0.01  # 与理论涨停价比对的容差(一个最小价位)
_SECONDS_SEAL_OPEN_GAP = 0.02  # 秒封代理：开盘距涨停≤2%(相对前收)且收盘封死视为买不进
# 受支持的口径版本(日线数据下可如实实现的子集)；其余(如 VWAP 买卖价)需分钟级数据，入口显式拒绝
_SUPPORTED_COST_VERSIONS = frozenset({"v_cost.0"})  # v_cost.0=B日开盘价买入
_SUPPORTED_SELL_POLICIES = frozenset({"NEXT_OPEN", "NEXT_CLOSE"})  # 卖出价=S日开盘/收盘
_SUPPORTED_EXEC_VERSIONS = frozenset({"v_exec.0", "v_exec.1"})  # 0=仅剔一字 / 1=剔一字+秒封


@dataclass
class BacktestConfig:
    """回测口径配置(落 limit_up_backtest_run.params_json 保证可复现)。"""

    start_date: date
    end_date: date
    exec_version: str = "v_exec.1"  # 可成交性版本：v_exec.0 仅剔一字 / v_exec.1 剔一字+秒封
    cost_version: str = "v_cost.0"  # 买入价口径：v_cost.0=B 日 open
    hold_window: int = 1  # 持有窗口(交易日数)：1=买入日次一交易日卖出
    sell_price_policy: str = "NEXT_OPEN"  # 卖出价口径
    include_fees: bool = False  # 是否扣费(默认毛收益，与实盘对账时显式标注)
    control_group_source: str = "CACHE_POOL"  # 对照组源
    fee_rate: float = 0.0013  # 含费时单边约 0.13%(佣金+印花税卖出单边+过户费近似)
    # 信号 prompt_version 收口：None=每个信号日各取"最新一批(prompt_version)"，避免多版本并存双计；
    # 指定具体版本则只回测该版本(A/B 回放)。落入 run_key 保证可复现。
    prompt_version: str | None = None

    def run_key(self) -> str:
        """口径哈希(幂等重跑键)：区间+版本+窗口+对照组源+信号版本收口。"""

        raw = "|".join(
            [
                self.start_date.isoformat(),
                self.end_date.isoformat(),
                self.exec_version,
                self.cost_version,
                str(self.hold_window),
                self.sell_price_policy,
                str(self.include_fees),
                self.control_group_source,
                self.prompt_version or "LATEST_PER_DAY",
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _board_of(ts_code: str) -> str:
    """按代码前缀判板别：创业板 GEM(±20%)，其余主板 MAIN(±10%)。"""

    return "GEM" if (ts_code or "")[:3] in _GEM_PREFIXES else "MAIN"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dec6(value: float | None) -> Decimal | None:
    """float → DECIMAL(.,6)；None 透传(用 str 规避二进制误差)。"""

    return None if value is None else Decimal(str(round(value, 6)))


class LimitUpBacktestService:
    """打板回测：数据装载 → 撮合 → 评估 → 落库。

    创建日期：2026-06-13
    author: claude
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- 交易日历 / 行情 / 涨跌停 ----------------

    def _next_open_day(self, after_date: date) -> date | None:
        """a_trade_calendar 中 > after_date 的最近开市日(禁自然日+1)。"""

        return self.db.execute(
            select(ATradeCalendar.cal_date)
            .where(
                ATradeCalendar.exchange == _CALENDAR_EXCHANGE,
                ATradeCalendar.is_open == 1,
                ATradeCalendar.cal_date > after_date,
            )
            .order_by(ATradeCalendar.cal_date)
            .limit(1)
        ).scalar_one_or_none()

    def _prev_open_day(self, before_date: date) -> date | None:
        """a_trade_calendar 中 < before_date 的最近开市日(前一交易日，禁自然日-1)。"""

        return self.db.execute(
            select(ATradeCalendar.cal_date)
            .where(
                ATradeCalendar.exchange == _CALENDAR_EXCHANGE,
                ATradeCalendar.is_open == 1,
                ATradeCalendar.cal_date < before_date,
            )
            .order_by(ATradeCalendar.cal_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _quote(self, ts_code: str, trade_date: date) -> TencentUnadjustedDailyQuote | None:
        """取不复权日线行情(adjust_type='NONE')。"""

        return self.db.execute(
            select(TencentUnadjustedDailyQuote).where(
                TencentUnadjustedDailyQuote.ts_code == ts_code,
                TencentUnadjustedDailyQuote.trade_date == trade_date,
                TencentUnadjustedDailyQuote.adjust_type == "NONE",
            )
        ).scalar_one_or_none()

    @staticmethod
    def _pre_close(quote: TencentUnadjustedDailyQuote) -> float | None:
        """前收盘(不复权·同行口径)：优先 close-change_amount，退化 close/(1+pct_chg/100)。"""

        close = _as_float(quote.close)
        if close is None:
            return None
        chg = _as_float(quote.change_amount)
        if chg is not None:
            return close - chg
        pct = _as_float(quote.pct_chg)
        if pct is not None and (1 + pct / 100) != 0:
            return close / (1 + pct / 100)
        return None

    def _resolve_pre_close(
        self, ts_code: str, trade_date: date, quote: TencentUnadjustedDailyQuote
    ) -> float | None:
        """前收盘(稳健)：先用同行 change_amount/pct_chg；缺失时取前一开市日收盘。

        腾讯不复权日线只提供 开/收/高/低/量，change_amount 与 pct_chg 均为 None，
        故对腾讯数据必须用"前一交易日收盘"推导前收盘，才能算涨停价、判一字/秒封。
        前一交易日经 a_trade_calendar 裁定(禁自然日-1)。
        """

        same_row = self._pre_close(quote)
        if same_row is not None:
            return same_row
        prev_day = self._prev_open_day(trade_date)
        if prev_day is None:
            return None
        prev_quote = self._quote(ts_code, prev_day)
        return _as_float(prev_quote.close) if prev_quote is not None else None

    def _is_flat_limit_down(
        self, ts_code: str, trade_date: date, quote: TencentUnadjustedDailyQuote
    ) -> bool:
        """是否"无量跌停封死"(卖出顺延判据)：当日 high==low 且较前收盘下跌。

        pct_chg 可用则直接判 <0；腾讯数据 pct_chg 为 None 时用前收盘推导(close<前收盘)。
        """

        if not self._is_flat(quote):
            return False
        pct = _as_float(quote.pct_chg)
        if pct is not None:
            return pct < 0
        pre_close = self._resolve_pre_close(ts_code, trade_date, quote)
        close = _as_float(quote.close)
        return pre_close is not None and close is not None and close < pre_close

    @staticmethod
    def _is_flat(quote: TencentUnadjustedDailyQuote) -> bool:
        """当日是否"一字/无振幅"(high==low)——日线下一字与秒封同形态。"""

        high = _as_float(quote.high)
        low = _as_float(quote.low)
        return high is not None and low is not None and high == low

    # ---------------- 单信号撮合 ----------------

    def _seal_kind(
        self,
        quote: TencentUnadjustedDailyQuote,
        lup: float | None,
        pre_close: float | None,
        limit_type: str | None,
        exec_version: str,
    ) -> str | None:
        """判定买入日"买不进"类型：返回 ONE_WORD / SECONDS_SEAL / None。

        口径(优先用理论涨停价 lup 比对，避免"flat且上涨"的误判)：
          - 一字：limit_type 标一字，或当日 high==low 且开盘即贴涨停价(全天封死) → 任何版本都剔；
          - 秒封：v_exec.1 才剔——高开贴近涨停(距涨停≤2%)且收盘封死在涨停价(高开秒上板买不到好价)；
          - lup/pre_close 缺失(无法定涨停价)时退化为 limit_type 标记 + flat&上涨 旧判据，只判一字。
        """

        is_one_word_tag = "一字" in (limit_type or "")
        # 涨停价不可得：退化判据(仅一字)，保证缺数据不漏剔明显一字
        if lup is None or pre_close is None:
            if is_one_word_tag or (self._is_flat(quote) and (_as_float(quote.pct_chg) or 0.0) > 0):
                return "ONE_WORD"
            return None

        open_ = _as_float(quote.open)
        high = _as_float(quote.high)
        close = _as_float(quote.close)
        at_limit_open = open_ is not None and abs(open_ - lup) <= _PRICE_EPS
        # 一字：标记命中 或 全天无振幅且开盘即封在涨停价
        if is_one_word_tag or (self._is_flat(quote) and at_limit_open):
            return "ONE_WORD"
        if exec_version == "v_exec.0":
            return None  # v_exec.0 只剔一字，秒封视为可成交
        # 秒封(v_exec.1)：收盘封死涨停(close 与 high 均贴涨停价)且高开贴近涨停 → 保守剔除
        sealed_close = (
            close is not None
            and abs(close - lup) <= _PRICE_EPS
            and high is not None
            and abs(high - lup) <= _PRICE_EPS
        )
        if sealed_close and open_ is not None and pre_close > 0:
            open_gap = (lup - open_) / pre_close  # 开盘距涨停的相对缺口
            if open_gap <= _SECONDS_SEAL_OPEN_GAP:
                return "SECONDS_SEAL"
        return None

    def _backtest_one(
        self,
        ts_code: str,
        signal_trade_date: date,
        limit_type: str | None,
        cfg: BacktestConfig,
    ) -> dict[str, Any]:
        """撮合单条信号，返回 limit_up_backtest_result 字段 dict。

        买入日 B 一律由 a_trade_calendar 裁定(=信号日 T 的下一开市日)，不信任信号侧可能写错的
        target_trade_date(铁律 A：T+1 必须经交易日历映射)；卖出日 S=B 起第 hold_window 个交易日。
        """

        board = _board_of(ts_code)
        row: dict[str, Any] = {
            "ts_code": ts_code,
            "signal_trade_date": signal_trade_date,
            "board": board,
            "hold_window": cfg.hold_window,
            "tradable_flag": 0,
            "limit_down_rollover_days": 0,
        }
        buy_day = self._next_open_day(signal_trade_date)  # 铁律A：B=日历下一开市日
        row["target_trade_date"] = buy_day
        if buy_day is None:
            row["miss_reason"] = "NO_QUOTE"
            return row
        q_buy = self._quote(ts_code, buy_day)
        if q_buy is None:
            row["miss_reason"] = "NO_QUOTE"
            return row

        # 前收盘走稳健口径(腾讯数据无 change_amount，回退前一交易日收盘)，才能算涨停价、判一字/秒封
        pre_close = self._resolve_pre_close(ts_code, buy_day, q_buy)
        # 涨停价：存库用 Decimal(DECIMAL 列)，判定比对用 float(与开高收 float 同型)
        lup_dec = limit_up_price(pre_close, board) if pre_close is not None else None  # type: ignore[arg-type]
        lup = float(lup_dec) if lup_dec is not None else None
        if lup_dec is not None:
            row["limit_up_price"] = lup_dec
        # 买不进判定(按涨停价 + exec 版本)：一字任何版本剔、秒封仅 v_exec.1 剔
        seal = self._seal_kind(q_buy, lup, pre_close, limit_type, cfg.exec_version)
        if seal is not None:
            row["miss_reason"] = seal
            return row  # 不计收益，计入分母留痕

        # 买入价(v_cost.0=B 日 open；其余成本版本已在 run() 入口拒绝)
        buy_price = _as_float(q_buy.open)
        if buy_price is None or buy_price <= 0:
            row["miss_reason"] = "NO_QUOTE"
            return row
        row["tradable_flag"] = 1
        row["buy_price"] = _dec6(buy_price)

        # 卖出日：B 起第 hold_window 个交易日；无量跌停封死则顺延(至多 _ROLLOVER_CAP)
        sell_day = buy_day
        for _ in range(cfg.hold_window):
            nxt = self._next_open_day(sell_day)
            if nxt is None:
                sell_day = None
                break
            sell_day = nxt
        rollover = 0
        q_sell = self._quote(ts_code, sell_day) if sell_day else None
        while (
            sell_day is not None
            and q_sell is not None
            and self._is_flat_limit_down(ts_code, sell_day, q_sell)
            and rollover < _ROLLOVER_CAP
        ):
            sell_day = self._next_open_day(sell_day)
            rollover += 1
            q_sell = self._quote(ts_code, sell_day) if sell_day else None
        row["limit_down_rollover_days"] = rollover
        row["sell_date"] = sell_day
        if q_sell is None:
            row["miss_reason"] = "NO_QUOTE"
            row["tradable_flag"] = 0  # 买入后无卖出行情，无法形成完整交易，留痕不计收益
            return row

        # 卖出价(按 sell_price_policy；其余口径已在 run() 入口拒绝)
        sell_price = (
            _as_float(q_sell.close)
            if cfg.sell_price_policy == "NEXT_CLOSE"
            else _as_float(q_sell.open)
        )
        if sell_price is None:
            row["miss_reason"] = "NO_QUOTE"
            row["tradable_flag"] = 0
            return row
        row["sell_price"] = _dec6(sell_price)
        gross = (sell_price - buy_price) / buy_price
        fee = (cfg.fee_rate * 2) if cfg.include_fees else 0.0  # 买卖双边近似(含费时)
        net = gross - fee
        row["gross_return_pct"] = _dec6(gross)
        row["net_return_pct"] = _dec6(net)
        return row

    # ---------------- 对照组 ----------------

    def _control_mean_by_date(self, cfg: BacktestConfig) -> dict[date, float]:
        """对照组每日等权隔日收益均值(超额基准)，按 trade_date 聚合。"""

        rows = self.db.execute(
            select(
                LimitUpMarketPool.trade_date, LimitUpMarketPool.next_day_return_pct
            ).where(
                LimitUpMarketPool.trade_date >= cfg.start_date,
                LimitUpMarketPool.trade_date <= cfg.end_date,
                LimitUpMarketPool.source == cfg.control_group_source,
            )
        ).all()
        bucket: dict[date, list[float]] = {}
        for trade_date, ret in rows:
            v = _as_float(ret)
            if v is not None:
                bucket.setdefault(trade_date, []).append(v)
        return {d: statistics.fmean(vs) for d, vs in bucket.items() if vs}

    def backfill_market_pool(
        self, start_date: date, end_date: date, source: str = "CACHE_POOL"
    ) -> int:
        """方案 b 回填对照组：遍历 READY 报告，解析 context_json.limit_up_stocks，
        算同口径隔日收益(B=T+1 open→S=T+2 open)，upsert 进 limit_up_market_pool。返回写入条数。
        """

        analyses = (
            self.db.execute(
                select(LimitUpAnalysisCache)
                .where(
                    LimitUpAnalysisCache.trade_date >= start_date,
                    LimitUpAnalysisCache.trade_date <= end_date,
                    LimitUpAnalysisCache.status == "READY",
                )
                .order_by(LimitUpAnalysisCache.trade_date)
            )
            .scalars()
            .all()
        )
        written = 0
        seen_dates: set[date] = set()
        for analysis in analyses:
            # 同一 trade_date 可能有多份 READY(force 重生成)，只取首个遇到的(已按 trade_date 排序)
            if analysis.trade_date in seen_dates or not analysis.context_json:
                continue
            seen_dates.add(analysis.trade_date)
            try:
                context = json.loads(analysis.context_json)
            except (TypeError, ValueError):
                continue
            pool = context.get("limit_up_stocks") or []
            buy_day = self._next_open_day(analysis.trade_date)
            sell_day = self._next_open_day(buy_day) if buy_day else None
            for stock in pool:
                if not isinstance(stock, dict):
                    continue
                code = str(stock.get("ts_code") or "")
                if not code:
                    continue
                ret = self._pool_next_day_return(code, buy_day, sell_day)
                self._upsert_market_pool(analysis.trade_date, code, stock, ret, source)
                written += 1
        self.db.commit()
        return written

    def _pool_next_day_return(
        self, ts_code: str, buy_day: date | None, sell_day: date | None
    ) -> float | None:
        """对照组隔日收益(B open→S open)，与信号回测同口径；缺行情 None。"""

        if buy_day is None or sell_day is None:
            return None
        q_buy = self._quote(ts_code, buy_day)
        q_sell = self._quote(ts_code, sell_day)
        if q_buy is None or q_sell is None:
            return None
        b = _as_float(q_buy.open)
        s = _as_float(q_sell.open)
        if not b or s is None:
            return None
        return (s - b) / b

    def _upsert_market_pool(
        self, trade_date: date, ts_code: str, stock: dict[str, Any], ret: float | None, source: str
    ) -> None:
        """对照组单行 upsert(按 trade_date+ts_code+source 幂等)。"""

        existing = self.db.execute(
            select(LimitUpMarketPool).where(
                LimitUpMarketPool.trade_date == trade_date,
                LimitUpMarketPool.ts_code == ts_code,
                LimitUpMarketPool.source == source,
            )
        ).scalar_one_or_none()
        tech = stock.get("technical") if isinstance(stock.get("technical"), dict) else {}
        board_level = stock.get("board_level")
        values = {
            "name": stock.get("name"),
            "board_level": board_level if isinstance(board_level, int) else None,
            "limit_type": stock.get("limit_type"),
            "theme": stock.get("theme") or stock.get("limit_up_reason"),
            "seal_ratio_pct": _dec6(_as_float(stock.get("seal_ratio_pct"))),
            "next_day_return_pct": _dec6(ret),
        }
        if existing is None:
            self.db.add(
                LimitUpMarketPool(
                    trade_date=trade_date, ts_code=ts_code, source=source, **values
                )
            )
        else:
            for key, val in values.items():
                setattr(existing, key, val)
        _ = tech  # 预留(未来可落更多快照字段)

    # ---------------- 主流程 ----------------

    def _load_signals(self, cfg: BacktestConfig) -> list[LimitUpSelectedStock]:
        """装载回测信号并按 prompt_version 收口，杜绝同 (ts_code, trade_date) 跨版本并存。

        落表唯一键为 (trade_date, ts_code, prompt_version)：版本 bump 后同票同日会留多行，
        若不收口则回测双计指标，且回测结果唯一键 (run_id, ts_code, signal_trade_date, hold_window)
        不含版本维度，写入时直接 IntegrityError 中断整批。故：
          - cfg.prompt_version 指定 → 只取该版本(A/B 回放)；
          - 否则 → 每个信号日取"最新一批"(该日 id 最大行所属版本)，同导出接口"取最新 READY"口径。
        """

        rows = (
            self.db.execute(
                select(LimitUpSelectedStock)
                .where(
                    LimitUpSelectedStock.trade_date >= cfg.start_date,
                    LimitUpSelectedStock.trade_date <= cfg.end_date,
                )
                .order_by(LimitUpSelectedStock.trade_date, LimitUpSelectedStock.id)
            )
            .scalars()
            .all()
        )
        if cfg.prompt_version is not None:
            return [r for r in rows if r.prompt_version == cfg.prompt_version]
        # 每个信号日取"最新一批"的 prompt_version：该日 id 最大行所属版本(批次按 id 单调递增)
        latest_version_by_day: dict[date, str | None] = {}
        for r in rows:
            # 行已按 (trade_date, id) 升序，遍历到的末值即该日最新批次
            latest_version_by_day[r.trade_date] = r.prompt_version
        return [r for r in rows if r.prompt_version == latest_version_by_day[r.trade_date]]

    def run(self, cfg: BacktestConfig) -> int:
        """编排一次回测：建/复用 run → 撮合 → 写明细 → 评估 → 标记完成。返回 run_id。"""

        # 入口校验口径版本：日线数据无法如实实现的口径(如 VWAP 买卖价)直接拒绝，避免静默退化误导对比
        if cfg.exec_version not in _SUPPORTED_EXEC_VERSIONS:
            raise ValueError(f"unsupported exec_version: {cfg.exec_version}")
        if cfg.cost_version not in _SUPPORTED_COST_VERSIONS:
            raise ValueError(f"unsupported cost_version(日线仅支持开盘价买入): {cfg.cost_version}")
        if cfg.sell_price_policy not in _SUPPORTED_SELL_POLICIES:
            raise ValueError(
                f"unsupported sell_price_policy(日线仅支持开/收盘): {cfg.sell_price_policy}"
            )

        run_key = cfg.run_key()
        run = self.db.execute(
            select(LimitUpBacktestRun).where(LimitUpBacktestRun.run_key == run_key)
        ).scalar_one_or_none()
        if run is None:
            run = LimitUpBacktestRun(
                run_key=run_key,
                start_date=cfg.start_date,
                end_date=cfg.end_date,
                exec_version=cfg.exec_version,
                cost_version=cfg.cost_version,
                hold_window=cfg.hold_window,
                sell_price_policy=cfg.sell_price_policy,
                include_fees=cfg.include_fees,
                control_group_source=cfg.control_group_source,
                params_json=json.dumps(_config_to_jsonable(cfg), ensure_ascii=False),
                status="RUNNING",
                started_at=datetime.now(UTC).replace(tzinfo=None),
            )
            self.db.add(run)
            self.db.flush()
        else:
            # 幂等重跑：清同 run_id 旧明细再写，状态回 RUNNING
            self.db.execute(
                delete(LimitUpBacktestResult).where(LimitUpBacktestResult.run_id == run.id)
            )
            run.status = "RUNNING"
            run.started_at = datetime.now(UTC).replace(tzinfo=None)

        signals = self._load_signals(cfg)
        control_mean = self._control_mean_by_date(cfg)
        now = datetime.now(UTC).replace(tzinfo=None)
        rows: list[LimitUpBacktestResult] = []
        empty_days: set[date] = set()
        for sig in signals:
            is_empty = sig.market_state == _EMPTY_MARKET_STATE
            role_tags = sig.role_tags if isinstance(sig.role_tags, list) else None
            role = role_tags[0] if role_tags else None
            base = {
                "run_id": run.id,
                "ts_code": sig.ts_code,
                "signal_trade_date": sig.trade_date,
                "target_trade_date": sig.target_trade_date,
                "hold_window": cfg.hold_window,
                "board": sig.board,
                "leader_strength_score": sig.leader_strength_score,
                "role": role,
                "strategy_family": sig.strategy_family,
                "market_state": sig.market_state,
                "is_empty_day": 1 if is_empty else 0,
                "computed_at": now,
            }
            if is_empty:
                # 空仓日：策略不参与，收益记 0 留痕(计入分母不剔除)
                empty_days.add(sig.trade_date)
                base.update({"tradable_flag": 0, "miss_reason": "EMPTY_GATE"})
                rows.append(LimitUpBacktestResult(**base))
                continue
            matched = self._backtest_one(sig.ts_code, sig.trade_date, sig.limit_type, cfg)
            # 相对对照组超额(gross-vs-gross，对照组与信号同口径毛收益)
            gross = matched.get("gross_return_pct")
            cmean = control_mean.get(sig.trade_date)
            if gross is not None and cmean is not None:
                matched["control_excess_pct"] = _dec6(float(gross) - cmean)
            base.update(matched)
            base["board"] = matched.get("board") or sig.board
            rows.append(LimitUpBacktestResult(**base))

        self.db.add_all(rows)
        summary = self._evaluate(rows)
        run.signal_count = len(rows)
        run.tradable_count = sum(1 for r in rows if r.tradable_flag == 1)
        run.empty_day_count = len(empty_days)
        run.summary_json = json.dumps(summary, ensure_ascii=False)
        run.status = "SUCCESS"
        run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.commit()
        return run.id

    def _evaluate(self, rows: list[LimitUpBacktestResult]) -> dict[str, Any]:
        """评估：成交收益分布 + 组合级(空仓/买不进记0)收益 + 分组均值 + 超额 + 基础 IC。

        两套口径分清楚，避免读数歧义：
          - distribution：仅"可成交样本"的毛/净收益分布(买入收益本身好不好)；
          - portfolio：按信号日等权聚合、空仓日与全买不进日记 0(组合实际能拿到的收益，含闸门成本)。
        """

        grosses = [float(r.gross_return_pct) for r in rows if r.gross_return_pct is not None]
        nets = [float(r.net_return_pct) for r in rows if r.net_return_pct is not None]
        summary: dict[str, Any] = {
            "signal_count": len(rows),
            "tradable_count": sum(1 for r in rows if r.tradable_flag == 1),
            "empty_day_signal_count": sum(1 for r in rows if r.is_empty_day == 1),
            "miss_counts": _count_by(rows, lambda r: r.miss_reason),
            "buyable_return_count": len(grosses),
        }
        if grosses:
            wins = [g for g in grosses if g > 0]
            losses = [g for g in grosses if g < 0]
            summary["distribution"] = {
                "mean": round(statistics.fmean(grosses), 6),
                "mean_net": round(statistics.fmean(nets), 6) if nets else 0.0,
                "median": round(statistics.median(grosses), 6),
                "stdev": round(statistics.pstdev(grosses), 6) if len(grosses) > 1 else 0.0,
                "hit_rate": round(len(wins) / len(grosses), 4),
                "p10": round(_percentile(grosses, 0.10), 6),
                "p90": round(_percentile(grosses, 0.90), 6),
                "avg_win": round(statistics.fmean(wins), 6) if wins else 0.0,
                "avg_loss": round(statistics.fmean(losses), 6) if losses else 0.0,
            }
        # 组合级口径(设计 §7.5.4)：按信号日聚合，空仓日/全买不进日贡献 0，体现闸门与漏单成本
        summary["portfolio"] = self._portfolio_metrics(rows)
        # 分组均值(先可成交过滤)：按 market_state / role
        summary["by_market_state"] = _group_mean(rows, lambda r: r.market_state)
        summary["by_role"] = _group_mean(rows, lambda r: r.role)
        # 相对对照组超额(均值)
        excesses = [float(r.control_excess_pct) for r in rows if r.control_excess_pct is not None]
        if excesses:
            summary["control_excess_mean"] = round(statistics.fmean(excesses), 6)
            summary["control_excess_count"] = len(excesses)
        # 基础 IC：leader_strength_score 与 gross 的 Pearson(可成交样本)
        pairs = [
            (float(r.leader_strength_score), float(r.gross_return_pct))
            for r in rows
            if r.leader_strength_score is not None and r.gross_return_pct is not None
        ]
        ic = _pearson(pairs)
        if ic is not None:
            summary["leader_strength_ic"] = round(ic, 4)
        # go/no-go 结构化裁决（评审 D1）：把"据回测放行实盘"的判定代码化，落入 summary 供上线流程强制读取，
        # 而非人工肉眼看数字。阈值为保守占位（已授权先占位，待回测/实盘校准固化）。
        summary["go_no_go"] = evaluate_go_no_go(summary)
        return summary

    @staticmethod
    def _portfolio_metrics(rows: list[LimitUpBacktestResult]) -> dict[str, Any]:
        """组合级收益：按 signal_trade_date 等权，当日无可成交收益(空仓/全买不进)记 0。

        日收益 = 当日可成交毛收益均值(无则 0)；累计收益 = ∏(1+日收益)-1；
        zero_days = 当日所有信号都没产生收益的交易日数(空仓日 + 全买不进日)，体现组合的"踏空成本"。
        """

        by_day: dict[date, list[float]] = {}
        for r in rows:
            by_day.setdefault(r.signal_trade_date, [])
            if r.gross_return_pct is not None:
                by_day[r.signal_trade_date].append(float(r.gross_return_pct))
        if not by_day:
            return {"day_count": 0}
        day_returns = [
            (statistics.fmean(vs) if vs else 0.0) for _, vs in sorted(by_day.items())
        ]
        cumulative = 1.0
        for r in day_returns:
            cumulative *= 1 + r
        return {
            "day_count": len(day_returns),
            "zero_days": sum(1 for r in day_returns if r == 0.0),
            "mean_daily": round(statistics.fmean(day_returns), 6),
            "median_daily": round(statistics.median(day_returns), 6),
            "day_hit_rate": round(sum(1 for r in day_returns if r > 0) / len(day_returns), 4),
            "cumulative": round(cumulative - 1, 6),
        }


def _config_to_jsonable(cfg: BacktestConfig) -> dict[str, Any]:
    """BacktestConfig → 可 JSON 序列化 dict(date 转 isoformat)。"""

    data = asdict(cfg)
    data["start_date"] = cfg.start_date.isoformat()
    data["end_date"] = cfg.end_date.isoformat()
    return data


# go/no-go 硬阈值（保守占位，评审 D1）。用户已授权：先用保守占位值，后续按回测/实盘校准固化并随版本 bump。
# 口径见 doc/archive/09 修复计划「待确认业务口径」。完整统计显著性(置信区间/bootstrap，D2)与默认含费
# 净收益口径(D3)为后续增强；本判定先把「据回测放行实盘」的出口建起来并被上线流程强制读取。
_GONOGO_MIN_BUYABLE = 30        # 最小可成交样本数（样本不足无法判定，判 INSUFFICIENT）
_GONOGO_MIN_DAYS = 10           # 最小交易日数
_GONOGO_MIN_HIT_RATE = 0.40    # 可成交样本最小胜率
_GONOGO_MIN_MEAN = 0.0          # 可成交样本毛收益均值下限（须 >0）
_GONOGO_MIN_EXCESS = 0.0        # 对照组超额均值下限（须 >0）
_GONOGO_MIN_CUMULATIVE = 0.0   # 组合累计收益下限（须 >0）
_GONOGO_MIN_P10 = -0.10        # p10 尾部不破限（不差于 -10%）


def evaluate_go_no_go(summary: dict[str, Any]) -> dict[str, Any]:
    """据回测 summary 产出结构化 go/no-go 裁决（评审 D1：原本只产指标、无任何判定出口）。

    判据（全部硬条件通过才 GO；样本/交易日不足判 INSUFFICIENT，绝不可据此上实盘）：
    - 样本充足：buyable_return_count ≥ MIN_BUYABLE 且 portfolio.day_count ≥ MIN_DAYS；
    - 胜率：distribution.hit_rate ≥ MIN_HIT_RATE；
    - 可成交均值为正：distribution.mean > MIN_MEAN；
    - 对照组超额为正：control_excess_mean > MIN_EXCESS；
    - 组合累计为正：portfolio.cumulative > MIN_CUMULATIVE；
    - 尾部风险：distribution.p10 ≥ MIN_P10。
    返回 {verdict: GO|NO_GO|INSUFFICIENT, checks: [{name,value,threshold,passed}], reasons: [...]}。
    """
    dist = summary.get("distribution") or {}
    port = summary.get("portfolio") or {}
    buyable = summary.get("buyable_return_count", 0) or 0
    days = port.get("day_count", 0) or 0

    # 样本不足 → INSUFFICIENT（不参与 GO/NO_GO，明确标记不可上实盘）。
    if buyable < _GONOGO_MIN_BUYABLE or days < _GONOGO_MIN_DAYS:
        return {
            "verdict": "INSUFFICIENT",
            "checks": [],
            "reasons": [
                f"样本不足: buyable={buyable}(需≥{_GONOGO_MIN_BUYABLE}) "
                f"days={days}(需≥{_GONOGO_MIN_DAYS})"
            ],
        }

    checks: list[dict[str, Any]] = []

    def _chk(name: str, value: Any, ok: bool, threshold: Any) -> bool:
        checks.append({"name": name, "value": value, "threshold": threshold, "passed": bool(ok)})
        return bool(ok)

    hit = dist.get("hit_rate")
    mean = dist.get("mean")
    p10 = dist.get("p10")
    excess = summary.get("control_excess_mean")
    cumulative = port.get("cumulative")

    passed = True
    passed &= _chk("hit_rate", hit, hit is not None and hit >= _GONOGO_MIN_HIT_RATE, _GONOGO_MIN_HIT_RATE)
    passed &= _chk("mean", mean, mean is not None and mean > _GONOGO_MIN_MEAN, _GONOGO_MIN_MEAN)
    passed &= _chk("control_excess_mean", excess, excess is not None and excess > _GONOGO_MIN_EXCESS, _GONOGO_MIN_EXCESS)
    passed &= _chk("cumulative", cumulative, cumulative is not None and cumulative > _GONOGO_MIN_CUMULATIVE, _GONOGO_MIN_CUMULATIVE)
    passed &= _chk("p10", p10, p10 is not None and p10 >= _GONOGO_MIN_P10, _GONOGO_MIN_P10)

    reasons = [f"{c['name']}={c['value']} 未达阈值 {c['threshold']}" for c in checks if not c["passed"]]
    return {"verdict": "GO" if passed else "NO_GO", "checks": checks, "reasons": reasons}


def _count_by(rows: list[Any], key) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = key(r) or "OK"
        out[k] = out.get(k, 0) + 1
    return out


def _group_mean(rows: list[Any], key) -> dict[str, dict[str, Any]]:
    """分组(先可成交过滤)：每组样本数/平均毛收益/胜率。"""

    bucket: dict[str, list[float]] = {}
    for r in rows:
        if r.tradable_flag != 1 or r.gross_return_pct is None:
            continue
        k = str(key(r) or "UNKNOWN")
        bucket.setdefault(k, []).append(float(r.gross_return_pct))
    return {
        k: {
            "count": len(vs),
            "mean": round(statistics.fmean(vs), 6),
            "hit_rate": round(sum(1 for v in vs if v > 0) / len(vs), 4),
        }
        for k, vs in bucket.items()
        if vs
    }


def _percentile(values: list[float], q: float) -> float:
    """简单分位(线性插值)。"""

    if not values:
        return 0.0
    s = sorted(values)
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    """Pearson 相关系数(无 numpy)；样本不足/零方差返回 None。"""

    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx**0.5 * vy**0.5)


# field 仅为保留 dataclass 默认工厂能力的占位引用(避免静态检查误删导入)。
_ = field
