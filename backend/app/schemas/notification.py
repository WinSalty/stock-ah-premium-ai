from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


class PushplusBindingResponse(OrmModel):
    """PushPlus 好友绑定响应，不返回好友 token。

    创建日期：2026-05-05
    author: sunshengxian
    """

    is_bound: bool
    status: str = "NOT_BOUND"
    friend_id: int | None = None
    friend_nick_name: str | None = None
    friend_remark: str | None = None
    is_follow: bool | None = None
    bound_at: datetime | None = None


class AdminPushplusBindingResponse(PushplusBindingResponse):
    """管理员查看 PushPlus 绑定响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    id: int
    user_id: int
    username: str
    is_active: bool


class PushplusQrCodeRequest(BaseModel):
    """PushPlus 好友二维码创建请求。

    创建日期：2026-05-05
    author: sunshengxian
    """

    expire_seconds: int = Field(default=604800, ge=60, le=2592000)
    scan_count: int = Field(default=1, ge=-1, le=999)


class PushplusQrCodeResponse(BaseModel):
    """PushPlus 好友二维码响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    qr_code_img_url: str


class PushplusFriendResponse(BaseModel):
    """PushPlus 好友列表响应，不返回好友 token。

    创建日期：2026-05-05
    author: sunshengxian
    """

    id: int
    friend_id: int
    nick_name: str | None = None
    remark: str | None = None
    is_follow: bool
    create_time: str | None = None


class PushplusCallbackFriendInfo(BaseModel):
    """PushPlus 新增好友回调中的好友信息。

    创建日期：2026-05-05
    author: sunshengxian
    """

    token: str
    friendId: int
    isFollow: int | None = None
    nickName: str | None = None
    havePhone: int | None = None
    createTime: str | None = None
    emailStatus: int | None = None


class PushplusCallbackRequest(BaseModel):
    """PushPlus 回调请求。

    创建日期：2026-05-05
    author: sunshengxian
    """

    event: str
    qrCode: str | None = None
    friendInfo: PushplusCallbackFriendInfo | None = None


class PushplusBindRequest(BaseModel):
    """绑定 PushPlus 好友请求。

    创建日期：2026-05-05
    author: sunshengxian
    """

    friend_id: int


class AdminPushplusBindRequest(PushplusBindRequest):
    """管理员手动绑定系统用户和 PushPlus 好友请求。

    创建日期：2026-05-05
    author: sunshengxian
    """

    user_id: int


class TestPushRequest(BaseModel):
    """测试推送请求。

    创建日期：2026-05-05
    author: sunshengxian
    """

    title: str = Field(default="AH 提醒测试", max_length=128)
    content: str = Field(default="PushPlus 好友消息推送已连通。", max_length=2000)


class TestPushResponse(BaseModel):
    """测试推送响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    ok: bool
    message_id: str | None = None


class AlertEventResponse(OrmModel):
    """提醒事件响应。

    创建日期：2026-05-05
    author: sunshengxian
    """

    id: int
    user_id: int
    watchlist_id: int | None
    event_type: str
    trading_day: date
    metric_direction: str | None
    metric_premium_pct: Decimal | None
    target_premium_pct: Decimal | None
    price_alert_market: str | None
    price_alert_operator: str | None
    price_alert_ts_code: str | None
    last_price: Decimal | None
    target_price: Decimal | None
    message_title: str
    push_status: str
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PushplusMessageLogResponse(OrmModel):
    """管理员查看 PushPlus 推送消息流水。

    创建日期：2026-05-06
    author: sunshengxian
    """

    id: int
    user_id: int
    username: str | None = None
    display_name: str | None = None
    alert_event_id: int | None
    recipient_type: str
    recipient_friend_id: int | None
    recipient_name: str | None
    message_title: str
    message_content: str
    push_channel: str
    push_status: str
    push_message_id: str | None
    error_message: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
