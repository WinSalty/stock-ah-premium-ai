from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.notification import LimitUpAnalysisCache
from app.schemas.xueqiu_publish import XueqiuCredentialRequest
from app.services.auth_service import AuthService
from app.services.xueqiu_publish_service import XUEQIU_MODE_DRAFT, XueqiuPublishService


def make_db() -> Session:
    """创建雪球发布测试用内存数据库。

    创建日期：2026-05-10
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def add_ready_report(db: Session) -> LimitUpAnalysisCache:
    """写入可转换为雪球长文的测试报告。

    创建日期：2026-05-10
    author: sunshengxian
    """

    report = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="2026-05-08 A股涨停打板复盘",
        content_html=(
            "<div style=\"background:#fff\"><div style=\"padding:10px\">"
            "<h2>市场情绪</h2><p>涨停家数达 125 家，最高标 7 板。</p>"
            "</div></div>"
        ),
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def test_admin_default_permissions_include_xueqiu_publish() -> None:
    """确认管理员默认拥有雪球发布菜单权限。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    settings = Settings(default_admin_username="admin", default_admin_password="pwd")
    user = AuthService(db, settings).ensure_default_admin()

    assert "xueqiu_publish" in AuthService(db, settings).get_user_permissions(user)


def test_credential_summary_masks_cookie() -> None:
    """确认登录态摘要不返回完整 Cookie 值。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    user = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    service = XueqiuPublishService(db, Settings())

    summary = service.save_credential(
        XueqiuCredentialRequest(
            cookie_text="xq_a_token=secret-token; u=12345; device_id=device",
            user_agent="Mozilla/5.0",
        ),
        user,
    )

    assert summary.configured is True
    assert "secret-token" not in (summary.cookie_preview or "")
    assert "xq_a_token" in (summary.cookie_preview or "")


def test_preview_latest_report_unwraps_pushplus_container() -> None:
    """确认雪球预览稿移除 PushPlus 外层样式并追加风险提示。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    report = add_ready_report(db)
    preview = XueqiuPublishService(db, Settings()).preview_latest_report(report.id)

    assert preview.title == "2026-05-08 打板复盘：涨停生态、题材强度与次日观察"
    assert "style=" not in preview.content_html
    assert "风险提示" in preview.content_html
    assert "涨停家数达 125 家" in preview.content_text


def test_publish_record_is_idempotent_for_same_mode() -> None:
    """确认同一报告同一发布模式只生成一条流水。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    report = add_ready_report(db)
    service = XueqiuPublishService(db, Settings())

    first = service._get_or_create_record(report, XUEQIU_MODE_DRAFT, None, None)
    db.commit()
    second = service._get_or_create_record(report, XUEQIU_MODE_DRAFT, None, None)

    assert first.id == second.id
