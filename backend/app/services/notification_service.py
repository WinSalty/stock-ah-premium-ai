from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.market import (
    ADailyQuote,
    ATradeCalendar,
    HKDailyQuote,
    HKTradeCalendar,
    WatchlistStock,
)
from app.db.models.notification import AlertEvent, PushplusBinding
from app.schemas.notification import (
    AdminPushplusBindingResponse,
    PushplusBindingResponse,
    PushplusFriendResponse,
)
from app.services.premium_query_service import PremiumQueryService
from app.services.pushplus_client import PushplusClient, PushplusError, PushplusFriend

logger = logging.getLogger(__name__)

EVENT_THRESHOLD_REACHED = "THRESHOLD_REACHED"
EVENT_PRICE_REACHED = "PRICE_REACHED"
PUSH_CHANNEL = "PUSHPLUS"
PUSH_STATUS_SENT = "SENT"
PUSH_STATUS_FAILED = "FAILED"
PRICE_OPERATOR_GTE = "GTE"
PRICE_OPERATOR_LTE = "LTE"
MARKET_A = "A"
MARKET_H = "H"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class NotificationError(ValueError):
    """消息推送业务错误。

    创建日期：2026-05-05
    author: sunshengxian
    """


class NotificationService:
    """PushPlus 绑定、测试推送和交易日提醒服务。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        pushplus_client: PushplusClient | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.pushplus_client = pushplus_client or PushplusClient(self.settings)
        self.premium_query_service = PremiumQueryService(db)

    def get_pushplus_binding(self, user_id: int) -> PushplusBindingResponse:
        """读取当前用户 PushPlus 绑定状态。

        创建日期：2026-05-05
        author: sunshengxian
        """

        binding = self._latest_binding(user_id)
        if binding is None:
            return PushplusBindingResponse(is_bound=False)
        return self._binding_response(binding)

    def list_pushplus_bindings(self) -> list[AdminPushplusBindingResponse]:
        """管理员查询所有 PushPlus 绑定状态。

        创建日期：2026-05-05
        author: sunshengxian
        """

        rows = self.db.execute(
            select(PushplusBinding, AppUser)
            .join(AppUser, AppUser.id == PushplusBinding.user_id)
            .order_by(desc(PushplusBinding.updated_at), PushplusBinding.id)
        ).all()
        return [
            AdminPushplusBindingResponse(
                id=binding.id,
                user_id=binding.user_id,
                username=user.username,
                is_active=binding.is_active,
                **self._binding_response(binding, include_names=True).model_dump(),
            )
            for binding, user in rows
        ]

    def create_pushplus_qr_code(
        self,
        user: AppUser,
        expire_seconds: int,
        scan_count: int,
    ) -> str:
        """创建用于添加好友的 PushPlus 个人二维码。

        创建日期：2026-05-05
        author: sunshengxian
        """

        content = self._binding_ticket_for_user(user.id)
        try:
            return self.pushplus_client.get_personal_qr_code(content, expire_seconds, scan_count)
        except PushplusError as exc:
            raise NotificationError(str(exc)) from exc

    def list_pushplus_friends(self) -> list[PushplusFriendResponse]:
        """查询 PushPlus 好友列表，响应中不暴露好友 token。

        创建日期：2026-05-05
        author: sunshengxian
        """

        try:
            friends = self.pushplus_client.list_friends()
        except PushplusError as exc:
            raise NotificationError(str(exc)) from exc
        return [
            PushplusFriendResponse(
                id=item.id,
                friend_id=item.friend_id,
                nick_name=item.nick_name,
                remark=item.remark,
                is_follow=item.is_follow,
                create_time=item.create_time,
            )
            for item in friends
        ]

    def bind_pushplus_friend(self, user: AppUser, friend_id: int) -> PushplusBindingResponse:
        """将当前用户绑定到 PushPlus 好友令牌。

        创建日期：2026-05-05
        author: sunshengxian
        """

        friend = self._find_friend(friend_id)
        existing = self.db.scalar(
            select(PushplusBinding).where(PushplusBinding.user_id == user.id)
        )
        now = self._now_naive()
        if existing is None:
            existing = PushplusBinding(
                user_id=user.id,
                friend_id=friend.friend_id,
                friend_token=friend.token,
                bound_at=now,
            )
            self.db.add(existing)
        existing.friend_id = friend.friend_id
        existing.friend_token = friend.token
        existing.friend_nick_name = friend.nick_name
        existing.friend_remark = friend.remark
        existing.is_follow = friend.is_follow
        existing.is_active = True
        existing.bound_at = now
        self.db.commit()
        self.db.refresh(existing)
        return self._binding_response(existing)

    def bind_pushplus_callback(
        self,
        content: str | None,
        friend_id: int,
        friend_token: str,
        nick_name: str | None,
        is_follow: bool,
    ) -> PushplusBindingResponse:
        """处理 PushPlus 新增好友回调并按绑定票据自动绑定系统用户。

        创建日期：2026-05-05
        author: sunshengxian
        """

        user_id = self._parse_binding_ticket_user_id(content)
        user = self.db.get(AppUser, user_id)
        if user is None or not user.is_active:
            raise NotificationError("绑定票据对应的系统用户不存在或已停用")
        binding = self.db.scalar(
            select(PushplusBinding).where(PushplusBinding.user_id == user_id)
        )
        now = self._now_naive()
        if binding is None:
            binding = PushplusBinding(
                user_id=user_id,
                friend_id=friend_id,
                friend_token=friend_token,
                bound_at=now,
            )
            self.db.add(binding)
        binding.friend_id = friend_id
        binding.friend_token = friend_token
        binding.friend_nick_name = self._normalize_optional_text(nick_name)
        binding.friend_remark = None
        binding.is_follow = is_follow
        binding.is_active = True
        binding.bound_at = now
        self.db.commit()
        self.db.refresh(binding)
        return self._binding_response(binding)

    def unbind_pushplus_friend(self, user_id: int) -> bool:
        """停用当前用户 PushPlus 绑定。

        创建日期：2026-05-05
        author: sunshengxian
        """

        binding = self._active_binding(user_id)
        if binding is None:
            return False
        binding.is_active = False
        self.db.commit()
        return True

    def send_test_push(self, user_id: int, title: str, content: str) -> str:
        """向当前用户绑定好友发送测试消息。

        创建日期：2026-05-05
        author: sunshengxian
        """

        binding = self._require_active_binding(user_id)
        try:
            return self.pushplus_client.send_friend_message(binding.friend_token, title, content)
        except PushplusError as exc:
            raise NotificationError(str(exc)) from exc

    def scan_alerts_for_day(
        self,
        trading_day: date | None = None,
        user_id: int | None = None,
    ) -> list[AlertEvent]:
        """扫描阈值和股价提醒；只有交易日数据触发推送。

        创建日期：2026-05-05
        author: sunshengxian
        """

        target_day = trading_day or self._today()
        statement = select(WatchlistStock).where(WatchlistStock.is_active.is_(True))
        if user_id is not None:
            statement = statement.where(WatchlistStock.user_id == user_id)
        watchlist_items = list(self.db.scalars(statement).all())
        events: list[AlertEvent] = []
        for item in watchlist_items:
            if not item.push_enabled:
                continue
            if self._active_binding(item.user_id) is None:
                continue
            threshold_event = self._scan_threshold_alert(item, target_day)
            if threshold_event is not None:
                events.append(threshold_event)
            price_event = self._scan_price_alert(item, target_day)
            if price_event is not None:
                events.append(price_event)
        return events

    def list_alert_events(self, user_id: int, limit: int = 50) -> list[AlertEvent]:
        """查询当前用户最近提醒事件。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return list(
            self.db.scalars(
                select(AlertEvent)
                .where(AlertEvent.user_id == user_id)
                .order_by(desc(AlertEvent.id))
                .limit(limit)
            ).all()
        )

    def _scan_threshold_alert(
        self,
        item: WatchlistStock,
        trading_day: date,
    ) -> AlertEvent | None:
        if item.target_premium_pct is None or not self._is_joint_trade_day(trading_day):
            return None
        premium_row = self.premium_query_service.latest_pair_row(item.a_ts_code, item.hk_ts_code)
        if premium_row is None or premium_row.trade_date != trading_day:
            return None
        direction = "AH" if item.preferred_direction == "AH" else "HA"
        metric = premium_row.ah_premium if direction == "AH" else premium_row.ha_premium
        if metric is None or metric < item.target_premium_pct:
            return None
        title = f"{self._stock_label(item)} {direction} 阈值触发"
        content = self._threshold_message(item, trading_day, direction, metric)
        dedupe_key = (
            f"{EVENT_THRESHOLD_REACHED}:{item.user_id}:{item.id}:{direction}:"
            f"{item.target_premium_pct}:{trading_day.isoformat()}"
        )
        return self._create_and_push_event(
            item=item,
            event_type=EVENT_THRESHOLD_REACHED,
            trading_day=trading_day,
            title=title,
            content=content,
            dedupe_key=dedupe_key,
            metric_direction=direction,
            metric_premium_pct=metric,
            target_premium_pct=item.target_premium_pct,
        )

    def _scan_price_alert(
        self,
        item: WatchlistStock,
        trading_day: date,
    ) -> AlertEvent | None:
        if (
            not item.price_alert_enabled
            or item.price_alert_target_price is None
            or item.price_alert_market not in {MARKET_A, MARKET_H}
            or not self._is_market_trade_day(item.price_alert_market, trading_day)
        ):
            return None
        ts_code = item.a_ts_code if item.price_alert_market == MARKET_A else item.hk_ts_code
        last_price = self._latest_close(item.price_alert_market, ts_code, trading_day)
        if last_price is None:
            return None
        operator = (
            item.price_alert_operator
            if item.price_alert_operator == PRICE_OPERATOR_LTE
            else PRICE_OPERATOR_GTE
        )
        reached = (
            last_price >= item.price_alert_target_price
            if operator == PRICE_OPERATOR_GTE
            else last_price <= item.price_alert_target_price
        )
        if not reached:
            return None
        title = f"{self._stock_label(item)} 股价提醒"
        content = self._price_message(item, trading_day, ts_code, last_price, operator)
        dedupe_key = (
            f"{EVENT_PRICE_REACHED}:{item.user_id}:{item.id}:{item.price_alert_market}:"
            f"{operator}:{item.price_alert_target_price}:{trading_day.isoformat()}"
        )
        return self._create_and_push_event(
            item=item,
            event_type=EVENT_PRICE_REACHED,
            trading_day=trading_day,
            title=title,
            content=content,
            dedupe_key=dedupe_key,
            price_alert_market=item.price_alert_market,
            price_alert_operator=operator,
            price_alert_ts_code=ts_code,
            last_price=last_price,
            target_price=item.price_alert_target_price,
        )

    def _create_and_push_event(
        self,
        item: WatchlistStock,
        event_type: str,
        trading_day: date,
        title: str,
        content: str,
        dedupe_key: str,
        metric_direction: str | None = None,
        metric_premium_pct: Decimal | None = None,
        target_premium_pct: Decimal | None = None,
        price_alert_market: str | None = None,
        price_alert_operator: str | None = None,
        price_alert_ts_code: str | None = None,
        last_price: Decimal | None = None,
        target_price: Decimal | None = None,
    ) -> AlertEvent | None:
        event = AlertEvent(
            user_id=item.user_id,
            watchlist_id=item.id,
            event_type=event_type,
            trading_day=trading_day,
            metric_direction=metric_direction,
            metric_premium_pct=metric_premium_pct,
            target_premium_pct=target_premium_pct,
            price_alert_market=price_alert_market,
            price_alert_operator=price_alert_operator,
            price_alert_ts_code=price_alert_ts_code,
            last_price=last_price,
            target_price=target_price,
            message_title=title,
            message_content=content,
            push_channel=PUSH_CHANNEL,
            push_status="PENDING",
            dedupe_key=dedupe_key,
        )
        self.db.add(event)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return None
        self.db.refresh(event)
        binding = self._require_active_binding(item.user_id)
        try:
            event.push_message_id = self.pushplus_client.send_friend_message(
                binding.friend_token,
                title,
                content,
            )
            event.push_status = PUSH_STATUS_SENT
            event.sent_at = self._now_naive()
        except PushplusError as exc:
            event.push_status = PUSH_STATUS_FAILED
            event.error_message = str(exc)
            logger.error(
                "PushPlus 提醒发送失败 event_id=%s user_id=%s type=%s error=%s",
                event.id,
                item.user_id,
                event_type,
                str(exc),
            )
        self.db.commit()
        self.db.refresh(event)
        return event

    def _threshold_message(
        self,
        item: WatchlistStock,
        trading_day: date,
        direction: str,
        metric: Decimal,
    ) -> str:
        return "\n".join(
            [
                "# AH 阈值触发",
                "",
                f"{self._stock_label(item)} {direction} 溢价达到 {metric}%",
                "",
                f"- A 股：{item.a_ts_code}",
                f"- H 股：{item.hk_ts_code}",
                f"- 方向：{direction}",
                f"- 目标阈值：{item.target_premium_pct}%",
                f"- 交易日：{trading_day.isoformat()}",
            ]
        )

    def _price_message(
        self,
        item: WatchlistStock,
        trading_day: date,
        ts_code: str,
        last_price: Decimal,
        operator: str,
    ) -> str:
        operator_label = ">=" if operator == PRICE_OPERATOR_GTE else "<="
        market_label = "A 股" if item.price_alert_market == MARKET_A else "H 股"
        return "\n".join(
            [
                "# 股价提醒触发",
                "",
                (
                    f"{self._stock_label(item)} {market_label}价格 "
                    f"{last_price} {operator_label} {item.price_alert_target_price}"
                ),
                "",
                f"- 证券代码：{ts_code}",
                f"- 市场：{market_label}",
                f"- 触发条件：{operator_label} {item.price_alert_target_price}",
                f"- 交易日：{trading_day.isoformat()}",
            ]
        )

    def _latest_close(self, market: str, ts_code: str, trading_day: date) -> Decimal | None:
        model = ADailyQuote if market == MARKET_A else HKDailyQuote
        row = self.db.scalar(
            select(model)
            .where(model.ts_code == ts_code, model.trade_date == trading_day)
            .order_by(desc(model.trade_date))
            .limit(1)
        )
        return row.close if row is not None else None

    def _is_joint_trade_day(self, trading_day: date) -> bool:
        return self._is_market_trade_day(MARKET_A, trading_day) and self._is_market_trade_day(
            MARKET_H,
            trading_day,
        )

    def _is_market_trade_day(self, market: str, trading_day: date) -> bool:
        if market == MARKET_A:
            return bool(
                self.db.scalar(
                    select(ATradeCalendar.is_open).where(
                        ATradeCalendar.exchange == "SSE",
                        ATradeCalendar.cal_date == trading_day,
                    )
                )
                == 1
            )
        if market == MARKET_H:
            return bool(
                self.db.scalar(
                    select(HKTradeCalendar.is_open).where(HKTradeCalendar.cal_date == trading_day)
                )
                == 1
            )
        return False

    def _find_friend(self, friend_id: int) -> PushplusFriend:
        try:
            friends = self.pushplus_client.list_friends()
        except PushplusError as exc:
            raise NotificationError(str(exc)) from exc
        for friend in friends:
            if friend.friend_id == friend_id:
                return friend
        raise NotificationError("未找到对应 PushPlus 好友，请扫码后刷新好友列表")

    def _active_binding(self, user_id: int) -> PushplusBinding | None:
        return self.db.scalar(
            select(PushplusBinding).where(
                PushplusBinding.user_id == user_id,
                PushplusBinding.is_active.is_(True),
            )
        )

    def _latest_binding(self, user_id: int) -> PushplusBinding | None:
        return self.db.scalar(
            select(PushplusBinding)
            .where(PushplusBinding.user_id == user_id)
            .order_by(desc(PushplusBinding.updated_at), desc(PushplusBinding.id))
            .limit(1)
        )

    def _require_active_binding(self, user_id: int) -> PushplusBinding:
        binding = self._active_binding(user_id)
        if binding is None:
            raise NotificationError("当前用户尚未绑定 PushPlus 好友")
        return binding

    def _binding_response(
        self,
        binding: PushplusBinding,
        include_names: bool | None = None,
    ) -> PushplusBindingResponse:
        show_names = binding.is_active if include_names is None else include_names
        return PushplusBindingResponse(
            is_bound=binding.is_active,
            status="BOUND" if binding.is_active else "DISABLED",
            friend_id=binding.friend_id,
            friend_nick_name=binding.friend_nick_name if show_names else None,
            friend_remark=binding.friend_remark if show_names else None,
            is_follow=binding.is_follow,
            bound_at=binding.bound_at,
        )

    def _parse_binding_ticket_user_id(self, content: str | None) -> int:
        prefix = "stock-ah-premium-ai:binding:"
        if not content or not content.startswith(prefix):
            raise NotificationError("PushPlus 回调绑定票据无效")
        if ":sig:" not in content:
            raise NotificationError("PushPlus 回调绑定票据签名缺失")
        user_part, signature = content.split(":sig:", maxsplit=1)
        try:
            user_id = int(user_part.removeprefix(prefix))
        except ValueError as exc:
            raise NotificationError("PushPlus 回调绑定票据用户参数无效") from exc
        expected = self._qr_signature(user_id)
        if not hmac.compare_digest(signature, expected):
            raise NotificationError("PushPlus 回调绑定票据签名无效")
        return user_id

    def _binding_ticket_for_user(self, user_id: int) -> str:
        return f"stock-ah-premium-ai:binding:{user_id}:sig:{self._qr_signature(user_id)}"

    def _qr_signature(self, user_id: int) -> str:
        digest = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            f"pushplus-binding:{user_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest[:24]

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _stock_label(self, item: WatchlistStock) -> str:
        return item.display_name or item.a_ts_code

    def _today(self) -> date:
        return datetime.now(LOCAL_TZ).date()

    def _now_naive(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
