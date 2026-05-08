from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes_notifications import router as notifications_router
from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import (
    ATradeCalendar,
    HKTradeCalendar,
    RealtimeQuoteSnapshot,
    WatchlistStock,
)
from app.db.models.notification import AlertEvent, PushplusBinding, PushplusMessageLog
from app.db.session import get_db
from app.schemas.watchlist import WatchlistCreate
from app.services.notification_service import (
    EVENT_PRICE_REACHED,
    EVENT_THRESHOLD_REACHED,
    NotificationError,
    NotificationService,
)
from app.services.pushplus_client import PushplusClient, PushplusFriend
from app.services.watchlist_service import WatchlistError, WatchlistService

LOCAL_TEST_TZ = ZoneInfo("Asia/Shanghai")


class FakePushplusClient:
    """测试用 PushPlus 客户端。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(self, friends: list[PushplusFriend] | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.friends = friends or []

    def get_personal_qr_code(
        self,
        content: str,
        expire_seconds: int,
        scan_count: int,
    ) -> str:
        return f"https://pushplus.example/qr?content={content}"

    def send_friend_message(self, to_token: str, title: str, content: str) -> str:
        self.sent.append((to_token, title, content))
        return f"msg-{len(self.sent)}"

    def send_personal_message(self, title: str, content: str) -> str:
        self.sent.append(("PERSONAL", title, content))
        return f"msg-{len(self.sent)}"

    def list_friends(self) -> list[PushplusFriend]:
        return self.friends


def add_user_with_binding(db: Session) -> AppUser:
    """写入测试用户和 PushPlus 绑定。

    创建日期：2026-05-05
    author: sunshengxian
    """

    user = AppUser(username="notify", password_hash="hash", role="USER", is_active=True)
    db.add(user)
    db.flush()
    db.add(
        PushplusBinding(
            user_id=user.id,
            friend_id=1001,
            friend_token="friend-token",
            friend_nick_name="测试好友",
            is_follow=True,
            is_active=True,
            bound_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()
    db.refresh(user)
    return user


def add_joint_trade_day(db: Session, target_day: date) -> None:
    """写入 A/H 共同交易日。

    创建日期：2026-05-05
    author: sunshengxian
    """

    db.add_all(
        [
            ATradeCalendar(exchange="SSE", cal_date=target_day, is_open=1),
            HKTradeCalendar(cal_date=target_day, is_open=1),
        ]
    )


def add_realtime_quotes(
    db: Session,
    *,
    a_ts_code: str = "600036.SH",
    hk_ts_code: str = "03968.HK",
    a_price: Decimal = Decimal("100"),
    hk_price: Decimal = Decimal("10"),
    fx_rate: Decimal = Decimal("7"),
    quote_time: datetime | None = None,
) -> None:
    """写入测试用实时快照行情。

    创建日期：2026-05-05
    author: sunshengxian
    """

    target_time = quote_time or datetime(2026, 5, 5, 10, 30, 0)
    db.add_all(
        [
            RealtimeQuoteSnapshot(
                market="A",
                symbol=a_ts_code,
                last_price=a_price,
                currency="CNY",
                quote_time=target_time,
                source="TEST",
                quality="REALTIME",
            ),
            RealtimeQuoteSnapshot(
                market="HK",
                symbol=hk_ts_code,
                last_price=hk_price,
                currency="HKD",
                quote_time=target_time,
                source="TEST",
                quality="REALTIME",
            ),
            RealtimeQuoteSnapshot(
                market="FX",
                symbol="HKD/CNY",
                last_price=fx_rate,
                currency="CNY",
                quote_time=target_time,
                source="TEST",
                quality="REALTIME",
            ),
        ]
    )


def build_notification_test_client(engine) -> TestClient:
    """构建通知路由测试客户端。

    创建日期：2026-05-06
    author: sunshengxian
    """

    app = FastAPI()
    app.include_router(notifications_router, prefix="/api")

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_pushplus_credentials_can_share_one_file(tmp_path) -> None:
    """确认 PushPlus token 和 SecretKey 可共用一个本机凭据文件。

    创建日期：2026-05-05
    author: sunshengxian
    """

    credential_file = tmp_path / "pushplus.txt"
    credential_file.write_text(
        "PUSHPLUS_TOKEN=test-token\nPUSHPLUS_SECRET_KEY=test-secret\n",
        encoding="utf-8",
    )
    settings = Settings(
        pushplus_token_file=credential_file,
        pushplus_secret_key_file=credential_file,
    )

    assert settings.resolve_pushplus_token() == "test-token"
    assert settings.resolve_pushplus_secret_key() == "test-secret"


def test_pushplus_client_send_uses_html_template(monkeypatch) -> None:
    """确认 PushPlus 发送消息固定使用 HTML 模板。

    创建日期：2026-05-05
    author: sunshengxian
    """

    captured: dict[str, object] = {}
    client = PushplusClient(Settings(pushplus_token="test-token", pushplus_token_file=None))

    def fake_request(method: str, path: str, **kwargs: object) -> str:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs["json"]
        return "message-id"

    monkeypatch.setattr(client, "_request", fake_request)

    message_id = client.send_friend_message("friend-token", "测试", "<b>连通</b>")

    assert message_id == "message-id"
    assert captured["path"] == "/send"
    assert isinstance(captured["json"], dict)
    assert captured["json"]["template"] == "html"
    assert captured["json"]["to"] == "friend-token"


def test_pushplus_client_personal_message_omits_friend_token(monkeypatch) -> None:
    """确认 PushPlus 一对一消息不携带好友 token。

    创建日期：2026-05-06
    author: sunshengxian
    """

    captured: dict[str, object] = {}
    client = PushplusClient(Settings(pushplus_token="test-token", pushplus_token_file=None))

    def fake_request(method: str, path: str, **kwargs: object) -> str:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs["json"]
        return "message-id"

    monkeypatch.setattr(client, "_request", fake_request)

    message_id = client.send_personal_message("测试", "<b>连通</b>")

    assert message_id == "message-id"
    assert captured["path"] == "/send"
    assert isinstance(captured["json"], dict)
    assert captured["json"]["token"] == "test-token"
    assert captured["json"]["template"] == "html"
    assert "to" not in captured["json"]


def test_pushplus_client_list_friends_accepts_alternate_nickname_field(monkeypatch) -> None:
    """确认 PushPlus 好友列表可兼容不同昵称字段名。

    创建日期：2026-05-06
    author: sunshengxian
    """

    client = PushplusClient(Settings(pushplus_token="test-token", pushplus_token_file=None))
    monkeypatch.setattr(client, "_get_access_key", lambda: "access-key")

    def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        return {
            "list": [
                {
                    "id": 1,
                    "friendId": 9001,
                    "token": "friend-token-9001",
                    "nickname": "字段昵称",
                    "isFollow": 1,
                }
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)

    friends = client.list_friends()

    assert friends[0].nick_name == "字段昵称"


def test_test_push_wraps_content_as_html() -> None:
    """确认测试推送会包装为 HTML 内容。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)

        message_id = NotificationService(db, pushplus_client=fake_client).send_test_push(
            user.id,
            "AH 提醒测试",
            "PushPlus 好友消息推送已连通。",
        )

    assert message_id == "msg-1"
    assert len(fake_client.sent) == 1
    sent_content = fake_client.sent[0][2]
    assert "<table" in sent_content
    assert "PushPlus HTML 测试消息" in sent_content
    assert "消息链路已连通" in sent_content
    assert "价差信号" in sent_content
    assert "#7c3aed" not in sent_content
    with Session(engine) as db:
        logs = list(db.scalars(select(PushplusMessageLog)).all())
    assert len(logs) == 1
    assert logs[0].message_title == "AH 提醒测试"
    assert logs[0].recipient_type == "FRIEND"
    assert logs[0].recipient_name == "测试好友"
    assert logs[0].push_status == "SENT"
    assert logs[0].push_message_id == "msg-1"


def test_test_push_message_uses_east8_display_time() -> None:
    """确认测试推送正文中的发送时间按东八区展示。

    创建日期：2026-05-08
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        before_local = datetime.now(LOCAL_TEST_TZ).replace(tzinfo=None)
        NotificationService(db, pushplus_client=fake_client).send_test_push(
            user.id,
            "时间测试",
            "推送记录内容",
        )
        after_local = datetime.now(LOCAL_TEST_TZ).replace(tzinfo=None)

    assert len(fake_client.sent) == 1
    html_content = fake_client.sent[0][2]
    local_texts = {
        before_local.strftime("%Y-%m-%d %H:%M:%S"),
        after_local.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # PushPlus 正文会在微信中直接展示，不能依赖前端再做 UTC 到东八区转换；
    # 测试允许执行过程跨秒，只要命中发送前后任一东八区秒级时间即可。
    assert any(local_text in html_content for local_text in local_texts)


def test_admin_test_push_uses_personal_message_without_binding() -> None:
    """确认 admin 测试推送无需好友绑定，使用一对一消息。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient()
    settings = Settings(default_admin_username="admin")
    with Session(engine) as db:
        admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)

        message_id = NotificationService(
            db,
            settings=settings,
            pushplus_client=fake_client,
        ).send_test_push(
            admin.id,
            "AH 提醒测试",
            "PushPlus 一对一消息推送已连通。",
        )

    assert message_id == "msg-1"
    assert len(fake_client.sent) == 1
    assert fake_client.sent[0][0] == "PERSONAL"
    assert "PushPlus 一对一消息推送已连通" in fake_client.sent[0][2]
    with Session(engine) as db:
        logs = list(db.scalars(select(PushplusMessageLog)).all())
    assert len(logs) == 1
    assert logs[0].recipient_type == "PERSONAL"
    assert logs[0].recipient_name == "admin"


def test_bound_user_cannot_create_pushplus_qr_code() -> None:
    """确认已绑定用户不能再次生成绑定二维码。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = add_user_with_binding(db)
        try:
            NotificationService(db, pushplus_client=FakePushplusClient()).create_pushplus_qr_code(
                user,
                expire_seconds=604800,
                scan_count=1,
            )
        except NotificationError as exc:
            error_message = str(exc)
        else:
            error_message = ""

    assert "不支持重复绑定" in error_message


def test_threshold_alert_pushes_once_per_deviation_level() -> None:
    """确认阈值提醒同一偏离档位去重，偏离增加到新档位后再次推送。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        add_joint_trade_day(db, target_day)
        db.add_all(
            [
                WatchlistStock(
                    user_id=user.id,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    display_name="招商银行",
                    preferred_direction="AH",
                    target_premium_pct=Decimal("30"),
                    is_active=True,
                )
            ]
        )
        add_realtime_quotes(db, a_price=Decimal("98"))
        db.commit()

        first_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 0, tzinfo=LOCAL_TEST_TZ),
        )
        second_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 1, tzinfo=LOCAL_TEST_TZ),
        )
        add_realtime_quotes(
            db,
            a_price=Decimal("99"),
            quote_time=datetime(2026, 5, 5, 10, 30, 2),
        )
        db.commit()
        third_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 3, tzinfo=LOCAL_TEST_TZ),
        )

        total_events = list(db.scalars(select(AlertEvent)).all())

    assert len(first_events) == 1
    assert second_events == []
    assert len(third_events) == 1
    assert third_events[0].event_type == EVENT_THRESHOLD_REACHED
    assert len(total_events) == 2
    assert len(fake_client.sent) == 2
    assert "<table" in fake_client.sent[0][2]
    assert "当前溢价" in fake_client.sent[0][2]
    assert "目标阈值" in fake_client.sent[0][2]
    assert "A 股价格" in fake_client.sent[0][2]
    assert "98 人民币" in fake_client.sent[0][2]
    assert "H 股价格" in fake_client.sent[0][2]
    assert "10 港币" in fake_client.sent[0][2]
    assert "HKD/CNY 汇率" in fake_client.sent[0][2]
    assert "7" in fake_client.sent[0][2]
    with Session(engine) as db:
        logs = list(db.scalars(select(PushplusMessageLog)).all())
    assert len(logs) == 2
    assert {log.alert_event_id for log in logs} == {event.id for event in total_events}


def test_threshold_alert_skips_when_fx_quote_date_is_stale() -> None:
    """确认历史汇率快照不会参与实时阈值提醒。

    创建日期：2026-05-08
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        add_joint_trade_day(db, target_day)
        db.add(
            WatchlistStock(
                user_id=user.id,
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                display_name="招商银行",
                preferred_direction="HA",
                target_premium_pct=Decimal("10"),
                is_active=True,
            )
        )
        # A/H 报价为本轮扫描日，但 HKD/CNY 汇率仍停留在历史日期时，
        # 即使价格组合会超过阈值，也必须整条实时阈值链路停止。
        db.add_all(
            [
                RealtimeQuoteSnapshot(
                    market="A",
                    symbol="600036.SH",
                    last_price=Decimal("37.95"),
                    currency="CNY",
                    quote_time=datetime(2026, 5, 5, 14, 5, 34),
                    source="TEST",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="HK",
                    symbol="03968.HK",
                    last_price=Decimal("47.22"),
                    currency="HKD",
                    quote_time=datetime(2026, 5, 5, 14, 5, 34),
                    source="TEST",
                    quality="REALTIME",
                ),
                RealtimeQuoteSnapshot(
                    market="FX",
                    symbol="HKD/CNY",
                    last_price=Decimal("0.9115"),
                    currency="CNY",
                    quote_time=datetime(2024, 10, 14, 14, 5, 34),
                    source="TEST",
                    quality="REALTIME",
                ),
            ]
        )
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 14, 5, 35, tzinfo=LOCAL_TEST_TZ),
        )
        total_events = list(db.scalars(select(AlertEvent)).all())
        logs = list(db.scalars(select(PushplusMessageLog)).all())

    assert events == []
    assert total_events == []
    assert logs == []
    assert fake_client.sent == []


def test_admin_can_list_pushplus_message_logs() -> None:
    """确认管理员可查看 PushPlus 推送流水。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        service = NotificationService(db, pushplus_client=fake_client)
        service.send_test_push(user.id, "记录测试", "推送记录内容")

        logs = service.list_pushplus_message_logs()

    assert len(logs) == 1
    assert logs[0].username == "notify"
    assert logs[0].recipient_name == "测试好友"
    assert logs[0].message_title == "记录测试"
    assert logs[0].push_status == "SENT"


def test_admin_can_search_pushplus_message_logs() -> None:
    """确认 PushPlus 推送流水支持关键词、状态和用户过滤。

    创建日期：2026-05-08
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        other_user = AppUser(username="other", password_hash="hash", role="USER", is_active=True)
        db.add(other_user)
        db.commit()
        db.refresh(other_user)
        service = NotificationService(db, pushplus_client=fake_client)
        service.send_test_push(user.id, "记录测试", "推送记录内容")
        db.add(
            PushplusMessageLog(
                user_id=other_user.id,
                recipient_type="PERSONAL",
                recipient_name="other",
                message_title="其他消息",
                message_content="不匹配内容",
                push_channel="PUSHPLUS",
                push_status="FAILED",
            )
        )
        db.commit()

        logs = service.list_pushplus_message_logs(
            keyword="记录内容",
            status="sent",
            user_id=user.id,
        )

    assert len(logs) == 1
    assert logs[0].username == "notify"
    assert logs[0].message_title == "记录测试"


def test_threshold_alert_limits_daily_event_type_to_five_per_user() -> None:
    """确认阈值提醒每个用户每天最多推送五条。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        add_joint_trade_day(db, target_day)
        for index in range(6):
            a_ts_code = f"60003{index}.SH"
            hk_ts_code = f"0396{index}.HK"
            db.add(
                WatchlistStock(
                    user_id=user.id,
                    a_ts_code=a_ts_code,
                    hk_ts_code=hk_ts_code,
                    display_name=f"测试股票{index}",
                    preferred_direction="AH",
                    target_premium_pct=Decimal("30"),
                    is_active=True,
                )
            )
            add_realtime_quotes(db, a_ts_code=a_ts_code, hk_ts_code=hk_ts_code)
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 0, tzinfo=LOCAL_TEST_TZ),
        )

    assert len(events) == 5
    assert len(fake_client.sent) == 5


def test_pushplus_callback_binds_user_from_qr_content() -> None:
    """确认 PushPlus 新增好友回调按二维码绑定票据自动绑定。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="callback-user", password_hash="hash", role="USER", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        service = NotificationService(db)
        ticket = service._binding_ticket_for_user(user_id)
        binding = service.bind_pushplus_callback(
            ticket,
            friend_id=2001,
            friend_token="callback-token",
            nick_name="扫码用户",
            is_follow=True,
        )

    assert ticket.startswith(f"sapai:{user_id}:")
    assert len(ticket) <= 32
    assert binding.is_bound is True
    assert binding.friend_id == 2001
    assert binding.friend_nick_name == "扫码用户"


def test_pushplus_callback_fills_friend_name_from_friend_list() -> None:
    """确认回调未携带昵称时可从 PushPlus 好友列表补齐备注或昵称。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(
            username="callback-friend-list",
            password_hash="hash",
            role="USER",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        service = NotificationService(
            db,
            pushplus_client=FakePushplusClient(
                friends=[
                    PushplusFriend(
                        id=9,
                        friend_id=2009,
                        token="callback-token-2009",
                        nick_name="列表昵称",
                        remark="列表备注",
                        is_follow=True,
                        create_time=None,
                    )
                ]
            ),
        )

        binding = service.bind_pushplus_callback(
            service._binding_ticket_for_user(user.id),
            friend_id=2009,
            friend_token="callback-token-2009",
            nick_name=None,
            is_follow=False,
        )

    assert binding.friend_nick_name == "列表昵称"
    assert binding.friend_remark == "列表备注"
    assert binding.is_follow is True


def test_pushplus_callback_rejects_invalid_qr_signature() -> None:
    """确认 PushPlus 回调绑定票据签名必须匹配。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="bad-signature", password_hash="hash", role="USER", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        try:
            NotificationService(db).bind_pushplus_callback(
                f"sapai:{user.id}:bad-signature",
                friend_id=2002,
                friend_token="callback-token",
                nick_name="扫码用户",
                is_follow=True,
            )
        except NotificationError as exc:
            error_message = str(exc)
        else:
            error_message = ""

    assert "签名无效" in error_message


def test_admin_bind_pushplus_friend_for_user_stores_friend_token() -> None:
    """确认管理员手动绑定指定用户时保存 PushPlus 好友令牌。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient(
        friends=[
            PushplusFriend(
                id=11,
                friend_id=3001,
                token="friend-token-3001",
                nick_name="手动好友",
                remark="",
                is_follow=True,
                create_time=None,
            )
        ]
    )
    with Session(engine) as db:
        user = AppUser(username="manual-bind", password_hash="hash", role="USER", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        service = NotificationService(db, pushplus_client=fake_client)
        binding = service.bind_pushplus_friend_for_user(
            user_id,
            3001,
        )
        stored = db.scalar(select(PushplusBinding).where(PushplusBinding.user_id == user_id))

    assert binding.is_bound is True
    assert binding.friend_id == 3001
    assert stored is not None
    assert stored.friend_token == "friend-token-3001"


def test_admin_bind_rejects_friend_bound_to_other_user() -> None:
    """确认一个 PushPlus 好友不能手动绑定到多个用户。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fake_client = FakePushplusClient(
        friends=[
            PushplusFriend(
                id=11,
                friend_id=3001,
                token="friend-token-3001",
                nick_name="手动好友",
                remark="",
                is_follow=True,
                create_time=None,
            )
        ]
    )
    with Session(engine) as db:
        first_user = AppUser(username="bound-1", password_hash="hash", role="USER", is_active=True)
        second_user = AppUser(
            username="bound-2",
            password_hash="hash",
            role="USER",
            is_active=True,
        )
        db.add_all([first_user, second_user])
        db.flush()
        db.add(
            PushplusBinding(
                user_id=first_user.id,
                friend_id=3001,
                friend_token="friend-token-3001",
                is_follow=True,
                is_active=True,
                bound_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.commit()

        try:
            NotificationService(db, pushplus_client=fake_client).bind_pushplus_friend_for_user(
                second_user.id,
                3001,
            )
        except NotificationError as exc:
            error_message = str(exc)
        else:
            error_message = ""

    assert "已绑定其他用户" in error_message


def test_pushplus_callback_rejects_friend_bound_to_other_user() -> None:
    """确认回调绑定时一个 PushPlus 好友不能绑定到多个用户。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first_user = AppUser(
            username="callback-1",
            password_hash="hash",
            role="USER",
            is_active=True,
        )
        second_user = AppUser(
            username="callback-2",
            password_hash="hash",
            role="USER",
            is_active=True,
        )
        db.add_all([first_user, second_user])
        db.flush()
        db.add(
            PushplusBinding(
                user_id=first_user.id,
                friend_id=4001,
                friend_token="callback-token-4001",
                is_follow=True,
                is_active=True,
                bound_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.commit()

        service = NotificationService(db)
        ticket = service._binding_ticket_for_user(second_user.id)
        try:
            service.bind_pushplus_callback(
                ticket,
                friend_id=4001,
                friend_token="callback-token-4001",
                nick_name="扫码用户",
                is_follow=True,
            )
        except NotificationError as exc:
            error_message = str(exc)
        else:
            error_message = ""

    assert "已绑定其他用户" in error_message


def test_pushplus_callback_endpoint_accepts_validation_probe() -> None:
    """确认 PushPlus 回调地址校验请求可返回标准成功响应。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = build_notification_test_client(engine)

    response = client.post("/api/notifications/pushplus/callback", json={})

    assert response.status_code == 200
    assert response.json() == {"code": 200, "msg": "success"}


def test_pushplus_callback_endpoint_accepts_get_probe() -> None:
    """确认 PushPlus 使用 GET 校验回调地址时也能通过。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = build_notification_test_client(engine)

    response = client.get("/api/notifications/pushplus/callback")

    assert response.status_code == 200
    assert response.json() == {"code": 200, "msg": "success"}


def test_pushplus_callback_endpoint_binds_user_from_add_friend_payload() -> None:
    """确认 PushPlus 真实回调可通过公网接口完成用户绑定。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(
            username="callback-api-user",
            password_hash="hash",
            role="USER",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ticket = NotificationService(db)._binding_ticket_for_user(user.id)

    client = build_notification_test_client(engine)
    response = client.post(
        "/api/notifications/pushplus/callback",
        json={
            "event": "add_friend",
            "qrCode": ticket,
            "friendInfo": {
                "friendId": 9527,
                "token": "friend-token-9527",
                "nickName": "公网扫码用户",
                "isFollow": 1,
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 200, "msg": "success"}
    with Session(engine) as db:
        stored = db.scalar(select(PushplusBinding).where(PushplusBinding.user_id == user.id))
    assert stored is not None
    assert stored.friend_id == 9527
    assert stored.friend_token == "friend-token-9527"


def test_pushplus_callback_endpoint_accepts_alternate_nickname_field() -> None:
    """确认公网回调可兼容 PushPlus 不同昵称字段名。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(
            username="callback-nickname-user",
            password_hash="hash",
            role="USER",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ticket = NotificationService(db)._binding_ticket_for_user(user.id)

    client = build_notification_test_client(engine)
    response = client.post(
        "/api/notifications/pushplus/callback",
        json={
            "event": "add_friend",
            "qrCode": ticket,
            "friendInfo": {
                "friendId": 9528,
                "token": "friend-token-9528",
                "nickname": "兼容昵称",
                "isFollow": 1,
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 200, "msg": "success"}
    with Session(engine) as db:
        stored = db.scalar(select(PushplusBinding).where(PushplusBinding.user_id == user.id))
    assert stored is not None
    assert stored.friend_nick_name == "兼容昵称"


def test_pushplus_callback_endpoint_ignores_invalid_qrcode_probe() -> None:
    """确认 PushPlus 使用测试二维码值探测 POST 回调时不会阻断保存。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = build_notification_test_client(engine)

    response = client.post(
        "/api/notifications/pushplus/callback",
        json={
            "event": "add_friend",
            "qrCode": "pushplus-probe",
            "friendInfo": {
                "friendId": 5,
                "token": "probe-friend-token",
                "nickName": "探测请求",
                "isFollow": 1,
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 200, "msg": "success"}
    with Session(engine) as db:
        stored = list(db.scalars(select(PushplusBinding)).all())
    assert stored == []


def test_watchlist_alert_requires_pushplus_binding() -> None:
    """确认用户设置提醒前必须完成 PushPlus 绑定。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="no-binding", password_hash="hash", role="USER", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        try:
            WatchlistService(db).create(
                payload=WatchlistCreate(
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    target_premium_pct=Decimal("30"),
                ),
                user_id=user.id,
            )
        except WatchlistError as exc:
            error_message = str(exc)
        else:
            error_message = ""

    assert "PushPlus" in error_message


def test_admin_watchlist_alert_does_not_require_pushplus_binding() -> None:
    """确认 admin 设置提醒无需先绑定 PushPlus 好友。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(default_admin_username="admin")
    with Session(engine) as db:
        admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)

        item = WatchlistService(db, settings=settings).create(
            payload=WatchlistCreate(
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                target_premium_pct=Decimal("30"),
            ),
            user_id=admin.id,
        )

    assert item.push_enabled is True
    assert item.target_premium_pct == Decimal("30")


def test_watchlist_alert_can_disable_push_without_binding() -> None:
    """确认关闭消息推送后可保存提醒配置且不要求 PushPlus 绑定。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = AppUser(username="push-off", password_hash="hash", role="USER", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        item = WatchlistService(db).create(
            payload=WatchlistCreate(
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                target_premium_pct=Decimal("30"),
                push_enabled=False,
            ),
            user_id=user.id,
        )

    assert item.push_enabled is False


def test_scan_skips_watchlist_when_push_disabled() -> None:
    """确认关闭消息推送后扫描任务不发送 PushPlus 消息。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        add_joint_trade_day(db, target_day)
        db.add_all(
            [
                WatchlistStock(
                    user_id=user.id,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    target_premium_pct=Decimal("30"),
                    push_enabled=False,
                    is_active=True,
                )
            ]
        )
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )

    assert events == []
    assert fake_client.sent == []


def test_admin_threshold_alert_uses_personal_message_without_binding() -> None:
    """确认 admin 提醒推送无需好友绑定，使用一对一消息。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    settings = Settings(default_admin_username="admin")
    with Session(engine) as db:
        admin = AppUser(username="admin", password_hash="hash", role="ADMIN", is_active=True)
        db.add(admin)
        db.flush()
        add_joint_trade_day(db, target_day)
        db.add(
            WatchlistStock(
                user_id=admin.id,
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                display_name="招商银行",
                preferred_direction="AH",
                target_premium_pct=Decimal("30"),
                is_active=True,
            )
        )
        add_realtime_quotes(db, a_price=Decimal("98"))
        db.commit()

        events = NotificationService(
            db,
            settings=settings,
            pushplus_client=fake_client,
        ).scan_alerts_for_day(
            target_day,
            admin.id,
            datetime(2026, 5, 5, 10, 30, 0, tzinfo=LOCAL_TEST_TZ),
        )

    assert len(events) == 1
    assert events[0].push_status == "SENT"
    assert len(fake_client.sent) == 1
    assert fake_client.sent[0][0] == "PERSONAL"


def test_price_alert_skips_when_market_is_closed() -> None:
    """确认股价提醒不在休市日推送。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        db.add_all(
            [
                ATradeCalendar(exchange="SSE", cal_date=target_day, is_open=0),
                HKTradeCalendar(cal_date=target_day, is_open=1),
                WatchlistStock(
                    user_id=user.id,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    a_price_alert_enabled=True,
                    a_price_alert_operator="GTE",
                    a_price_alert_target_price=Decimal("35"),
                    is_active=True,
                ),
            ]
        )
        add_realtime_quotes(db, a_price=Decimal("36"))
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 0, tzinfo=LOCAL_TEST_TZ),
        )

    assert events == []
    assert fake_client.sent == []


def test_price_alert_pushes_once_per_deviation_level() -> None:
    """确认股价提醒同一偏离档位去重，价格偏离增加到新档位后再次推送。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        add_joint_trade_day(db, target_day)
        db.add_all(
            [
                WatchlistStock(
                    user_id=user.id,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    a_price_alert_enabled=True,
                    a_price_alert_operator="LTE",
                    a_price_alert_target_price=Decimal("35"),
                    is_active=True,
                ),
            ]
        )
        add_realtime_quotes(db, a_price=Decimal("35"))
        db.commit()

        first_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 0, tzinfo=LOCAL_TEST_TZ),
        )
        first_event_type = first_events[0].event_type
        second_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 1, tzinfo=LOCAL_TEST_TZ),
        )
        add_realtime_quotes(
            db,
            a_price=Decimal("34.2"),
            quote_time=datetime(2026, 5, 5, 10, 30, 2),
        )
        db.commit()
        third_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 3, tzinfo=LOCAL_TEST_TZ),
        )

    assert len(first_events) == 1
    assert first_event_type == EVENT_PRICE_REACHED
    assert second_events == []
    assert len(third_events) == 1
    assert len(fake_client.sent) == 2
    assert "当前价格" in fake_client.sent[0][2]
    assert "目标价格" in fake_client.sent[0][2]


def test_price_alert_supports_a_and_h_markets() -> None:
    """确认同一自选股可同时触发 A 股和 H 股股价提醒。

    创建日期：2026-05-06
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_day = date(2026, 5, 5)
    fake_client = FakePushplusClient()
    with Session(engine) as db:
        user = add_user_with_binding(db)
        add_joint_trade_day(db, target_day)
        db.add(
            WatchlistStock(
                user_id=user.id,
                a_ts_code="600036.SH",
                hk_ts_code="03968.HK",
                a_price_alert_enabled=True,
                a_price_alert_operator="GTE",
                a_price_alert_target_price=Decimal("35"),
                h_price_alert_enabled=True,
                h_price_alert_operator="LTE",
                h_price_alert_target_price=Decimal("9"),
                is_active=True,
            )
        )
        add_realtime_quotes(db, a_price=Decimal("36"), hk_price=Decimal("8.8"))
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
            datetime(2026, 5, 5, 10, 30, 0, tzinfo=LOCAL_TEST_TZ),
        )
        event_markets = {event.price_alert_market for event in events}

    assert len(events) == 2
    assert event_markets == {"A", "H"}
    assert len(fake_client.sent) == 2
