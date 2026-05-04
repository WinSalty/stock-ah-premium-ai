from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_market import router as market_router
from app.api.routes_query import router as query_router
from app.api.routes_settings import router as settings_router
from app.api.routes_sync import router as sync_router
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """创建 FastAPI 应用。

    创建日期：2026-05-04
    author: sunshengxian
    """

    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(settings_router, prefix="/api", tags=["settings"])
    app.include_router(sync_router, prefix="/api", tags=["sync"])
    app.include_router(market_router, prefix="/api", tags=["market"])
    app.include_router(query_router, prefix="/api", tags=["query"])
    app.include_router(chat_router, prefix="/api", tags=["chat"])
    return app


app = create_app()
