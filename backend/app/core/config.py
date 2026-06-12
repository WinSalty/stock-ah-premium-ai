from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 打板报告技术指标股票池默认上限翻倍到 240，只影响关注股票短窗口指标计算，不扩大到全市场扫描。
LIMIT_UP_PUSH_DEFAULT_INDICATOR_STOCK_LIMIT = 240


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
    tushare_api_url: str = Field(default="https://tt.xiaodefa.cn", alias="TUSHARE_API_URL")
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
    tushare_request_max_attempts: int = Field(default=5, alias="TUSHARE_REQUEST_MAX_ATTEMPTS")
    tushare_retry_backoff_seconds: float = Field(default=3.0, alias="TUSHARE_RETRY_BACKOFF_SECONDS")
    llm_base_url: str = Field(default="https://api.deepseek.com", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_api_key_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/deepseek-apikey.txt"),
        alias="LLM_API_KEY_FILE",
    )
    llm_model: str | None = Field(default="deepseek-v4-flash", alias="LLM_MODEL")
    llm_daily_call_limit: int = Field(default=100, alias="LLM_DAILY_CALL_LIMIT")
    image_gen_base_url: str = Field(
        default="https://api.86gamestore.com",
        alias="IMAGE_GEN_BASE_URL",
    )
    image_gen_api_key: str | None = Field(default=None, alias="IMAGE_GEN_API_KEY")
    image_gen_api_key_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/86gamestore-image-apikey.txt"),
        alias="IMAGE_GEN_API_KEY_FILE",
    )
    image_gen_model: str = Field(default="gpt-image-2", alias="IMAGE_GEN_MODEL")
    image_gen_timeout_seconds: float = Field(default=500.0, alias="IMAGE_GEN_TIMEOUT_SECONDS")
    image_gen_daily_limit_default: int = Field(default=10, alias="IMAGE_GEN_DAILY_LIMIT_DEFAULT")
    image_gen_storage_backend: str = Field(default="oss", alias="IMAGE_GEN_STORAGE_BACKEND")
    image_gen_storage_dir: Path = Field(
        default=Path("/opt/stock-ah-premium-ai/data/generated-images"),
        alias="IMAGE_GEN_STORAGE_DIR",
    )
    image_gen_oss_endpoint: str | None = Field(default=None, alias="IMAGE_GEN_OSS_ENDPOINT")
    image_gen_oss_bucket: str | None = Field(default=None, alias="IMAGE_GEN_OSS_BUCKET")
    image_gen_oss_prefix: str = Field(
        default="stock-ah-premium-ai/generated-images",
        alias="IMAGE_GEN_OSS_PREFIX",
    )
    image_gen_oss_access_key_id: str | None = Field(
        default=None,
        alias="IMAGE_GEN_OSS_ACCESS_KEY_ID",
    )
    image_gen_oss_access_key_id_file: Path | None = Field(
        default=None,
        alias="IMAGE_GEN_OSS_ACCESS_KEY_ID_FILE",
    )
    image_gen_oss_access_key_secret: str | None = Field(
        default=None,
        alias="IMAGE_GEN_OSS_ACCESS_KEY_SECRET",
    )
    image_gen_oss_access_key_secret_file: Path | None = Field(
        default=None,
        alias="IMAGE_GEN_OSS_ACCESS_KEY_SECRET_FILE",
    )
    image_gen_oss_security_token: str | None = Field(
        default=None,
        alias="IMAGE_GEN_OSS_SECURITY_TOKEN",
    )
    image_gen_oss_security_token_file: Path | None = Field(
        default=None,
        alias="IMAGE_GEN_OSS_SECURITY_TOKEN_FILE",
    )
    image_gen_oss_signed_url_expires_seconds: int = Field(
        default=86400,
        alias="IMAGE_GEN_OSS_SIGNED_URL_EXPIRES_SECONDS",
    )
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
    # ---- Agent 问答引擎（问答模块 Agent 化重构，阶段 0 起逐步生效）----
    # Agent 循环模型独立于 legacy 问答模型：工具调用准确性优先，默认用 pro 档。
    agent_model: str = Field(default="deepseek-v4-pro", alias="AGENT_MODEL")
    # 单轮回答内工具迭代上限；达到上限后强制模型基于已有材料收尾作答。
    agent_max_iterations: int = Field(default=8, alias="AGENT_MAX_ITERATIONS")
    # 单轮 messages 材料字符预算；超限时从最早的工具结果开始压缩为摘要。
    agent_context_budget_chars: int = Field(
        default=48000,
        alias="AGENT_CONTEXT_BUDGET_CHARS",
    )
    # 用户可感知配额：问答轮数/天（区别于 llm_daily_call_limit 的内部调用硬上限）。
    chat_daily_round_limit: int = Field(default=50, alias="CHAT_DAILY_ROUND_LIMIT")
    # ---- 博查联网搜索 ----
    bocha_base_url: str = Field(default="https://api.bochaai.com", alias="BOCHA_BASE_URL")
    bocha_api_key: str | None = Field(default=None, alias="BOCHA_API_KEY")
    bocha_api_key_file: Path | None = Field(
        default=Path("/Users/salty/codeProject/ai/doc/博查-apikey.txt"),
        alias="BOCHA_API_KEY_FILE",
    )
    # 搜索（含网页正文抓取）次数/天；用尽后 web_search 工具当日自动降级移除。
    agent_web_search_daily_limit: int = Field(
        default=100,
        alias="AGENT_WEB_SEARCH_DAILY_LIMIT",
    )
    # ---- Python 沙箱 ----
    # 沙箱执行次数/天；用尽后 run_python 工具当日自动降级移除。
    agent_run_python_daily_limit: int = Field(
        default=100,
        alias="AGENT_RUN_PYTHON_DAILY_LIMIT",
    )
    # 墙钟超时：到期对沙箱进程组整体 SIGKILL，防止 CPU 限额外的 IO 阻塞挂死。
    py_sandbox_wall_timeout_seconds: int = Field(
        default=20,
        alias="PY_SANDBOX_WALL_TIMEOUT_SECONDS",
    )
    # CPU 时间上限（RLIMIT_CPU），防死循环烧 CPU。
    py_sandbox_cpu_seconds: int = Field(default=10, alias="PY_SANDBOX_CPU_SECONDS")
    # 地址空间上限（RLIMIT_AS），防内存炸弹。
    py_sandbox_memory_mb: int = Field(default=512, alias="PY_SANDBOX_MEMORY_MB")
    # stdout 截断长度：超出部分丢弃，只回填给模型可消化的结果片段。
    py_sandbox_output_max_chars: int = Field(
        default=8000,
        alias="PY_SANDBOX_OUTPUT_MAX_CHARS",
    )
    # ---- 问答治理（阶段 5）----
    # 流式问答同时活跃的后台 worker 上限（旧评审 R5）：每个流式请求起一个独立
    # SessionLocal 的 daemon 线程，无上限会耗尽数据库连接池；超限时友好排队/拒绝。
    chat_stream_max_concurrency: int = Field(
        default=8,
        alias="CHAT_STREAM_MAX_CONCURRENCY",
    )
    # 获取流式并发名额的最长等待秒数：超时仍拿不到名额则返回繁忙提示，避免请求挂死。
    chat_stream_acquire_timeout_seconds: float = Field(
        default=15.0,
        alias="CHAT_STREAM_ACQUIRE_TIMEOUT_SECONDS",
    )
    # 指标保留天数（旧评审 R4）：清理脚本删除早于该天数的 llm_call_metric，<=0 表示不清理。
    llm_metric_retention_days: int = Field(
        default=90,
        alias="LLM_METRIC_RETENTION_DAYS",
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
        default=LIMIT_UP_PUSH_DEFAULT_INDICATOR_STOCK_LIMIT,
        alias="LIMIT_UP_PUSH_INDICATOR_STOCK_LIMIT",
    )
    limit_up_push_chain_focus_stock_limit: int = Field(
        default=20,
        alias="LIMIT_UP_PUSH_CHAIN_FOCUS_STOCK_LIMIT",
    )
    limit_up_push_high_board_focus_stock_limit: int = Field(
        default=10,
        alias="LIMIT_UP_PUSH_HIGH_BOARD_FOCUS_STOCK_LIMIT",
    )
    # 首板重点入选上限：“少量精选”口径，过大会稀释精选定位并抬升筹码补数调用量。
    limit_up_push_first_board_focus_stock_limit: int = Field(
        default=5,
        alias="LIMIT_UP_PUSH_FIRST_BOARD_FOCUS_STOCK_LIMIT",
    )
    limit_up_push_cyq_lookback_days: int = Field(
        default=20,
        alias="LIMIT_UP_PUSH_CYQ_LOOKBACK_DAYS",
    )
    limit_up_push_stage_cache_enabled: bool = Field(
        default=True,
        alias="LIMIT_UP_PUSH_STAGE_CACHE_ENABLED",
    )
    # v3：最终合成阶段新增首板重点个股小节（首板个股精选扩展），按既定规约提示词变更必须 bump；
    # bump 会使全部阶段缓存失效并重新生成，属预期行为；存量 READY 报告不受影响。
    limit_up_push_final_prompt_version: str = Field(
        default="limit-up-multi-stage-v3",
        alias="LIMIT_UP_PUSH_FINAL_PROMPT_VERSION",
    )
    limit_up_push_generating_stale_minutes: int = Field(
        default=30,
        alias="LIMIT_UP_PUSH_GENERATING_STALE_MINUTES",
    )
    # 推送内容模式：ADVICE=推送投资建议（重构后默认）；REPORT=推送完整报告，
    # 严格回滚通道——REPORT 模式不触发建议生成、不写建议列，行为与重构前一致。
    limit_up_push_content_mode: str = Field(
        default="ADVICE",
        alias="LIMIT_UP_PUSH_CONTENT_MODE",
    )
    # PushPlus 渠道：建议生成失败时是否降级推送完整报告（默认开，保障早盘交付）。
    limit_up_push_advice_fallback_to_report: bool = Field(
        default=True,
        alias="LIMIT_UP_PUSH_ADVICE_FALLBACK_TO_REPORT",
    )
    nine_turn_push_scheduler_enabled: bool = Field(
        default=False,
        alias="NINE_TURN_PUSH_SCHEDULER_ENABLED",
    )
    nine_turn_push_poll_minutes: str = Field(
        default="10,20,30,40,50",
        alias="NINE_TURN_PUSH_POLL_MINUTES",
    )
    nine_turn_push_poll_hours: str = Field(default="21-22", alias="NINE_TURN_PUSH_POLL_HOURS")
    nine_turn_push_model: str = Field(default="deepseek-v4-pro", alias="NINE_TURN_PUSH_MODEL")
    nine_turn_push_reasoning_effort: str = Field(
        default="max",
        alias="NINE_TURN_PUSH_REASONING_EFFORT",
    )
    nine_turn_push_prompt_version: str = Field(
        default="nine-turn-v1",
        alias="NINE_TURN_PUSH_PROMPT_VERSION",
    )
    nine_turn_context_signal_limit: int = Field(default=240, alias="NINE_TURN_CONTEXT_SIGNAL_LIMIT")
    nine_turn_context_watch_limit: int = Field(default=360, alias="NINE_TURN_CONTEXT_WATCH_LIMIT")
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
    # 雪球发布内容模式：独立于 PushPlus，两渠道受众不同允许分别回滚。
    xueqiu_limit_up_content_mode: str = Field(
        default="ADVICE",
        alias="XUEQIU_LIMIT_UP_CONTENT_MODE",
    )
    # 雪球渠道建议失败降级开关：默认关——公开平台宁可当日不发，
    # 也不在"建议模式"下发出与预期不符的整报；与 PushPlus 降级开关独立。
    xueqiu_limit_up_advice_fallback_to_report: bool = Field(
        default=False,
        alias="XUEQIU_LIMIT_UP_ADVICE_FALLBACK_TO_REPORT",
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

    def resolve_bocha_api_key(self) -> str | None:
        """按本机文件优先、环境变量兜底的顺序读取博查搜索 API Key。

        Key 缺失时联网搜索工具会从 Agent 工具目录中移除并平滑降级，
        因此这里只负责读取，不抛异常。

        创建日期：2026-06-11
        author: claude
        """

        return self._read_optional_secret(self.bocha_api_key_file, self.bocha_api_key)

    def resolve_image_gen_api_key(self) -> str | None:
        """按本机数据盘外密钥文件优先、环境变量兜底的顺序读取文生图 API Key。

        创建日期：2026-05-27
        author: sunshengxian
        """

        if self.image_gen_api_key_file and self.image_gen_api_key_file.exists():
            api_key = self.image_gen_api_key_file.read_text(encoding="utf-8").strip()
            if api_key:
                return api_key
        if self.image_gen_api_key:
            return self.image_gen_api_key.strip()
        return None

    def resolve_image_gen_oss_access_key_id(self) -> str | None:
        """按文件优先、环境变量兜底读取图片 OSS AccessKey ID。

        创建日期：2026-06-06
        author: sunshengxian
        """

        return self._read_optional_secret(
            self.image_gen_oss_access_key_id_file,
            self.image_gen_oss_access_key_id,
        )

    def resolve_image_gen_oss_access_key_secret(self) -> str | None:
        """按文件优先、环境变量兜底读取图片 OSS AccessKey Secret。

        创建日期：2026-06-06
        author: sunshengxian
        """

        return self._read_optional_secret(
            self.image_gen_oss_access_key_secret_file,
            self.image_gen_oss_access_key_secret,
        )

    def resolve_image_gen_oss_security_token(self) -> str | None:
        """按文件优先、环境变量兜底读取图片 OSS STS 临时令牌。

        创建日期：2026-06-06
        author: sunshengxian
        """

        return self._read_optional_secret(
            self.image_gen_oss_security_token_file,
            self.image_gen_oss_security_token,
        )

    def _read_optional_secret(self, path: Path | None, value: str | None) -> str | None:
        """读取可选密钥，避免 OSS 和各类外部服务凭据写入代码仓库。

        创建日期：2026-06-06
        author: sunshengxian
        """

        if path and path.is_file():
            secret = path.read_text(encoding="utf-8").strip()
            if secret:
                return secret
        if value:
            return value.strip()
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
