"""沙箱子进程包装器：先施加资源限制与审计钩子，再执行用户代码。

独立脚本口径（chat-agent-refactor-design-and-plan.md 3.4 节）：
- 由 SandboxExecutor 以 `{venv_python} -I sandbox_runner.py main.py` 启动：
  -I 隔离模式忽略环境变量注入与用户 site，venv 解释器保证 pandas/numpy 可用；
- 本文件绝不 import 项目内任何模块（它运行在沙箱进程里，必须自包含）；
- 约束分四层（与父进程的墙钟超时、临时目录、环境白名单叠加）：
  1. rlimit：CPU 时间 / 地址空间 / 单文件写入上限；
  2. audit hook：禁网（socket.*）、禁子进程（subprocess/os.system/exec/spawn/fork）、
     禁越界写（open 写模式且路径在工作目录之外）、禁动态加载（ctypes.dlopen）；
  3. 命中即抛 SandboxSecurityError 终止，违规行为写 stderr 供审计；
  4. audit hook 属软约束（纯 C 扩展可绕过），叠加其余约束满足个人项目安全要求。
- 平台差异（设计 v3 修订 11）：RLIMIT_AS 在 macOS 上不可靠且 pandas 自身占用大，
  rlimit 设置失败时容错降级（记 stderr），由墙钟超时 + CPU 限额兜底。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import os
import runpy
import sys

# 资源限制默认值：父进程通过命令行参数覆盖（不读环境变量，-I 模式下环境已清空）。
DEFAULT_CPU_SECONDS = 10
DEFAULT_MEMORY_MB = 512
DEFAULT_FSIZE_MB = 16


class SandboxSecurityError(RuntimeError):
    """沙箱安全违规：用户代码触发被禁止的系统行为。

    创建日期：2026-06-12
    author: claude
    """


def _apply_rlimits(cpu_seconds: int, memory_mb: int) -> None:
    """施加 CPU / 地址空间 / 单文件写入上限；单项失败降级不致命。

    创建日期：2026-06-12
    author: claude
    """

    import resource

    limits = [
        ("RLIMIT_CPU", resource.RLIMIT_CPU, cpu_seconds),
        ("RLIMIT_AS", resource.RLIMIT_AS, memory_mb * 1024 * 1024),
        ("RLIMIT_FSIZE", resource.RLIMIT_FSIZE, DEFAULT_FSIZE_MB * 1024 * 1024),
    ]
    for name, key, value in limits:
        try:
            resource.setrlimit(key, (value, value))
        except (ValueError, OSError) as exc:
            # macOS 对 RLIMIT_AS 常拒绝设置；降级记录，依赖墙钟超时与 CPU 限额兜底。
            print(f"[sandbox] {name} 设置失败已降级：{exc}", file=sys.stderr)


def _preload_libraries() -> None:
    """在安装审计钩子前预热 pandas/numpy。

    numpy/pandas 导入 C 扩展时会触发 ctypes.dlopen，而审计钩子要禁止用户代码
    动态加载库；若不预热，合法的 import pandas 会被钩子误杀。预热后这些扩展已
    在 sys.modules 缓存，用户代码再 import 不会重复 dlopen，禁动态加载约束仍有效。
    预热失败（环境未装）不致命，由用户代码 import 时自行报错。

    创建日期：2026-06-12
    author: claude
    """

    for module_name in ("numpy", "pandas"):
        try:
            __import__(module_name)
        except Exception as exc:  # noqa: BLE001
            print(f"[sandbox] 预热 {module_name} 失败：{exc}", file=sys.stderr)


def _install_audit_hook(work_dir: str) -> None:
    """安装审计钩子：拦截网络、子进程、越界写与动态加载。

    创建日期：2026-06-12
    author: claude
    """

    # 前缀命中即拒绝的事件族：网络与进程类行为对计算型沙箱没有合法用途。
    banned_prefixes = (
        "socket.",
        "subprocess.",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.fork",
        "os.posix_spawn",
        "ctypes.dlopen",
        "webbrowser.open",
    )
    real_work_dir = os.path.realpath(work_dir)

    def hook(event: str, args: tuple) -> None:
        for prefix in banned_prefixes:
            if event.startswith(prefix):
                raise SandboxSecurityError(f"沙箱禁止行为：{event}")
        if event == "open":
            path, mode = args[0], args[1]
            mode_text = str(mode or "r")
            # 只拦截写模式；读权限由临时目录隔离 + 环境清空保障（数据都在 data/ 内）。
            if any(flag in mode_text for flag in ("w", "a", "x", "+")):
                target = os.path.realpath(
                    path if isinstance(path, str) else os.fsdecode(path)
                )
                if not target.startswith(real_work_dir + os.sep) and target != real_work_dir:
                    raise SandboxSecurityError(f"沙箱禁止越界写文件：{target}")

    sys.addaudithook(hook)


def main() -> None:
    """入口：参数为 [用户脚本] [cpu秒] [内存MB]，约束就绪后执行用户代码。

    创建日期：2026-06-12
    author: claude
    """

    if len(sys.argv) < 2:
        print("[sandbox] 缺少用户脚本参数", file=sys.stderr)
        raise SystemExit(2)
    script = sys.argv[1]
    cpu_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CPU_SECONDS
    memory_mb = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_MEMORY_MB
    _apply_rlimits(cpu_seconds, memory_mb)
    # 顺序关键：先预热 C 扩展库，再装审计钩子，否则 import pandas 会被禁动态加载误杀。
    _preload_libraries()
    _install_audit_hook(os.getcwd())
    try:
        runpy.run_path(script, run_name="__main__")
    except SandboxSecurityError as exc:
        print(f"[sandbox] {exc}", file=sys.stderr)
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
