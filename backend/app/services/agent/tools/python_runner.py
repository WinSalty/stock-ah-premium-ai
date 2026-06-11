"""run_python 工具：subprocess 沙箱执行 Python 计算（pandas/numpy 可用）。

口径（chat-agent-refactor-design-and-plan.md 3.4 节）：
- SandboxExecutor 负责：临时工作目录 + data/ 数据注入 + manifest、`-I` 隔离模式
  启动 sandbox_runner 包装器（rlimit + audit hook 在子进程内施加）、环境变量
  白名单（仅 PATH/LANG）、start_new_session 便于墙钟超时对整组 SIGKILL；
- 本轮 query_database / get_stock_data 的完整结果以 JSON 文件挂载于 data/，
  manifest 同时回填给模型，模型据此读文件计算；
- stdout/stderr 截断后回填；非零退出模型可修正重试（计入轮内 run_python 配额）；
- 代码与输出经引擎统一写 llm_call_metric（phase=tool_run_python）审计留痕；
- SandboxExecutor 接口化：部署机具备 Docker 条件时可替换容器实现而不动工具层。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.agent.budget import TurnState, truncate_text
from app.services.agent.tool_registry import ToolResult, ToolSpec

logger = logging.getLogger(__name__)

# 沙箱包装器脚本路径：与本文件同包的独立脚本，子进程内自包含运行。
SANDBOX_RUNNER_PATH = Path(__file__).resolve().parent.parent / "sandbox_runner.py"
_QUOTA_TIMEZONE = ZoneInfo("Asia/Shanghai")


def run_python_daily_quota_exhausted(db: Session, settings: Settings) -> bool:
    """判断沙箱执行的当日配额是否用尽（用尽则工具当日降级移除）。

    创建日期：2026-06-12
    author: claude
    """

    limit = settings.agent_run_python_daily_limit
    if limit <= 0:
        return False
    from app.db.models.chat import LlmCallMetric

    now = datetime.now(_QUOTA_TIMEZONE).replace(tzinfo=None)
    today_start = datetime.combine(now.date(), time.min)
    statement = select(func.count(LlmCallMetric.id)).where(
        LlmCallMetric.phase == "tool_run_python",
        LlmCallMetric.created_at >= today_start,
        LlmCallMetric.created_at < today_start + timedelta(days=1),
    )
    try:
        used = int(db.scalar(statement) or 0)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.error("沙箱日配额统计失败，按未用尽处理", exc_info=True)
        return False
    return used >= limit


@dataclass
class SandboxResult:
    """一次沙箱执行的结果。

    创建日期：2026-06-12
    author: claude
    """

    ok: bool
    exit_code: int | None
    stdout: str
    stderr_summary: str
    manifest: list[dict[str, Any]]
    timed_out: bool = False


class SandboxExecutor:
    """subprocess 沙箱执行器。

    安全层次（与设计 3.4 一致）：隔离子进程（-I + 环境白名单 + 临时 cwd）
    + 子进程内 rlimit/audit hook（sandbox_runner.py）+ 父进程墙钟超时整组 SIGKILL。

    创建日期：2026-06-12
    author: claude
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        code: str,
        data_files: list[tuple[str, str, Any]],
    ) -> SandboxResult:
        """执行用户代码。

        data_files 为 (文件名, 用途说明, 可 JSON 序列化内容) 列表，
        写入工作目录 data/ 子目录并生成 manifest.json。

        创建日期：2026-06-12
        author: claude
        """

        work_dir = Path(tempfile.gettempdir()) / f"agent-py-{uuid.uuid4().hex}"
        data_dir = work_dir / "data"
        data_dir.mkdir(parents=True)
        try:
            manifest = self._write_data_files(data_dir, data_files)
            (work_dir / "main.py").write_text(code, encoding="utf-8")
            return self._run_subprocess(work_dir, manifest)
        finally:
            # 工作目录一次性使用：执行完即清理，失败也不留临时数据。
            shutil.rmtree(work_dir, ignore_errors=True)

    def _write_data_files(
        self,
        data_dir: Path,
        data_files: list[tuple[str, str, Any]],
    ) -> list[dict[str, Any]]:
        """写入数据文件与 manifest.json，返回 manifest 内容。

        创建日期：2026-06-12
        author: claude
        """

        manifest: list[dict[str, Any]] = []
        for file_name, description, content in data_files:
            target = data_dir / file_name
            target.write_text(
                json.dumps(content, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            rows = len(content) if isinstance(content, list) else None
            manifest.append(
                {"file": f"data/{file_name}", "description": description, "rows": rows}
            )
        (data_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        return manifest

    def _run_subprocess(self, work_dir: Path, manifest: list[dict[str, Any]]) -> SandboxResult:
        """启动沙箱子进程并按墙钟超时整组终止。

        创建日期：2026-06-12
        author: claude
        """

        max_chars = self.settings.py_sandbox_output_max_chars
        command = [
            sys.executable,
            "-I",
            str(SANDBOX_RUNNER_PATH),
            "main.py",
            str(self.settings.py_sandbox_cpu_seconds),
            str(self.settings.py_sandbox_memory_mb),
        ]
        # 环境白名单：只保留 PATH/LANG，杜绝密钥与数据库地址泄入沙箱。
        env = {key: os.environ[key] for key in ("PATH", "LANG") if key in os.environ}
        process = subprocess.Popen(
            command,
            cwd=str(work_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(
                timeout=self.settings.py_sandbox_wall_timeout_seconds
            )
        except subprocess.TimeoutExpired:
            # 墙钟到期对整个进程组 SIGKILL：覆盖用户代码自行 fork 失败前的残留线程。
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            stdout, stderr = process.communicate()
            return SandboxResult(
                ok=False,
                exit_code=None,
                stdout=truncate_text(stdout or "", max_chars),
                stderr_summary=(
                    f"执行超过墙钟上限 {self.settings.py_sandbox_wall_timeout_seconds}s 被终止"
                ),
                manifest=manifest,
                timed_out=True,
            )
        return SandboxResult(
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout=truncate_text(stdout or "", max_chars),
            stderr_summary=truncate_text(stderr or "", 2000),
            manifest=manifest,
        )


def _collect_data_files(state: TurnState) -> list[tuple[str, str, Any]]:
    """汇总本轮工具结果为沙箱数据文件清单（SQL 完整结果 + 个股数据包）。

    创建日期：2026-06-12
    author: claude
    """

    data_files: list[tuple[str, str, Any]] = []
    for index, purpose, rows in state.sql_results:
        data_files.append(
            (f"sql_result_{index}.json", f"query_database 第 {index} 次结果：{purpose}", rows)
        )
    for seq, (ts_code, packages, context) in enumerate(state.stock_packages, start=1):
        safe_code = ts_code.replace(".", "_")
        data_files.append(
            (
                f"stock_{safe_code}_{seq}.json",
                f"get_stock_data {ts_code} 数据包（{packages}）",
                context,
            )
        )
    return data_files


def build_run_python_tool(settings: Settings, turn_state: TurnState) -> ToolSpec:
    """构造 run_python 工具。

    创建日期：2026-06-12
    author: claude
    """

    executor = SandboxExecutor(settings)

    def handler(args: dict[str, Any], state: TurnState) -> ToolResult:
        """执行沙箱计算并回填 stdout 与 manifest。

        创建日期：2026-06-12
        author: claude
        """

        code = str(args.get("code") or "").strip()
        if not code:
            return ToolResult(ok=False, payload="缺少 code 参数。", summary="缺少代码")
        data_files = _collect_data_files(state)
        result = executor.execute(code, data_files)
        manifest_text = json.dumps(result.manifest, ensure_ascii=False)
        body = {
            "ok": result.ok,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr_summary": result.stderr_summary,
            "manifest": result.manifest,
        }
        if result.timed_out:
            summary = "执行超时被终止"
        elif result.ok:
            summary = f"计算完成（输出 {len(result.stdout)} 字符）"
        else:
            summary = f"执行失败（exit={result.exit_code}）"
        return ToolResult(
            ok=result.ok,
            payload=json.dumps(body, ensure_ascii=False)
            + f"\n（data/ 目录文件清单：{manifest_text}）",
            summary=summary,
        )

    return ToolSpec(
        name="run_python",
        description=(
            "在沙箱中执行 Python 计算。可用库：pandas/numpy/标准库。"
            "本轮已查询的数据以 JSON 文件挂载于 data/ 目录"
            "（文件清单见每次返回的 manifest，data/manifest.json 也可读）。"
            "无网络、无法访问 data/ 与工作目录之外的路径、不能启动子进程。"
            "结果必须 print 输出，否则拿不到任何返回。"
            "适用：相关性/年化/波动率/回测统计等数值计算；"
            "禁止用于能直接 SQL 聚合得到的简单求和排序。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "完整可执行脚本，结果必须 print 输出",
                },
                "purpose": {
                    "type": "string",
                    "description": "一句话说明计算目的，用于界面展示",
                },
            },
            "required": ["code", "purpose"],
        },
        handler=handler,
        summarize=lambda args: f"计算：{str(args.get('purpose') or 'Python 计算')[:50]}",
        capability_note=(
            "run_python：沙箱内执行 pandas/numpy 计算"
            "（本轮已查数据自动挂载 data/ 目录），用于相关性、年化、回测等数值分析。"
        ),
    )
