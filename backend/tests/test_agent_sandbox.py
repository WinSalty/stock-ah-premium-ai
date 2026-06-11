"""Python 沙箱安全用例集：以真实子进程执行验证 SandboxExecutor 各项安全约束。

覆盖口径（chat-agent-refactor-design-and-plan.md 3.4 节安全分层）：
- 合法计算路径：pandas 读 data/ 注入文件 + manifest 回填正确；
- 资源约束：死循环被 CPU/墙钟杀、阻塞被墙钟超时杀、内存炸弹（仅非 macOS）；
- audit hook 软约束：禁网（socket）、禁子进程（subprocess/os.system）、禁越界写；
- 工作目录内写文件放行、非零退出可观察、stdout 截断；
- 工具层：build_run_python_tool handler、_collect_data_files 文件名映射、
  run_python_daily_quota_exhausted 日配额判定（内存 SQLite）。

说明：这些是真实子进程测试，不 mock subprocess，会真的启动 Python 解释器执行用户代码；
为加快整体耗时，单测内把墙钟/CPU 超时配置调小（墙钟 5s、CPU 2s 为默认基线，
个别用例进一步压到 3s/2s）。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models.chat import LlmCallMetric
from app.services.agent.budget import TurnState
from app.services.agent.tools.python_runner import (
    SandboxExecutor,
    _collect_data_files,
    build_run_python_tool,
    run_python_daily_quota_exhausted,
)

# 配额判定使用的东八区时区：与被测实现保持一致，保证今日边界对齐。
_QUOTA_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _settings(**overrides: Any) -> Settings:
    """构造与本机密钥文件完全隔离的测试配置。

    显式置空所有 *_file 密钥来源，避免读到开发机真实密钥；沙箱超时默认压小
    （墙钟 5s、CPU 2s）以加快真实子进程测试，个别用例再按需覆盖。

    创建日期：2026-06-12
    author: claude
    """

    defaults: dict[str, Any] = {
        "llm_api_key": "k",
        "llm_api_key_file": None,
        "tushare_token": "t",
        "tushare_token_file": None,
        # 沙箱超时基线：墙钟 5s、CPU 2s，足够合法 pandas 计算完成又不至于拖慢测试。
        "py_sandbox_wall_timeout_seconds": 5,
        "py_sandbox_cpu_seconds": 2,
        "py_sandbox_memory_mb": 512,
        "py_sandbox_output_max_chars": 8000,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _execute_with_guard(
    executor: SandboxExecutor,
    code: str,
    data_files: list[tuple[str, str, Any]],
    guard_seconds: float,
) -> Any:
    """带兜底看门狗执行沙箱：超过 guard_seconds 仍未返回则强制让测试失败。

    被测实现自身有墙钟超时会终止子进程，但若实现存在 bug（如墙钟逻辑失效），
    测试不应真的挂死。本环境未安装 pytest-timeout，因此用后台线程在超时后
    向本进程发 SIGALRM 兜底；正常返回时立即取消看门狗。

    创建日期：2026-06-12
    author: claude
    """

    timed_out_flag: dict[str, bool] = {"hit": False}

    def _watchdog() -> None:
        timed_out_flag["hit"] = True
        # 主线程仍卡在 communicate 时用 SIGALRM 打断，避免测试进程永久挂起。
        signal.raise_signal(signal.SIGALRM)

    # 仅安装一次性 alarm 信号处理：触发即抛异常打断 communicate。
    def _on_alarm(_signum: int, _frame: Any) -> None:
        raise TimeoutError("沙箱执行超过测试看门狗上限，疑似被测墙钟超时失效")

    old_handler = signal.signal(signal.SIGALRM, _on_alarm)
    timer = threading.Timer(guard_seconds, _watchdog)
    timer.start()
    try:
        return executor.execute(code, data_files)
    finally:
        timer.cancel()
        signal.signal(signal.SIGALRM, old_handler)


def test_legal_pandas_correlation_returns_ok() -> None:
    """用例 1：合法 pandas 计算读 data/ 注入文件并 print，返回 ok 且 manifest 正确。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings())
    code = (
        "import json\n"
        "import pandas as pd\n"
        "with open('data/sql_result_1.json', encoding='utf-8') as f:\n"
        "    rows = json.load(f)\n"
        "df = pd.DataFrame(rows)\n"
        "corr = df['a'].corr(df['b'])\n"
        "print('CORR=', round(corr, 4))\n"
    )
    data_files = [("sql_result_1.json", "价格", [{"a": 1, "b": 2}, {"a": 2, "b": 4}])]
    result = executor.execute(code, data_files)

    assert result.ok is True
    assert result.exit_code == 0
    # a 与 b 完全正相关，corr 应为 1.0。
    assert "CORR= 1.0" in result.stdout
    assert result.manifest[0]["file"] == "data/sql_result_1.json"
    assert result.manifest[0]["rows"] == 2


def test_infinite_loop_killed_by_cpu_or_wallclock() -> None:
    """用例 2：死循环被 CPU 限额（SIGXCPU）或墙钟（SIGKILL）终止，二者皆可接受。

    墙钟设 3s、CPU 设 2s，加测试看门狗 8s 兜底防止真跑满；断言执行失败：
    not ok 且（退出码非 0 或 timed_out 为真）。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(
        _settings(py_sandbox_wall_timeout_seconds=3, py_sandbox_cpu_seconds=2)
    )
    result = _execute_with_guard(executor, "while True:\n    pass\n", [], guard_seconds=8.0)

    assert result.ok is False
    # CPU 限额命中 → 非零退出码；墙钟命中 → exit_code 为 None 且 timed_out=True。
    assert (result.exit_code not in (0, None)) or result.timed_out


def test_blocking_sleep_killed_by_wallclock() -> None:
    """用例 3：不烧 CPU 的阻塞 sleep 被墙钟超时杀，timed_out=True 且 stderr 含“墙钟”。

    墙钟设 3s（sleep 30s 远超），加看门狗 8s 兜底。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings(py_sandbox_wall_timeout_seconds=3))
    result = _execute_with_guard(
        executor, "import time\ntime.sleep(30)\n", [], guard_seconds=8.0
    )

    assert result.timed_out is True
    assert result.ok is False
    assert "墙钟" in result.stderr_summary


def test_socket_network_blocked() -> None:
    """用例 4：socket 联网被 audit hook 拦截，执行失败且 stderr 含“socket”或“禁止”。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings())
    code = "import socket\nsocket.create_connection(('1.1.1.1', 80))\n"
    result = _execute_with_guard(executor, code, [], guard_seconds=8.0)

    assert result.ok is False
    assert "socket" in result.stderr_summary or "禁止" in result.stderr_summary


def test_subprocess_blocked() -> None:
    """用例 5：subprocess 启动子进程被拦截，执行失败且 stderr 含“subprocess”或“禁止”。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings())
    code = "import subprocess\nsubprocess.run(['ls'])\n"
    result = _execute_with_guard(executor, code, [], guard_seconds=8.0)

    assert result.ok is False
    assert "subprocess" in result.stderr_summary or "禁止" in result.stderr_summary


def test_os_system_blocked() -> None:
    """用例 6：os.system 调用 shell 被拦截，执行失败。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings())
    code = "import os\nos.system('ls')\n"
    result = _execute_with_guard(executor, code, [], guard_seconds=8.0)

    assert result.ok is False


def test_escape_write_outside_workdir_blocked() -> None:
    """用例 7：越界写工作目录外文件被拦截，执行失败、目标文件未创建、stderr 含“越界”。

    用唯一文件名避免与历史残留冲突，并在断言后清理（理论上不应被创建）。

    创建日期：2026-06-12
    author: claude
    """

    escape_path = f"/tmp/agent-escape-{uuid.uuid4().hex}.txt"
    executor = SandboxExecutor(_settings())
    code = f"open({escape_path!r}, 'w').write('x')\n"
    try:
        result = _execute_with_guard(executor, code, [], guard_seconds=8.0)

        assert result.ok is False
        # 越界写应被 audit hook 在真正落盘前拦下，目标文件不存在。
        assert os.path.exists(escape_path) is False
        assert "越界" in result.stderr_summary
    finally:
        # 防御性清理：若被测实现存在 bug 让文件真被创建，避免污染本机临时目录。
        if os.path.exists(escape_path):
            os.remove(escape_path)


def test_write_inside_workdir_allowed() -> None:
    """用例 8：工作目录内写文件被放行（不拦截），执行成功。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings())
    code = "open('out.txt', 'w').write('ok')\nprint('wrote')\n"
    result = _execute_with_guard(executor, code, [], guard_seconds=8.0)

    assert result.ok is True
    assert "wrote" in result.stdout


def test_nonzero_exit_observable() -> None:
    """用例 9：用户代码抛异常导致非零退出，ok=False、exit_code 非 0、stderr 含异常信息。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings())
    result = _execute_with_guard(
        executor, "raise ValueError('boom')\n", [], guard_seconds=8.0
    )

    assert result.ok is False
    assert result.exit_code not in (0, None)
    assert "ValueError" in result.stderr_summary or "boom" in result.stderr_summary


def test_stdout_truncated_when_over_limit() -> None:
    """用例 10：print 超长字符串超过 py_sandbox_output_max_chars 时 stdout 被截断并带标记。

    把上限压到 100，print 一个 5000 字符串；截断标记为 budget.truncate_text 的“（已截断）”。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(_settings(py_sandbox_output_max_chars=100))
    code = "print('x' * 5000)\n"
    result = _execute_with_guard(executor, code, [], guard_seconds=8.0)

    assert result.ok is True
    # 截断后长度 = 100 + 标记长度，远小于原始 5000。
    assert len(result.stdout) < 5000
    assert "已截断" in result.stdout


@pytest.mark.skipif(sys.platform == "darwin", reason="RLIMIT_AS 在 macOS 不可靠")
def test_memory_bomb_killed() -> None:
    """用例 11：分配超内存大数组被 RLIMIT_AS 杀，执行失败（macOS 跳过）。

    设计 v3 修订 11：RLIMIT_AS 在 macOS 不可靠，故 darwin 平台跳过本用例；
    非 macOS 才断言 ok=False。内存上限压到 256MB，尝试分配 2GB bytearray。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(
        _settings(py_sandbox_memory_mb=256, py_sandbox_wall_timeout_seconds=10)
    )
    code = "x = bytearray(2 * 1024 * 1024 * 1024)\nprint(len(x))\n"
    result = _execute_with_guard(executor, code, [], guard_seconds=12.0)

    assert result.ok is False


def test_run_python_tool_handler_success() -> None:
    """用例 12a：run_python 工具 handler 读 data/ 注入文件算 mean 并 print，ToolResult.ok=True。

    构造 TurnState 预置 sql_results，经 build_run_python_tool 生成工具，
    直接调 handler；断言 payload 含 stdout 与 manifest。

    创建日期：2026-06-12
    author: claude
    """

    settings = _settings()
    state = TurnState()
    state.sql_results = [(1, "测试", [{"v": 1}, {"v": 3}])]
    tool = build_run_python_tool(settings, state)
    code = (
        "import json\n"
        "import pandas as pd\n"
        "with open('data/sql_result_1.json', encoding='utf-8') as f:\n"
        "    rows = json.load(f)\n"
        "print('MEAN=', pd.DataFrame(rows)['v'].mean())\n"
    )
    result = tool.handler({"code": code, "purpose": "算均值"}, state)

    assert result.ok is True
    # 1 与 3 的均值为 2.0，应出现在 stdout 中；payload 同时回填 manifest 文件清单。
    assert "MEAN= 2.0" in result.payload
    assert "sql_result_1.json" in result.payload


def test_run_python_tool_handler_missing_code() -> None:
    """用例 12b：run_python 工具缺 code 参数时直接返回 ok=False。

    创建日期：2026-06-12
    author: claude
    """

    settings = _settings()
    state = TurnState()
    tool = build_run_python_tool(settings, state)
    result = tool.handler({"purpose": "无代码"}, state)

    assert result.ok is False
    assert "缺少 code" in result.payload


def test_collect_data_files_names_and_descriptions() -> None:
    """用例 13：_collect_data_files 由 sql_results 与 stock_packages 生成正确文件名与说明。

    创建日期：2026-06-12
    author: claude
    """

    state = TurnState()
    state.sql_results = [(1, "查询溢价", [{"x": 1}])]
    state.stock_packages = [("600036.SH", "日线", {"close": [1, 2, 3]})]
    data_files = _collect_data_files(state)

    names = [item[0] for item in data_files]
    assert "sql_result_1.json" in names
    # ts_code 中的点替换为下划线，序号从 1 开始拼入文件名。
    assert "stock_600036_SH_1.json" in names
    sql_item = next(item for item in data_files if item[0] == "sql_result_1.json")
    assert "查询溢价" in sql_item[1]
    stock_item = next(item for item in data_files if item[0] == "stock_600036_SH_1.json")
    assert "600036.SH" in stock_item[1]


def _make_metric(now: datetime) -> LlmCallMetric:
    """构造一条 phase=tool_run_python 的当日指标，用于日配额计数。

    created_at 写东八区今日同一时刻（去 tzinfo，与被测实现的 naive 比较口径一致）。

    创建日期：2026-06-12
    author: claude
    """

    return LlmCallMetric(
        question_id="q",
        phase="tool_run_python",
        success=1,
        created_at=now,
        updated_at=now,
    )


def test_run_python_daily_quota_exhausted_branches() -> None:
    """用例 14：日配额判定的达限/未达/limit<=0 三条分支。

    内存 SQLite 建表后预插今日 phase=tool_run_python 指标；
    - 预插 2 条且 limit=2 → 已用尽 True；
    - limit=3（>已用 2）→ 未用尽 False；
    - limit=0 → 直接 False（关闭限流）。

    创建日期：2026-06-12
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # 东八区今日时刻（去 tzinfo）：落在被测实现的 [今日0点, 明日0点) 计数窗口内。
    now = datetime.now(_QUOTA_TIMEZONE).replace(tzinfo=None)
    with Session(engine) as db:
        db.add_all([_make_metric(now), _make_metric(now)])
        db.commit()

        # 达限：已用 2 >= limit 2。
        assert (
            run_python_daily_quota_exhausted(db, _settings(agent_run_python_daily_limit=2)) is True
        )
        # 未达限：已用 2 < limit 3。
        assert (
            run_python_daily_quota_exhausted(db, _settings(agent_run_python_daily_limit=3)) is False
        )
        # limit<=0：限流关闭，直接判未用尽。
        assert (
            run_python_daily_quota_exhausted(db, _settings(agent_run_python_daily_limit=0)) is False
        )
