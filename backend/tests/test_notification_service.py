from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.market import (
    ADailyQuote,
    ATradeCalendar,
    HKTradeCalendar,
    OfficialAHComparison,
    WatchlistStock,
)
from app.db.models.notification import AlertEvent, PushplusBinding
from app.schemas.watchlist import WatchlistCreate
from app.services.notification_service import (
    EVENT_PRICE_REACHED,
    NotificationError,
    NotificationService,
)
from app.services.watchlist_service import WatchlistError, WatchlistService


class FakePushplusClient:
    """测试用 PushPlus 客户端。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_friend_message(self, to_token: str, title: str, content: str) -> str:
        self.sent.append((to_token, title, content))
        return f"msg-{len(self.sent)}"


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


def test_threshold_alert_pushes_once_per_trading_day() -> None:
    """确认阈值触发仅在共同交易日推送且同一天去重。

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
                ),
                OfficialAHComparison(
                    trade_date=target_day,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    ah_premium=Decimal("31"),
                    ha_premium=Decimal("-23.664"),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                ),
            ]
        )
        db.commit()

        first_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )
        second_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )

        total_events = db.scalar(select(AlertEvent))

    assert len(first_events) == 1
    assert second_events == []
    assert total_events is not None
    assert len(fake_client.sent) == 1


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
                ),
                OfficialAHComparison(
                    trade_date=target_day,
                    a_ts_code="600036.SH",
                    hk_ts_code="03968.HK",
                    ah_premium=Decimal("31"),
                    ha_premium=Decimal("-23.664"),
                    is_realtime=False,
                    data_source="TUSHARE_OFFICIAL",
                ),
            ]
        )
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )

    assert events == []
    assert fake_client.sent == []


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
                    price_alert_enabled=True,
                    price_alert_market="A",
                    price_alert_operator="GTE",
                    price_alert_target_price=Decimal("35"),
                    is_active=True,
                ),
                ADailyQuote(
                    ts_code="600036.SH",
                    trade_date=target_day,
                    close=Decimal("36"),
                ),
            ]
        )
        db.commit()

        events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )

    assert events == []
    assert fake_client.sent == []


def test_price_alert_pushes_once_per_trading_day() -> None:
    """确认股价提醒达到用户价格后同一天仅推送一次。

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
                    price_alert_enabled=True,
                    price_alert_market="A",
                    price_alert_operator="LTE",
                    price_alert_target_price=Decimal("35"),
                    is_active=True,
                ),
                ADailyQuote(
                    ts_code="600036.SH",
                    trade_date=target_day,
                    close=Decimal("34.8"),
                ),
            ]
        )
        db.commit()

        first_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )
        first_event_type = first_events[0].event_type
        second_events = NotificationService(db, pushplus_client=fake_client).scan_alerts_for_day(
            target_day,
            user.id,
        )

    assert len(first_events) == 1
    assert first_event_type == EVENT_PRICE_REACHED
    assert second_events == []
    assert len(fake_client.sent) == 1
