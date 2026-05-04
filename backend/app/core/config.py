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
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    cors_origins: list[str] = Field(default=["http://localhost:5173"], alias="APP_CORS_ORIGINS")
    query_limit_default: int = 200
    query_limit_max: int = 1000

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
        """按环境变量优先、本机文件兜底的顺序读取 Tushare Token。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if self.tushare_token:
            return self.tushare_token.strip()
        if self.tushare_token_file and self.tushare_token_file.exists():
            token = self.tushare_token_file.read_text(encoding="utf-8").strip()
            return token or None
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取缓存后的应用配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return Settings()
