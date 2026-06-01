from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.db.models.market import AStockBasic, ATradeCalendar
from app.db.models.notification import (
    LimitUpPushRecipient,
    NineTurnAnalysisCache,
    NineTurnPushDelivery,
)
from app.schemas.nine_turn_push import (
    NineTurnDeliveryItem,
    NineTurnReportDetail,
    NineTurnReportListItem,
)
from app.services.date_utils import parse_tushare_date
from app.services.limit_up_push_service import (
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_GENERATING,
    ANALYSIS_STATUS_READY,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PENDING,
    DELIVERY_STATUS_SENT,
    DELIVERY_STATUS_SKIPPED,
)
from app.services.llm_metric_definitions import phase_description, phase_label
from app.services.llm_service import LLM_CHAT_TIMEOUT_SECONDS
from app.services.notification_service import NotificationService
from app.services.tushare_client import TushareClient

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
NINE_TURN_REQUIRED_API = "stk_nineturn"
NINE_TURN_FREQ_DAILY = "daily"
NINE_TURN_DELIVERY_KIND_DATA_READY = "DATA_READY"
NINE_TURN_DELIVERY_KIND_MANUAL = "MANUAL"
NINE_TURN_LLM_PHASE = "nine_turn_analysis"
NINE_TURN_LLM_TITLE = "神奇九转推送"
NINE_TURN_FIELDS = (
    "ts_code",
    "trade_date",
    "freq",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
    "up_count",
    "down_count",
    "nine_up_turn",
    "nine_down_turn",
)


class NineTurnPushError(ValueError):
    """神奇九转推送业务错误。

    创建日期：2026-06-01
    author: sunshengxian
    """


class NineTurnPushService:
    """神奇九转数据抓取、LLM 报告、PushPlus 推送和雪球发文编排服务。

    创建日期：2026-06-01
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        tushare_client: TushareClient | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.tushare_client = tushare_client or TushareClient(self.settings)
        self.notification_service = notification_service or NotificationService(db, self.settings)

    def ensure_latest_analysis_push_and_publish(
        self,
    ) -> tuple[NineTurnAnalysisCache | None, int, int | None]:
        """定时入口：数据就绪后生成九转报告、推送打板接收人并同步到雪球。

        创建日期：2026-06-01
        author: sunshengxian
        """

        trade_date = self.latest_a_trade_date()
        analysis = self.ensure_analysis_for_trade_date(trade_date)
        if analysis is None or analysis.status != ANALYSIS_STATUS_READY:
            return analysis, 0, None
        pushed = self.push_report(
            analysis.id,
            NINE_TURN_DELIVERY_KIND_DATA_READY,
            self._data_ready_scheduled_at(trade_date),
        )
        xueqiu_record_id = self.publish_report_to_xueqiu_by_scheduler(analysis.id)
        return analysis, pushed, xueqiu_record_id

    def ensure_analysis_for_trade_date(self, trade_date: date) -> NineTurnAnalysisCache | None:
        """按交易日确保神奇九转报告缓存存在。

        创建日期：2026-06-01
        author: sunshengxian
        """

        snapshot = self._build_context_snapshot(trade_date)
        if not snapshot["data_ready"]:
            logger.info("神奇九转数据尚未就绪 trade_date=%s", trade_date)
            return None
        context = snapshot["context"]
        data_quality = snapshot["data_quality"]
        snapshot_hash = self._snapshot_hash(context)
        existing = self._ready_or_generating_analysis(trade_date, snapshot_hash)
        if existing is not None:
            return existing
        analysis = NineTurnAnalysisCache(
            trade_date=trade_date,
            freq=NINE_TURN_FREQ_DAILY,
            model=self.settings.nine_turn_push_model,
            prompt_version=self.settings.nine_turn_push_prompt_version,
            data_snapshot_hash=snapshot_hash,
            status=ANALYSIS_STATUS_GENERATING,
            title=f"{trade_date:%Y-%m-%d} 神奇九转反转信号复盘",
            context_json=self._json_dumps(context),
            data_quality_json=self._json_dumps(data_quality),
        )
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)
        try:
            content_html, content_markdown = self._generate_llm_report(context)
        except Exception as exc:
            analysis.status = ANALYSIS_STATUS_FAILED
            analysis.error_message = str(exc)[:1000]
            self.db.commit()
            logger.error("神奇九转 LLM 报告生成失败 trade_date=%s", trade_date, exc_info=True)
            raise
        analysis.content_html = content_html
        analysis.content_markdown = content_markdown
        analysis.status = ANALYSIS_STATUS_READY
        analysis.generated_at = self._now_naive()
        analysis.error_message = None
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def push_report(
        self,
        analysis_id: int,
        scheduled_kind: str,
        scheduled_at: datetime,
        target_user_ids: list[int] | None = None,
    ) -> int:
        """按打板推送接收人名单推送指定九转报告。

        创建日期：2026-06-01
        author: sunshengxian
        """

        analysis = self.db.get(NineTurnAnalysisCache, analysis_id)
        if (
            analysis is None
            or analysis.status != ANALYSIS_STATUS_READY
            or not analysis.content_html
        ):
            raise NineTurnPushError("报告不存在或尚未生成完成")
        recipients = self._enabled_limit_up_recipients(target_user_ids)
        if target_user_ids is not None and not recipients:
            raise NineTurnPushError("请选择已配置且启用的打板推送接收人")
        pushed = 0
        for recipient in recipients:
            delivery = self._get_or_create_delivery(
                analysis, recipient.user_id, scheduled_kind, scheduled_at
            )
            if delivery.status == DELIVERY_STATUS_SENT:
                continue
            if not self.notification_service.can_send_pushplus_to_user(recipient.user_id):
                delivery.status = DELIVERY_STATUS_SKIPPED
                delivery.error_message = "用户未绑定 PushPlus，且不是默认管理员个人通道"
                self.db.commit()
                continue
            try:
                message_id = self.notification_service.send_pushplus_message(
                    recipient.user_id,
                    analysis.title,
                    analysis.content_html,
                )
                log_id = self._latest_pushplus_log_id(recipient.user_id, message_id)
            except Exception as exc:
                delivery.status = DELIVERY_STATUS_FAILED
                delivery.error_message = str(exc)[:1000]
                self.db.commit()
                continue
            delivery.status = DELIVERY_STATUS_SENT
            delivery.pushplus_message_log_id = log_id
            delivery.sent_at = self._now_naive()
            delivery.error_message = None
            self.db.commit()
            pushed += 1
        return pushed

    def publish_report_to_xueqiu_by_scheduler(self, analysis_id: int) -> int | None:
        """按雪球配置将九转报告保存草稿或正式发布，九转报告不附带封面图。

        创建日期：2026-06-01
        author: sunshengxian
        """

        from app.services.xueqiu_publish_service import XueqiuPublishError, XueqiuPublishService

        try:
            record = XueqiuPublishService(
                self.db, self.settings
            ).save_or_publish_nine_turn_report_by_scheduler(analysis_id)
        except XueqiuPublishError as exc:
            logger.error("神奇九转雪球发文失败 analysis_id=%s error=%s", analysis_id, exc)
            return None
        return record.id if record is not None else None

    def list_reports(
        self,
        limit: int = 30,
        keyword: str | None = None,
        status: str | None = None,
        trade_date: date | None = None,
    ) -> list[NineTurnReportListItem]:
        """查询神奇九转报告列表。

        创建日期：2026-06-01
        author: sunshengxian
        """

        statement = select(NineTurnAnalysisCache)
        normalized_keyword = self._normalize_optional_text(keyword)
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            statement = statement.where(
                or_(
                    NineTurnAnalysisCache.title.like(like_keyword),
                    NineTurnAnalysisCache.content_html.like(like_keyword),
                    NineTurnAnalysisCache.content_markdown.like(like_keyword),
                    NineTurnAnalysisCache.data_quality_json.like(like_keyword),
                )
            )
        normalized_status = self._normalize_optional_text(status)
        if normalized_status:
            statement = statement.where(NineTurnAnalysisCache.status == normalized_status.upper())
        if trade_date is not None:
            statement = statement.where(NineTurnAnalysisCache.trade_date == trade_date)
        rows = self.db.scalars(
            statement.order_by(
                desc(NineTurnAnalysisCache.trade_date), desc(NineTurnAnalysisCache.id)
            ).limit(limit)
        ).all()
        return [self._report_list_item(row) for row in rows]

    def get_report(self, report_id: int) -> NineTurnReportDetail:
        """读取单份神奇九转报告详情。

        创建日期：2026-06-01
        author: sunshengxian
        """

        report = self.db.get(NineTurnAnalysisCache, report_id)
        if report is None:
            raise NineTurnPushError("报告不存在")
        return NineTurnReportDetail(
            **self._report_list_item(report).model_dump(),
            content_html=report.content_html,
            content_markdown=report.content_markdown,
            context=self._json_loads_dict(report.context_json),
            data_quality=self._json_loads_list(report.data_quality_json),
        )

    def list_deliveries(
        self,
        limit: int = 100,
        keyword: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
    ) -> list[NineTurnDeliveryItem]:
        """查询神奇九转报告业务推送流水。

        创建日期：2026-06-01
        author: sunshengxian
        """

        statement = (
            select(NineTurnPushDelivery, NineTurnAnalysisCache, AppUser)
            .join(
                NineTurnAnalysisCache, NineTurnAnalysisCache.id == NineTurnPushDelivery.analysis_id
            )
            .join(AppUser, AppUser.id == NineTurnPushDelivery.user_id)
        )
        normalized_keyword = self._normalize_optional_text(keyword)
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            statement = statement.where(
                or_(
                    NineTurnAnalysisCache.title.like(like_keyword),
                    NineTurnPushDelivery.scheduled_kind.like(like_keyword),
                    NineTurnPushDelivery.error_message.like(like_keyword),
                    AppUser.username.like(like_keyword),
                    AppUser.display_name.like(like_keyword),
                )
            )
        normalized_status = self._normalize_optional_text(status)
        if normalized_status:
            statement = statement.where(NineTurnPushDelivery.status == normalized_status.upper())
        if user_id is not None:
            statement = statement.where(NineTurnPushDelivery.user_id == user_id)
        rows = self.db.execute(statement.order_by(desc(NineTurnPushDelivery.id)).limit(limit)).all()
        return [
            NineTurnDeliveryItem(
                id=delivery.id,
                analysis_id=delivery.analysis_id,
                trade_date=analysis.trade_date,
                user_id=delivery.user_id,
                username=user.username,
                display_name=user.display_name,
                scheduled_kind=delivery.scheduled_kind,
                scheduled_at=delivery.scheduled_at,
                status=delivery.status,
                pushplus_message_log_id=delivery.pushplus_message_log_id,
                error_message=delivery.error_message,
                sent_at=delivery.sent_at,
                created_at=delivery.created_at,
                updated_at=delivery.updated_at,
            )
            for delivery, analysis, user in rows
        ]

    def latest_a_trade_date(self, today: date | None = None) -> date:
        """读取不晚于今天的最近 A 股交易日，匹配九转当日晚间更新口径。

        创建日期：2026-06-01
        author: sunshengxian
        """

        today = today or self._today_local()
        trade_date = self.db.scalar(
            select(ATradeCalendar.cal_date)
            .where(ATradeCalendar.cal_date <= today, ATradeCalendar.is_open == 1)
            .order_by(desc(ATradeCalendar.cal_date))
            .limit(1)
        )
        return trade_date or today

    def _build_context_snapshot(self, trade_date: date) -> dict[str, Any]:
        quality: list[dict[str, Any]] = []
        rows = self._query_nine_turn_rows(trade_date, quality)
        if not rows:
            return {"data_ready": False, "context": {}, "data_quality": quality}
        rows = self._attach_stock_names(rows)
        signal_rows = [row for row in rows if self._is_turn_signal(row)]
        watch_rows = [
            row for row in rows if not self._is_turn_signal(row) and self._is_watch_signal(row)
        ]
        context = {
            "trade_date": trade_date.isoformat(),
            "freq": NINE_TURN_FREQ_DAILY,
            "data_sources": [NINE_TURN_REQUIRED_API],
            "summary": self._summary(rows, signal_rows, watch_rows),
            "nine_up_turns": self._sort_signal_rows(
                [row for row in signal_rows if row.get("nine_up_turn")]
            ),
            "nine_down_turns": self._sort_signal_rows(
                [row for row in signal_rows if row.get("nine_down_turn")]
            ),
            "watch_list": self._sort_watch_rows(watch_rows)[
                : self.settings.nine_turn_context_watch_limit
            ],
            "sample_size": len(rows),
            "data_quality": quality,
            "analysis_instructions": {
                "focus": (
                    "把上九转视为短线高位衰竭/兑现风险线索，把下九转视为"
                    "超跌反弹观察线索，同时结合价格位置、成交额和临近九转做分层判断。"
                ),
                "risk": ("九转是技术信号，不是单独买卖点；必须写清二次确认条件和失败信号。"),
            },
        }
        return {"data_ready": True, "context": context, "data_quality": quality}

    def _query_nine_turn_rows(
        self, trade_date: date, quality: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # Tushare 文档要求 stk_nineturn 单次最多 10000 行；A 股日频全市场通常低于该上限，
        # 因此按交易日一次拉取完整日频快照，若为空则视为 21 点后数据尚未落地并等待下次轮询。
        params = {
            "trade_date": f"{trade_date:%Y-%m-%d} 00:00:00",
            "freq": NINE_TURN_FREQ_DAILY,
        }
        try:
            result = self.tushare_client.query(
                NINE_TURN_REQUIRED_API, params=params, fields=list(NINE_TURN_FIELDS)
            )
        except Exception as exc:
            quality.append(
                {
                    "api_name": NINE_TURN_REQUIRED_API,
                    "status": "FAILED",
                    "row_count": 0,
                    "message": str(exc)[:300],
                }
            )
            return []
        rows = [self._normalize_api_row(row) for row in result.rows]
        quality.append(
            {
                "api_name": NINE_TURN_REQUIRED_API,
                "status": "OK" if rows else "EMPTY",
                "row_count": len(rows),
                "message": "freq=daily",
            }
        )
        return rows

    def _attach_stock_names(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ts_codes = sorted({str(row.get("ts_code") or "") for row in rows if row.get("ts_code")})
        if not ts_codes:
            return rows
        # 九转接口本身不返回股票名称；本地股票基础表只按代码批量补名称，
        # 避免为了展示名称逐股调用外部接口。
        basics = {
            item.ts_code: item.name
            for item in self.db.scalars(
                select(AStockBasic).where(AStockBasic.ts_code.in_(ts_codes))
            ).all()
        }
        for row in rows:
            row["name"] = basics.get(str(row.get("ts_code") or ""), "")
        return rows

    def _summary(
        self,
        rows: list[dict[str, Any]],
        signal_rows: list[dict[str, Any]],
        watch_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        up_turns = [row for row in signal_rows if row.get("nine_up_turn")]
        down_turns = [row for row in signal_rows if row.get("nine_down_turn")]
        up_watch = [row for row in watch_rows if self._numeric(row.get("up_count")) >= 7]
        down_watch = [row for row in watch_rows if self._numeric(row.get("down_count")) >= 7]
        return {
            "total_rows": len(rows),
            "nine_up_turn_count": len(up_turns),
            "nine_down_turn_count": len(down_turns),
            "up_count_7_8_count": len(up_watch),
            "down_count_7_8_count": len(down_watch),
            "largest_amount_signals": self._top_amount(signal_rows, 20),
        }

    def _is_turn_signal(self, row: dict[str, Any]) -> bool:
        return bool(row.get("nine_up_turn") or row.get("nine_down_turn"))

    def _is_watch_signal(self, row: dict[str, Any]) -> bool:
        return self._numeric(row.get("up_count")) >= 7 or self._numeric(row.get("down_count")) >= 7

    def _sort_signal_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda row: self._numeric(row.get("amount")), reverse=True)[
            : self.settings.nine_turn_context_signal_limit
        ]

    def _sort_watch_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                max(self._numeric(row.get("up_count")), self._numeric(row.get("down_count"))),
                self._numeric(row.get("amount")),
            ),
            reverse=True,
        )

    def _top_amount(self, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        return self._sort_signal_rows(rows)[:limit]

    def _generate_llm_report(self, context: dict[str, Any]) -> tuple[str, str]:
        system_prompt = self._nine_turn_system_prompt()
        prompt = self._nine_turn_user_prompt(context)
        markdown = self._chat_completion_with_reasoning(prompt, system_prompt)
        html_content = self._normalize_report_html(markdown)
        return html_content, markdown

    def _chat_completion_with_reasoning(self, prompt: str, system_prompt: str) -> str:
        # 九转报告使用独立模型配置，避免调整短线技术报告时影响普通问答或打板报告；
        # 请求载荷记录到 LLM 耗时表，便于后续排查提示词版本和数据快照。
        api_key = self.settings.resolve_llm_api_key()
        if not api_key:
            raise NineTurnPushError("DeepSeek API Key 未配置")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.nine_turn_push_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "reasoning_effort": self.settings.nine_turn_push_reasoning_effort,
        }
        request_payload_json = self._json_dumps(payload)
        question_id = uuid4().hex
        started_at = perf_counter()
        try:
            with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS * 2) as client:
                response = client.post(
                    url, headers={"Authorization": f"Bearer {api_key}"}, json=payload
                )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except Exception as exc:
            self._record_llm_metric(
                question_id, False, started_at, request_payload_json, None, str(exc)[:500]
            )
            raise
        self._record_llm_metric(question_id, True, started_at, request_payload_json, content, None)
        return str(content or "")

    def _record_llm_metric(
        self,
        question_id: str,
        success: bool,
        started_at: float,
        request_payload_json: str,
        response_content: str | None,
        error_message: str | None,
    ) -> None:
        metric = LlmCallMetric(
            question_id=question_id,
            conversation_title=NINE_TURN_LLM_TITLE,
            phase=NINE_TURN_LLM_PHASE,
            phase_label=phase_label(NINE_TURN_LLM_PHASE),
            phase_description=phase_description(NINE_TURN_LLM_PHASE),
            provider="DeepSeek",
            model=self.settings.nine_turn_push_model,
            success=1 if success else 0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            output_chars=len(response_content or ""),
            request_payload_json=request_payload_json,
            response_content=response_content,
            error_message=error_message,
        )
        self.db.add(metric)
        self.db.commit()

    def _nine_turn_system_prompt(self) -> str:
        """生成神奇九转报告系统提示词。

        创建日期：2026-06-01
        author: sunshengxian
        """

        return """
你是专注 A 股技术面、趋势衰竭和反转信号的短线复盘分析师。
你会阅读系统提供的神奇九转结构化数据，输出适合 PushPlus 和雪球长文阅读的中文 HTML 报告。

要求：
1. 先给出当日九转信号总览，区分“上九转”“下九转”和 7/8 临近九转观察池。
2. 上九转要重点分析高位兑现、趋势衰竭和需要规避追高的条件；
   下九转要重点分析超跌修复、止跌确认和左侧试错边界。
3. 必须列出“上九转重点股”“下九转重点股”“临近九转观察池”三个小节；
   如果某类为空，也要说明数据为空和可能含义。
4. 个股分析不要机械买卖建议，要给出二次确认条件、失败信号、观察优先级和隔日跟踪口径。
5. 不编造材料中没有的精确数值；数据缺失时说明不确定性，不要假装已经看到。
6. 输出纯 HTML 片段，不要 Markdown 代码块，不要包裹 html/body 标签。
7. HTML 需要适合微信和雪球阅读：使用 h2/h3、p、ul、ol、table、strong，避免脚本、外链样式和图片。
""".strip()

    def _nine_turn_user_prompt(self, context: dict[str, Any]) -> str:
        """生成包含交易日结构化上下文的用户提示词。

        创建日期：2026-06-01
        author: sunshengxian
        """

        return (
            "请基于以下神奇九转数据生成完整复盘报告。重点解释上九转/下九转信号的短线含义、"
            "优先观察对象、二次确认条件、失败信号和隔日跟踪计划。\n\n"
            f"结构化数据：\n{self._json_dumps(context)}"
        )

    def _normalize_report_html(self, content: str) -> str:
        stripped = content.strip()
        stripped = re.sub(r"^```(?:html)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        if "<" in stripped and ">" in stripped:
            return self._wrap_html(stripped)
        return self._wrap_html(
            "<p>" + html.escape(stripped).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        )

    def _wrap_html(self, body: str) -> str:
        return (
            "<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            'line-height:1.72;color:#14202e;background:#f6f8fb;padding:14px;">'
            '<div style="max-width:760px;margin:0 auto;background:#fff;border:1px solid #dfe6ef;'
            'border-radius:10px;padding:18px;">'
            f"{body}"
            "</div></div>"
        )

    def _ready_or_generating_analysis(
        self, trade_date: date, snapshot_hash: str
    ) -> NineTurnAnalysisCache | None:
        return self.db.scalar(
            select(NineTurnAnalysisCache)
            .where(
                NineTurnAnalysisCache.trade_date == trade_date,
                NineTurnAnalysisCache.freq == NINE_TURN_FREQ_DAILY,
                NineTurnAnalysisCache.model == self.settings.nine_turn_push_model,
                NineTurnAnalysisCache.prompt_version == self.settings.nine_turn_push_prompt_version,
                NineTurnAnalysisCache.data_snapshot_hash == snapshot_hash,
                NineTurnAnalysisCache.status.in_(
                    [ANALYSIS_STATUS_READY, ANALYSIS_STATUS_GENERATING]
                ),
            )
            .order_by(desc(NineTurnAnalysisCache.id))
            .limit(1)
        )

    def _enabled_limit_up_recipients(
        self, target_user_ids: list[int] | None = None
    ) -> list[LimitUpPushRecipient]:
        statement = select(LimitUpPushRecipient).where(LimitUpPushRecipient.enabled.is_(True))
        if target_user_ids is not None:
            unique_ids = sorted({user_id for user_id in target_user_ids if user_id > 0})
            if not unique_ids:
                return []
            statement = statement.where(LimitUpPushRecipient.user_id.in_(unique_ids))
        # 九转报告明确复用打板推送名单，接收人停用、换绑或权限变化都由打板推送配置统一控制。
        return list(self.db.scalars(statement.order_by(LimitUpPushRecipient.id)).all())

    def _get_or_create_delivery(
        self,
        analysis: NineTurnAnalysisCache,
        user_id: int,
        scheduled_kind: str,
        scheduled_at: datetime,
    ) -> NineTurnPushDelivery:
        delivery = NineTurnPushDelivery(
            analysis_id=analysis.id,
            user_id=user_id,
            scheduled_kind=scheduled_kind,
            scheduled_at=scheduled_at,
            status=DELIVERY_STATUS_PENDING,
        )
        self.db.add(delivery)
        try:
            self.db.commit()
            self.db.refresh(delivery)
            return delivery
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(NineTurnPushDelivery).where(
                    NineTurnPushDelivery.analysis_id == analysis.id,
                    NineTurnPushDelivery.user_id == user_id,
                    NineTurnPushDelivery.scheduled_kind == scheduled_kind,
                    NineTurnPushDelivery.scheduled_at == scheduled_at,
                )
            )
            if existing is None:
                raise
            return existing

    def _latest_pushplus_log_id(self, user_id: int, message_id: str) -> int | None:
        from app.db.models.notification import PushplusMessageLog

        return self.db.scalar(
            select(PushplusMessageLog.id)
            .where(
                PushplusMessageLog.user_id == user_id,
                PushplusMessageLog.push_message_id == message_id,
            )
            .order_by(desc(PushplusMessageLog.id))
            .limit(1)
        )

    def _report_list_item(self, report: NineTurnAnalysisCache) -> NineTurnReportListItem:
        return NineTurnReportListItem(
            id=report.id,
            trade_date=report.trade_date,
            freq=report.freq,
            title=report.title,
            status=report.status,
            model=report.model,
            prompt_version=report.prompt_version,
            data_snapshot_hash=report.data_snapshot_hash,
            generated_at=report.generated_at,
            created_at=report.created_at,
            updated_at=report.updated_at,
            error_message=report.error_message,
        )

    def _normalize_api_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                normalized[key] = self._decimal_to_float(value)
            elif hasattr(value, "item"):
                normalized[key] = value.item()
            elif isinstance(value, date):
                normalized[key] = value.isoformat()
            else:
                normalized[key] = value
        if "trade_date" in normalized:
            parsed = self._parse_nine_turn_trade_date(normalized.get("trade_date"))
            normalized["trade_date"] = (
                parsed.isoformat() if parsed else normalized.get("trade_date")
            )
        return normalized

    def _parse_nine_turn_trade_date(self, value: Any) -> date | None:
        """兼容 stk_nineturn 返回的 YYYYMMDD 或带时分秒日期。

        创建日期：2026-06-01
        author: sunshengxian
        """

        if isinstance(value, str) and "-" in value:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                return None
        return parse_tushare_date(value)

    def _snapshot_hash(self, context: dict[str, Any]) -> str:
        return hashlib.sha256(self._json_dumps(context).encode("utf-8")).hexdigest()

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _json_loads_dict(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _json_loads_list(self, value: str | None) -> list[dict[str, Any]]:
        if not value:
            return []
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _numeric(self, value: Any) -> float:
        if value is None or value == "":
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _decimal_to_float(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    def _today_local(self) -> date:
        return datetime.now(LOCAL_TZ).date()

    def _now_naive(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def _data_ready_scheduled_at(self, trade_date: date) -> datetime:
        return datetime.combine(trade_date, time(21, 10))
