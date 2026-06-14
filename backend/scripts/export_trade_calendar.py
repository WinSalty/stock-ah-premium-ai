"""交易日历导出脚本：把 a_trade_calendar 中 is_open=1 的交易日导出为纯文本文件。

业务意图
    信号侧（本仓库）是交易日历 a_trade_calendar 的唯一权威数据源；执行侧（QMT 端，独立机器/独立仓库）
    通过环境变量 QMT_TRADE_CALENDAR_FILE 指向一个"每行一个 YYYY-MM-DD"的纯文本交易日清单，
    加载为执行侧的 StaticTradeCalendar，用于把买入日 B 映射到下一交易日 next_open（隔日卖出等）。
    本脚本就是这两侧之间的"导出闸口"：在信号侧读库、生成执行侧可直接消费的静态交易日历文件，
    保持信号侧/QMT 侧解耦（执行侧不直连信号侧 DB，只读这份导出文件）。

与执行侧 fail-closed（E1）口径的关系
    执行侧 StaticTradeCalendar 对 next_open 采用 fail-closed：若请求的交易日落在静态日历覆盖范围之外
    （越界，next_open 找不到），执行侧应当拒绝下单/拒绝映射而不是猜测，从而避免在"日历没同步到未来"时
    把单子打到错误日期。因此本脚本的覆盖校验非常关键：导出时若发现最大交易日距今天不足 min-future-days，
    说明未来交易日没同步够，执行侧大概率会在 next_open 处 fail-closed（越界拒绝）。此时必须先把
    a_trade_calendar 的未来日期补齐再重新导出，否则执行侧会按 fail-closed 口径停摆。

幂等/可复现口径
    输出内容只由 (exchange, start, 库内 is_open=1 的交易日集合) 决定，刻意不把"当前时间/生成时刻"写进文件，
    保证同样的库状态多次导出得到逐字节一致的文件（便于 diff、便于 scp 覆盖上线时判断是否真有变化）。
    运行时刻只打到日志（stderr/stdout），不进文件。

DB 入口
    复用信号侧既有入口 app.db.session.SessionLocal（其内部由 app.core.config.get_settings() 读取
    database_url），不在脚本里硬编码任何 DSN/账号口令。脚本随后端 .venv 在 backend/ 目录下运行，
    与 scripts/cleanup-llm-metrics.sh、tests/backfill/limit_up_backfill.py 的运行约定一致。

创建日期：2026-06-14
author: claude
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# 防御性 sys.path：本脚本既可由 `cd backend && python scripts/export_trade_calendar.py` 运行，
# 也可能被绝对路径直接调用。无论 CWD 在哪，都把 backend 根目录（本文件父目录的父目录）补进 sys.path，
# 保证 `import app.*` 可用，且不依赖把脚本装进包。
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# 仅记录进度/告警到控制台；不写入导出文件，保证文件内容可复现。
logger = logging.getLogger("export_trade_calendar")

# 文件头注释行前缀：执行侧解析时按 '#' 开头整行跳过；这里固化为常量，便于与执行侧解析口径对齐。
COMMENT_PREFIX = "#"


def build_header_line(exchange: str) -> str:
    """构造导出文件的文件头注释行。

    业务意图：给文件一个自解释的来源说明，便于人工核对"这份清单是哪条交易所、来自哪张表、什么口径"。
    边界：刻意不写生成时间，避免把不确定性源（当前时刻）写进文件而破坏可复现性；
        时间只在日志里打印。返回值不含换行，由写文件处统一负责行尾。
    """

    return (
        f"{COMMENT_PREFIX} 交易日({exchange}) 导出自 a_trade_calendar is_open=1，"
        f"每行一个 YYYY-MM-DD，按日期升序；执行侧 QMT_TRADE_CALENDAR_FILE 消费"
    )


def format_calendar_lines(exchange: str, cal_dates: list[date]) -> list[str]:
    """把交易日列表渲染成最终文件的所有行（含文件头），日期统一格式化为 YYYY-MM-DD。

    业务意图：把"渲染"从"取数/写盘"中拆出来，成为纯函数，便于不连库做单测。
    边界：调用方需保证 cal_dates 已按升序排好且已去重（取数 SQL 已 ORDER BY 升序、表上有
        (exchange, cal_date) 唯一约束，正常情况下天然有序去重）；本函数不再二次排序，
        以免掩盖上游异常数据。date 对象用 isoformat() 得到 YYYY-MM-DD，跨平台稳定。
    """

    lines = [build_header_line(exchange)]
    # 每个交易日一行；isoformat() 对 datetime.date 恒为 'YYYY-MM-DD'，无时区歧义（纯日期，无时分秒）。
    lines.extend(cal_date.isoformat() for cal_date in cal_dates)
    return lines


def check_future_coverage(
    cal_dates: list[date],
    today: date,
    min_future_days: int,
) -> tuple[bool, date | None, date]:
    """校验导出的交易日是否覆盖到足够的未来日期（纯逻辑，可不依赖 DB 单测）。

    业务意图：执行侧 next_open 越界即 fail-closed（E1），所以导出时必须确认"最大交易日"已经
        覆盖到今天往后至少 min_future_days 天，否则执行侧近几天就会撞到日历边界而停摆。
    入参：
        cal_dates       —— 已升序的交易日列表（可能为空）。
        today           —— 判定基准"今天"（由调用方传入，便于单测注入固定日期）。
        min_future_days —— 要求覆盖到的最小未来自然日天数（注意是自然日，不是交易日，给冗余余量）。
    返回：(coverage_ok, max_cal_date, required_until)
        coverage_ok    —— 是否满足覆盖要求；cal_dates 为空时恒为 False（什么都没导出，必然不够）。
        max_cal_date   —— 导出的最大交易日；空列表时为 None。
        required_until —— 要求至少覆盖到的日期（today + min_future_days），用于打印提示。
    边界：min_future_days<=0 视为"不要求未来覆盖"，此时只要有数据即判 OK；
        用 >= 比较，即恰好覆盖到 required_until 当天也算满足。
    """

    required_until = today + timedelta(days=max(min_future_days, 0))
    if not cal_dates:
        # 空导出：没有任何交易日，无论阈值多少都视为未覆盖，交由调用方打 WARNING。
        return False, None, required_until
    max_cal_date = cal_dates[-1]  # 升序列表，末元素即最大交易日
    # min_future_days<=0：显式关闭未来覆盖校验，只要有数据即判满足；>0 才要求最大交易日覆盖到未来。
    coverage_ok = True if min_future_days <= 0 else max_cal_date >= required_until
    return coverage_ok, max_cal_date, required_until


def load_open_trade_dates(exchange: str, start: date) -> list[date]:
    """从 a_trade_calendar 读取指定交易所、start 起、is_open=1 的交易日，按 cal_date 升序返回。

    业务意图：这是唯一与 DB 交互的环节，复用信号侧既有 SessionLocal 入口，不硬编码 DSN。
    取数口径：exchange=? AND is_open=1 AND cal_date>=start，ORDER BY cal_date ASC。
        过滤 is_open=1 是因为执行侧只关心"开市交易日"；start 用于裁掉太久远的历史，控制文件体积。
    边界：在函数内部 import，避免无 DB 依赖的纯逻辑单测在导入本模块时被迫拉起 SQLAlchemy 引擎。
    """

    # 延迟导入：纯逻辑函数（如 check_future_coverage）单测时无需可用的 DB/驱动即可导入本模块。
    from sqlalchemy import select

    from app.db.models.market import ATradeCalendar
    from app.db.session import SessionLocal

    # 用 with 管理会话生命周期，与 cleanup-llm-metrics.sh 中 `with SessionLocal() as db:` 口径一致。
    with SessionLocal() as db:
        stmt = (
            select(ATradeCalendar.cal_date)
            .where(
                ATradeCalendar.exchange == exchange,
                ATradeCalendar.is_open == 1,
                ATradeCalendar.cal_date >= start,
            )
            .order_by(ATradeCalendar.cal_date.asc())
        )
        # scalars() 直接取 cal_date 列，得到 list[date]；唯一约束保证 (exchange, cal_date) 不重复。
        return list(db.execute(stmt).scalars().all())


def write_calendar_file(output_path: Path, lines: list[str]) -> None:
    """把渲染好的行写入目标文件，统一用 \n 行尾、UTF-8 编码、末尾补一个换行。

    业务意图：产出执行侧可直接消费的纯文本文件。
    边界：自动创建父目录（执行侧/运维可能把文件放到尚不存在的目录）；统一 LF 行尾，避免 Windows
        CRLF 让执行侧逐行解析多出 \r。先写临时文件再原子替换，避免导出中途失败留下半截文件
        被执行侧读到（与 fail-closed 配合，宁可保留旧的完整文件也不给残缺文件）。
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 同目录临时文件 + os.replace 原子替换：保证读侧要么看到旧完整文件、要么看到新完整文件。
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    content = "\n".join(lines) + "\n"
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。

    默认值口径：
        --output           默认 trade_days.txt（相对当前工作目录；上线时一般传执行侧约定的绝对路径）。
        --exchange         默认 SSE（上交所日历即 A 股统一交易日历，沪深同历）。
        --start            默认 '2024-01-01'，裁掉过久历史，控制文件体积；执行侧只需近段+未来。
        --min-future-days  默认 60（自然日），给执行侧 next_open 预留充足未来覆盖余量。
    """

    parser = argparse.ArgumentParser(
        description="导出 a_trade_calendar 中 is_open=1 的交易日为纯文本（供执行侧 QMT_TRADE_CALENDAR_FILE 使用）",
    )
    parser.add_argument(
        "--output",
        default="trade_days.txt",
        help="导出文件路径（默认 trade_days.txt，上线建议传执行侧约定的绝对路径）",
    )
    parser.add_argument(
        "--exchange",
        default="SSE",
        help="交易所代码，对应 a_trade_calendar.exchange（默认 SSE）",
    )
    parser.add_argument(
        "--start",
        default="2024-01-01",
        help="起始日期 YYYY-MM-DD，仅导出 cal_date>=start 的交易日（默认 2024-01-01）",
    )
    parser.add_argument(
        "--min-future-days",
        type=int,
        default=60,
        help="要求覆盖到的最小未来自然日天数；不足则打 WARNING（默认 60，<=0 表示不校验未来覆盖）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """脚本主流程：取数 -> 渲染 -> 校验未来覆盖 -> 写文件 -> 打印摘要。

    返回值用作进程退出码：成功（含仅 WARNING）返回 0；致命错误（如 start 非法、零交易日）返回非 0，
    便于挂 cron / 上线脚本据退出码判断是否需要人工介入。
    """

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    # 解析 start：非法日期直接致命退出，避免把错误区间静默导出成"看似成功"的残缺清单。
    try:
        start = date.fromisoformat(args.start)
    except ValueError:
        logger.error("非法 --start 参数 %r，需形如 YYYY-MM-DD", args.start)
        return 2

    output_path = Path(args.output)
    logger.info(
        "开始导出交易日历：exchange=%s start=%s output=%s min_future_days=%d",
        args.exchange,
        start.isoformat(),
        output_path,
        args.min_future_days,
    )

    # 取数：唯一连库环节。
    cal_dates = load_open_trade_dates(args.exchange, start)

    # 零交易日：通常意味着 exchange 写错或库未同步；视为致命错误，避免导出空文件让执行侧拿到空日历。
    if not cal_dates:
        logger.error(
            "未查到任何 is_open=1 交易日（exchange=%s, start>=%s）；请确认 exchange 取值与 a_trade_calendar 是否已同步",
            args.exchange,
            start.isoformat(),
        )
        return 3

    # 渲染为最终文件行（纯函数，不含时间）。
    lines = format_calendar_lines(args.exchange, cal_dates)

    # 未来覆盖校验：基于"今天"判断最大交易日是否够远。today 在 main 内取一次，传入纯函数便于单测替换。
    today = date.today()
    coverage_ok, max_cal_date, required_until = check_future_coverage(
        cal_dates,
        today,
        args.min_future_days,
    )

    # 先写盘再决定退出码：即便未来覆盖不足，也仍然导出当前可得的清单（旧数据总比没有强），
    # 但用醒目 WARNING 强烈提示运维先补未来日期，避免执行侧 next_open 越界 fail-closed 停摆。
    write_calendar_file(output_path, lines)

    # 打印导出摘要：条数 + 日期范围，便于人工/日志快速核对。
    first_cal_date = cal_dates[0]
    logger.info(
        "导出完成：%d 个交易日，范围 %s ~ %s，已写入 %s",
        len(cal_dates),
        first_cal_date.isoformat(),
        max_cal_date.isoformat() if max_cal_date else "-",
        output_path,
    )

    if args.min_future_days > 0 and not coverage_ok:
        # 醒目 WARNING：用分隔线包裹，确保在批量日志里一眼可见。
        logger.warning("=" * 72)
        logger.warning(
            "未覆盖足够未来交易日：最大交易日 %s < 要求覆盖到 %s（今天 %s + %d 天）",
            max_cal_date.isoformat() if max_cal_date else "-",
            required_until.isoformat(),
            today.isoformat(),
            args.min_future_days,
        )
        logger.warning(
            "执行侧 next_open 可能越界（StaticTradeCalendar fail-closed/E1 会拒绝映射）；"
            "请先同步 a_trade_calendar 未来日期再重新导出。"
        )
        logger.warning("=" * 72)

    # 覆盖不足只告警不失败：文件已是当前可得的最佳结果，是否补数据由运维按 WARNING 决策。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
