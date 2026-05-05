from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_llm_metrics import router as llm_metrics_router
from app.api.routes_market import router as market_router
from app.api.routes_query import router as query_router
from app.api.routes_settings import router as settings_router
from app.api.routes_sync import router as sync_router
from app.api.routes_watchlist import router as watchlist_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.jobs.scheduler import create_scheduler
from app.jobs.sync_jobs import register_incremental_sync_jobs
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


def build_lifespan(settings: Settings):
    """构建应用生命周期，按配置启动后台增量同步调度器。

    创建日期：2026-05-04
    author: sunshengxian
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        scheduler = None
        with SessionLocal() as db:
            AuthService(db, settings).ensure_default_admin()
        if settings.sync_scheduler_enabled:
            scheduler = create_scheduler(settings.sync_scheduler_timezone)
            register_incremental_sync_jobs(scheduler)
            scheduler.start()
            app.state.scheduler = scheduler
            logger.info("同步调度器已启动 timezone=%s", settings.sync_scheduler_timezone)
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
                logger.info("同步调度器已停止")

    return lifespan


def create_app() -> FastAPI:
    """创建 FastAPI 应用。

    创建日期：2026-05-04
    author: sunshengxian
    """

    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=build_lifespan(settings),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router, prefix="/api", tags=["auth"])
    app.include_router(settings_router, prefix="/api", tags=["settings"])
    app.include_router(sync_router, prefix="/api", tags=["sync"])
    app.include_router(market_router, prefix="/api", tags=["market"])
    app.include_router(watchlist_router, prefix="/api", tags=["watchlist"])
    app.include_router(query_router, prefix="/api", tags=["query"])
    app.include_router(chat_router, prefix="/api", tags=["chat"])
    app.include_router(llm_metrics_router, prefix="/api", tags=["llm-metrics"])
    return app


app = create_app()
