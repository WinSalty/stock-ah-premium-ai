"""打板回测数据回填脚本（一次性运维工具，按 --step 分步或 all 串跑）。

本脚本只做"编排调用现成 service 的回填"，零业务逻辑重造：
  - a_stock_st : SyncService.run_sync 历史回填每日 ST 名单（universe 按信号日当日判 ST，杜绝前视）
  - quotes     : TencentKlineService 抓不复权日线 → tencent_unadjusted_daily_quote（撮合 B/S 所需）
  - signals    : LimitUpPushService._persist_selected_stocks 从历史 READY 报告回填信号落表
  - pool       : LimitUpBacktestService.backfill_market_pool 回填对照组涨停池

执行顺序（--step all）：a_stock_st → quotes → signals → pool。依赖关系：
  对照组/最终回测的隔日收益依赖不复权行情，故 quotes 必须先于 pool 与回测；
  信号落表时 universe 过滤按当日 a_stock_st 判 ST，故 a_stock_st 应先于 signals。
所有步骤幂等可重跑；耗时步 quotes 按 ts_code 检查点断点续跑（--resume），失败不写检查点以便重试。

创建日期：2026-06-13
author: claude
用法见 scripts/limit-up-backfill.sh
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(BACKEND_DIR))
# 回填产物（检查点/错误清单）属运行时数据，放 .runtime 不进 git。
RUNTIME_DIR = BACKEND_DIR.parent / ".runtime" / "limit-up-backfill"

# 默认信号回测窗口（报告最早 READY 日 ~ 最新），可被 --start-date/--end-date 覆盖。
DEFAULT_START = date(2026, 5, 7)
DEFAULT_END = date(2026, 6, 12)
ST_FULL_START = date(2025, 8, 12)  # a_stock_st 历史起点（与 DatasetSpec.full_start_date 对齐）
A_SUFFIXES = (".SH", ".SZ")  # 只回填 A 股主板/创业板/科创代码段（腾讯 symbol 需后缀派生）


# ---------------- 通用工具 ----------------


def _stamp() -> str:
    """本地时间戳（脚本进程，用于报告/检查点记录，非交易时间口径）。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_done(path: Path) -> set[str]:
    """读取检查点已完成 id 集合（断点续跑用）。"""

    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(str(json.loads(line)["id"]))
        except (ValueError, KeyError):
            continue
    return done


def _append_record(path: Path, record: dict) -> None:
    """追加一条 JSONL 记录（检查点/错误清单），逐条 flush 保证中断不丢。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _open_day_after(db, anchor: date, steps: int) -> date:
    """a_trade_calendar 中 anchor 之后第 steps 个开市日（撮合 B/S 上界，禁自然日加减）。"""

    from sqlalchemy import select

    from app.db.models.market import ATradeCalendar

    cur = anchor
    for _ in range(steps):
        nxt = db.execute(
            select(ATradeCalendar.cal_date)
            .where(
                ATradeCalendar.exchange == "SSE",
                ATradeCalendar.is_open == 1,
                ATradeCalendar.cal_date > cur,
            )
            .order_by(ATradeCalendar.cal_date)
            .limit(1)
        ).scalar_one_or_none()
        if nxt is None:
            return cur  # 日历未来段不足时退回当前，由调用方自行兜底
        cur = nxt
    return cur


def _enumerate_universe_codes(db, start: date, end: date) -> list[str]:
    """枚举 [start,end] 区间需回填行情的打板股全集（去重）。

    来源并集：每份 READY 报告 context_json 的 limit_up_stocks（全市场涨停池，对照组源）
    + pipeline.selected_{first_board,chain,high_board}_stocks（信号侧候选，是涨停池子集）。
    只保留 A 股 .SH/.SZ 后缀代码（腾讯行情 symbol 派生需要），其余（港股/异常）丢弃。
    """

    from sqlalchemy import select

    from app.db.models.notification import LimitUpAnalysisCache

    payloads = db.execute(
        select(LimitUpAnalysisCache.context_json).where(
            LimitUpAnalysisCache.status == "READY",
            LimitUpAnalysisCache.trade_date >= start,
            LimitUpAnalysisCache.trade_date <= end,
        )
    ).scalars().all()
    codes: set[str] = set()
    for raw in payloads:
        if not raw:
            continue
        try:
            ctx = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for stock in ctx.get("limit_up_stocks") or []:
            if isinstance(stock, dict) and stock.get("ts_code"):
                codes.add(str(stock["ts_code"]))
        pipeline = ctx.get("pipeline") or {}
        for key in (
            "selected_first_board_stocks",
            "selected_chain_stocks",
            "selected_high_board_stocks",
        ):
            for stock in pipeline.get(key) or []:
                if isinstance(stock, dict) and stock.get("ts_code"):
                    codes.add(str(stock["ts_code"]))
    return sorted(c for c in codes if c.upper().endswith(A_SUFFIXES))


# ---------------- 各回填步骤 ----------------


def step_a_stock_st(db, st_start: date, st_end: date) -> None:
    """步骤①：历史回填每日 ST 名单（run_sync full，spec 内部按交易日逐日拉、upsert 幂等）。"""

    from app.services.sync_service import SyncService

    print(f"[backfill:a_stock_st] {_stamp()} 区间 {st_start}~{st_end} 开始")
    run = SyncService(db).run_sync(
        "a_stock_st", {"mode": "full", "start_date": st_start, "end_date": st_end}
    )
    print(
        f"[backfill:a_stock_st] 完成 run_id={run.id} status={run.status} "
        f"row_count={run.row_count} error={run.error_message}"
    )


def step_quotes(db, start: date, end: date, *, resume: bool) -> None:
    """步骤②：抓打板 universe 不复权日线（撮合 B/S 所需）。按 ts_code 断点续跑。"""

    from app.db.models.market import TencentUnadjustedDailyQuote
    from app.services.repository import UpsertRepository
    from app.services.tencent_kline_service import TencentKlineService

    codes = _enumerate_universe_codes(db, start, end)
    # 行情下界取信号起点；上界取 end 之后第 2 个开市日（撮合 S=next_open(next_open(maxT))）。
    q_start = start
    q_end = _open_day_after(db, end, 2)
    ckpt = RUNTIME_DIR / "quotes-checkpoint.jsonl"
    err_path = RUNTIME_DIR / "quotes-errors.jsonl"
    done = _load_done(ckpt) if resume else set()
    service = TencentKlineService()  # 内置 0.8s/次 限流，无需额外 sleep
    repo = UpsertRepository(db)
    total = len(codes)
    ok = skipped = failed = rows_written = 0
    print(
        f"[backfill:quotes] {_stamp()} universe={total} 行情区间 {q_start}~{q_end} resume={resume}"
    )
    for idx, code in enumerate(codes, 1):
        if code in done:
            skipped += 1
            continue
        try:
            rows = service.fetch_unadjusted_daily(code, q_start, q_end)
            cnt = repo.upsert_many(TencentUnadjustedDailyQuote, [r.to_model_row() for r in rows])
            db.commit()
            rows_written += cnt
            ok += 1
            # 成功才写检查点；失败不写，--resume 时自动重试该只。
            _append_record(ckpt, {"id": code, "rows": cnt, "ts": _stamp()})
            print(f"[backfill:quotes] ({idx}/{total}) {code} rows={cnt}")
        except Exception as exc:  # 单只失败（空响应/网络/限流）记错续跑，不中断整批
            db.rollback()
            failed += 1
            _append_record(err_path, {"id": code, "error": str(exc)[:300], "ts": _stamp()})
            print(f"[backfill:quotes] ({idx}/{total}) {code} ERROR {exc}")
    print(
        f"[backfill:quotes] 完成 ok={ok} skipped={skipped} failed={failed} "
        f"rows={rows_written}（失败清单见 {err_path}）"
    )


def step_signals(db, settings, start: date, end: date) -> None:
    """步骤③：从历史 READY 报告回填信号落表（每个信号日取最新一批，delete-then-insert 幂等）。"""

    from sqlalchemy import func, select

    from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
    from app.services.limit_up_push_service import LimitUpPushService

    # 守卫：增强层开关关闭时 _persist 会早退、静默不落表，回填无意义，直接报错提示。
    if not settings.limit_up_leader_scoring_enabled:
        raise SystemExit(
            "LIMIT_UP_LEADER_SCORING_ENABLED=false，信号回填会被守卫早退；请先开启再回填。"
        )
    analyses = db.execute(
        select(LimitUpAnalysisCache)
        .where(
            LimitUpAnalysisCache.status == "READY",
            LimitUpAnalysisCache.trade_date >= start,
            LimitUpAnalysisCache.trade_date <= end,
        )
        .order_by(LimitUpAnalysisCache.trade_date, LimitUpAnalysisCache.id)
    ).scalars().all()
    # 同一信号日可能有多份 READY（force 重生成）：升序遍历取末值=该日 id 最大的最新批。
    latest_by_day: dict[date, LimitUpAnalysisCache] = {}
    for analysis in analyses:
        latest_by_day[analysis.trade_date] = analysis
    service = LimitUpPushService(db, settings=settings)
    total = len(latest_by_day)
    written_days = empty_days = 0
    print(f"[backfill:signals] {_stamp()} 信号日 {total} 天 区间 {start}~{end}")
    for trade_date in sorted(latest_by_day):
        analysis = latest_by_day[trade_date]
        try:
            ctx = json.loads(analysis.context_json) if analysis.context_json else {}
        except (TypeError, ValueError):
            ctx = {}
        service._persist_selected_stocks(analysis, ctx)  # savepoint 包裹、整组覆盖、幂等
        db.commit()
        cnt = db.execute(
            select(func.count())
            .select_from(LimitUpSelectedStock)
            .where(LimitUpSelectedStock.trade_date == trade_date)
        ).scalar_one()
        if cnt:
            written_days += 1
        else:
            empty_days += 1  # 旧报告无 pipeline / 当日空仓 / 全落选时整组无候选，属正常
        print(
            f"[backfill:signals] {trade_date} prompt={analysis.prompt_version} rows={cnt}"
        )
    print(f"[backfill:signals] 完成 有落表天数={written_days} 无候选天数={empty_days}")


def step_pool(db, start: date, end: date, source: str) -> None:
    """步骤④：回填对照组涨停池（依赖行情已回填，算同口径隔日收益）。"""

    from app.services.limit_up_backtest_service import LimitUpBacktestService

    print(f"[backfill:pool] {_stamp()} 区间 {start}~{end} source={source}")
    written = LimitUpBacktestService(db).backfill_market_pool(start, end, source=source)
    print(f"[backfill:pool] 完成 written={written}")


# ---------------- 入口 ----------------


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="打板回测数据回填（信号/对照组/不复权行情 + a_stock_st 历史）"
    )
    parser.add_argument(
        "--step",
        default="all",
        choices=["a_stock_st", "quotes", "signals", "pool", "all"],
        help="回填步骤；all 按 a_stock_st→quotes→signals→pool 顺序串跑",
    )
    parser.add_argument("--start-date", type=_parse_date, default=DEFAULT_START, help="信号窗口起")
    parser.add_argument("--end-date", type=_parse_date, default=DEFAULT_END, help="信号窗口止")
    parser.add_argument(
        "--st-start-date", type=_parse_date, default=ST_FULL_START, help="a_stock_st 历史回填起点"
    )
    parser.add_argument(
        "--st-end-date", type=_parse_date, default=None, help="a_stock_st 历史回填止（默认今天）"
    )
    parser.add_argument("--source", default="CACHE_POOL", help="对照组源 CACHE_POOL/LIMIT_LIST_D")
    parser.add_argument("--resume", action="store_true", help="quotes 步按 ts_code 检查点续跑")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    st_end = args.st_end_date or date.today()
    print(f"[backfill] step={args.step} 信号窗口 {args.start_date}~{args.end_date} 启动 {_stamp()}")
    db = SessionLocal()
    try:
        if args.step in ("a_stock_st", "all"):
            step_a_stock_st(db, args.st_start_date, st_end)
        if args.step in ("quotes", "all"):
            step_quotes(db, args.start_date, args.end_date, resume=args.resume)
        if args.step in ("signals", "all"):
            step_signals(db, settings, args.start_date, args.end_date)
        if args.step in ("pool", "all"):
            step_pool(db, args.start_date, args.end_date, args.source)
    finally:
        db.close()
    print(f"[backfill] 全部完成 {_stamp()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
