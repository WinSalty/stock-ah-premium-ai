from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import ATradeCalendar
from app.db.models.notification import LimitUpAnalysisCache, LimitUpPushRecipient, PushplusBinding
from app.services.limit_up_push_service import LimitUpPushService
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
        settings=Settings(llm_api_key="key", llm_api_key_file=None, tushare_token="token", tushare_token_file=None),
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
