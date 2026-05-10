from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    app_name: str = "港股通 A/H 溢价数据助手"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    database_url: str = Field(
        default="mysql+pymysql://root@127.0.0.1:3306/stock_ah_ai?charset=utf8mb4",
        alias="STOCK_AH_DB_URL",
    )
    tushare_api_url: str = Field(default="http://tsy.xiaodefa.cn", alias="TUSHARE_API_URL")
    tushare_token: str | None = Field(default=None, alias="TUSHARE_TOKEN")
    tushare_token_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/tushare-token.txt"),
        alias="TUSHARE_TOKEN_FILE",
    )
    tushare_timeout_seconds: float = Field(default=30.0, alias="TUSHARE_TIMEOUT_SECONDS")
    tushare_request_interval_seconds: float = Field(
        default=0.6,
        alias="TUSHARE_REQUEST_INTERVAL_SECONDS",
    )
    llm_base_url: str = Field(default="https://api.deepseek.com", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_api_key_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/deepseek-apikey.txt"),
        alias="LLM_API_KEY_FILE",
    )
    llm_model: str | None = Field(default="deepseek-v4-flash", alias="LLM_MODEL")
    llm_daily_call_limit: int = Field(default=100, alias="LLM_DAILY_CALL_LIMIT")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )
    qwen_api_key: str | None = Field(default=None, alias="QWEN_API_KEY")
    qwen_api_key_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/qwen-apikey.txt"),
        alias="QWEN_API_KEY_FILE",
    )
    qwen_question_router_model: str | None = Field(
        default=None,
        alias="QWEN_QUESTION_ROUTER_MODEL",
    )
    qwen_question_classifier_model: str | None = Field(
        default=None,
        alias="QWEN_QUESTION_CLASSIFIER_MODEL",
    )
    auth_secret_key: str = Field(default="stock-ah-premium-local-secret", alias="AUTH_SECRET_KEY")
    auth_token_expire_hours: int = Field(default=168, alias="AUTH_TOKEN_EXPIRE_HOURS")
    auth_remember_login_expire_days: int = Field(
        default=30,
        alias="AUTH_REMEMBER_LOGIN_EXPIRE_DAYS",
    )
    default_admin_username: str = Field(default="admin", alias="DEFAULT_ADMIN_USERNAME")
    default_admin_password: str = Field(default="admin123456", alias="DEFAULT_ADMIN_PASSWORD")
    cors_origins: list[str] = Field(default=["http://localhost:5173"], alias="APP_CORS_ORIGINS")
    query_limit_default: int = 200
    query_limit_max: int = 1000
    sync_scheduler_enabled: bool = Field(default=True, alias="SYNC_SCHEDULER_ENABLED")
    sync_scheduler_timezone: str = Field(default="Asia/Shanghai", alias="SYNC_SCHEDULER_TIMEZONE")
    alert_scheduler_enabled: bool = Field(default=True, alias="ALERT_SCHEDULER_ENABLED")
    alert_scan_minutes: int = Field(default=30, alias="ALERT_SCAN_MINUTES")
    alert_scan_seconds: int = Field(default=1, alias="ALERT_SCAN_SECONDS")
    alert_scan_hours: str = Field(default="9-16", alias="ALERT_SCAN_HOURS")
    limit_up_push_scheduler_enabled: bool = Field(
        default=True,
        alias="LIMIT_UP_PUSH_SCHEDULER_ENABLED",
    )
    limit_up_push_poll_minutes: str = Field(
        default="31,36,41,46,51,56",
        alias="LIMIT_UP_PUSH_POLL_MINUTES",
    )
    limit_up_push_poll_hours: str = Field(default="8-9", alias="LIMIT_UP_PUSH_POLL_HOURS")
    limit_up_push_weekend_replay_hour: int = Field(
        default=22,
        alias="LIMIT_UP_PUSH_WEEKEND_REPLAY_HOUR",
    )
    limit_up_push_model: str = Field(default="deepseek-v4-pro", alias="LIMIT_UP_PUSH_MODEL")
    limit_up_push_reasoning_effort: str = Field(
        default="max",
        alias="LIMIT_UP_PUSH_REASONING_EFFORT",
    )
    limit_up_push_prompt_version: str = Field(
        default="limit-up-v1",
        alias="LIMIT_UP_PUSH_PROMPT_VERSION",
    )
    limit_up_push_indicator_days: int = Field(default=40, alias="LIMIT_UP_PUSH_INDICATOR_DAYS")
    limit_up_push_indicator_stock_limit: int = Field(
        default=120,
        alias="LIMIT_UP_PUSH_INDICATOR_STOCK_LIMIT",
    )
    xueqiu_publish_scheduler_enabled: bool = Field(
        default=True,
        alias="XUEQIU_PUBLISH_SCHEDULER_ENABLED",
    )
    xueqiu_publish_auto_publish: bool = Field(default=False, alias="XUEQIU_PUBLISH_AUTO_PUBLISH")
    xueqiu_publish_poll_minutes: str = Field(
        default="30",
        alias="XUEQIU_PUBLISH_POLL_MINUTES",
    )
    xueqiu_publish_poll_hours: str = Field(default="8", alias="XUEQIU_PUBLISH_POLL_HOURS")
    xueqiu_publish_default_cover_pic: str = Field(
        default="https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png",
        alias="XUEQIU_PUBLISH_DEFAULT_COVER_PIC",
    )
    xueqiu_publish_timeout_seconds: float = Field(
        default=20.0,
        alias="XUEQIU_PUBLISH_TIMEOUT_SECONDS",
    )
    xueqiu_publish_default_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        alias="XUEQIU_PUBLISH_DEFAULT_USER_AGENT",
    )
    pushplus_enabled: bool = Field(default=True, alias="PUSHPLUS_ENABLED")
    pushplus_base_url: str = Field(default="https://www.pushplus.plus", alias="PUSHPLUS_BASE_URL")
    pushplus_token: str | None = Field(default=None, alias="PUSHPLUS_TOKEN")
    pushplus_token_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/pushplus.txt"),
        alias="PUSHPLUS_TOKEN_FILE",
    )
    pushplus_secret_key: str | None = Field(default=None, alias="PUSHPLUS_SECRET_KEY")
    pushplus_secret_key_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/pushplus.txt"),
        alias="PUSHPLUS_SECRET_KEY_FILE",
    )
    pushplus_template: str = Field(default="html", alias="PUSHPLUS_TEMPLATE")
    pushplus_channel: str = Field(default="wechat", alias="PUSHPLUS_CHANNEL")
    pushplus_timeout_seconds: float = Field(default=15.0, alias="PUSHPLUS_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        """解析 CORS 配置。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def resolve_tushare_token(self) -> str | None:
        """按本机文件优先、环境变量兜底的顺序读取 Tushare Token。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if self.tushare_token_file and self.tushare_token_file.exists():
            token = self.tushare_token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
        if self.tushare_token:
            return self.tushare_token.strip()
        return None

    def resolve_llm_api_key(self) -> str | None:
        """按本机文件优先、环境变量兜底的顺序读取 LLM API Key。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if self.llm_api_key_file and self.llm_api_key_file.exists():
            api_key = self.llm_api_key_file.read_text(encoding="utf-8").strip()
            if api_key:
                return api_key
        if self.llm_api_key:
            return self.llm_api_key.strip()
        return None

    def resolve_qwen_api_key(self) -> str | None:
        """按本机文件优先、环境变量兜底的顺序读取 Qwen API Key。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if self.qwen_api_key_file and self.qwen_api_key_file.exists():
            api_key = self.qwen_api_key_file.read_text(encoding="utf-8").strip()
            if api_key:
                return api_key
        if self.qwen_api_key:
            return self.qwen_api_key.strip()
        return None

    def resolve_question_router_model(self) -> str | None:
        """读取问答前置路由模型，未单独配置时跟随默认问答模型。

        创建日期：2026-05-05
        author: sunshengxian
        """

        # 历史版本把路由器固定在 Qwen；保留旧环境变量兼容，
        # 但默认跟随主问答模型，DeepSeek 临时不可用时由调用层统一切到备用 Qwen。
        if self.qwen_question_classifier_model:
            return self.qwen_question_classifier_model.strip()
        if self.qwen_question_router_model:
            return self.qwen_question_router_model.strip()
        return self.llm_model.strip() if self.llm_model else None

    def resolve_pushplus_token(self) -> str | None:
        """按本机文件优先、环境变量兜底的顺序读取 PushPlus 用户 Token。

        创建日期：2026-05-05
        author: sunshengxian
        """

        file_values = self._read_pushplus_credential_file(self.pushplus_token_file)
        if file_values.get("token"):
            return file_values["token"]
        if self.pushplus_token:
            return self.pushplus_token.strip()
        return None

    def resolve_pushplus_secret_key(self) -> str | None:
        """按本机文件优先、环境变量兜底的顺序读取 PushPlus 开放接口密钥。

        创建日期：2026-05-05
        author: sunshengxian
        """

        file_values = self._read_pushplus_credential_file(self.pushplus_secret_key_file)
        if file_values.get("secret_key"):
            return file_values["secret_key"]
        if self.pushplus_secret_key:
            return self.pushplus_secret_key.strip()
        return None

    def _read_pushplus_credential_file(self, path: Path | None) -> dict[str, str]:
        """解析 PushPlus 本机凭据文件，支持键值或前两行写法。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if not path or not path.exists():
            return {}
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        values: dict[str, str] = {}
        positional: list[str] = []
        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", maxsplit=1)
            elif ":" in line:
                key, value = line.split(":", maxsplit=1)
            else:
                positional.append(line)
                continue
            normalized_key = key.strip().lower().replace("-", "_")
            normalized_value = value.strip()
            if not normalized_value:
                continue
            if normalized_key in {"pushplus_token", "token", "user_token", "用户token"}:
                values["token"] = normalized_value
            elif normalized_key in {
                "pushplus_secret_key",
                "secret_key",
                "secretkey",
                "secret",
                "密钥",
            }:
                values["secret_key"] = normalized_value
        if "token" not in values and positional:
            values["token"] = positional[0]
        if "secret_key" not in values and len(positional) >= 2:
            values["secret_key"] = positional[1]
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取缓存后的应用配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return Settings()
