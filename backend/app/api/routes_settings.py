from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """健康检查接口。

    创建日期：2026-05-04
    author: sunshengxian
    """

    return {"status": "ok"}


@router.get("/settings/public")
def public_settings() -> dict[str, object]:
    """返回不含敏感信息的前端配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    settings = get_settings()
    return {
        "appName": settings.app_name,
        "appVersion": settings.app_version,
        "tushareConfigured": bool(settings.resolve_tushare_token()),
        "llmConfigured": bool(settings.resolve_llm_api_key() and settings.llm_model),
        "qwenConfigured": bool(settings.resolve_qwen_api_key()),
    }
