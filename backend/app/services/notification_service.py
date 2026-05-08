from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, date, datetime, time
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.market import (
    ATradeCalendar,
    HKTradeCalendar,
    WatchlistStock,
)
from app.db.models.notification import AlertEvent, PushplusBinding, PushplusMessageLog
from app.schemas.notification import (
    AdminPushplusBindingResponse,
    PushplusBindingResponse,
    PushplusFriendResponse,
    PushplusMessageLogResponse,
)
from app.services.pushplus_client import PushplusClient, PushplusError, PushplusFriend
from app.services.realtime_market_service import RealtimeMarketDataService, RealtimeQuote
from app.services.realtime_premium_service import (
    REALTIME_QUALITY,
    STALE_FX_QUALITY,
    RealtimePremiumService,
)

logger = logging.getLogger(__name__)

EVENT_THRESHOLD_REACHED = "THRESHOLD_REACHED"
EVENT_PRICE_REACHED = "PRICE_REACHED"
PUSH_CHANNEL = "PUSHPLUS"
PUSH_STATUS_SENT = "SENT"
PUSH_STATUS_FAILED = "FAILED"
PUSH_STATUS_PENDING = "PENDING"
PUSH_RECIPIENT_FRIEND = "FRIEND"
PUSH_RECIPIENT_PERSONAL = "PERSONAL"
DAILY_EVENT_TYPE_LIMIT = 5
THRESHOLD_DEVIATION_STEP_PCT = Decimal("1")
PRICE_DEVIATION_STEP_PCT = Decimal("2")
PRICE_OPERATOR_GTE = "GTE"
PRICE_OPERATOR_LTE = "LTE"
MARKET_A = "A"
MARKET_H = "H"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
A_REALTIME_SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0)))
H_REALTIME_SESSIONS = ((time(9, 30), time(12, 0)), (time(13, 0), time(16, 0)))
REALTIME_THRESHOLD_QUALITIES = {REALTIME_QUALITY, STALE_FX_QUALITY}
HTML_CARD_STYLE = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "color:#14202e;background:#f3f6f2;padding:14px;"
)
HTML_PANEL_STYLE = (
    "max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #d9e4dc;"
    "border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(40,64,48,.08);"
)
HTML_HEADER_STYLE = "padding:16px 18px;color:#ffffff;"
HTML_BODY_STYLE = "padding:16px 18px 18px;"
HTML_BADGE_STYLE = (
    "display:inline-block;padding:3px 8px;border-radius:999px;background:rgba(255,255,255,.2);"
    "font-size:12px;line-height:1.4;"
)
HTML_SUMMARY_STYLE = (
    "font-size:15px;font-weight:600;line-height:1.75;background:#fbf8ef;"
    "border:1px solid #eadfbe;border-radius:8px;padding:10px 12px;"
)
HTML_MUTED_STYLE = "color:#66705f;font-size:12px;line-height:1.7;margin:10px 0 0;"
HTML_TABLE_STYLE = (
    "width:100%;border-collapse:separate;border-spacing:0;margin-top:12px;font-size:14px;"
)
HTML_LABEL_CELL_STYLE = (
    "width:34%;padding:9px 10px;border-top:1px solid #edf0e8;color:#68715f;background:#fbfcf7;"
)
HTML_VALUE_CELL_STYLE = "padding:9px 10px;border-top:1px solid #edf0e8;color:#14202e;"
HTML_VISUAL_WRAP_STYLE = (
    "margin-top:14px;padding:10px 12px;border-radius:10px;background:rgba(255,255,255,.16);"
)
HTML_VISUAL_BAR_BASE_STYLE = (
    "display:inline-block;width:8px;margin-right:5px;border-radius:6px 6px 2px 2px;"
    "vertical-align:bottom;background:#f5e6b8;"
)


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
        self.realtime_market_data_service = RealtimeMarketDataService.from_db(db)
        self.realtime_premium_service = RealtimePremiumService(
            db,
            market_data_service=self.realtime_market_data_service,
        )

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

        if self._active_binding(user.id) is not None:
            raise NotificationError("当前用户已绑定 PushPlus，不支持重复绑定")
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

        return self.bind_pushplus_friend_for_user(user.id, friend_id)

    def bind_pushplus_friend_for_user(
        self,
        user_id: int,
        friend_id: int,
    ) -> PushplusBindingResponse:
        """管理员将指定系统用户绑定到 PushPlus 好友令牌。

        创建日期：2026-05-05
        author: sunshengxian
        """

        user = self.db.get(AppUser, user_id)
        if user is None or not user.is_active:
            raise NotificationError("绑定用户不存在或已停用")
        existing = self.db.scalar(
            select(PushplusBinding).where(PushplusBinding.user_id == user_id)
        )
        if existing is not None and existing.is_active:
            raise NotificationError("当前用户已绑定 PushPlus，不支持重复绑定")
        friend = self._find_friend(friend_id)
        self._ensure_friend_not_bound(friend.friend_id, friend.token, user_id)
        now = self._now_naive()
        if existing is None:
            existing = PushplusBinding(
                user_id=user_id,
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
        if binding is not None and binding.is_active:
            raise NotificationError("当前用户已绑定 PushPlus，不支持重复绑定")
        self._ensure_friend_not_bound(friend_id, friend_token, user_id)
        friend = self._find_friend_or_none(friend_id)
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
        binding.friend_nick_name = self._normalize_optional_text(nick_name) or (
            friend.nick_name if friend else None
        )
        binding.friend_remark = friend.remark if friend else None
        binding.is_follow = friend.is_follow if friend else is_follow
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
        """向当前用户发送测试消息。

        创建日期：2026-05-05
        author: sunshengxian
        """

        html_content = self._test_message(title, content)
        try:
            return self._send_pushplus_message(user_id, title, html_content)
        except PushplusError as exc:
            raise NotificationError(str(exc)) from exc

    def scan_alerts_for_day(
        self,
        trading_day: date | None = None,
        user_id: int | None = None,
        scan_time: datetime | None = None,
    ) -> list[AlertEvent]:
        """扫描实时阈值和股价提醒；只有交易日交易时段数据触发推送。

        创建日期：2026-05-05
        author: sunshengxian
        """

        local_scan_time = scan_time.astimezone(LOCAL_TZ) if scan_time else self._now_local()
        target_day = trading_day or local_scan_time.date()
        statement = select(WatchlistStock).where(WatchlistStock.is_active.is_(True))
        if user_id is not None:
            statement = statement.where(WatchlistStock.user_id == user_id)
        watchlist_items = list(self.db.scalars(statement).all())
        events: list[AlertEvent] = []
        self.realtime_market_data_service = RealtimeMarketDataService.from_db(
            self.db,
            local_scan_time.date(),
        )
        # 提醒扫描按本轮扫描日校验 A/H/汇率快照日期，避免测试回放或补扫时误用机器当天。
        self.realtime_premium_service = RealtimePremiumService(
            self.db,
            market_data_service=self.realtime_market_data_service,
            local_today=local_scan_time.date(),
        )
        for item in watchlist_items:
            if not item.push_enabled:
                continue
            if not self.can_send_pushplus_to_user(item.user_id):
                continue
            threshold_event = self._scan_threshold_alert(item, target_day, local_scan_time)
            if threshold_event is not None:
                events.append(threshold_event)
            for market in (MARKET_A, MARKET_H):
                price_event = self._scan_price_alert(item, target_day, local_scan_time, market)
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

    def list_pushplus_message_logs(
        self,
        limit: int = 100,
        keyword: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
    ) -> list[PushplusMessageLogResponse]:
        """管理员查询 PushPlus 推送流水。

        创建日期：2026-05-06
        author: sunshengxian
        """

        # 推送记录搜索只覆盖运维排查需要的标题、正文、接收人和用户展示字段；
        # 响应模型仍不返回好友 token，避免搜索接口扩大敏感字段暴露面。
        statement = select(PushplusMessageLog, AppUser).join(
            AppUser,
            AppUser.id == PushplusMessageLog.user_id,
        )
        normalized_keyword = self._normalize_optional_text(keyword)
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            statement = statement.where(
                or_(
                    PushplusMessageLog.message_title.like(like_keyword),
                    PushplusMessageLog.message_content.like(like_keyword),
                    PushplusMessageLog.recipient_name.like(like_keyword),
                    PushplusMessageLog.push_message_id.like(like_keyword),
                    AppUser.username.like(like_keyword),
                    AppUser.display_name.like(like_keyword),
                )
            )
        normalized_status = self._normalize_optional_text(status)
        if normalized_status:
            statement = statement.where(
                PushplusMessageLog.push_status == normalized_status.upper()
            )
        if user_id is not None:
            statement = statement.where(PushplusMessageLog.user_id == user_id)
        rows = self.db.execute(
            statement.order_by(desc(PushplusMessageLog.id)).limit(limit)
        ).all()
        return [
            PushplusMessageLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=user.username,
                display_name=user.display_name,
                alert_event_id=log.alert_event_id,
                recipient_type=log.recipient_type,
                recipient_friend_id=log.recipient_friend_id,
                recipient_name=log.recipient_name,
                message_title=log.message_title,
                message_content=log.message_content,
                push_channel=log.push_channel,
                push_status=log.push_status,
                push_message_id=log.push_message_id,
                error_message=log.error_message,
                sent_at=log.sent_at,
                created_at=log.created_at,
                updated_at=log.updated_at,
            )
            for log, user in rows
        ]

    def _scan_threshold_alert(
        self,
        item: WatchlistStock,
        trading_day: date,
        scan_time: datetime,
    ) -> AlertEvent | None:
        if (
            item.target_premium_pct is None
            or not self._is_joint_trade_day(trading_day)
            or not self._is_joint_realtime_session(scan_time)
        ):
            return None
        realtime = self.realtime_premium_service.calculate_pair(
            a_ts_code=item.a_ts_code,
            hk_ts_code=item.hk_ts_code,
            a_name=item.display_name,
            watchlist=item,
        )
        if realtime.quote_quality not in REALTIME_THRESHOLD_QUALITIES:
            return None
        direction = realtime.metric_direction
        metric = realtime.metric_premium_pct
        if metric is None or metric < item.target_premium_pct:
            return None
        deviation_pct = metric - item.target_premium_pct
        alert_level = self._deviation_level(deviation_pct, THRESHOLD_DEVIATION_STEP_PCT)
        threshold_count = self._daily_event_type_count(
            item.user_id,
            trading_day,
            EVENT_THRESHOLD_REACHED,
        )
        if threshold_count >= DAILY_EVENT_TYPE_LIMIT:
            return None
        title = f"{self._stock_label(item)} {direction} 阈值触发"
        content = self._threshold_message(item, trading_day, direction, metric, realtime)
        dedupe_key = (
            f"{EVENT_THRESHOLD_REACHED}:{item.user_id}:{item.id}:{direction}:"
            f"{item.target_premium_pct}:level-{alert_level}:{trading_day.isoformat()}"
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
        scan_time: datetime,
        market: str,
    ) -> AlertEvent | None:
        if market == MARKET_A:
            enabled = item.a_price_alert_enabled
            operator_config = item.a_price_alert_operator
            target_price = item.a_price_alert_target_price
            ts_code = item.a_ts_code
        else:
            enabled = item.h_price_alert_enabled
            operator_config = item.h_price_alert_operator
            target_price = item.h_price_alert_target_price
            ts_code = item.hk_ts_code
        if (
            not enabled
            or target_price is None
            or not self._is_market_trade_day(market, trading_day)
            or not self._is_market_realtime_session(market, scan_time)
        ):
            return None
        quote = self._latest_realtime_quote(market, ts_code)
        if not self._is_realtime_quote_usable(quote):
            return None
        last_price = quote.last_price
        operator = (
            operator_config
            if operator_config == PRICE_OPERATOR_LTE
            else PRICE_OPERATOR_GTE
        )
        reached = (
            last_price >= target_price
            if operator == PRICE_OPERATOR_GTE
            else last_price <= target_price
        )
        if not reached:
            return None
        deviation_pct = self._price_deviation_pct(
            last_price,
            target_price,
            operator,
        )
        alert_level = self._deviation_level(deviation_pct, PRICE_DEVIATION_STEP_PCT)
        price_count = self._daily_event_type_count(
            item.user_id,
            trading_day,
            EVENT_PRICE_REACHED,
        )
        if price_count >= DAILY_EVENT_TYPE_LIMIT:
            return None
        title = f"{self._stock_label(item)} 股价提醒"
        content = self._price_message(
            item,
            trading_day,
            ts_code,
            last_price,
            operator,
            market,
            target_price,
        )
        dedupe_key = (
            f"{EVENT_PRICE_REACHED}:{item.user_id}:{item.id}:{market}:"
            f"{operator}:{target_price}:level-{alert_level}:{trading_day.isoformat()}"
        )
        return self._create_and_push_event(
            item=item,
            event_type=EVENT_PRICE_REACHED,
            trading_day=trading_day,
            title=title,
            content=content,
            dedupe_key=dedupe_key,
            price_alert_market=market,
            price_alert_operator=operator,
            price_alert_ts_code=ts_code,
            last_price=last_price,
            target_price=target_price,
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
        try:
            event.push_message_id = self._send_pushplus_message(
                item.user_id,
                title,
                content,
                alert_event_id=event.id,
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

    def _daily_event_type_count(self, user_id: int, trading_day: date, event_type: str) -> int:
        """统计用户单日单类提醒数量。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return len(
            self.db.scalars(
                select(AlertEvent.id).where(
                    AlertEvent.user_id == user_id,
                    AlertEvent.trading_day == trading_day,
                    AlertEvent.event_type == event_type,
                )
            ).all()
        )

    def _deviation_level(self, deviation_pct: Decimal, step_pct: Decimal) -> int:
        """按偏离比例计算提醒档位，触发当档为 0。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if deviation_pct <= 0:
            return 0
        return int(deviation_pct // step_pct)

    def _price_deviation_pct(
        self,
        last_price: Decimal,
        target_price: Decimal,
        operator: str,
    ) -> Decimal:
        """计算股价相对提醒价的偏离百分比。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if target_price <= 0:
            return Decimal("0")
        distance = (
            last_price - target_price
            if operator == PRICE_OPERATOR_GTE
            else target_price - last_price
        )
        if distance <= 0:
            return Decimal("0")
        return (distance / target_price) * Decimal("100")

    def _threshold_message(
        self,
        item: WatchlistStock,
        trading_day: date,
        direction: str,
        metric: Decimal,
        realtime: object,
    ) -> str:
        target = item.target_premium_pct or Decimal("0")
        distance = metric - target
        current_text = self._format_decimal(metric)
        target_text = self._format_decimal(target)
        a_price = getattr(realtime, "a_last_price", None)
        hk_price = getattr(realtime, "hk_last_price", None)
        fx_rate = getattr(realtime, "hkd_cny_rate", None)
        # 阈值推送中的价格和汇率来自同一次实时溢价计算，保证用户收到的
        # A/H 股价、HKD/CNY 汇率与触发溢价口径一致。
        quote_details = [
            ("A 股价格", f"{self._format_decimal(a_price)} 人民币" if a_price is not None else "-"),
            ("H 股价格", f"{self._format_decimal(hk_price)} 港币" if hk_price is not None else "-"),
            ("HKD/CNY 汇率", self._format_decimal(fx_rate) if fx_rate is not None else "-"),
        ]
        return self._html_message(
            title="AH 溢价阈值触发",
            badge="阈值提醒",
            accent="#2f6f4e",
            summary=(
                f"{self._stock_label(item)} {direction} 溢价当前为 {current_text}%，"
                f"已达到目标阈值 {target_text}%。"
            ),
            details=[
                ("触发类型", "溢价阈值提醒"),
                ("标的名称", self._stock_label(item)),
                ("A 股代码", item.a_ts_code),
                ("H 股代码", item.hk_ts_code),
                ("提醒方向", f"{direction} 溢价"),
                ("当前溢价", f"{current_text}%"),
                ("目标阈值", f"{target_text}%"),
                ("超过阈值", f"{self._format_decimal(distance)}%"),
                *quote_details,
                ("交易日", trading_day.isoformat()),
            ],
        )

    def _price_message(
        self,
        item: WatchlistStock,
        trading_day: date,
        ts_code: str,
        last_price: Decimal,
        operator: str,
        market: str,
        target_price: Decimal,
    ) -> str:
        operator_symbol = ">=" if operator == PRICE_OPERATOR_GTE else "<="
        operator_text = "大于等于" if operator == PRICE_OPERATOR_GTE else "小于等于"
        market_label = "A 股" if market == MARKET_A else "H 股"
        price_text = self._format_decimal(last_price)
        target_text = self._format_decimal(target_price)
        currency = "人民币" if market == MARKET_A else "港币"
        return self._html_message(
            title="股价提醒触发",
            badge="股价提醒",
            accent="#b7791f",
            summary=(
                f"{self._stock_label(item)} {market_label}最新收盘价 {price_text} "
                f"已{operator_text}目标价格 {target_text}。"
            ),
            details=[
                ("触发类型", "股价提醒"),
                ("标的名称", self._stock_label(item)),
                ("证券代码", ts_code),
                ("提醒市场", market_label),
                ("当前价格", f"{price_text} {currency}"),
                ("目标价格", f"{target_text} {currency}"),
                ("触发条件", f"当前价格 {operator_symbol} {target_text}"),
                ("交易日", trading_day.isoformat()),
            ],
        )

    def _test_message(self, title: str, content: str) -> str:
        return self._html_message(
            title=title,
            badge="测试推送",
            accent="#2f5f7f",
            summary=content or "PushPlus 好友消息推送已连通。",
            details=[
                ("消息类型", "PushPlus HTML 测试消息"),
                ("发送时间", self._now_naive().strftime("%Y-%m-%d %H:%M:%S")),
                ("结果说明", "收到本消息表示当前账号 PushPlus 好友消息链路已连通。"),
            ],
        )

    def _html_message(
        self,
        title: str,
        badge: str,
        accent: str,
        summary: str,
        details: list[tuple[str, str]],
    ) -> str:
        rows = "".join(
            (
                "<tr>"
                f'<td style="{HTML_LABEL_CELL_STYLE}">{escape(label)}</td>'
                f'<td style="{HTML_VALUE_CELL_STYLE}">{escape(value)}</td>'
                "</tr>"
            )
            for label, value in details
        )
        return (
            f'<div style="{HTML_CARD_STYLE}">'
            f'<div style="{HTML_PANEL_STYLE}">'
            f'<div style="background:{accent};{HTML_HEADER_STYLE}">'
            f'<div style="{HTML_BADGE_STYLE}">{escape(badge)}</div>'
            f'<div style="font-size:19px;font-weight:700;margin-top:8px;line-height:1.35;">'
            f"{escape(title)}"
            "</div>"
            f"{self._html_signal_visual()}"
            "</div>"
            f'<div style="{HTML_BODY_STYLE}">'
            f'<div style="{HTML_SUMMARY_STYLE}">{escape(summary)}</div>'
            f'<div style="{HTML_MUTED_STYLE}">'
            "本次触发明细如下，请结合交易日、标的和目标条件复核。"
            "</div>"
            f'<table style="{HTML_TABLE_STYLE}"><tbody>{rows}</tbody></table>'
            "</div>"
            "</div>"
            "</div>"
        )

    def _format_decimal(self, value: Decimal) -> str:
        text = format(value.normalize(), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def _html_signal_visual(self) -> str:
        bar_specs = ((10, "0.48"), (18, "0.66"), (13, "0.58"), (25, "0.9"), (32, "1"))
        bars = "".join(
            (
                f'<span style="{HTML_VISUAL_BAR_BASE_STYLE}'
                f'height:{height}px;opacity:{opacity};"></span>'
            )
            for height, opacity in bar_specs
        )
        return (
            f'<div style="{HTML_VISUAL_WRAP_STYLE}">'
            '<span style="display:inline-block;margin-right:10px;font-size:12px;opacity:.86;">'
            "价差信号"
            "</span>"
            f"{bars}"
            '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            'background:#ffffff;margin-left:4px;vertical-align:middle;"></span>'
            "</div>"
        )

    def _ensure_friend_not_bound(
        self,
        friend_id: int,
        friend_token: str,
        target_user_id: int,
    ) -> None:
        occupied = self.db.scalar(
            select(PushplusBinding).where(
                PushplusBinding.is_active.is_(True),
                PushplusBinding.user_id != target_user_id,
                (
                    (PushplusBinding.friend_id == friend_id)
                    | (PushplusBinding.friend_token == friend_token)
                ),
            )
        )
        if occupied is not None:
            raise NotificationError("该 PushPlus 好友已绑定其他用户，不支持重复绑定")

    def _latest_realtime_quote(self, market: str, ts_code: str) -> RealtimeQuote | None:
        if market == MARKET_A:
            return self.realtime_market_data_service.provider.get_a_quote(ts_code)
        if market == MARKET_H:
            return self.realtime_market_data_service.provider.get_hk_quote(ts_code)
        return None

    def _is_realtime_quote_usable(self, quote: RealtimeQuote | None) -> bool:
        return bool(
            quote is not None
            and quote.last_price is not None
            and quote.last_price > 0
            and (quote.quality or "").upper() == REALTIME_QUALITY
        )

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

    def _is_joint_realtime_session(self, scan_time: datetime) -> bool:
        return self._is_market_realtime_session(
            MARKET_A,
            scan_time,
        ) and self._is_market_realtime_session(MARKET_H, scan_time)

    def _is_market_realtime_session(self, market: str, scan_time: datetime) -> bool:
        sessions = A_REALTIME_SESSIONS if market == MARKET_A else H_REALTIME_SESSIONS
        current_time = scan_time.astimezone(LOCAL_TZ).time()
        return any(start <= current_time <= end for start, end in sessions)

    def _find_friend(self, friend_id: int) -> PushplusFriend:
        try:
            friends = self.pushplus_client.list_friends()
        except PushplusError as exc:
            raise NotificationError(str(exc)) from exc
        for friend in friends:
            if friend.friend_id == friend_id:
                return friend
        raise NotificationError("未找到对应 PushPlus 好友，请扫码后刷新好友列表")

    def _find_friend_or_none(self, friend_id: int) -> PushplusFriend | None:
        try:
            return self._find_friend(friend_id)
        except NotificationError:
            return None

    def can_send_pushplus_to_user(self, user_id: int) -> bool:
        """判断指定用户是否具备 PushPlus 推送通道。

        创建日期：2026-05-06
        author: sunshengxian
        """

        return self._active_binding(user_id) is not None or self._is_default_admin_user(user_id)

    def _send_pushplus_message(
        self,
        user_id: int,
        title: str,
        content: str,
        alert_event_id: int | None = None,
    ) -> str:
        log = self._create_pushplus_message_log(user_id, title, content, alert_event_id)
        try:
            if log.recipient_type == PUSH_RECIPIENT_PERSONAL:
                message_id = self.pushplus_client.send_personal_message(title, content)
            else:
                binding = self._require_active_binding(user_id)
                message_id = self.pushplus_client.send_friend_message(
                    binding.friend_token,
                    title,
                    content,
                )
        except PushplusError as exc:
            log.push_status = PUSH_STATUS_FAILED
            log.error_message = str(exc)
            self.db.commit()
            raise
        log.push_status = PUSH_STATUS_SENT
        log.push_message_id = message_id
        log.sent_at = self._now_naive()
        self.db.commit()
        return message_id

    def _create_pushplus_message_log(
        self,
        user_id: int,
        title: str,
        content: str,
        alert_event_id: int | None,
    ) -> PushplusMessageLog:
        binding = (
            None
            if self._is_default_admin_user(user_id)
            else self._require_active_binding(user_id)
        )
        log = PushplusMessageLog(
            user_id=user_id,
            alert_event_id=alert_event_id,
            recipient_type=PUSH_RECIPIENT_PERSONAL if binding is None else PUSH_RECIPIENT_FRIEND,
            recipient_friend_id=binding.friend_id if binding else None,
            recipient_name=self._pushplus_recipient_name(user_id, binding),
            message_title=title,
            message_content=content,
            push_channel=PUSH_CHANNEL,
            push_status=PUSH_STATUS_PENDING,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def _pushplus_recipient_name(
        self,
        user_id: int,
        binding: PushplusBinding | None,
    ) -> str | None:
        if binding is not None:
            return binding.friend_remark or binding.friend_nick_name or f"好友 {binding.friend_id}"
        user = self.db.get(AppUser, user_id)
        if user is None:
            return "PushPlus 个人账号"
        return user.display_name or user.username or "PushPlus 个人账号"

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

    def _is_default_admin_user(self, user_id: int) -> bool:
        user = self.db.get(AppUser, user_id)
        if user is None or not user.is_active:
            return False
        return user.username == self.settings.default_admin_username

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
        if not content:
            raise NotificationError("PushPlus 回调绑定票据无效")
        parts = content.split(":")
        if len(parts) != 3 or parts[0] != "sapai":
            raise NotificationError("PushPlus 回调绑定票据无效")
        _, user_part, signature = parts
        if not signature:
            raise NotificationError("PushPlus 回调绑定票据签名缺失")
        try:
            user_id = int(user_part)
        except ValueError as exc:
            raise NotificationError("PushPlus 回调绑定票据用户参数无效") from exc
        if user_id <= 0:
            raise NotificationError("PushPlus 回调绑定票据用户参数无效")
        expected = self._qr_signature(user_id)
        if not hmac.compare_digest(signature, expected):
            raise NotificationError("PushPlus 回调绑定票据签名无效")
        return user_id

    def _binding_ticket_for_user(self, user_id: int) -> str:
        return f"sapai:{user_id}:{self._qr_signature(user_id)}"

    def _qr_signature(self, user_id: int) -> str:
        digest = hmac.new(
            self.settings.auth_secret_key.encode("utf-8"),
            f"pushplus-binding:{user_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest[:16]

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _stock_label(self, item: WatchlistStock) -> str:
        return item.display_name or item.a_ts_code

    def _today(self) -> date:
        return datetime.now(LOCAL_TZ).date()

    def _now_local(self) -> datetime:
        return datetime.now(LOCAL_TZ)

    def _now_naive(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
