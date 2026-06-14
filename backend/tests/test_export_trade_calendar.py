"""交易日历导出脚本纯逻辑单测（不连库）。

只覆盖 check_future_coverage / format_calendar_lines / build_header_line 这些纯函数——
load_open_trade_dates 连库部分由目标机/集成环节验证，这里不拉起真实 DB。
"""

from __future__ import annotations

from datetime import date, timedelta

from scripts.export_trade_calendar import (
    build_header_line,
    check_future_coverage,
    format_calendar_lines,
)

_TODAY = date(2026, 6, 14)


def test_future_coverage_sufficient_boundary():
    """最大交易日 = today+min_future_days（边界相等）→ 覆盖充足（>= 判定）。"""
    days = [date(2026, 1, 2), _TODAY + timedelta(days=60)]
    ok, mx, required_until = check_future_coverage(days, _TODAY, 60)
    assert ok is True
    assert mx == _TODAY + timedelta(days=60)
    assert required_until == _TODAY + timedelta(days=60)


def test_future_coverage_insufficient():
    """最大交易日 < 要求覆盖到的日期 → 覆盖不足，返回真实 max/required 供告警。"""
    ok, mx, required_until = check_future_coverage([date(2026, 6, 20)], _TODAY, 60)
    assert ok is False
    assert mx == date(2026, 6, 20)
    assert required_until == _TODAY + timedelta(days=60)


def test_future_coverage_empty_is_not_ok():
    """空交易日列表恒判未覆盖（什么都没导出），max=None。"""
    ok, mx, _ = check_future_coverage([], _TODAY, 60)
    assert ok is False and mx is None


def test_future_coverage_disabled_when_threshold_non_positive():
    """min_future_days<=0 表示不校验未来覆盖：只要有数据即 OK。"""
    ok, _, _ = check_future_coverage([date(2026, 6, 13)], _TODAY, 0)
    assert ok is True


def test_format_lines_header_then_ascending_iso_dates():
    """渲染：首行为 # 注释头，随后每行一个升序 YYYY-MM-DD。"""
    lines = format_calendar_lines("SSE", [date(2026, 6, 12), date(2026, 6, 15)])
    assert lines[0].startswith("#") and "SSE" in lines[0]
    assert lines[1] == "2026-06-12"
    assert lines[2] == "2026-06-15"


def test_header_line_has_no_timestamp_for_reproducibility():
    """文件头不含时间戳（保证同库状态导出逐字节可复现）。"""
    h1 = build_header_line("SSE")
    h2 = build_header_line("SSE")
    assert h1 == h2
