from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """为 FastAPI 依赖提供数据库会话。

    创建日期：2026-05-04
    author: sunshengxian
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
