from __future__ import annotations

from fastapi import APIRouter

from app.api.deps_auth import CurrentUser, DbSession
from app.core.config import get_settings
from app.schemas.auth import OverviewChartSettings
from app.services.auth_service import AuthService

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
        "pushplusConfigured": bool(settings.resolve_pushplus_token()),
    }


@router.get("/settings/overview-chart", response_model=OverviewChartSettings)
def get_overview_chart_settings(
    db: DbSession,
    current_user: CurrentUser,
) -> OverviewChartSettings:
    """读取总览趋势图指标设置。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return AuthService(db).get_overview_chart_settings(current_user)


@router.put("/settings/overview-chart", response_model=OverviewChartSettings)
def update_overview_chart_settings(
    payload: OverviewChartSettings,
    db: DbSession,
    current_user: CurrentUser,
) -> OverviewChartSettings:
    """保存总览趋势图指标设置。

    创建日期：2026-05-05
    author: sunshengxian
    """

    return AuthService(db).update_overview_chart_settings(current_user, payload)
