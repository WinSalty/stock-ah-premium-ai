from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings

PUSHPLUS_SUCCESS_CODE = 200
DEFAULT_PAGE_SIZE = 50


class PushplusError(RuntimeError):
    """PushPlus 调用错误。

    创建日期：2026-05-05
    author: sunshengxian
    """


@dataclass(frozen=True)
class PushplusFriend:
    """PushPlus 好友信息。

    创建日期：2026-05-05
    author: sunshengxian
    """

    id: int
    friend_id: int
    token: str
    nick_name: str | None
    remark: str | None
    is_follow: bool
    create_time: str | None


class PushplusClient:
    """PushPlus 好友与消息接口客户端。

    创建日期：2026-05-05
    author: sunshengxian
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.pushplus_base_url.rstrip("/")

    def get_personal_qr_code(
        self,
        content: str,
        expire_seconds: int,
        scan_count: int,
    ) -> str:
        """获取 PushPlus 个人好友二维码图片地址。

        创建日期：2026-05-05
        author: sunshengxian
        """

        access_key = self._get_access_key()
        data = self._request(
            "GET",
            "/api/open/friend/getQrCode",
            headers={"access-key": access_key},
            params={
                "content": content,
                "second": expire_seconds,
                "scanCount": scan_count,
            },
        )
        url = data.get("qrCodeImgUrl") if isinstance(data, dict) else None
        if not url:
            raise PushplusError("PushPlus 未返回二维码地址")
        return str(url)

    def list_friends(
        self,
        current: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[PushplusFriend]:
        """获取 PushPlus 好友列表。

        创建日期：2026-05-05
        author: sunshengxian
        """

        access_key = self._get_access_key()
        data = self._request(
            "POST",
            "/api/open/friend/list",
            headers={"access-key": access_key},
            json={"current": current, "pageSize": page_size},
        )
        rows = data.get("list", []) if isinstance(data, dict) else []
        friends: list[PushplusFriend] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            token = str(row.get("token") or "").strip()
            friend_id = int(row.get("friendId") or 0)
            row_id = int(row.get("id") or 0)
            if not token or not friend_id or not row_id:
                continue
            friends.append(
                PushplusFriend(
                    id=row_id,
                    friend_id=friend_id,
                    token=token,
                    nick_name=self._optional_str(row.get("nickName")),
                    remark=self._optional_str(row.get("remark")),
                    is_follow=int(row.get("isFollow") or 0) == 1,
                    create_time=self._optional_str(row.get("createTime")),
                )
            )
        return friends

    def send_friend_message(self, to_token: str, title: str, content: str) -> str:
        """通过 PushPlus 好友消息发送微信提醒。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if not self.settings.pushplus_enabled:
            raise PushplusError("PushPlus 推送未启用")
        token = self.settings.resolve_pushplus_token()
        if not token:
            raise PushplusError("PushPlus token 未配置")
        data = self._request(
            "POST",
            "/send",
            json={
                "token": token,
                "title": title,
                "content": content,
                "to": to_token,
                "template": self.settings.pushplus_template,
                "channel": self.settings.pushplus_channel,
            },
        )
        return str(data or "")

    def _get_access_key(self) -> str:
        token = self.settings.resolve_pushplus_token()
        secret_key = self.settings.resolve_pushplus_secret_key()
        if not token:
            raise PushplusError("PushPlus token 未配置")
        if not secret_key:
            raise PushplusError("PushPlus secretKey 未配置，无法调用好友开放接口")
        data = self._request(
            "POST",
            "/api/common/openApi/getAccessKey",
            json={"token": token, "secretKey": secret_key},
        )
        access_key = data.get("accessKey") if isinstance(data, dict) else None
        if not access_key:
            raise PushplusError("PushPlus 未返回 AccessKey")
        return str(access_key)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.settings.pushplus_timeout_seconds) as client:
                response = client.request(method, url, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PushplusError("PushPlus 接口调用失败") from exc
        code = payload.get("code") if isinstance(payload, dict) else None
        if code != PUSHPLUS_SUCCESS_CODE:
            message = payload.get("msg") if isinstance(payload, dict) else None
            raise PushplusError(str(message or "PushPlus 返回失败"))
        return payload.get("data") if isinstance(payload, dict) else None

    def _optional_str(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
