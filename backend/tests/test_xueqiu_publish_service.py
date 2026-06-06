from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmChatMessage, LlmChatSession
from app.db.models.market import ATradeCalendar
from app.db.models.notification import LimitUpAnalysisCache, PushplusMessageLog, XueqiuPublishRecord
from app.schemas.xueqiu_publish import (
    XueqiuChatAnswerPublishRequest,
    XueqiuCredentialRequest,
    XueqiuPublishSettingRequest,
)
from app.services.auth_service import AuthService
from app.services.limit_up_push_service import LimitUpPushService
from app.services.xueqiu_publish_service import (
    XUEQIU_MODE_DRAFT,
    XUEQIU_SOURCE_CHAT_ANSWER,
    XUEQIU_STATUS_DRAFTED,
    XueqiuPublishError,
    XueqiuPublishService,
)

EAST8_TZ = ZoneInfo("Asia/Shanghai")


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


def add_ready_report_for_date(db: Session, trade_date: date) -> LimitUpAnalysisCache:
    """写入指定交易日的 READY 报告，便于校验定时任务不会误取旧报告。

    创建日期：2026-05-10
    author: sunshengxian
    """

    report = LimitUpAnalysisCache(
        trade_date=trade_date,
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash=f"hash-{trade_date:%Y%m%d}",
        status="READY",
        title=f"{trade_date:%Y-%m-%d} A股涨停打板复盘",
        content_html=(
            '<div style="background:#fff"><div style="padding:10px">'
            "<h2>市场情绪</h2><p>涨停家数达 125 家，最高标 7 板。</p>"
            "</div></div>"
        ),
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def enable_scheduler_setting(
    service: XueqiuPublishService,
    user: AppUser,
    *,
    publish: bool = False,
) -> None:
    """保存测试用定时配置，统一命中任意小时和分钟。

    创建日期：2026-05-10
    author: sunshengxian
    """

    service.save_publish_setting(
        XueqiuPublishSettingRequest(
            scheduler_enabled=True,
            auto_publish=publish,
            poll_hours="*",
            poll_minutes="*",
            default_cover_pic="",
        ),
        user,
    )


def save_test_credential(service: XueqiuPublishService, user: AppUser) -> None:
    """保存可用于单测桩函数的雪球登录态。

    创建日期：2026-05-10
    author: sunshengxian
    """

    service.save_credential(
        XueqiuCredentialRequest(
            cookie_text="xq_a_token=secret-token; u=12345; device_id=device",
            user_agent="Mozilla/5.0",
        ),
        user,
    )


def test_admin_default_permissions_include_xueqiu_publish() -> None:
    """确认管理员默认拥有雪球发布菜单权限。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    settings = Settings(default_admin_username="admin", default_admin_password="pwd")
    user = AuthService(db, settings).ensure_default_admin()

    assert "xueqiu_publish" in AuthService(db, settings).get_user_permissions(user)
    assert "chat_xueqiu_publish" in AuthService(db, settings).get_user_permissions(user)


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
    """确认普通操作会复用同一报告同一发布模式的最近流水。

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


def test_force_retry_creates_new_record_without_mutating_old_record() -> None:
    """确认强制重试新增流水并保留被网页删除的旧草稿记录。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    report = add_ready_report(db)
    service = XueqiuPublishService(db, Settings())
    old_record = service._get_or_create_record(report, XUEQIU_MODE_DRAFT, None, None)
    old_record.status = XUEQIU_STATUS_DRAFTED
    old_record.draft_id = "deleted-draft-id"
    old_record.status_id = "old-status-id"
    old_record.article_url = "https://xueqiu.com/old"
    old_record.published_at = datetime.now(UTC).replace(tzinfo=None)
    old_record.response_json = '{"draft": {"id": "deleted-draft-id"}}'
    db.commit()

    new_record = service._get_or_create_record(report, XUEQIU_MODE_DRAFT, None, None, force=True)

    assert new_record.id != old_record.id
    assert new_record.draft_id is None
    assert old_record.draft_id == "deleted-draft-id"
    assert old_record.article_url == "https://xueqiu.com/old"


def test_xueqiu_cover_pic_removes_image_style_suffix() -> None:
    """确认从既有雪球文章复制的封面图地址会还原为原图地址。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    service = XueqiuPublishService(db, Settings())

    assert (
        service._normalize_cover_pic("https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png!800.jpg")
        == "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"
    )


def test_publish_setting_can_be_saved_from_admin_page() -> None:
    """确认雪球发布页可保存定时开关、模式和默认封面。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    user = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    service = XueqiuPublishService(db, Settings(xueqiu_publish_scheduler_enabled=True))

    summary = service.save_publish_setting(
        XueqiuPublishSettingRequest(
            scheduler_enabled=True,
            auto_publish=True,
            poll_hours="8",
            poll_minutes="30",
            default_cover_pic="https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png!800.jpg",
        ),
        user,
    )

    assert summary.scheduler_enabled is True
    assert summary.auto_publish is True
    assert summary.poll_hours == "8"
    assert summary.poll_minutes == "30"
    assert summary.default_cover_pic == "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"
    assert summary.effective_scheduler_registered is True


def test_scheduler_cron_field_matches_page_config() -> None:
    """确认定时任务按页面保存的小时和分钟表达式匹配。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    service = XueqiuPublishService(db, Settings())

    assert service._cron_field_matches("30", 30) is True
    assert service._cron_field_matches("31,36,41", 36) is True
    assert service._cron_field_matches("8-9", 9) is True
    assert service._cron_field_matches("*/5", 40) is True
    assert service._cron_field_matches("30", 31) is False


def test_chat_answer_can_be_saved_as_xueqiu_draft(monkeypatch) -> None:
    """确认问答回答可转成雪球稳定支持的列表 HTML 后保存草稿。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.flush()
    session = LlmChatSession(user_id=admin.id, title="招商银行分析")
    db.add(session)
    db.flush()
    answer = LlmChatMessage(
        session_id=session.id,
        role="assistant",
        content="## 核心结论\n\n| 指标 | 判断 |\n| --- | --- |\n| ROE | 稳定 |",
    )
    db.add(answer)
    db.commit()
    db.refresh(admin)
    db.refresh(answer)
    service = XueqiuPublishService(db, Settings())
    save_test_credential(service, admin)

    def fake_chat_completion(_self, _prompt, _system_prompt=None, **_kwargs):
        if _kwargs.get("trace") and _kwargs["trace"].phase == "xueqiu_title":
            return "招商银行财务质量与估值观察"
        return (
            "<h2>核心结论</h2><ul>"
            "<li><strong>指标：</strong>ROE；<strong>判断：</strong>稳定</li>"
            "</ul>"
        )

    monkeypatch.setattr(
        "app.services.llm_service.LlmService._chat_completion",
        fake_chat_completion,
    )
    monkeypatch.setattr(
        service,
        "_save_draft",
        lambda _credential, _record: {"id": "chat-draft-id"},
    )

    record = service.save_or_publish_chat_answer(
        XueqiuChatAnswerPublishRequest(message_id=answer.id),
        admin,
    )

    saved = db.get(XueqiuPublishRecord, record.id)
    assert saved is not None
    assert saved.analysis_id is None
    assert saved.chat_message_id == answer.id
    assert saved.source_type == XUEQIU_SOURCE_CHAT_ANSWER
    assert saved.status == XUEQIU_STATUS_DRAFTED
    assert saved.title == "招商银行财务质量与估值观察"
    assert len(saved.title) <= 50
    assert "<li>" in saved.content_html
    assert "<table" not in saved.content_html
    assert saved.draft_id == "chat-draft-id"


def test_chat_answer_existing_draft_is_refreshed_as_html(monkeypatch) -> None:
    """确认已有问答草稿再次保存时会重新转换列表 HTML 并更新原草稿。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.flush()
    session = LlmChatSession(user_id=admin.id, title="招商银行分析")
    db.add(session)
    db.flush()
    answer = LlmChatMessage(
        session_id=session.id,
        role="assistant",
        content="## 核心结论\n\n| 指标 | 判断 |\n| --- | --- |\n| ROE | 稳定 |",
    )
    db.add(answer)
    db.flush()
    stale_record = XueqiuPublishRecord(
        analysis_id=None,
        chat_message_id=answer.id,
        source_type=XUEQIU_SOURCE_CHAT_ANSWER,
        publish_mode=XUEQIU_MODE_DRAFT,
        status=XUEQIU_STATUS_DRAFTED,
        title="旧标题",
        content_html=answer.content,
        cover_pic=None,
        draft_id="old-chat-draft-id",
        created_by_user_id=admin.id,
    )
    db.add(stale_record)
    db.commit()
    db.refresh(admin)
    db.refresh(answer)
    db.refresh(stale_record)
    service = XueqiuPublishService(db, Settings())
    save_test_credential(service, admin)
    saved_records: list[tuple[str | None, str]] = []

    def fake_chat_completion(_self, _prompt, _system_prompt=None, **_kwargs):
        if _kwargs.get("trace") and _kwargs["trace"].phase == "xueqiu_title":
            return "招商银行财务质量与估值观察"
        return (
            "<h2>核心结论</h2><ul>"
            "<li><strong>指标：</strong>ROE；<strong>判断：</strong>稳定</li>"
            "</ul>"
        )

    def fake_save_draft(_credential, record):
        # 重复保存应沿用旧 draft_id 更新雪球草稿，同时把 Markdown 占位替换为 HTML。
        saved_records.append((record.draft_id, record.content_html))
        return {"id": "old-chat-draft-id"}

    monkeypatch.setattr(
        "app.services.llm_service.LlmService._chat_completion",
        fake_chat_completion,
    )
    monkeypatch.setattr(service, "_save_draft", fake_save_draft)

    record = service.save_or_publish_chat_answer(
        XueqiuChatAnswerPublishRequest(
            message_id=answer.id,
            cover_pic="https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png!800.jpg",
        ),
        admin,
    )

    saved = db.get(XueqiuPublishRecord, record.id)
    assert saved is not None
    assert saved.id == stale_record.id
    assert saved_records == [
        (
            "old-chat-draft-id",
            (
                "<h2>核心结论</h2><ul>"
                "<li><strong>指标：</strong>ROE；<strong>判断：</strong>稳定</li>"
                "</ul>"
            ),
        )
    ]
    assert saved.title == "招商银行财务质量与估值观察"
    assert "<li>" in saved.content_html
    assert "<table" not in saved.content_html
    assert "| --- |" not in saved.content_html
    assert saved.cover_pic == "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"


def test_chat_answer_uses_default_cover_when_payload_cover_is_empty(monkeypatch) -> None:
    """确认问答快捷发布未传封面时继承雪球发布页默认封面。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.flush()
    session = LlmChatSession(user_id=admin.id, title="默认封面测试")
    db.add(session)
    db.flush()
    answer = LlmChatMessage(
        session_id=session.id,
        role="assistant",
        content="## 核心结论\n\n腾讯经营质量改善。",
    )
    db.add(answer)
    db.commit()
    db.refresh(admin)
    db.refresh(answer)
    service = XueqiuPublishService(db, Settings())
    save_test_credential(service, admin)
    service.save_publish_setting(
        XueqiuPublishSettingRequest(
            scheduler_enabled=False,
            auto_publish=False,
            poll_hours="8",
            poll_minutes="30",
            default_cover_pic="https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png!800.jpg",
        ),
        admin,
    )
    captured_covers: list[str | None] = []

    def fake_chat_completion(_self, _prompt, _system_prompt=None, **_kwargs):
        if _kwargs.get("trace") and _kwargs["trace"].phase == "xueqiu_title":
            return "腾讯经营质量改善"
        return "<h2>核心结论</h2><p>腾讯经营质量改善。</p>"

    def fake_save_draft(_credential, record):
        # 问答页没有封面输入，服务端必须在真正保存草稿前补齐默认封面。
        captured_covers.append(record.cover_pic)
        return {"id": "chat-draft-id"}

    monkeypatch.setattr(
        "app.services.llm_service.LlmService._chat_completion",
        fake_chat_completion,
    )
    monkeypatch.setattr(service, "_save_draft", fake_save_draft)

    record = service.save_or_publish_chat_answer(
        XueqiuChatAnswerPublishRequest(message_id=answer.id),
        admin,
    )

    assert captured_covers == ["https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"]
    assert record.cover_pic == "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"


def test_chat_answer_rejects_table_html_for_xueqiu_draft(monkeypatch) -> None:
    """确认问答 HTML 转换不再接受雪球草稿箱会压扁的 table 标签。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.flush()
    session = LlmChatSession(user_id=admin.id, title="表格压扁测试")
    db.add(session)
    db.flush()
    answer = LlmChatMessage(
        session_id=session.id,
        role="assistant",
        content="## 核心结论\n\n| 指标 | 判断 |\n| --- | --- |\n| ROE | 稳定 |",
    )
    db.add(answer)
    db.commit()
    db.refresh(admin)
    db.refresh(answer)
    service = XueqiuPublishService(db, Settings())

    monkeypatch.setattr(
        "app.services.llm_service.LlmService._chat_completion",
        lambda *_args, **_kwargs: (
            "<h2>核心结论</h2><table><tbody><tr><td>ROE</td><td>稳定</td></tr></tbody></table>"
        ),
    )

    try:
        service._chat_markdown_to_xueqiu_html(answer, admin)
    except XueqiuPublishError as exc:
        error_message = str(exc)
    else:
        error_message = ""

    assert "table 标签" in error_message


def test_save_draft_payload_includes_cover_display_flag(monkeypatch) -> None:
    """确认保存草稿时同时提交封面地址和展示封面开关。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    service = XueqiuPublishService(db, Settings())
    save_test_credential(service, admin)
    credential = service._enabled_credential()
    record = XueqiuPublishRecord(
        source_type=XUEQIU_SOURCE_CHAT_ANSWER,
        publish_mode=XUEQIU_MODE_DRAFT,
        status=XUEQIU_STATUS_DRAFTED,
        title="招商银行财务质量与估值观察",
        content_html="<h2>核心结论</h2><p>ROE 稳定。</p>",
        cover_pic="https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png",
        draft_id="draft-id",
        created_by_user_id=admin.id,
    )
    captured: dict[str, str] = {}

    def fake_post_form(_credential, _path, data, _referer):
        # 这里直接捕获发往雪球草稿接口的表单字段，避免单测依赖外部网络。
        captured.update(data)
        return {"id": "draft-id"}

    monkeypatch.setattr(service, "_post_form", fake_post_form)

    response = service._save_draft(credential, record)

    safe_payload = json.loads(record.request_payload_json or "{}")
    assert response == {"id": "draft-id"}
    assert captured["cover_pic"] == "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"
    assert captured["show_cover_pic"] == "true"
    assert safe_payload["show_cover_pic"] == "true"


def test_chat_answer_title_is_limited_to_xueqiu_max_length(monkeypatch) -> None:
    """确认问答发布标题会被 LLM 生成并兜底限制到雪球 50 字以内。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.flush()
    session = LlmChatSession(user_id=admin.id, title="长标题测试")
    db.add(session)
    db.flush()
    answer = LlmChatMessage(
        session_id=session.id,
        role="assistant",
        content="## 这是一个非常长非常长非常长非常长非常长非常长非常长的问答标题",
    )
    db.add(answer)
    db.commit()
    db.refresh(admin)
    db.refresh(answer)
    service = XueqiuPublishService(db, Settings())

    monkeypatch.setattr(
        "app.services.llm_service.LlmService._chat_completion",
        lambda *_args, **_kwargs: (
            "招商银行财务质量估值红利现金流风险反证条件观察和配置建议超长标题"
            "继续追加直到超过雪球标题限制再次追加更多文字"
        ),
    )

    title = service._chat_article_title(answer, admin, None)

    assert len(title) == 50
    assert title.startswith("招商银行财务质量")


def test_scheduler_publishes_current_t_minus_one_report_on_tuesday(monkeypatch) -> None:
    """确认周二定时发布只处理东八区当天对应的最新 T-1 报告。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add_all(
        [
            admin,
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1),
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 11), is_open=1),
        ]
    )
    db.commit()
    db.refresh(admin)
    old_report = add_ready_report_for_date(db, date(2026, 5, 8))
    expected_report = add_ready_report_for_date(db, date(2026, 5, 11))
    service = XueqiuPublishService(db, Settings(xueqiu_publish_scheduler_enabled=True))
    enable_scheduler_setting(service, admin)
    save_test_credential(service, admin)
    requested_trade_dates: list[date] = []

    def fake_ensure_analysis(self, trade_date: date) -> LimitUpAnalysisCache | None:
        # 定时发布单测只验证“选择哪个 T-1 报告”，不触发真实 KPL 数据抓取和 LLM 生成。
        requested_trade_dates.append(trade_date)
        return self.db.scalar(
            select(LimitUpAnalysisCache).where(LimitUpAnalysisCache.trade_date == trade_date)
        )

    monkeypatch.setattr(LimitUpPushService, "ensure_analysis_for_trade_date", fake_ensure_analysis)
    monkeypatch.setattr(
        service,
        "_now_local",
        lambda: datetime(2026, 5, 12, 8, 30, tzinfo=EAST8_TZ),
    )
    monkeypatch.setattr(service, "_save_draft", lambda _credential, _record: {"id": "draft-id"})

    record = service.save_or_publish_latest_by_scheduler()

    assert record is not None
    assert requested_trade_dates == [date(2026, 5, 11)]
    assert record.analysis_id == expected_report.id
    assert record.analysis_id != old_report.id
    assert record.status == XUEQIU_STATUS_DRAFTED


def test_scheduler_backfills_after_configured_time_when_report_becomes_ready(monkeypatch) -> None:
    """确认报告晚于配置分钟 READY 时，雪球定时任务会在当天补发且不重复调用接口。

    创建日期：2026-06-06
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add_all(
        [
            admin,
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 6, 5), is_open=1),
        ]
    )
    db.commit()
    db.refresh(admin)
    expected_report = add_ready_report_for_date(db, date(2026, 6, 5))
    service = XueqiuPublishService(db, Settings(xueqiu_publish_scheduler_enabled=True))
    save_test_credential(service, admin)
    service.save_publish_setting(
        XueqiuPublishSettingRequest(
            scheduler_enabled=True,
            auto_publish=False,
            poll_hours="8",
            poll_minutes="35",
            default_cover_pic="",
        ),
        admin,
    )
    requested_trade_dates: list[date] = []
    save_draft_calls: list[int] = []

    def fake_ensure_analysis(self, trade_date: date) -> LimitUpAnalysisCache | None:
        # 本用例模拟打板报告已在 08:35 之后生成完成，只验证补发窗口是否继续认当天 T-1 报告。
        requested_trade_dates.append(trade_date)
        return self.db.scalar(
            select(LimitUpAnalysisCache).where(LimitUpAnalysisCache.trade_date == trade_date)
        )

    def fake_save_draft(_credential, record: XueqiuPublishRecord) -> dict[str, str]:
        # 记录实际触达雪球草稿接口的次数，确保成功后后续每分钟调度不会重复提交。
        save_draft_calls.append(record.analysis_id or 0)
        return {"id": "draft-id"}

    monkeypatch.setattr(LimitUpPushService, "ensure_analysis_for_trade_date", fake_ensure_analysis)
    monkeypatch.setattr(
        service,
        "_now_local",
        lambda: datetime(2026, 6, 6, 8, 44, tzinfo=EAST8_TZ),
    )
    monkeypatch.setattr(service, "_save_draft", fake_save_draft)

    record = service.save_or_publish_latest_by_scheduler()
    repeat = service.save_or_publish_latest_by_scheduler()

    assert record is not None
    assert record.analysis_id == expected_report.id
    assert record.status == XUEQIU_STATUS_DRAFTED
    assert repeat is None
    assert requested_trade_dates == [date(2026, 6, 5), date(2026, 6, 5)]
    assert save_draft_calls == [expected_report.id]


def test_scheduler_skips_monday_even_when_report_exists(monkeypatch) -> None:
    """确认周一不自动写入雪球，避免把周末窗口外的报告误当 T-1 发布。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add_all(
        [
            admin,
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1),
        ]
    )
    db.commit()
    db.refresh(admin)
    add_ready_report_for_date(db, date(2026, 5, 8))
    service = XueqiuPublishService(db, Settings(xueqiu_publish_scheduler_enabled=True))
    enable_scheduler_setting(service, admin)
    save_test_credential(service, admin)
    monkeypatch.setattr(
        service,
        "_now_local",
        lambda: datetime(2026, 5, 11, 8, 30, tzinfo=EAST8_TZ),
    )

    record = service.save_or_publish_latest_by_scheduler()

    assert record is None


def test_publish_failure_sends_pushplus_alert_to_admin(monkeypatch) -> None:
    """确认雪球发布失败时向默认管理员发送 PushPlus 提醒。

    创建日期：2026-05-10
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    report = add_ready_report(db)
    service = XueqiuPublishService(
        db,
        Settings(
            default_admin_username="admin",
            pushplus_token="push-token",
            pushplus_token_file=None,
        ),
    )
    service.save_credential(
        XueqiuCredentialRequest(
            cookie_text="xq_a_token=secret-token; u=12345; device_id=device",
            user_agent="Mozilla/5.0",
        ),
        admin,
    )
    sent_messages: list[tuple[str, str]] = []

    def fake_save_draft(_credential, _record):
        raise XueqiuPublishError("Cookie 已失效")

    def fake_personal_message(self, title: str, content: str) -> str:
        sent_messages.append((title, content))
        return "push-message-id"

    monkeypatch.setattr(service, "_save_draft", fake_save_draft)
    monkeypatch.setattr(
        "app.services.pushplus_client.PushplusClient.send_personal_message",
        fake_personal_message,
    )

    try:
        service.save_or_publish_report(
            report.id,
            publish=False,
            force=True,
            cover_pic=None,
            user=admin,
        )
    except XueqiuPublishError as exc:
        error_message = str(exc)
    else:
        error_message = ""

    logs = list(db.scalars(select(PushplusMessageLog)).all())
    assert "Cookie 已失效" in error_message
    assert len(sent_messages) == 1
    assert sent_messages[0][0] == "雪球长文发布失败"
    assert "Cookie 已失效" in sent_messages[0][1]
    assert logs[-1].push_status == "SENT"
    assert logs[-1].push_message_id == "push-message-id"
