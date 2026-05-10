from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.chat import LlmChatMessage, LlmChatSession
from app.db.models.notification import (
    LimitUpAnalysisCache,
    XueqiuPublishCredential,
    XueqiuPublishRecord,
    XueqiuPublishSetting,
)
from app.schemas.xueqiu_publish import (
    XueqiuChatAnswerPublishRequest,
    XueqiuCredentialRequest,
    XueqiuCredentialSummary,
    XueqiuDraftPreview,
    XueqiuPublishRecordDetail,
    XueqiuPublishRecordItem,
    XueqiuPublishSettingRequest,
    XueqiuPublishSettingSummary,
)
from app.services.limit_up_push_service import ANALYSIS_STATUS_READY, LimitUpPushService
from app.services.llm_service import LlmCallTrace, LlmService
from app.services.notification_service import NotificationError, NotificationService

logger = logging.getLogger(__name__)

XUEQIU_MODE_DRAFT = "DRAFT"
XUEQIU_MODE_PUBLISH = "PUBLISH"
XUEQIU_SOURCE_LIMIT_UP_REPORT = "LIMIT_UP_REPORT"
XUEQIU_SOURCE_CHAT_ANSWER = "CHAT_ANSWER"
XUEQIU_STATUS_PENDING = "PENDING"
XUEQIU_STATUS_DRAFTED = "DRAFTED"
XUEQIU_STATUS_PUBLISHED = "PUBLISHED"
XUEQIU_STATUS_FAILED = "FAILED"
XUEQIU_IMAGE_STYLE_SUFFIX_PATTERN = re.compile(r"!(?:\d+\.jpg|[A-Za-z0-9_.,-]+)$")
EAST8_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_XUEQIU_COVER_PIC = "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"
XUEQIU_SCHEDULER_WEEKDAYS = {1, 2, 3, 4, 5}
CHAT_XUEQIU_HTML_SYSTEM_PROMPT = """你是严谨的雪球长文 HTML 排版转换器。
任务：把用户提供的中文 Markdown 投资回答转换成适合雪球长文接口保存的 HTML 片段。

硬性要求：
1. 只输出 HTML 片段，不要输出 Markdown、代码块、解释、DOCTYPE、html/body/head 标签。
2. 保留原回答的标题层级、项目符号、重点加粗、段落和逻辑顺序，不新增投资结论。
3. Markdown 表格禁止转换为 `<table>`，必须改写成 `<h3>` 小标题加 `<ul><li>` 列表；
   每一行用一个 li，表头字段用中文冒号串联。
4. 不要使用 script、style、iframe、form、button、input、svg、canvas、img 或外链资源。
5. 只允许使用 h2/h3/p/strong/em/ul/ol/li/br/hr 标签，禁止使用 table/thead/tbody/tr/th/td。
6. 输出必须是合法闭合 HTML，所有文本内容按原文表达，不要编造数据。
"""
CHAT_XUEQIU_TITLE_SYSTEM_PROMPT = """你是雪球长文标题编辑。
请根据用户提供的投资问答回答，生成一个适合雪球长文的中文短标题。

硬性要求：
1. 只输出标题本身，不要解释，不要加引号，不要 Markdown。
2. 标题必须不超过 50 个汉字或字符。
3. 标题要简短、自然、具体，优先包含核心股票/主题和判断方向。
4. 不要使用夸张营销词，不要编造原文没有的股票、数据或结论。
"""
XUEQIU_TITLE_MAX_LENGTH = 50


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

    def get_publish_setting(self) -> XueqiuPublishSettingSummary:
        """读取雪球发布定时配置。

        创建日期：2026-05-10
        author: sunshengxian
        """

        setting = self._setting_or_create()
        return self._setting_summary(setting)

    def save_publish_setting(
        self,
        payload: XueqiuPublishSettingRequest,
        user: AppUser,
    ) -> XueqiuPublishSettingSummary:
        """保存雪球发布定时配置。

        创建日期：2026-05-10
        author: sunshengxian
        """

        setting = self._setting_or_create()
        setting.scheduler_enabled = payload.scheduler_enabled
        setting.auto_publish = payload.auto_publish
        setting.poll_hours = self._normalize_cron_field(payload.poll_hours, "小时")
        setting.poll_minutes = self._normalize_cron_field(payload.poll_minutes, "分钟")
        setting.default_cover_pic = self._normalize_cover_pic(payload.default_cover_pic)
        setting.updated_by_user_id = user.id
        self.db.commit()
        self.db.refresh(setting)
        return self._setting_summary(setting)

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
        record = self._get_or_create_record(analysis, mode, cover_pic, user, force=force)
        if record.status in {XUEQIU_STATUS_DRAFTED, XUEQIU_STATUS_PUBLISHED} and not force:
            return record
        title, content_html = self._build_article(analysis)
        record.title = title
        record.content_html = content_html
        record.cover_pic = self._normalize_cover_pic(cover_pic)
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
            self._send_admin_failure_alert(record, analysis, mode, exc)
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

    def save_or_publish_chat_answer(
        self,
        payload: XueqiuChatAnswerPublishRequest,
        user: AppUser,
    ) -> XueqiuPublishRecord:
        """将问答回答转换为 HTML 后保存为雪球草稿或正式发布。

        创建日期：2026-05-10
        author: sunshengxian
        """

        credential = self._enabled_credential()
        message = self._chat_answer_message(payload.message_id, user)
        mode = XUEQIU_MODE_PUBLISH if payload.publish else XUEQIU_MODE_DRAFT
        record = self._get_or_create_chat_record(message, payload, user, mode)
        if record.status == XUEQIU_STATUS_PUBLISHED and not payload.force:
            return record
        # 问答草稿允许重复点击“保存草稿”来刷新同一条雪球草稿内容；
        # 只对已发布流水保持幂等返回，避免未勾选强制时重复正式发文。
        title = self._chat_article_title(message, user, payload.title)
        content_html = self._chat_markdown_to_xueqiu_html(message, user)
        record.title = title
        record.content_html = content_html
        record.cover_pic = self._resolve_chat_cover_pic(payload.cover_pic)
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
            if not payload.publish:
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
            self._send_admin_failure_alert(record, None, mode, exc)
            logger.error(
                "问答回答发布雪球失败 message_id=%s mode=%s",
                message.id,
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

        setting = self._setting_or_create()
        if not setting.scheduler_enabled:
            return None
        now = self._now_local()
        today = now.date()
        # 服务层保留周二到周六的二次防线，避免手动触发 job 或 cron 配置漂移时，
        # 把非 T-1 窗口的报告误保存到雪球。
        if not self._scheduler_publish_day(today):
            return None
        if not self._scheduler_time_matches(setting, now):
            return None
        limit_service = LimitUpPushService(self.db, self.settings)
        target_trade_date = limit_service.latest_a_trade_date(today=today)
        analysis = limit_service.ensure_analysis_for_trade_date(target_trade_date)
        if (
            analysis is None
            or analysis.status != ANALYSIS_STATUS_READY
            or not analysis.content_html
            or analysis.trade_date != target_trade_date
        ):
            # 定时发布只认当前东八区日期推导出的最新 T-1 交易日报告；
            # 任何空报告、未生成完成或交易日错配都跳过，等待下一分钟/下次调度重试。
            return None
        return self.save_or_publish_report(
            analysis.id,
            publish=setting.auto_publish,
            force=False,
            cover_pic=setting.default_cover_pic or DEFAULT_XUEQIU_COVER_PIC,
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
            .outerjoin(
                LimitUpAnalysisCache,
                LimitUpAnalysisCache.id == XueqiuPublishRecord.analysis_id,
            )
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
            .outerjoin(
                LimitUpAnalysisCache,
                LimitUpAnalysisCache.id == XueqiuPublishRecord.analysis_id,
            )
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
            # 草稿接口也需要显式声明是否展示封面，否则部分草稿箱列表只保存 URL，
            # 但不会把封面图作为长文封面渲染出来。
            "show_cover_pic": "true" if record.cover_pic else "false",
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
        force: bool = False,
    ) -> XueqiuPublishRecord:
        if not force:
            existing = self._latest_record_for_mode(analysis.id, mode)
            if existing is not None:
                return existing
        title, content_html = self._build_article(analysis)
        record = XueqiuPublishRecord(
            analysis_id=analysis.id,
            source_type=XUEQIU_SOURCE_LIMIT_UP_REPORT,
            publish_mode=mode,
            status=XUEQIU_STATUS_PENDING,
            title=title,
            content_html=content_html,
            cover_pic=self._normalize_cover_pic(cover_pic),
            created_by_user_id=user.id if user else None,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def _get_or_create_chat_record(
        self,
        message: LlmChatMessage,
        payload: XueqiuChatAnswerPublishRequest,
        user: AppUser,
        mode: str,
    ) -> XueqiuPublishRecord:
        """读取或创建问答回答发布流水。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if not payload.force:
            existing = self._latest_chat_record_for_mode(message.id, mode)
            if existing is not None:
                return existing
        # 先用原始 Markdown 占位，真正提交前再由 LLM 转换为雪球 HTML；
        # 这样转换或接口失败时也能保留本次发布尝试的流水。
        record = XueqiuPublishRecord(
            analysis_id=None,
            chat_message_id=message.id,
            source_type=XUEQIU_SOURCE_CHAT_ANSWER,
            publish_mode=mode,
            status=XUEQIU_STATUS_PENDING,
            title=self._fallback_chat_article_title(message, payload.title),
            content_html=message.content,
            cover_pic=self._resolve_chat_cover_pic(payload.cover_pic),
            created_by_user_id=user.id,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def _latest_record_for_mode(
        self,
        analysis_id: int,
        mode: str,
    ) -> XueqiuPublishRecord | None:
        """读取同一报告和发布模式下最近一条流水。

        创建日期：2026-05-10
        author: sunshengxian
        """

        # 默认保存和定时任务只复用最近流水，避免重复提交；强制新建时绕过这里，
        # 让被雪球网页端删除的草稿也能重新创建，并保留旧流水用于审计。
        return self.db.scalar(
            select(XueqiuPublishRecord)
            .where(
                XueqiuPublishRecord.analysis_id == analysis_id,
                XueqiuPublishRecord.publish_mode == mode,
            )
            .order_by(desc(XueqiuPublishRecord.created_at), desc(XueqiuPublishRecord.id))
            .limit(1)
        )

    def _latest_chat_record_for_mode(
        self,
        message_id: int,
        mode: str,
    ) -> XueqiuPublishRecord | None:
        """读取同一问答回答和发布模式下最近一条流水。

        创建日期：2026-05-10
        author: sunshengxian
        """

        # 问答发布默认复用最近流水，避免同一回答反复创建草稿；管理员勾选强制时新增流水，
        # 用于在雪球网页端删除旧草稿后重新生成。
        return self.db.scalar(
            select(XueqiuPublishRecord)
            .where(
                XueqiuPublishRecord.chat_message_id == message_id,
                XueqiuPublishRecord.publish_mode == mode,
            )
            .order_by(desc(XueqiuPublishRecord.created_at), desc(XueqiuPublishRecord.id))
            .limit(1)
        )

    def _build_article(self, analysis: LimitUpAnalysisCache) -> tuple[str, str]:
        title = f"{analysis.trade_date:%Y-%m-%d} 打板复盘：涨停生态、题材强度与次日观察"
        body = self._unwrap_report_body(analysis.content_html or "")
        disclaimer = (
            "<p><strong>风险提示：</strong>本文为基于公开数据和模型整理的市场复盘，"
            "不构成任何投资建议。短线打板波动剧烈，请结合自身风险承受能力独立判断。</p>"
        )
        return title, f"{body}{disclaimer}"

    def _chat_answer_message(self, message_id: int, user: AppUser) -> LlmChatMessage:
        """读取当前用户自己的问答助手回答。

        创建日期：2026-05-10
        author: sunshengxian
        """

        message = self.db.scalar(
            select(LlmChatMessage)
            .join(LlmChatSession, LlmChatSession.id == LlmChatMessage.session_id)
            .where(
                LlmChatMessage.id == message_id,
                LlmChatMessage.role == "assistant",
                LlmChatSession.user_id == user.id,
                LlmChatSession.deleted_at.is_(None),
            )
            .limit(1)
        )
        if message is None or not message.content.strip():
            raise XueqiuPublishError("未找到可发布的问答回答")
        return message

    def _chat_article_title(
        self,
        message: LlmChatMessage,
        user: AppUser,
        custom_title: str | None,
    ) -> str:
        """生成问答回答发布到雪球的 50 字以内标题。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if custom_title and custom_title.strip():
            return self._normalize_xueqiu_title(custom_title)
        try:
            title = LlmService(self.db, self.settings)._chat_completion(
                (
                    "请为下面这段投资问答回答生成一个 50 字以内的雪球长文短标题。\n\n"
                    f"问答回答：\n{message.content[:4000]}"
                ),
                system_prompt=CHAT_XUEQIU_TITLE_SYSTEM_PROMPT,
                model=self.settings.llm_model,
                temperature=0,
                trace=LlmCallTrace(
                    question_id=f"xqt{message.id}",
                    phase="xueqiu_title",
                    user_id=user.id,
                    session_id=message.session_id,
                    conversation_title="问答回答发布雪球标题",
                    user_name=(user.display_name or user.username),
                ),
            )
        except Exception:
            logger.error("问答回答雪球标题生成失败 message_id=%s", message.id, exc_info=True)
            title = self._fallback_chat_article_title(message, None)
        return self._normalize_xueqiu_title(title)

    def _fallback_chat_article_title(
        self,
        message: LlmChatMessage,
        custom_title: str | None,
    ) -> str:
        """生成不依赖外部模型的问答标题兜底。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if custom_title and custom_title.strip():
            return self._normalize_xueqiu_title(custom_title)
        first_heading = re.search(r"^#{1,3}\s+(.+)$", message.content, flags=re.MULTILINE)
        if first_heading:
            return self._normalize_xueqiu_title(first_heading.group(1))
        first_line = next(
            (line.strip() for line in message.content.splitlines() if line.strip()),
            "",
        )
        return self._normalize_xueqiu_title(first_line)

    def _normalize_xueqiu_title(self, title: str | None) -> str:
        """清洗并硬限制雪球标题长度，避免接口 50 字限制报错。

        创建日期：2026-05-10
        author: sunshengxian
        """

        normalized = self._plain_text(title or "").strip(" -_:：，。,.")
        if not normalized:
            normalized = "投资问答复盘"
        return normalized[:XUEQIU_TITLE_MAX_LENGTH]

    def _chat_markdown_to_xueqiu_html(self, message: LlmChatMessage, user: AppUser) -> str:
        """调用 LLM 将问答 Markdown 转为适合雪球长文的 HTML。

        创建日期：2026-05-10
        author: sunshengxian
        """

        prompt = (
            "请将下面 Markdown 投资问答回答转换为雪球长文 HTML 片段。"
            "注意：表格必须改写为 h3 + ul/li 列表，禁止输出 table 标签。\n\n"
            f"Markdown 原文：\n{message.content}"
        )
        html_text = LlmService(self.db, self.settings)._chat_completion(
            prompt,
            system_prompt=CHAT_XUEQIU_HTML_SYSTEM_PROMPT,
            model=self.settings.llm_model,
            temperature=0,
            trace=LlmCallTrace(
                question_id=f"xq{message.id}",
                phase="xueqiu_html_convert",
                user_id=user.id,
                session_id=message.session_id,
                conversation_title="问答回答发布雪球",
                user_name=(user.display_name or user.username),
            ),
        )
        sanitized = self._sanitize_chat_html(html_text)
        if not sanitized:
            raise XueqiuPublishError("LLM 未返回可发布的 HTML 内容")
        if re.search(r"<\s*/?\s*(table|thead|tbody|tr|th|td)\b", sanitized, flags=re.IGNORECASE):
            # 雪球草稿箱会把 table 结构压扁为连续文本；问答发布统一使用段落/列表表达表格，
            # 牺牲一点密度换取草稿箱和正式文章的稳定可读性。
            raise XueqiuPublishError("LLM 返回了雪球草稿箱不稳定支持的 table 标签")
        allowed_tag_pattern = r"<\s*(h2|h3|p|ul|ol|li|br|hr)\b"
        if not re.search(allowed_tag_pattern, sanitized, flags=re.IGNORECASE):
            # 问答发布必须保存 HTML 源码而不是 Markdown 原文；如果模型异常返回纯文本或
            # Markdown，这里直接失败，避免草稿箱继续沉淀不可渲染的旧格式内容。
            raise XueqiuPublishError("LLM 未把问答内容转换为 HTML")
        if self._contains_markdown_table(message.content) and "<li" not in sanitized.lower():
            # 原回答包含 Markdown 表格时，转换结果至少要出现列表行；
            # 否则说明表格信息可能丢失，应失败后让管理员重试。
            raise XueqiuPublishError("LLM 未把 Markdown 表格转换为雪球可读列表")
        return sanitized

    def _resolve_chat_cover_pic(self, cover_pic: str | None) -> str | None:
        """解析问答发布封面，未传入时继承雪球发布页默认封面。

        创建日期：2026-05-10
        author: sunshengxian
        """

        normalized = self._normalize_cover_pic(cover_pic)
        if normalized is not None:
            return normalized
        setting = self._setting_or_create()
        # 问答页只有一个快捷按钮，没有单独封面输入；这里沿用发布页配置，
        # 并允许管理员把默认封面清空来显式发布无封面草稿。
        return self._normalize_cover_pic(setting.default_cover_pic)

    def _contains_markdown_table(self, content: str) -> bool:
        """判断问答原文是否包含 Markdown 表格。

        创建日期：2026-05-10
        author: sunshengxian
        """

        lines = [line.strip() for line in content.splitlines()]
        separator_pattern = r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?"
        for index in range(len(lines) - 1):
            # 只识别标准 Markdown 表头 + 分隔线，避免普通竖线文本误判为表格。
            if "|" in lines[index] and re.fullmatch(separator_pattern, lines[index + 1]):
                return True
        return False

    def _sanitize_chat_html(self, content_html: str) -> str:
        """清理 LLM 转换结果，保留雪球长文可接受的安全 HTML 片段。

        创建日期：2026-05-10
        author: sunshengxian
        """

        cleaned = content_html.strip()
        cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        # HTML 由内部 LLM 根据白名单提示词生成，仍在入库前清掉脚本、样式和交互标签；
        # 表格结构保留为原生 table，便于雪球编辑器按源码渲染。
        cleaned = re.sub(
            r"<\s*(script|style|iframe|form|button|input|svg|canvas|img)[^>]*>[\s\S]*?<\s*/\s*\1\s*>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"<\s*(script|style|iframe|form|button|input|svg|canvas|img)[^>]*?/?>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\son[a-z]+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\sstyle\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _plain_text(self, text: str) -> str:
        """把 Markdown 标记规整为可用标题文本。

        创建日期：2026-05-10
        author: sunshengxian
        """

        without_marks = re.sub(r"[*_`#>\[\]()|]", " ", text)
        return re.sub(r"\s+", " ", without_marks).strip()

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

    def _normalize_cover_pic(self, cover_pic: str | None) -> str | None:
        """规整雪球封面图 URL，去掉网页展示用尺寸后缀。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if not cover_pic:
            return None
        normalized = cover_pic.strip()
        if not normalized:
            return None
        # 雪球正文图片常带 !800.jpg 一类展示尺寸后缀，草稿接口用于封面时可能不接受；
        # 入库和提交前统一还原到原图地址，保留管理员复制现有文章图片地址的便利性。
        return XUEQIU_IMAGE_STYLE_SUFFIX_PATTERN.sub("", normalized)

    def _send_admin_failure_alert(
        self,
        record: XueqiuPublishRecord,
        analysis: LimitUpAnalysisCache | None,
        mode: str,
        exc: Exception,
    ) -> None:
        """雪球发布失败后通过 PushPlus 提醒默认管理员。

        创建日期：2026-05-10
        author: sunshengxian
        """

        admin = self.db.scalar(
            select(AppUser)
            .where(
                AppUser.username == self.settings.default_admin_username,
                AppUser.is_active.is_(True),
            )
            .limit(1)
        )
        if admin is None:
            logger.error("雪球发布失败提醒跳过，默认管理员不存在 record_id=%s", record.id)
            return
        try:
            NotificationService(self.db, self.settings).send_pushplus_message(
                admin.id,
                "雪球长文发布失败",
                self._build_failure_alert_content(record, analysis, mode, exc),
            )
        except NotificationError:
            logger.error("雪球发布失败提醒发送失败 record_id=%s", record.id, exc_info=True)

    def _build_failure_alert_content(
        self,
        record: XueqiuPublishRecord,
        analysis: LimitUpAnalysisCache | None,
        mode: str,
        exc: Exception,
    ) -> str:
        """构造雪球发布失败 PushPlus HTML 内容。

        创建日期：2026-05-10
        author: sunshengxian
        """

        mode_label = "正式发布" if mode == XUEQIU_MODE_PUBLISH else "保存草稿"
        return (
            "<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "line-height:1.7;color:#182230;\">"
            "<h3 style=\"margin:0 0 12px;\">雪球长文发布失败</h3>"
            "<table style=\"width:100%;border-collapse:collapse;font-size:14px;\">"
            f"{self._failure_alert_row('流水 ID', str(record.id))}"
            f"{self._failure_alert_row('来源', self._record_source_label(record))}"
            f"{self._failure_alert_row('报告 ID', str(analysis.id) if analysis else '-')}"
            f"{self._failure_alert_row('交易日', str(analysis.trade_date) if analysis else '-')}"
            f"{self._failure_alert_row('问答消息 ID', str(record.chat_message_id or '-'))}"
            f"{self._failure_alert_row('动作', mode_label)}"
            f"{self._failure_alert_row('标题', record.title)}"
            f"{self._failure_alert_row('失败原因', str(exc))}"
            "</table>"
            "<p style=\"margin:12px 0 0;color:#667085;\">请到后台“雪球发布”菜单查看流水详情，"
            "重新保存 Cookie 或手动强制新建草稿后再试。</p>"
            "</div>"
        )

    def _record_source_label(self, record: XueqiuPublishRecord) -> str:
        """转换雪球流水来源标签。

        创建日期：2026-05-10
        author: sunshengxian
        """

        return "问答回答" if record.source_type == XUEQIU_SOURCE_CHAT_ANSWER else "打板报告"

    def _failure_alert_row(self, label: str, value: str) -> str:
        """生成失败提醒表格行并转义用户可变内容。

        创建日期：2026-05-10
        author: sunshengxian
        """

        return (
            "<tr>"
            "<td style=\"width:28%;padding:8px;border-top:1px solid #eaecf0;"
            "background:#f8fafc;color:#667085;\">"
            f"{html.escape(label)}</td>"
            "<td style=\"padding:8px;border-top:1px solid #eaecf0;color:#182230;\">"
            f"{html.escape(value[:500])}</td>"
            "</tr>"
        )

    def _setting_or_create(self) -> XueqiuPublishSetting:
        """读取或初始化雪球发布页面配置。

        创建日期：2026-05-10
        author: sunshengxian
        """

        setting = self.db.scalar(
            select(XueqiuPublishSetting).order_by(desc(XueqiuPublishSetting.id)).limit(1)
        )
        if setting is not None:
            return setting
        # 老库首次升级后如果没有配置行，使用保守默认值：不开启自动定时、不公开发布，
        # 只预置默认封面，等待管理员在页面确认后再启用任务。
        setting = XueqiuPublishSetting(
            scheduler_enabled=False,
            auto_publish=False,
            poll_hours=self.settings.xueqiu_publish_poll_hours,
            poll_minutes=self.settings.xueqiu_publish_poll_minutes,
            default_cover_pic=self._normalize_cover_pic(
                self.settings.xueqiu_publish_default_cover_pic or DEFAULT_XUEQIU_COVER_PIC
            ),
        )
        self.db.add(setting)
        self.db.flush()
        return setting

    def _setting_summary(self, setting: XueqiuPublishSetting) -> XueqiuPublishSettingSummary:
        """转换雪球发布配置响应，包含进程级调度注册状态。

        创建日期：2026-05-10
        author: sunshengxian
        """

        return XueqiuPublishSettingSummary(
            scheduler_enabled=setting.scheduler_enabled,
            auto_publish=setting.auto_publish,
            poll_hours=setting.poll_hours,
            poll_minutes=setting.poll_minutes,
            default_cover_pic=setting.default_cover_pic,
            effective_scheduler_registered=self.settings.xueqiu_publish_scheduler_enabled,
            updated_at=setting.updated_at,
        )

    def _normalize_cron_field(self, value: str, label: str) -> str:
        """校验页面配置的 cron 小时或分钟字段。

        创建日期：2026-05-10
        author: sunshengxian
        """

        normalized = value.strip()
        if not normalized:
            raise XueqiuPublishError(f"雪球定时{label}不能为空")
        if not re.fullmatch(r"[0-9,*/-]+", normalized):
            raise XueqiuPublishError(f"雪球定时{label}只支持数字、逗号、横线、星号和步长")
        return normalized

    def _scheduler_publish_day(self, today: date) -> bool:
        """判断当天是否允许执行 T-1 打板报告的雪球定时发布。

        创建日期：2026-05-10
        author: sunshengxian
        """

        # Python weekday: 周一为 0，周二到周六对应 1-5；
        # 周一尚无上一个交易日的“本周 T-1”发布窗口，周日也不做自动写入。
        return today.weekday() in XUEQIU_SCHEDULER_WEEKDAYS

    def _scheduler_time_matches(
        self,
        setting: XueqiuPublishSetting,
        now: datetime | None = None,
    ) -> bool:
        """判断当前东八区时间是否命中页面配置的调度时点。

        创建日期：2026-05-10
        author: sunshengxian
        """

        now = now or self._now_local()
        return self._cron_field_matches(setting.poll_hours, now.hour) and self._cron_field_matches(
            setting.poll_minutes,
            now.minute,
        )

    def _cron_field_matches(self, expression: str, value: int) -> bool:
        """匹配简化 cron 字段，支持星号、逗号、范围和步长。

        创建日期：2026-05-10
        author: sunshengxian
        """

        for part in expression.split(","):
            if self._cron_part_matches(part.strip(), value):
                return True
        return False

    def _cron_part_matches(self, part: str, value: int) -> bool:
        """匹配单段 cron 表达式。

        创建日期：2026-05-10
        author: sunshengxian
        """

        if not part:
            return False
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step <= 0:
            return False
        if base == "*":
            return value % step == 0
        if "-" in base:
            start_text, end_text = base.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            return start <= value <= end and (value - start) % step == 0
        return int(base) == value

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
            chat_message_id=record.chat_message_id,
            source_type=record.source_type,
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

    def _now_local(self) -> datetime:
        """返回东八区有时区当前时间，供调度日期和小时分钟共用同一时刻。

        创建日期：2026-05-10
        author: sunshengxian
        """

        return datetime.now(EAST8_TZ)

    def _now_naive(self) -> datetime:
        return self._now_local().replace(tzinfo=None)
