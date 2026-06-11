from __future__ import annotations

from pathlib import Path

from app.core.config import Settings


def _settings_without_local_files(**overrides) -> Settings:
    """构造不依赖本机密钥文件的配置，避免测试读取开发机真实 key。

    创建日期：2026-06-11
    author: claude
    """

    defaults = {
        "llm_api_key": None,
        "llm_api_key_file": None,
        "qwen_api_key": None,
        "qwen_api_key_file": None,
        "bocha_api_key": None,
        "bocha_api_key_file": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_resolve_bocha_api_key_prefers_key_file(tmp_path: Path) -> None:
    """确认博查 key 按文件优先读取，并去除首尾空白。

    创建日期：2026-06-11
    author: claude
    """

    key_file = tmp_path / "bocha-apikey.txt"
    key_file.write_text("  sk-bocha-from-file \n", encoding="utf-8")
    settings = _settings_without_local_files(
        bocha_api_key="sk-bocha-from-env",
        bocha_api_key_file=key_file,
    )

    assert settings.resolve_bocha_api_key() == "sk-bocha-from-file"


def test_resolve_bocha_api_key_falls_back_to_env_value(tmp_path: Path) -> None:
    """确认 key 文件缺失或为空时回落到环境变量值。

    创建日期：2026-06-11
    author: claude
    """

    missing_file = tmp_path / "not-exists.txt"
    settings = _settings_without_local_files(
        bocha_api_key="sk-bocha-from-env",
        bocha_api_key_file=missing_file,
    )

    assert settings.resolve_bocha_api_key() == "sk-bocha-from-env"


def test_resolve_bocha_api_key_returns_none_when_unconfigured() -> None:
    """确认完全未配置时返回 None，由工具目录层负责平滑降级。

    创建日期：2026-06-11
    author: claude
    """

    settings = _settings_without_local_files()

    assert settings.resolve_bocha_api_key() is None


def test_agent_settings_have_safe_defaults() -> None:
    """确认 Agent 引擎与沙箱配置默认值与设计文档 3.8 节口径一致。

    创建日期：2026-06-11
    author: claude
    """

    settings = _settings_without_local_files()

    assert settings.agent_model == "deepseek-v4-pro"
    assert settings.agent_max_iterations == 8
    assert settings.agent_context_budget_chars == 48000
    assert settings.chat_daily_round_limit == 50
    assert settings.bocha_base_url == "https://api.bochaai.com"
    assert settings.agent_web_search_daily_limit == 100
    assert settings.agent_run_python_daily_limit == 100
    assert settings.py_sandbox_wall_timeout_seconds == 20
    assert settings.py_sandbox_cpu_seconds == 10
    assert settings.py_sandbox_memory_mb == 512
    assert settings.py_sandbox_output_max_chars == 8000
