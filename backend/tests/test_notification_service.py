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
from app.db.session import get_db
from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import (
    ATradeCalendar,
    HKTradeCalendar,
    RealtimeQuoteSnapshot,
    WatchlistStock,
)
from app.db.models.notification import AlertEvent, PushplusBinding
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
        user = AppUser(username="callback-api-user", password_hash="hash", role="USER", is_active=True)
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
