from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.db.models.market import ATradeCalendar
from app.db.models.notification import (
    LimitUpAnalysisCache,
    LimitUpPushRecipient,
    LimitUpReportShare,
    PushplusBinding,
)
from app.schemas.limit_up_push import LimitUpRecipientUpdateItem, LimitUpRecipientUpdateRequest
from app.services.auth_service import AuthService
from app.services.limit_up_push_service import LimitUpPushError, LimitUpPushService
from app.services.tushare_client import TushareResult


class FakeTushareClient:
    """打板推送测试用 Tushare 客户端。

    创建日期：2026-05-08
    author: sunshengxian
    """

    def __init__(self, rows_by_api: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_api = rows_by_api
        self.calls: list[tuple[str, dict[str, object]]] = []

    def query(
        self,
        api_name: str,
        params: dict[str, object] | None = None,
        fields: list[str] | None = None,
    ) -> TushareResult:
        self.calls.append((api_name, params or {}))
        return TushareResult(fields=fields or [], rows=self.rows_by_api.get(api_name, []))


class FakeNotificationService:
    """打板推送测试用 PushPlus 服务。

    创建日期：2026-05-08
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str]] = []

    def can_send_pushplus_to_user(self, user_id: int) -> bool:
        return True

    def send_pushplus_message(self, user_id: int, title: str, content: str, alert_event_id: int | None = None) -> str:
        self.sent.append((user_id, title, content))
        return f"msg-{len(self.sent)}"


def make_db() -> Session:
    """创建内存数据库会话。

    创建日期：2026-05-08
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def add_user(db: Session) -> AppUser:
    """写入可接收打板推送的测试用户。

    创建日期：2026-05-08
    author: sunshengxian
    """

    user = AppUser(username="limit-user", password_hash="hash", role="USER", is_active=True)
    db.add(user)
    db.flush()
    db.add(
        PushplusBinding(
            user_id=user.id,
            friend_id=1001,
            friend_token="friend-token",
            is_follow=True,
            is_active=True,
            bound_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.add(LimitUpPushRecipient(user_id=user.id, enabled=True))
    db.commit()
    db.refresh(user)
    return user


def test_latest_trade_date_uses_previous_trade_day_for_kpl() -> None:
    """确认早盘 KPL 任务读取今天之前的最近交易日。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    db.add_all(
        [
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1),
            ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 11), is_open=1),
        ]
    )
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key=None, llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    assert service.latest_a_trade_date(date(2026, 5, 11)) == date(2026, 5, 8)


def test_limit_up_analysis_waits_for_kpl_data() -> None:
    """确认 KPL 数据未更新时不生成报告。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1))
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key=None, llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    assert service.ensure_analysis_for_trade_date(date(2026, 5, 8)) is None
    assert db.scalar(select(LimitUpAnalysisCache)) is None


def test_limit_up_report_cache_reuses_same_snapshot(monkeypatch) -> None:
    """确认同一 KPL 快照只调用一次 LLM 并复用报告缓存。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    fake_client = FakeTushareClient(
        {
            "kpl_list": [
                {
                    "ts_code": "000001.SZ",
                    "name": "测试股份",
                    "trade_date": "20260508",
                    "status": "2连板",
                    "theme": "人工智能",
                    "lu_desc": "AI 应用催化",
                }
            ]
        }
    )
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=fake_client,
        notification_service=FakeNotificationService(),
    )
    calls: list[dict[str, object]] = []

    def fake_generate(context: dict[str, object]) -> tuple[str, str]:
        calls.append(context)
        return "<h2>报告</h2>", "报告"

    monkeypatch.setattr(service, "_generate_llm_report", fake_generate)

    first = service.ensure_analysis_for_trade_date(date(2026, 5, 8))
    second = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert len(calls) == 1
    assert first.status == "READY"


def test_limit_up_failed_snapshot_retries_same_cache(monkeypatch) -> None:
    """确认同一数据快照首次生成失败后，后续轮询复用原缓存记录重试。

    创建日期：2026-06-02
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "theme": "人工智能",
                        "lu_desc": "AI 应用催化",
                    }
                ]
            }
        ),
        notification_service=FakeNotificationService(),
    )
    calls = 0

    def flaky_generate(context: dict[str, object]) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("模型网关临时异常")
        return "<h2>重试成功</h2>", "重试成功"

    monkeypatch.setattr(service, "_generate_llm_report", flaky_generate)

    with pytest.raises(RuntimeError):
        service.ensure_analysis_for_trade_date(date(2026, 5, 8))
    failed = db.scalar(select(LimitUpAnalysisCache))
    assert failed is not None
    assert failed.status == "FAILED"

    retried = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert retried is not None
    assert retried.id == failed.id
    assert retried.status == "READY"
    assert retried.error_message is None
    assert calls == 2


def test_limit_up_llm_error_response_is_recorded(monkeypatch) -> None:
    """确认 DeepSeek 非 choices 错误体会写入指标，便于排查真实上游响应。

    创建日期：2026-06-02
    author: sunshengxian
    """

    class FakeResponse:
        status_code = 200
        text = '{"error":{"message":"模型网关返回错误","code":"upstream_error"}}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "error": {
                    "message": "模型网关返回错误",
                    "code": "upstream_error",
                }
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            return FakeResponse()

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key="key",
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )
    monkeypatch.setattr("app.services.limit_up_push_service.httpx.Client", FakeClient)

    with pytest.raises(LimitUpPushError, match="模型网关返回错误"):
        service._chat_completion_with_reasoning("用户提示词", "系统提示词")
    metric = db.scalar(
        select(LlmCallMetric).where(LlmCallMetric.phase == "limit_up_analysis")
    )

    assert metric is not None
    assert metric.success == 0
    assert metric.response_content is not None
    assert "模型网关返回错误" in metric.response_content
    assert metric.error_message is not None
    assert "status=200" in metric.error_message


def test_limit_up_context_filters_st_stocks(monkeypatch) -> None:
    """确认打板报告上下文过滤 ST 风险警示股票。

    创建日期：2026-06-01
    author: sunshengxian
    """

    db = make_db()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "theme": "人工智能",
                        "lu_desc": "AI 应用催化",
                    },
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "trade_date": "20260508",
                        "status": "首板",
                        "theme": "摘帽预期",
                        "lu_desc": "风险警示股异动",
                    },
                ],
                "limit_step": [
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "trade_date": "20260508",
                        "nums": "1连",
                    },
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "nums": "2连",
                    },
                ],
                "top_list": [
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "trade_date": "20260508",
                        "net_amount": 1000,
                    }
                ],
            }
        ),
        notification_service=FakeNotificationService(),
    )
    captured: list[dict[str, object]] = []

    def fake_generate(context: dict[str, object]) -> tuple[str, str]:
        captured.append(context)
        return "<h2>报告</h2>", "报告"

    monkeypatch.setattr(service, "_generate_llm_report", fake_generate)

    analysis = service.ensure_analysis_for_trade_date(date(2026, 5, 8))

    assert analysis is not None
    assert captured
    context = captured[0]
    assert [row["name"] for row in context["limit_up_stocks"]] == ["测试股份"]
    assert [row["name"] for row in context["raw_supplement"]["limit_step"]] == ["测试股份"]
    assert context["raw_supplement"]["top_list"] == []
    assert any(
        item["api_name"] == "kpl_list" and item["message"] == "raw_rows=2; st_filtered=1"
        for item in context["data_quality"]
    )


def test_limit_up_push_uses_enabled_system_users(monkeypatch) -> None:
    """确认推送只面向启用的系统用户配置。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="打板报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    pushed = service.push_report(analysis.id, "MANUAL", datetime.now(UTC).replace(tzinfo=None))

    assert pushed == 1
    assert fake_notification.sent == [(user.id, "打板报告", "<h2>报告</h2>")]


def test_weekend_replay_respects_recipient_preference(monkeypatch) -> None:
    """确认周末晚间复推按接收人独立开关过滤。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    enabled_user = add_user(db)
    disabled_user = AppUser(username="weekend-off", password_hash="hash", role="USER", is_active=True)
    db.add(disabled_user)
    db.flush()
    db.add(LimitUpPushRecipient(user_id=disabled_user.id, enabled=True, weekend_replay_enabled=False))
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="周五打板报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    monkeypatch.setattr(service, "_today_local", lambda: date(2026, 5, 9))
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    replay_analysis, pushed = service.push_weekend_replay()

    assert replay_analysis is not None
    assert pushed == 1
    assert fake_notification.sent == [(enabled_user.id, "周五打板报告", "<h2>报告</h2>")]


def test_limit_up_push_only_targets_configured_recipients(monkeypatch) -> None:
    """确认手动指定推送也不能绕过启用接收人白名单。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db)
    other_user = AppUser(username="other-user", password_hash="hash", role="USER", is_active=True)
    db.add(other_user)
    fake_notification = FakeNotificationService()
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="打板报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=fake_notification,
    )
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    pushed = service.push_report(
        analysis.id,
        "MANUAL",
        datetime.now(UTC).replace(tzinfo=None),
        target_user_ids=[user.id, other_user.id],
    )

    assert pushed == 1
    assert fake_notification.sent == [(user.id, "打板报告", "<h2>报告</h2>")]


def test_update_recipients_syncs_limit_up_menu_permission() -> None:
    """确认管理员启停接收人时同步打板推送菜单权限。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    user = AppUser(
        username="receiver",
        password_hash="hash",
        role="USER",
        is_active=True,
        menu_permissions_json='["overview","profile"]',
    )
    db.add_all([admin, user])
    db.commit()
    db.refresh(user)
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    service.update_recipients(
        LimitUpRecipientUpdateRequest(
            recipients=[LimitUpRecipientUpdateItem(user_id=user.id, enabled=True, weekend_replay_enabled=False)]
        ),
        admin,
    )
    db.refresh(user)
    config = db.scalar(select(LimitUpPushRecipient).where(LimitUpPushRecipient.user_id == user.id))
    assert config is not None
    assert config.weekend_replay_enabled is False
    assert "limit_up_push" in AuthService(db).get_user_permissions(user)

    service.update_recipients(
        LimitUpRecipientUpdateRequest(recipients=[LimitUpRecipientUpdateItem(user_id=user.id, enabled=False)]),
        admin,
    )
    db.refresh(user)
    assert "limit_up_push" not in AuthService(db).get_user_permissions(user)


def test_limit_up_report_share_allows_temporary_public_view() -> None:
    """确认已生成报告可以创建临时分享并记录公开访问次数。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="可分享报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([admin, analysis])
    db.commit()
    db.refresh(admin)
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    share = service.create_report_share(analysis.id, 24, admin, "http://localhost:5173")
    public_report = service.get_public_report(share.token)

    stored_share = db.scalar(select(LimitUpReportShare).where(LimitUpReportShare.share_token == share.token))
    assert public_report.title == "可分享报告"
    assert public_report.content_html == "<h2>报告</h2>"
    assert share.share_url == f"http://localhost:5173/limit-up-share/{share.token}"
    assert stored_share is not None
    assert stored_share.view_count == 1
    assert stored_share.last_viewed_at is not None


def test_limit_up_report_share_rejects_expired_token() -> None:
    """确认过期分享链接不能继续公开读取报告。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="过期报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.flush()
    db.add(
        LimitUpReportShare(
            analysis_id=analysis.id,
            share_token="expired-token",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
    )
    db.commit()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    try:
        service.get_public_report("expired-token")
    except LimitUpPushError as exc:
        assert "无效或已过期" in str(exc)
    else:
        raise AssertionError("过期分享链接不应返回报告")


def test_limit_up_report_share_supports_permanent_link() -> None:
    """确认永久分享链接不依赖过期时间即可公开读取报告。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="永久报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([admin, analysis])
    db.commit()
    db.refresh(admin)
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    share = service.create_report_share(analysis.id, None, admin, "http://localhost:5173")
    public_report = service.get_public_report(share.token)

    assert share.permanent is True
    assert share.expires_at is None
    assert public_report.permanent is True
    assert public_report.expires_at is None
    assert public_report.title == "永久报告"


def test_limit_up_report_share_can_be_listed_and_revoked() -> None:
    """确认管理员可查看已生成分享链接并将其置为失效。

    创建日期：2026-05-09
    author: sunshengxian
    """

    db = make_db()
    admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
    analysis = LimitUpAnalysisCache(
        trade_date=date(2026, 5, 8),
        model="deepseek-v4-pro",
        prompt_version="limit-up-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="可失效报告",
        content_html="<h2>报告</h2>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add_all([admin, analysis])
    db.commit()
    db.refresh(admin)
    db.refresh(analysis)
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient({}),
        notification_service=FakeNotificationService(),
    )

    share = service.create_report_share(analysis.id, None, admin, "http://localhost:5173")
    shares = service.list_report_shares(analysis.id, "http://localhost:5173")
    revoked = service.revoke_report_share(analysis.id, shares[0].id, "http://localhost:5173")

    assert len(shares) == 1
    assert shares[0].token == share.token
    assert shares[0].status == "ACTIVE"
    assert revoked.status == "REVOKED"
    try:
        service.get_public_report(share.token)
    except LimitUpPushError as exc:
        assert "无效或已过期" in str(exc)
    else:
        raise AssertionError("失效分享链接不应继续公开读取")


def test_latest_analysis_push_is_idempotent_across_polling(monkeypatch) -> None:
    """确认早盘多次轮询同一份报告只推送一次。

    创建日期：2026-05-08
    author: sunshengxian
    """

    db = make_db()
    db.add(ATradeCalendar(exchange="SSE", cal_date=date(2026, 5, 8), is_open=1))
    user = add_user(db)
    fake_notification = FakeNotificationService()
    service = LimitUpPushService(
        db,
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
        tushare_client=FakeTushareClient(
            {
                "kpl_list": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试股份",
                        "trade_date": "20260508",
                        "status": "2连板",
                        "theme": "人工智能",
                        "lu_desc": "AI 应用催化",
                    }
                ]
            }
        ),
        notification_service=fake_notification,
    )
    monkeypatch.setattr(service, "_today_local", lambda: date(2026, 5, 9))
    monkeypatch.setattr(service, "_generate_llm_report", lambda context: ("<h2>报告</h2>", "报告"))
    monkeypatch.setattr(service, "_latest_pushplus_log_id", lambda user_id, message_id: None)

    first_analysis, first_pushed = service.ensure_latest_analysis_and_push()
    second_analysis, second_pushed = service.ensure_latest_analysis_and_push()

    assert first_analysis is not None
    assert second_analysis is not None
    assert first_analysis.id == second_analysis.id
    assert first_pushed == 1
    assert second_pushed == 0
    assert fake_notification.sent == [(user.id, "2026-05-08 A股涨停打板复盘", "<h2>报告</h2>")]
