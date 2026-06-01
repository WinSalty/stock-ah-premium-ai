from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import AStockBasic
from app.db.models.notification import (
    LimitUpPushRecipient,
    NineTurnAnalysisCache,
    NineTurnPushDelivery,
    PushplusBinding,
    XueqiuPublishCredential,
    XueqiuPublishRecord,
)
from app.services.nine_turn_push_service import NineTurnPushService
from app.services.tushare_client import TushareResult
from app.services.xueqiu_publish_service import XueqiuPublishService


class FakeTushareClient:
    """神奇九转测试用 Tushare 客户端。

    创建日期：2026-06-01
    author: sunshengxian
    """

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object]]] = []

    def query(
        self,
        api_name: str,
        params: dict[str, object] | None = None,
        fields: list[str] | None = None,
    ) -> TushareResult:
        self.calls.append((api_name, params or {}))
        return TushareResult(fields=fields or [], rows=self.rows)


class FakeNotificationService:
    """神奇九转测试用 PushPlus 服务。

    创建日期：2026-06-01
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str]] = []

    def can_send_pushplus_to_user(self, user_id: int) -> bool:
        return True

    def send_pushplus_message(
        self, user_id: int, title: str, content: str, alert_event_id: int | None = None
    ) -> str:
        self.sent.append((user_id, title, content))
        return f"nine-msg-{len(self.sent)}"


def make_db() -> Session:
    """创建内存数据库会话。

    创建日期：2026-06-01
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def settings() -> Settings:
    """创建不读取本机密钥文件的测试配置。

    创建日期：2026-06-01
    author: sunshengxian
    """

    return Settings(
        llm_api_key="key",
        llm_api_key_file=None,
        tushare_token="token",
        tushare_token_file=None,
    )


def add_limit_up_recipient(db: Session) -> AppUser:
    """写入可复用打板推送名单的测试用户。

    创建日期：2026-06-01
    author: sunshengxian
    """

    user = AppUser(username="nine-user", password_hash="hash", role="USER", is_active=True)
    db.add(user)
    db.flush()
    db.add(
        PushplusBinding(
            user_id=user.id,
            friend_id=2001,
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


def test_nine_turn_waits_for_data_ready() -> None:
    """确认神奇九转接口为空时不生成报告。

    创建日期：2026-06-01
    author: sunshengxian
    """

    db = make_db()
    service = NineTurnPushService(db, settings=settings(), tushare_client=FakeTushareClient([]))

    assert service.ensure_analysis_for_trade_date(date(2026, 5, 29)) is None
    assert db.scalar(select(NineTurnAnalysisCache)) is None


def test_nine_turn_report_cache_reuses_same_snapshot(monkeypatch) -> None:
    """确认同一九转快照只调用一次 LLM 并复用缓存。

    创建日期：2026-06-01
    author: sunshengxian
    """

    db = make_db()
    db.add(AStockBasic(ts_code="000001.SZ", symbol="000001", name="平安银行"))
    db.commit()
    service = NineTurnPushService(
        db,
        settings=settings(),
        tushare_client=FakeTushareClient(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "2026-05-29 00:00:00",
                    "freq": "daily",
                    "close": 12.3,
                    "amount": 100000,
                    "up_count": 9,
                    "down_count": 0,
                    "nine_up_turn": 1,
                    "nine_down_turn": 0,
                }
            ]
        ),
    )
    calls: list[dict[str, object]] = []

    def fake_generate(context: dict[str, object]) -> tuple[str, str]:
        calls.append(context)
        return "<h2>九转报告</h2>", "九转报告"

    monkeypatch.setattr(service, "_generate_llm_report", fake_generate)

    first = service.ensure_analysis_for_trade_date(date(2026, 5, 29))
    second = service.ensure_analysis_for_trade_date(date(2026, 5, 29))

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert len(calls) == 1
    assert first.status == "READY"
    assert "nine_up_turns" in calls[0]


def test_nine_turn_push_reuses_limit_up_recipients(monkeypatch) -> None:
    """确认九转报告只推送给打板推送已启用接收人。

    创建日期：2026-06-01
    author: sunshengxian
    """

    db = make_db()
    user = add_limit_up_recipient(db)
    notification_service = FakeNotificationService()
    service = NineTurnPushService(
        db,
        settings=settings(),
        tushare_client=FakeTushareClient(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260529",
                    "freq": "daily",
                    "amount": 100000,
                    "up_count": 0,
                    "down_count": 9,
                    "nine_up_turn": 0,
                    "nine_down_turn": 1,
                }
            ]
        ),
        notification_service=notification_service,
    )
    monkeypatch.setattr(
        service, "_generate_llm_report", lambda context: ("<h2>下九转</h2>", "下九转")
    )
    analysis = service.ensure_analysis_for_trade_date(date(2026, 5, 29))

    assert analysis is not None
    assert service.push_report(analysis.id, "MANUAL", service._now_naive()) == 1
    assert notification_service.sent[0][0] == user.id
    assert (
        db.scalar(
            select(NineTurnPushDelivery).where(NineTurnPushDelivery.analysis_id == analysis.id)
        )
        is not None
    )


def test_nine_turn_xueqiu_record_has_no_cover_pic(monkeypatch) -> None:
    """确认神奇九转发布雪球时不携带封面图。

    创建日期：2026-06-01
    author: sunshengxian
    """

    db = make_db()
    db.add(
        XueqiuPublishCredential(
            enabled=True,
            cookie_text="xq_a_token=fake; u=1",
            user_agent="pytest",
            mp_base_url="https://mp.xueqiu.com",
            referer_url="https://mp.xueqiu.com/write/",
        )
    )
    analysis = NineTurnAnalysisCache(
        trade_date=date(2026, 5, 29),
        freq="daily",
        model="deepseek-v4-pro",
        prompt_version="nine-turn-v1",
        data_snapshot_hash="hash",
        status="READY",
        title="神奇九转报告",
        content_html="<div><div><h2>神奇九转</h2></div></div>",
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    service = XueqiuPublishService(db, settings())
    monkeypatch.setattr(service, "_save_draft", lambda credential, record: {"id": "draft-1"})

    record = service.save_or_publish_nine_turn_report(analysis.id, publish=False, force=False)

    assert record.cover_pic is None
    assert record.nine_turn_analysis_id == analysis.id
    assert record.source_type == "NINE_TURN_REPORT"
    assert (
        db.scalar(select(XueqiuPublishRecord).where(XueqiuPublishRecord.id == record.id))
        is not None
    )
