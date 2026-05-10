from __future__ import annotations

import html
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.notification import (
    LimitUpAnalysisCache,
    XueqiuPublishCredential,
    XueqiuPublishRecord,
)
from app.schemas.xueqiu_publish import (
    XueqiuCredentialRequest,
    XueqiuCredentialSummary,
    XueqiuDraftPreview,
    XueqiuPublishRecordDetail,
    XueqiuPublishRecordItem,
)
from app.services.limit_up_push_service import ANALYSIS_STATUS_READY, LimitUpPushService

logger = logging.getLogger(__name__)

XUEQIU_MODE_DRAFT = "DRAFT"
XUEQIU_MODE_PUBLISH = "PUBLISH"
XUEQIU_STATUS_PENDING = "PENDING"
XUEQIU_STATUS_DRAFTED = "DRAFTED"
XUEQIU_STATUS_PUBLISHED = "PUBLISHED"
XUEQIU_STATUS_FAILED = "FAILED"


class XueqiuPublishError(ValueError):
    """雪球发布业务错误。

    创建日期：2026-05-10
    author: sunshengxian
    """


class XueqiuPublishService:
    """雪球创作者平台长文草稿与发布服务。

    创建日期：2026-05-10
    author: sunshengxian
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def get_credential_summary(self) -> XueqiuCredentialSummary:
        """读取雪球登录态摘要，不返回完整 Cookie。

        创建日期：2026-05-10
        author: sunshengxian
        """

        credential = self._credential_or_none()
        if credential is None:
            return XueqiuCredentialSummary(configured=False)
        return XueqiuCredentialSummary(
            configured=True,
            enabled=credential.enabled,
            cookie_preview=self._cookie_preview(credential.cookie_text),
            user_agent=credential.user_agent,
            mp_base_url=credential.mp_base_url,
            referer_url=credential.referer_url,
            expires_at=credential.expires_at,
            last_verified_at=credential.last_verified_at,
            last_error=credential.last_error,
            updated_at=credential.updated_at,
        )

    def save_credential(
        self,
        payload: XueqiuCredentialRequest,
        user: AppUser,
    ) -> XueqiuCredentialSummary:
        """保存管理员提供的雪球浏览器登录态。

        创建日期：2026-05-10
        author: sunshengxian
        """

        normalized_cookie = self._normalize_cookie(payload.cookie_text)
        user_agent = payload.user_agent.strip() or self.settings.xueqiu_publish_default_user_agent
        credential = self._credential_or_none()
        if credential is None:
            credential = XueqiuPublishCredential(
                enabled=payload.enabled,
                cookie_text=normalized_cookie,
                user_agent=user_agent,
                mp_base_url=self._normalize_base_url(payload.mp_base_url),
                referer_url=payload.referer_url.strip() or "https://mp.xueqiu.com/write/",
                expires_at=payload.expires_at,
                updated_by_user_id=user.id,
            )
            self.db.add(credential)
        else:
            # 更新登录态时重置最近验证错误，避免旧错误继续误导管理员；
            # 真实有效性由“验证登录态”按钮重新确认。
            credential.enabled = payload.enabled
            credential.cookie_text = normalized_cookie
            credential.user_agent = user_agent
            credential.mp_base_url = self._normalize_base_url(payload.mp_base_url)
            credential.referer_url = payload.referer_url.strip() or "https://mp.xueqiu.com/write/"
            credential.expires_at = payload.expires_at
            credential.last_error = None
            credential.updated_by_user_id = user.id
        self.db.commit()
        return self.get_credential_summary()

    def verify_credential(self) -> XueqiuCredentialSummary:
        """用雪球创作者后台页面验证 Cookie 是否仍可用。

        创建日期：2026-05-10
        author: sunshengxian
        """

        credential = self._enabled_credential()
        try:
            with self._client(credential) as client:
                response = client.get(
                    self._url(credential, "/list/article/"),
                    headers=self._headers(credential, referer=credential.referer_url),
                )
            body = response.text[:2000]
            if response.status_code >= 400 or "登录" in body and "article" not in body.lower():
                raise XueqiuPublishError(f"雪球登录态可能已失效，HTTP {response.status_code}")
            credential.last_verified_at = self._now_naive()
            credential.last_error = None
        except Exception as exc:
            credential.last_error = str(exc)
            self.db.commit()
            raise XueqiuPublishError(str(exc)) from exc
        self.db.commit()
        return self.get_credential_summary()

    def preview_latest_report(self, analysis_id: int | None = None) -> XueqiuDraftPreview:
        """预览最新或指定打板报告转换后的雪球长文稿。

        创建日期：2026-05-10
        author: sunshengxian
        """

        analysis = self._resolve_analysis(analysis_id)
        title, content_html = self._build_article(analysis)
        return XueqiuDraftPreview(
            analysis_id=analysis.id,
            trade_date=analysis.trade_date,
            source_title=analysis.title,
            title=title,
            content_html=content_html,
            content_text=self._html_to_text(content_html),
        )

    def save_or_publish_report(
        self,
        analysis_id: int | None,
        publish: bool,
        force: bool,
        cover_pic: str | None,
        user: AppUser | None = None,
    ) -> XueqiuPublishRecord:
        """将打板报告保存为雪球草稿或正式发布。

        创建日期：2026-05-10
        author: sunshengxian
        """

        credential = self._enabled_credential()
        analysis = self._resolve_analysis(analysis_id)
        mode = XUEQIU_MODE_PUBLISH if publish else XUEQIU_MODE_DRAFT
        record = self._get_or_create_record(analysis, mode, cover_pic, user)
        if record.status in {XUEQIU_STATUS_DRAFTED, XUEQIU_STATUS_PUBLISHED} and not force:
            return record
        title, content_html = self._build_article(analysis)
        if force:
            self._reset_remote_identity_for_retry(record)
        record.title = title
        record.content_html = content_html
        record.cover_pic = cover_pic.strip() if cover_pic else None
        record.status = XUEQIU_STATUS_PENDING
        record.error_message = None
        self.db.flush()
        try:
            draft_response = self._save_draft(credential, record)
            draft_id = str(draft_response.get("id") or draft_response.get("draft_id") or "")
            if not draft_id:
                raise XueqiuPublishError("雪球草稿接口未返回 draft id")
            record.draft_id = draft_id
            record.response_json = self._json_dumps({"draft": draft_response})
            if not publish:
                record.status = XUEQIU_STATUS_DRAFTED
                self.db.commit()
                self.db.refresh(record)
                return record
            session_token = self._fetch_session_token(credential, draft_id)
            publish_response = self._publish_status(credential, record, session_token)
            status_id = self._extract_status_id(publish_response)
            record.status = XUEQIU_STATUS_PUBLISHED
            record.status_id = status_id
            record.article_url = self._build_article_url(publish_response, status_id)
            record.response_json = self._json_dumps(
                {"draft": draft_response, "publish": publish_response}
            )
            record.published_at = self._now_naive()
        except Exception as exc:
            record.status = XUEQIU_STATUS_FAILED
            record.error_message = str(exc)
            self.db.commit()
            logger.error(
                "雪球长文发布失败 analysis_id=%s mode=%s",
                analysis.id,
                mode,
                exc_info=True,
            )
            raise XueqiuPublishError(str(exc)) from exc
        self.db.commit()
        self.db.refresh(record)
        return record

    def save_or_publish_latest_by_scheduler(self) -> XueqiuPublishRecord | None:
        """定时任务入口：确保最新报告存在后按配置保存草稿或发布。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if not self.settings.xueqiu_publish_scheduler_enabled:
            return None
        limit_service = LimitUpPushService(self.db, self.settings)
        analysis = limit_service.ensure_analysis_for_trade_date(limit_service.latest_a_trade_date())
        if analysis is None or analysis.status != ANALYSIS_STATUS_READY:
            return None
        return self.save_or_publish_report(
            analysis.id,
            publish=self.settings.xueqiu_publish_auto_publish,
            force=False,
            cover_pic=None,
        )

    def list_records(
        self,
        limit: int = 100,
        status: str | None = None,
    ) -> list[XueqiuPublishRecordItem]:
        """查询雪球发布流水。

        创建日期：2026-05-10
        author: sunshengxian
        """

        statement = (
            select(XueqiuPublishRecord, LimitUpAnalysisCache.trade_date)
            .join(LimitUpAnalysisCache, LimitUpAnalysisCache.id == XueqiuPublishRecord.analysis_id)
            .order_by(desc(XueqiuPublishRecord.id))
            .limit(limit)
        )
        if status:
            statement = statement.where(XueqiuPublishRecord.status == status.strip().upper())
        return [
            self._record_item(record, trade_date)
            for record, trade_date in self.db.execute(statement).all()
        ]

    def get_record(self, record_id: int) -> XueqiuPublishRecordDetail:
        """读取雪球发布流水详情。

        创建日期：2026-05-10
        author: sunshengxian
        """

        row = self.db.execute(
            select(XueqiuPublishRecord, LimitUpAnalysisCache.trade_date)
            .join(LimitUpAnalysisCache, LimitUpAnalysisCache.id == XueqiuPublishRecord.analysis_id)
            .where(XueqiuPublishRecord.id == record_id)
        ).one_or_none()
        if row is None:
            raise XueqiuPublishError("发布记录不存在")
        record, trade_date = row
        item = self._record_item(record, trade_date)
        return XueqiuPublishRecordDetail(
            **item.model_dump(),
            content_html=record.content_html,
            cover_pic=record.cover_pic,
            request_payload_json=record.request_payload_json,
            response_json=record.response_json,
        )

    def _save_draft(
        self,
        credential: XueqiuPublishCredential,
        record: XueqiuPublishRecord,
    ) -> dict[str, Any]:
        """调用雪球自动保存接口生成或更新草稿。

        创建日期：2026-05-10
        author: sunshengxian
        """

        data = {
            "id": record.draft_id or "",
            "text": record.content_html,
            "title": record.title,
            "cover_pic": record.cover_pic or "",
            "flags": "false",
            "original_event": "",
            "status_id": record.status_id or "",
            "legal_user_visible": "false",
        }
        record.request_payload_json = self._json_dumps(self._safe_payload(data))
        return self._post_form(
            credential,
            "/xq/statuses/draft/save.json",
            data,
            credential.referer_url,
        )

    def _fetch_session_token(self, credential: XueqiuPublishCredential, draft_id: str) -> str:
        """获取正式发文所需的短期 session_token。

        创建日期：2026-05-10
        author: sunshengxian
        """

        referer = self._url(credential, f"/write/draft/{draft_id}")
        with self._client(credential) as client:
            response = client.get(
                self._url(
                    credential,
                    "/xq/provider/session/token.json?api_path=%2Fstatuses%2Fupdate.json",
                ),
                headers=self._headers(credential, referer=referer),
            )
        payload = self._parse_response(response)
        token = str(payload.get("session_token") or "")
        if not token:
            raise XueqiuPublishError("雪球 session_token 接口未返回 token")
        return token

    def _publish_status(
        self,
        credential: XueqiuPublishCredential,
        record: XueqiuPublishRecord,
        session_token: str,
    ) -> dict[str, Any]:
        """调用雪球正式发文接口。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if not record.draft_id:
            raise XueqiuPublishError("缺少雪球草稿 id，无法正式发布")
        data = {
            "title": record.title,
            "status": record.content_html,
            "cover_pic": record.cover_pic or "",
            "show_cover_pic": "true" if record.cover_pic else "false",
            "original": "false",
            "industry_category_name": "",
            "original_event_id": "",
            "original_event_active": "true",
            "legal_user_visible": "false",
            "draft_id": record.draft_id,
            "session_token": session_token,
        }
        record.request_payload_json = self._json_dumps(self._safe_payload(data))
        return self._post_form(credential, "/xq/statuses/update.json", data, credential.referer_url)

    def _post_form(
        self,
        credential: XueqiuPublishCredential,
        path: str,
        data: dict[str, str],
        referer: str,
    ) -> dict[str, Any]:
        """以浏览器同源表单请求口径调用雪球接口。

        创建日期：2026-05-10
        author: sunshengxian
        """

        headers = self._headers(
            credential,
            referer=referer,
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
        )
        with self._client(credential) as client:
            response = client.post(self._url(credential, path), headers=headers, data=data)
        return self._parse_response(response)

    def _headers(
        self,
        credential: XueqiuPublishCredential,
        referer: str,
        content_type: str | None = None,
    ) -> dict[str, str]:
        """构造雪球创作者后台正常浏览器请求头。

        创建日期：2026-05-10
        author: sunshengxian
        """

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Cookie": credential.cookie_text,
            "Host": self._host(credential.mp_base_url),
            "Origin": credential.mp_base_url.rstrip("/"),
            "Pragma": "no-cache",
            "Referer": referer,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": credential.user_agent,
            "X-Requested-With": "XMLHttpRequest",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _client(self, credential: XueqiuPublishCredential) -> httpx.Client:
        return httpx.Client(
            timeout=self.settings.xueqiu_publish_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": credential.user_agent},
        )

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise XueqiuPublishError(f"雪球接口 HTTP {response.status_code}: {response.text[:200]}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise XueqiuPublishError(f"雪球接口返回非 JSON: {response.text[:200]}") from exc
        if isinstance(payload, dict) and payload.get("error_code"):
            raise XueqiuPublishError(
                str(payload.get("error_description") or payload.get("error_code"))
            )
        if not isinstance(payload, dict):
            raise XueqiuPublishError("雪球接口返回结构异常")
        return payload

    def _resolve_analysis(self, analysis_id: int | None) -> LimitUpAnalysisCache:
        if analysis_id:
            analysis = self.db.get(LimitUpAnalysisCache, analysis_id)
        else:
            analysis = self.db.scalar(
                select(LimitUpAnalysisCache)
                .where(LimitUpAnalysisCache.status == ANALYSIS_STATUS_READY)
                .order_by(desc(LimitUpAnalysisCache.trade_date), desc(LimitUpAnalysisCache.id))
                .limit(1)
            )
        if (
            analysis is None
            or analysis.status != ANALYSIS_STATUS_READY
            or not analysis.content_html
        ):
            raise XueqiuPublishError("未找到可发布的 READY 打板报告")
        return analysis

    def _get_or_create_record(
        self,
        analysis: LimitUpAnalysisCache,
        mode: str,
        cover_pic: str | None,
        user: AppUser | None,
    ) -> XueqiuPublishRecord:
        title, content_html = self._build_article(analysis)
        record = XueqiuPublishRecord(
            analysis_id=analysis.id,
            publish_mode=mode,
            status=XUEQIU_STATUS_PENDING,
            title=title,
            content_html=content_html,
            cover_pic=cover_pic.strip() if cover_pic else None,
            created_by_user_id=user.id if user else None,
        )
        self.db.add(record)
        try:
            self.db.flush()
            return record
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(XueqiuPublishRecord).where(
                    XueqiuPublishRecord.analysis_id == analysis.id,
                    XueqiuPublishRecord.publish_mode == mode,
                )
            )
            if existing is None:
                raise
            return existing

    def _reset_remote_identity_for_retry(self, record: XueqiuPublishRecord) -> None:
        """强制重试前清理本地保存的雪球远端对象标识。

        创建日期：2026-05-10
        author: sunshengxian
        """

        # 管理员在雪球网页端删除草稿后，本地流水仍会保留旧 draft_id；
        # 强制重试代表远端对象可能已经不可用，因此清空远端 ID，让保存接口重新创建草稿。
        record.draft_id = None
        record.status_id = None
        record.article_url = None
        record.published_at = None
        record.response_json = None

    def _build_article(self, analysis: LimitUpAnalysisCache) -> tuple[str, str]:
        title = f"{analysis.trade_date:%Y-%m-%d} 打板复盘：涨停生态、题材强度与次日观察"
        body = self._unwrap_report_body(analysis.content_html or "")
        disclaimer = (
            "<p><strong>风险提示：</strong>本文为基于公开数据和模型整理的市场复盘，"
            "不构成任何投资建议。短线打板波动剧烈，请结合自身风险承受能力独立判断。</p>"
        )
        return title, f"{body}{disclaimer}"

    def _unwrap_report_body(self, content_html: str) -> str:
        stripped = content_html.strip()
        # PushPlus 报告外层带有展示容器样式，发雪球时只保留正文结构，
        # 避免嵌套大块背景影响编辑器渲染。
        matches = re.findall(r"<div[^>]*>([\s\S]*)</div>", stripped, flags=re.IGNORECASE)
        if len(matches) >= 2:
            stripped = matches[-1].strip()
        stripped = re.sub(r"\sstyle=\"[^\"]*\"", "", stripped)
        stripped = re.sub(r"\sclass=\"[^\"]*\"", "", stripped)
        return stripped

    def _html_to_text(self, content_html: str) -> str:
        text = re.sub(r"<\s*(h[1-6]|p|li|br|tr)[^>]*>", "\n", content_html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _credential_or_none(self) -> XueqiuPublishCredential | None:
        return self.db.scalar(
            select(XueqiuPublishCredential).order_by(desc(XueqiuPublishCredential.id)).limit(1)
        )

    def _enabled_credential(self) -> XueqiuPublishCredential:
        credential = self._credential_or_none()
        if credential is None or not credential.enabled:
            raise XueqiuPublishError("雪球发布登录态未配置或未启用")
        if credential.expires_at and credential.expires_at < self._now_naive():
            raise XueqiuPublishError("雪球发布登录态已过期，请重新保存 Cookie")
        return credential

    def _record_item(self, record: XueqiuPublishRecord, trade_date: Any) -> XueqiuPublishRecordItem:
        return XueqiuPublishRecordItem(
            id=record.id,
            analysis_id=record.analysis_id,
            trade_date=trade_date,
            publish_mode=record.publish_mode,
            status=record.status,
            title=record.title,
            draft_id=record.draft_id,
            status_id=record.status_id,
            article_url=record.article_url,
            error_message=record.error_message,
            published_at=record.published_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _extract_status_id(self, payload: dict[str, Any]) -> str | None:
        for key in ("id", "status_id", "target_id"):
            value = payload.get(key)
            if value:
                return str(value)
        status = payload.get("status")
        if isinstance(status, dict):
            value = status.get("id") or status.get("status_id")
            if value:
                return str(value)
        return None

    def _build_article_url(self, payload: dict[str, Any], status_id: str | None) -> str | None:
        for key in ("url", "target_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        user_id = payload.get("user_id") or payload.get("uid")
        if status_id and user_id:
            return f"https://xueqiu.com/{user_id}/{status_id}"
        if status_id:
            return f"https://xueqiu.com/statuses/{status_id}"
        return None

    def _safe_payload(self, payload: dict[str, str]) -> dict[str, str]:
        return {
            key: ("<hidden>" if key == "session_token" else value)
            for key, value in payload.items()
        }

    def _normalize_cookie(self, cookie: str) -> str:
        normalized = "; ".join(
            part.strip() for part in cookie.replace("\n", ";").split(";") if part.strip()
        )
        if "=" not in normalized:
            raise XueqiuPublishError("Cookie 格式不正确")
        return normalized

    def _cookie_preview(self, cookie: str) -> str:
        names = [part.split("=", 1)[0].strip() for part in cookie.split(";") if "=" in part]
        if not names:
            return "已配置"
        return "；".join(names[:6]) + ("；..." if len(names) > 6 else "")

    def _normalize_base_url(self, value: str) -> str:
        normalized = value.strip().rstrip("/") or "https://mp.xueqiu.com"
        if not normalized.startswith("https://mp.xueqiu.com"):
            raise XueqiuPublishError("仅支持雪球创作者后台域名 https://mp.xueqiu.com")
        return normalized

    def _url(self, credential: XueqiuPublishCredential, path: str) -> str:
        return urljoin(credential.mp_base_url.rstrip("/") + "/", path.lstrip("/"))

    def _host(self, url: str) -> str:
        return url.split("//", 1)[-1].split("/", 1)[0]

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _now_naive(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
