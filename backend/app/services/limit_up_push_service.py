from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
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
from app.db.models.market import ADailyBasic, ADailyQuote, ATradeCalendar
from app.db.models.notification import (
    LimitUpAnalysisCache,
    LimitUpPushDelivery,
    LimitUpPushRecipient,
    PushplusBinding,
)
from app.schemas.limit_up_push import (
    LimitUpDeliveryItem,
    LimitUpRecipientItem,
    LimitUpRecipientUpdateRequest,
    LimitUpReportDetail,
    LimitUpReportListItem,
)
from app.services.date_utils import format_tushare_date, parse_tushare_date
from app.services.decimal_utils import to_decimal
from app.services.llm_metric_definitions import phase_description, phase_label
from app.services.llm_service import LLM_CHAT_TIMEOUT_SECONDS
from app.services.notification_service import NotificationService
from app.services.tushare_client import TushareClient

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ANALYSIS_STATUS_PENDING = "PENDING"
ANALYSIS_STATUS_GENERATING = "GENERATING"
ANALYSIS_STATUS_READY = "READY"
ANALYSIS_STATUS_FAILED = "FAILED"
DELIVERY_STATUS_PENDING = "PENDING"
DELIVERY_STATUS_SENT = "SENT"
DELIVERY_STATUS_FAILED = "FAILED"
DELIVERY_STATUS_SKIPPED = "SKIPPED"
DELIVERY_KIND_DATA_READY = "DATA_READY"
DELIVERY_KIND_SATURDAY_REPLAY = "SATURDAY_REPLAY"
DELIVERY_KIND_SUNDAY_REPLAY = "SUNDAY_REPLAY"
DELIVERY_KIND_MANUAL = "MANUAL"
LIMIT_UP_LLM_PHASE = "limit_up_analysis"
LIMIT_UP_LLM_TITLE = "打板数据推送"
KPL_REQUIRED_API = "kpl_list"
OPTIONAL_APIS: tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...] = (
    (
        "limit_list_ths",
        {},
        (
            "trade_date",
            "ts_code",
            "name",
            "price",
            "pct_chg",
            "open_num",
            "lu_desc",
            "limit_type",
            "tag",
            "status",
            "limit_order",
            "limit_amount",
            "amount",
            "turnover_rate",
            "free_float",
            "lu_limit_order",
            "limit_up_suc_rate",
            "turnover",
            "market_type",
        ),
    ),
    (
        "limit_list_d",
        {},
        (
            "trade_date",
            "ts_code",
            "name",
            "industry",
            "close",
            "pct_chg",
            "amount",
            "limit_amount",
            "float_mv",
            "turnover_ratio",
            "fd_amount",
            "first_time",
            "last_time",
            "open_times",
            "up_stat",
            "limit_times",
        ),
    ),
    (
        "limit_step",
        {},
        ("trade_date", "ts_code", "name", "nums"),
    ),
    (
        "limit_cpt_list",
        {},
        (
            "trade_date",
            "name",
            "days",
            "up_stat",
            "cons_nums",
            "up_nums",
            "pct_chg",
            "rank",
            "top_stock",
        ),
    ),
    (
        "top_list",
        {},
        (
            "trade_date",
            "ts_code",
            "name",
            "close",
            "pct_change",
            "turnover_rate",
            "amount",
            "l_sell",
            "l_buy",
            "l_amount",
            "net_amount",
            "net_rate",
            "amount_rate",
            "float_values",
            "reason",
        ),
    ),
)
KPL_FIELDS = (
    "ts_code",
    "name",
    "trade_date",
    "lu_time",
    "ld_time",
    "open_time",
    "last_time",
    "lu_desc",
    "tag",
    "theme",
    "net_change",
    "bid_amount",
    "status",
    "bid_change",
    "bid_turnover",
    "lu_bid_vol",
    "pct_chg",
    "bid_pct_chg",
    "rt_pct_chg",
    "limit_order",
    "amount",
    "turnover_rate",
    "free_float",
    "lu_limit_order",
)
DAILY_FIELDS = ("ts_code", "trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount")
DAILY_BASIC_FIELDS = ("ts_code", "trade_date", "turnover_rate", "volume_ratio", "total_mv", "circ_mv")


class LimitUpPushError(ValueError):
    """打板推送业务错误。

    创建日期：2026-05-08
    author: sunshengxian
    """


@dataclass(frozen=True)
class DataQualityItem:
    """打板数据接口质量记录。

    创建日期：2026-05-08
    author: sunshengxian
    """

    api_name: str
    status: str
    row_count: int = 0
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "status": self.status,
            "row_count": self.row_count,
            "message": self.message,
        }


class LimitUpPushService:
    """打板数据抓取、LLM 报告缓存和 PushPlus 推送服务。

    创建日期：2026-05-08
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

    def ensure_latest_analysis_and_push(self) -> tuple[LimitUpAnalysisCache | None, int]:
        """在 KPL 最新交易日数据可用后生成报告并立即推送。

        创建日期：2026-05-08
        author: sunshengxian
        """

        trade_date = self.latest_a_trade_date()
        analysis = self.ensure_analysis_for_trade_date(trade_date)
        if analysis is None or analysis.status != ANALYSIS_STATUS_READY:
            return analysis, 0
        return analysis, self.push_report(
            analysis.id,
            DELIVERY_KIND_DATA_READY,
            self._data_ready_scheduled_at(trade_date),
        )

    def ensure_analysis_for_trade_date(self, trade_date: date) -> LimitUpAnalysisCache | None:
        """按交易日确保打板报告缓存存在。

        创建日期：2026-05-08
        author: sunshengxian
        """

        snapshot = self._build_context_snapshot(trade_date)
        if not snapshot["data_ready"]:
            logger.info("KPL 打板数据尚未就绪 trade_date=%s", trade_date)
            return None
        context = snapshot["context"]
        data_quality = snapshot["data_quality"]
        snapshot_hash = self._snapshot_hash(context)
        existing = self._ready_or_generating_analysis(trade_date, snapshot_hash)
        if existing is not None:
            return existing
        analysis = LimitUpAnalysisCache(
            trade_date=trade_date,
            model=self.settings.limit_up_push_model,
            prompt_version=self.settings.limit_up_push_prompt_version,
            data_snapshot_hash=snapshot_hash,
            status=ANALYSIS_STATUS_GENERATING,
            title=f"{trade_date:%Y-%m-%d} A股涨停打板复盘",
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
            logger.error("打板 LLM 报告生成失败 trade_date=%s", trade_date, exc_info=True)
            raise
        analysis.content_html = content_html
        analysis.content_markdown = content_markdown
        analysis.status = ANALYSIS_STATUS_READY
        analysis.generated_at = self._now_naive()
        analysis.error_message = None
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def push_report(self, analysis_id: int, scheduled_kind: str, scheduled_at: datetime) -> int:
        """向所有启用接收人推送指定报告。

        创建日期：2026-05-08
        author: sunshengxian
        """

        analysis = self.db.get(LimitUpAnalysisCache, analysis_id)
        if analysis is None or analysis.status != ANALYSIS_STATUS_READY or not analysis.content_html:
            raise LimitUpPushError("报告不存在或尚未生成完成")
        recipients = self._enabled_recipients()
        pushed = 0
        for recipient in recipients:
            delivery = self._get_or_create_delivery(
                analysis,
                recipient.user_id,
                scheduled_kind,
                scheduled_at,
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

    def push_weekend_replay(self) -> tuple[LimitUpAnalysisCache | None, int]:
        """周六和周日复推最近一个周五交易日的缓存报告。

        创建日期：2026-05-08
        author: sunshengxian
        """

        today = self._today_local()
        if today.weekday() not in {5, 6}:
            return None, 0
        friday = today - timedelta(days=today.weekday() - 4)
        analysis = self._latest_ready_analysis(friday)
        if analysis is None:
            analysis = self.ensure_analysis_for_trade_date(friday)
        if analysis is None or analysis.status != ANALYSIS_STATUS_READY:
            return analysis, 0
        kind = DELIVERY_KIND_SATURDAY_REPLAY if today.weekday() == 5 else DELIVERY_KIND_SUNDAY_REPLAY
        return analysis, self.push_report(analysis.id, kind, self._weekend_replay_scheduled_at(today))

    def list_reports(
        self,
        limit: int = 30,
        keyword: str | None = None,
        status: str | None = None,
        trade_date: date | None = None,
    ) -> list[LimitUpReportListItem]:
        """查询打板报告列表。

        创建日期：2026-05-08
        author: sunshengxian
        """

        statement = select(LimitUpAnalysisCache)
        normalized_keyword = self._normalize_optional_text(keyword)
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            statement = statement.where(
                or_(
                    LimitUpAnalysisCache.title.like(like_keyword),
                    LimitUpAnalysisCache.content_html.like(like_keyword),
                    LimitUpAnalysisCache.content_markdown.like(like_keyword),
                    LimitUpAnalysisCache.data_quality_json.like(like_keyword),
                )
            )
        normalized_status = self._normalize_optional_text(status)
        if normalized_status:
            statement = statement.where(LimitUpAnalysisCache.status == normalized_status.upper())
        if trade_date is not None:
            statement = statement.where(LimitUpAnalysisCache.trade_date == trade_date)
        # 报告列表搜索只走报告标题、正文和质量摘要，避免把完整上下文 JSON 作为默认搜索对象拖慢页面。
        rows = self.db.scalars(
            statement.order_by(desc(LimitUpAnalysisCache.trade_date), desc(LimitUpAnalysisCache.id)).limit(limit)
        ).all()
        return [self._report_list_item(row) for row in rows]

    def get_report(self, report_id: int) -> LimitUpReportDetail:
        """读取单份打板报告详情。

        创建日期：2026-05-08
        author: sunshengxian
        """

        report = self.db.get(LimitUpAnalysisCache, report_id)
        if report is None:
            raise LimitUpPushError("报告不存在")
        return LimitUpReportDetail(
            **self._report_list_item(report).model_dump(),
            content_html=report.content_html,
            content_markdown=report.content_markdown,
            context=self._json_loads_dict(report.context_json),
            data_quality=self._json_loads_list(report.data_quality_json),
        )

    def list_recipients(self) -> list[LimitUpRecipientItem]:
        """查询系统用户维度的打板报告接收配置。

        创建日期：2026-05-08
        author: sunshengxian
        """

        configs = {
            item.user_id: item
            for item in self.db.scalars(select(LimitUpPushRecipient)).all()
        }
        users = self.db.scalars(select(AppUser).where(AppUser.is_active.is_(True)).order_by(AppUser.id)).all()
        return [self._recipient_item(user, configs.get(user.id)) for user in users]

    def update_recipients(self, payload: LimitUpRecipientUpdateRequest, operator: AppUser) -> list[LimitUpRecipientItem]:
        """保存管理员维护的系统用户接收人配置。

        创建日期：2026-05-08
        author: sunshengxian
        """

        requested = {item.user_id: item.enabled for item in payload.recipients}
        users = {
            user.id: user
            for user in self.db.scalars(select(AppUser).where(AppUser.id.in_(requested.keys()))).all()
        } if requested else {}
        for user_id, enabled in requested.items():
            user = users.get(user_id)
            if user is None or not user.is_active:
                raise LimitUpPushError(f"接收用户不存在或已停用：{user_id}")
            config = self.db.scalar(select(LimitUpPushRecipient).where(LimitUpPushRecipient.user_id == user_id))
            if config is None:
                config = LimitUpPushRecipient(
                    user_id=user_id,
                    enabled=enabled,
                    created_by_user_id=operator.id,
                    updated_by_user_id=operator.id,
                )
                self.db.add(config)
            else:
                config.enabled = enabled
                config.updated_by_user_id = operator.id
        self.db.commit()
        return self.list_recipients()

    def list_deliveries(
        self,
        limit: int = 100,
        keyword: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
    ) -> list[LimitUpDeliveryItem]:
        """查询打板报告业务推送流水。

        创建日期：2026-05-08
        author: sunshengxian
        """

        statement = (
            select(LimitUpPushDelivery, LimitUpAnalysisCache, AppUser)
            .join(LimitUpAnalysisCache, LimitUpAnalysisCache.id == LimitUpPushDelivery.analysis_id)
            .join(AppUser, AppUser.id == LimitUpPushDelivery.user_id)
        )
        normalized_keyword = self._normalize_optional_text(keyword)
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            statement = statement.where(
                or_(
                    LimitUpAnalysisCache.title.like(like_keyword),
                    LimitUpPushDelivery.scheduled_kind.like(like_keyword),
                    LimitUpPushDelivery.error_message.like(like_keyword),
                    AppUser.username.like(like_keyword),
                    AppUser.display_name.like(like_keyword),
                )
            )
        normalized_status = self._normalize_optional_text(status)
        if normalized_status:
            statement = statement.where(LimitUpPushDelivery.status == normalized_status.upper())
        if user_id is not None:
            statement = statement.where(LimitUpPushDelivery.user_id == user_id)
        rows = self.db.execute(statement.order_by(desc(LimitUpPushDelivery.id)).limit(limit)).all()
        return [
            LimitUpDeliveryItem(
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
        """读取早于今天的最近 A 股交易日。

        创建日期：2026-05-08
        author: sunshengxian
        """

        today = today or self._today_local()
        # KPL 口径是次日 8:30 更新，因此早盘任务永远处理“今天之前”的最近交易日；
        # 这样周二早上会生成周一报告，周六/周日会继续定位到周五数据。
        trade_date = self.db.scalar(
            select(ATradeCalendar.cal_date)
            .where(ATradeCalendar.cal_date < today, ATradeCalendar.is_open == 1)
            .order_by(desc(ATradeCalendar.cal_date))
            .limit(1)
        )
        return trade_date or (today - timedelta(days=1))

    def _build_context_snapshot(self, trade_date: date) -> dict[str, Any]:
        quality: list[dict[str, Any]] = []
        trade_date_str = format_tushare_date(trade_date)
        kpl_rows = self._safe_query(
            KPL_REQUIRED_API,
            {"trade_date": trade_date_str},
            KPL_FIELDS,
            quality,
            required=True,
        )
        if not kpl_rows:
            return {"data_ready": False, "context": {}, "data_quality": quality}
        optional_payload: dict[str, list[dict[str, Any]]] = {}
        for api_name, extra_params, fields in OPTIONAL_APIS:
            params = {"trade_date": trade_date_str, **extra_params}
            optional_payload[api_name] = self._safe_query(api_name, params, fields, quality, required=False)
        focus_codes = self._focus_ts_codes(kpl_rows, optional_payload)
        technical = self._technical_indicators(focus_codes, trade_date, quality)
        context = self._assemble_context(trade_date, kpl_rows, optional_payload, technical, quality)
        return {"data_ready": True, "context": context, "data_quality": quality}

    def _safe_query(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: tuple[str, ...],
        quality: list[dict[str, Any]],
        required: bool,
    ) -> list[dict[str, Any]]:
        # 所有 Tushare 请求都由白名单常量构造，运行时只注入交易日和固定口径；
        # 权限不足或接口延迟时写入 data_quality，必需接口为空才阻止报告生成。
        try:
            result = self.tushare_client.query(api_name, params=params, fields=list(fields))
        except Exception as exc:
            quality.append(DataQualityItem(api_name, "FAILED", 0, str(exc)[:300]).to_dict())
            if required:
                logger.info("必需打板接口暂不可用 api=%s params=%s", api_name, params)
            return []
        rows = [self._normalize_api_row(row) for row in result.rows]
        quality.append(DataQualityItem(api_name, "OK" if rows else "EMPTY", len(rows)).to_dict())
        return rows

    def _technical_indicators(
        self,
        ts_codes: list[str],
        trade_date: date,
        quality: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        limited_codes = ts_codes[: max(1, self.settings.limit_up_push_indicator_stock_limit)]
        indicators: dict[str, dict[str, Any]] = {}
        daily_missing: list[str] = []
        error_count = 0
        start_date = trade_date - timedelta(days=max(20, self.settings.limit_up_push_indicator_days))
        local_daily = self._local_daily_rows_by_code(limited_codes, start_date, trade_date)
        latest_basic = self._latest_daily_basic_by_code(limited_codes, trade_date, quality)
        for ts_code in limited_codes:
            params = {
                "ts_code": ts_code,
                "start_date": format_tushare_date(start_date),
                "end_date": format_tushare_date(trade_date),
            }
            daily_rows = local_daily.get(ts_code)
            if not daily_rows:
                # 本地日线可能因新股或同步缺口缺失；仅对缺口股票兜底调用 Tushare，
                # 既保证报告完整性，又避免常规路径产生数百次外部请求。
                daily_rows = self._query_indicator_api("daily", params, DAILY_FIELDS)
                daily_missing.append(ts_code)
            basic_rows = [latest_basic[ts_code]] if ts_code in latest_basic else []
            error_count += 1 if daily_rows is None else 0
            daily_rows = daily_rows or []
            indicators[ts_code] = self._calculate_indicator(daily_rows, basic_rows)
        # 技术指标最多涉及上百只股票，质量记录按接口聚合，避免上下文被逐股调用日志淹没。
        quality.append(
            DataQualityItem(
                "daily",
                "OK" if local_daily or len(daily_missing) < len(limited_codes) else "EMPTY",
                len(local_daily),
                f"local_rows={sum(len(rows) for rows in local_daily.values())}; fallback_codes={len(daily_missing)}; errors={error_count}",
            ).to_dict()
        )
        return indicators

    def _local_daily_rows_by_code(
        self,
        ts_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, list[dict[str, Any]]]:
        """从本地日线表批量读取技术指标所需行情。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if not ts_codes:
            return {}
        # 日线数据本项目已有增量同步，优先批量读本地库可大幅减少 Tushare 调用；
        # 只取关注股票和短窗口日期，避免把全市场历史行情塞进内存。
        rows = self.db.scalars(
            select(ADailyQuote)
            .where(
                ADailyQuote.ts_code.in_(ts_codes),
                ADailyQuote.trade_date >= start_date,
                ADailyQuote.trade_date <= end_date,
            )
            .order_by(ADailyQuote.ts_code, ADailyQuote.trade_date)
        ).all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row.ts_code, []).append(
                {
                    "ts_code": row.ts_code,
                    "trade_date": row.trade_date.isoformat(),
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "pct_chg": row.pct_chg,
                    "vol": row.vol,
                    "amount": row.amount,
                }
            )
        return grouped

    def _latest_daily_basic_by_code(
        self,
        ts_codes: list[str],
        trade_date: date,
        quality: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """批量读取最新交易日 daily_basic 指标。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if not ts_codes:
            quality.append(DataQualityItem("daily_basic", "EMPTY", 0, "no_focus_codes").to_dict())
            return {}
        local_rows = self.db.scalars(
            select(ADailyBasic).where(ADailyBasic.ts_code.in_(ts_codes), ADailyBasic.trade_date == trade_date)
        ).all()
        grouped = {
            row.ts_code: {
                "ts_code": row.ts_code,
                "trade_date": row.trade_date.isoformat(),
                "turnover_rate": row.turnover_rate,
                "volume_ratio": row.volume_ratio,
                "total_mv": row.total_mv,
                "circ_mv": row.circ_mv,
            }
            for row in local_rows
        }
        if len(grouped) >= len(ts_codes):
            quality.append(DataQualityItem("daily_basic", "OK", len(grouped), "source=local").to_dict())
            return grouped
        # daily_basic 本地库可能尚未完整同步；按交易日批量拉一次全市场最新估值指标，
        # 再只保留关注股票，避免逐股请求造成调度延迟和接口压力。
        rows = self._query_indicator_api(
            "daily_basic",
            {"trade_date": format_tushare_date(trade_date)},
            DAILY_BASIC_FIELDS,
        )
        if rows is None:
            quality.append(DataQualityItem("daily_basic", "FAILED", len(grouped), "batch_query_failed").to_dict())
            return grouped
        focus_set = set(ts_codes)
        for row in rows:
            code = str(row.get("ts_code") or "")
            if code in focus_set:
                grouped[code] = row
        status = "OK" if grouped else "EMPTY"
        quality.append(
            DataQualityItem(
                "daily_basic",
                status,
                len(grouped),
                f"source=local+tushare_batch; tushare_rows={len(rows)}",
            ).to_dict()
        )
        return grouped

    def _query_indicator_api(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: tuple[str, ...],
    ) -> list[dict[str, Any]] | None:
        try:
            result = self.tushare_client.query(api_name, params=params, fields=list(fields))
        except Exception:
            logger.info("打板技术指标接口暂不可用 api=%s ts_code=%s", api_name, params.get("ts_code"))
            return None
        return [self._normalize_api_row(row) for row in result.rows]

    def _calculate_indicator(
        self,
        daily_rows: list[dict[str, Any]],
        basic_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Tushare 日线通常按日期倒序返回，这里统一升序计算均线和短期涨幅；
        # 行数不足时只返回已有字段，避免为了指标完整性阻断整份报告。
        rows = sorted(daily_rows, key=lambda item: str(item.get("trade_date") or ""))
        closes = [to_decimal(row.get("close")) for row in rows if to_decimal(row.get("close")) is not None]
        amounts = [to_decimal(row.get("amount")) for row in rows if to_decimal(row.get("amount")) is not None]
        latest = rows[-1] if rows else {}
        latest_basic = sorted(basic_rows, key=lambda item: str(item.get("trade_date") or ""))[-1] if basic_rows else {}
        latest_close = to_decimal(latest.get("close"))
        return {
            "close": self._decimal_to_float(latest_close),
            "pct_chg": self._decimal_to_float(to_decimal(latest.get("pct_chg"))),
            "ma5": self._decimal_to_float(self._avg_decimal(closes[-5:])),
            "ma10": self._decimal_to_float(self._avg_decimal(closes[-10:])),
            "ma20": self._decimal_to_float(self._avg_decimal(closes[-20:])),
            "amount_ratio_5d": self._decimal_to_float(self._amount_ratio(amounts)),
            "return_5d_pct": self._decimal_to_float(self._window_return(closes, 5)),
            "return_10d_pct": self._decimal_to_float(self._window_return(closes, 10)),
            "turnover_rate": self._decimal_to_float(to_decimal(latest_basic.get("turnover_rate"))),
            "volume_ratio": self._decimal_to_float(to_decimal(latest_basic.get("volume_ratio"))),
            "circ_mv": self._decimal_to_float(to_decimal(latest_basic.get("circ_mv"))),
        }

    def _assemble_context(
        self,
        trade_date: date,
        kpl_rows: list[dict[str, Any]],
        optional_payload: dict[str, list[dict[str, Any]]],
        technical: dict[str, dict[str, Any]],
        quality: list[dict[str, Any]],
    ) -> dict[str, Any]:
        focus = self._focus_rows(kpl_rows, optional_payload, technical)
        themes = self._theme_summary(kpl_rows, optional_payload.get("limit_cpt_list", []))
        market_emotion = self._market_emotion(kpl_rows, optional_payload)
        capital_signals = self._capital_signals(kpl_rows, optional_payload.get("top_list", []))
        board_status = self._board_status_summary(kpl_rows)
        return {
            "trade_date": trade_date.isoformat(),
            "data_sources": [item["api_name"] for item in quality if item.get("status") == "OK"],
            "market_emotion": market_emotion,
            "themes": themes,
            "focus_stocks": focus,
            "board_status": board_status,
            "capital_signals": capital_signals,
            "limit_up_stocks": [self._compact_stock_row(row, technical.get(str(row.get("ts_code") or ""))) for row in kpl_rows[:180]],
            "raw_supplement": {
                "limit_step": optional_payload.get("limit_step", [])[:80],
                "top_list": optional_payload.get("top_list", [])[:120],
                "limit_cpt_list": optional_payload.get("limit_cpt_list", [])[:80],
            },
            "data_quality": quality,
            "analysis_instructions": {
                "focus": "特别关注二连、三连、高标和题材前排，结合封板质量、题材强度、技术状态和资金信号自由判断后续连板可能性。",
                "freedom": "不要机械套模板，可以按你认为更有解释力的结构组织报告，但必须给出可跟踪的接力条件和失败信号。",
            },
        }

    def _focus_ts_codes(self, kpl_rows: list[dict[str, Any]], optional_payload: dict[str, list[dict[str, Any]]]) -> list[str]:
        seen: set[str] = set()
        codes: list[str] = []
        for row in kpl_rows:
            status = str(row.get("status") or "")
            if any(token in status for token in ("2连", "3连", "连板", "首板")):
                code = str(row.get("ts_code") or "").strip()
                if code and code not in seen:
                    seen.add(code)
                    codes.append(code)
        for row in optional_payload.get("limit_step", []):
            code = str(row.get("ts_code") or "").strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return codes

    def _focus_rows(
        self,
        kpl_rows: list[dict[str, Any]],
        optional_payload: dict[str, list[dict[str, Any]]],
        technical: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        focus_codes = set(self._focus_ts_codes(kpl_rows, optional_payload))
        rows = [row for row in kpl_rows if str(row.get("ts_code") or "") in focus_codes]
        return [self._compact_stock_row(row, technical.get(str(row.get("ts_code") or ""))) for row in rows[:80]]

    def _compact_stock_row(self, row: dict[str, Any], indicator: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "ts_code": row.get("ts_code"),
            "name": row.get("name"),
            "status": row.get("status"),
            "theme": row.get("theme"),
            "limit_up_reason": row.get("lu_desc"),
            "first_limit_time": row.get("lu_time"),
            "last_limit_time": row.get("last_time"),
            "open_time": row.get("open_time"),
            "limit_order": row.get("limit_order"),
            "max_limit_order": row.get("lu_limit_order"),
            "limit_bid_volume": row.get("lu_bid_vol"),
            "amount": row.get("amount"),
            "net_change": row.get("net_change"),
            "pct_chg": row.get("pct_chg"),
            "real_time_pct_chg": row.get("rt_pct_chg"),
            "turnover_rate": row.get("turnover_rate"),
            "free_float": row.get("free_float"),
            "bid_amount": row.get("bid_amount"),
            "bid_change": row.get("bid_change"),
            "bid_turnover": row.get("bid_turnover"),
            "bid_pct_chg": row.get("bid_pct_chg"),
            "technical": indicator or {},
        }

    def _theme_summary(self, kpl_rows: list[dict[str, Any]], cpt_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: dict[str, dict[str, Any]] = {}
        for row in kpl_rows:
            themes = [item.strip() for item in re.split(r"[,，;；/、]", str(row.get("theme") or "")) if item.strip()]
            for theme in themes or ["未标注题材"]:
                bucket = counter.setdefault(theme, {"theme": theme, "stock_count": 0, "stocks": [], "reasons": []})
                bucket["stock_count"] += 1
                if len(bucket["stocks"]) < 12:
                    bucket["stocks"].append(row.get("name") or row.get("ts_code"))
                reason = row.get("lu_desc")
                if reason and len(bucket["reasons"]) < 8:
                    bucket["reasons"].append(reason)
        cpt_by_name = {str(row.get("name") or ""): row for row in cpt_rows}
        themes = sorted(counter.values(), key=lambda item: item["stock_count"], reverse=True)
        for item in themes:
            item["board_stats"] = cpt_by_name.get(item["theme"], {})
        return themes[:40]

    def _capital_signals(self, kpl_rows: list[dict[str, Any]], top_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        top_by_code = {str(row.get("ts_code") or ""): row for row in top_rows}
        signals: list[dict[str, Any]] = []
        for row in kpl_rows:
            code = str(row.get("ts_code") or "")
            top = top_by_code.get(code)
            if not top:
                continue
            signals.append(
                {
                    "ts_code": code,
                    "name": row.get("name"),
                    "theme": row.get("theme"),
                    "status": row.get("status"),
                    "net_amount": top.get("net_amount"),
                    "net_rate": top.get("net_rate"),
                    "amount_rate": top.get("amount_rate"),
                    "reason": top.get("reason"),
                }
            )
        # 龙虎榜信号按净买额排序，让模型优先看到资金接力最显著的涨停股。
        return sorted(signals, key=lambda item: float(item.get("net_amount") or 0), reverse=True)[:80]

    def _board_status_summary(self, kpl_rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, int] = {}
        for row in kpl_rows:
            key = str(row.get("status") or row.get("tag") or "未标注")
            summary[key] = summary.get(key, 0) + 1
        return {"counts": summary, "top_status": sorted(summary.items(), key=lambda item: item[1], reverse=True)[:20]}

    def _market_emotion(self, kpl_rows: list[dict[str, Any]], optional_payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        status_values = [str(row.get("status") or "") for row in kpl_rows]
        limit_step = optional_payload.get("limit_step", [])
        return {
            "kpl_row_count": len(kpl_rows),
            "limit_up_count": sum(1 for value in status_values if "板" in value or "涨停" in value),
            "second_board_count": sum(1 for value in status_values if "2" in value and "连" in value),
            "third_board_count": sum(1 for value in status_values if "3" in value and "连" in value),
            "chain_ladder_count": len(limit_step),
            "highest_chain": self._highest_chain(limit_step, status_values),
        }

    def _highest_chain(self, limit_step: list[dict[str, Any]], status_values: list[str]) -> int | None:
        values: list[int] = []
        for row in limit_step:
            raw = row.get("nums") or row.get("status") or row.get("type")
            values.extend(int(match) for match in re.findall(r"\d+", str(raw or "")))
        for status in status_values:
            values.extend(int(match) for match in re.findall(r"(\d+)\s*连", status))
        return max(values) if values else None

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _generate_llm_report(self, context: dict[str, Any]) -> tuple[str, str]:
        system_prompt = self._limit_up_system_prompt()
        prompt = self._limit_up_user_prompt(context)
        markdown = self._chat_completion_with_reasoning(prompt, system_prompt)
        html_content = self._normalize_report_html(markdown)
        return html_content, markdown

    def _chat_completion_with_reasoning(self, prompt: str, system_prompt: str) -> str:
        # 打板报告使用独立配置模型，不影响项目当前默认问答模型；
        # reasoning_effort 随 payload 透传给兼容接口，便于 DeepSeek Pro 用更强推理预算生成复盘。
        api_key = self.settings.resolve_llm_api_key()
        if not api_key:
            raise LimitUpPushError("DeepSeek API Key 未配置")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.limit_up_push_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "reasoning_effort": self.settings.limit_up_push_reasoning_effort,
        }
        request_payload_json = self._json_dumps(payload)
        question_id = uuid4().hex
        started_at = perf_counter()
        try:
            with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS * 2) as client:
                response = client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except Exception as exc:
            self._record_llm_metric(question_id, False, started_at, request_payload_json, None, str(exc)[:500])
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
            conversation_title=LIMIT_UP_LLM_TITLE,
            phase=LIMIT_UP_LLM_PHASE,
            phase_label=phase_label(LIMIT_UP_LLM_PHASE),
            phase_description=phase_description(LIMIT_UP_LLM_PHASE),
            provider="DeepSeek",
            model=self.settings.limit_up_push_model,
            success=1 if success else 0,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            output_chars=len(response_content or ""),
            request_payload_json=request_payload_json,
            response_content=response_content,
            error_message=error_message,
        )
        self.db.add(metric)
        self.db.commit()

    def _limit_up_system_prompt(self) -> str:
        return """
你是专注 A 股打板、连板生态和短线题材周期的复盘分析师。你会阅读系统提供的结构化数据，输出适合 PushPlus 长 HTML 展示的完整中文报告。

要求：
1. 重点分析涨停质量、题材强度、市场情绪周期、个股地位、二连三连晋级可能性、资金接力和失败信号。
2. 可以自由组织报告结构，不需要机械打分；但必须给出清晰的后续观察条件、反证条件和风险点。
3. 不编造材料中没有的精确数值；数据缺失时说明不确定性，不要假装已经看到。
4. 输出纯 HTML 片段，不要 Markdown 代码块，不要包裹 html/body 标签。
5. HTML 需要适合微信阅读：使用 h2/h3、p、ul、ol、table、strong，避免脚本和外链样式。
""".strip()

    def _limit_up_user_prompt(self, context: dict[str, Any]) -> str:
        return (
            "请基于以下打板数据生成完整复盘报告。你可以自由判断哪些线索最重要，但请特别关注二连、三连、空间板、题材前排和次日接力条件。\n\n"
            f"结构化数据：\n{self._json_dumps(context)}"
        )

    def _normalize_report_html(self, content: str) -> str:
        stripped = content.strip()
        stripped = re.sub(r"^```(?:html)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        if "<" in stripped and ">" in stripped:
            return self._wrap_html(stripped)
        return self._wrap_html("<p>" + html.escape(stripped).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>")

    def _wrap_html(self, body: str) -> str:
        return (
            "<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "line-height:1.72;color:#14202e;background:#f7f8f4;padding:14px;\">"
            "<div style=\"max-width:760px;margin:0 auto;background:#fff;border:1px solid #dfe6da;"
            "border-radius:10px;padding:18px;\">"
            f"{body}"
            "</div></div>"
        )

    def _ready_or_generating_analysis(self, trade_date: date, snapshot_hash: str) -> LimitUpAnalysisCache | None:
        return self.db.scalar(
            select(LimitUpAnalysisCache)
            .where(
                LimitUpAnalysisCache.trade_date == trade_date,
                LimitUpAnalysisCache.model == self.settings.limit_up_push_model,
                LimitUpAnalysisCache.prompt_version == self.settings.limit_up_push_prompt_version,
                LimitUpAnalysisCache.data_snapshot_hash == snapshot_hash,
                LimitUpAnalysisCache.status.in_([ANALYSIS_STATUS_READY, ANALYSIS_STATUS_GENERATING]),
            )
            .order_by(desc(LimitUpAnalysisCache.id))
            .limit(1)
        )

    def _latest_ready_analysis(self, trade_date: date) -> LimitUpAnalysisCache | None:
        return self.db.scalar(
            select(LimitUpAnalysisCache)
            .where(LimitUpAnalysisCache.trade_date == trade_date, LimitUpAnalysisCache.status == ANALYSIS_STATUS_READY)
            .order_by(desc(LimitUpAnalysisCache.id))
            .limit(1)
        )

    def _enabled_recipients(self) -> list[LimitUpPushRecipient]:
        return list(
            self.db.scalars(
                select(LimitUpPushRecipient).where(LimitUpPushRecipient.enabled.is_(True)).order_by(LimitUpPushRecipient.id)
            ).all()
        )

    def _get_or_create_delivery(
        self,
        analysis: LimitUpAnalysisCache,
        user_id: int,
        scheduled_kind: str,
        scheduled_at: datetime,
    ) -> LimitUpPushDelivery:
        delivery = LimitUpPushDelivery(
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
                select(LimitUpPushDelivery).where(
                    LimitUpPushDelivery.analysis_id == analysis.id,
                    LimitUpPushDelivery.user_id == user_id,
                    LimitUpPushDelivery.scheduled_kind == scheduled_kind,
                    LimitUpPushDelivery.scheduled_at == scheduled_at,
                )
            )
            if existing is None:
                raise
            return existing

    def _latest_pushplus_log_id(self, user_id: int, message_id: str) -> int | None:
        from app.db.models.notification import PushplusMessageLog

        log = self.db.scalar(
            select(PushplusMessageLog.id)
            .where(PushplusMessageLog.user_id == user_id, PushplusMessageLog.push_message_id == message_id)
            .order_by(desc(PushplusMessageLog.id))
            .limit(1)
        )
        return log

    def _recipient_item(self, user: AppUser, config: LimitUpPushRecipient | None) -> LimitUpRecipientItem:
        binding = self.db.scalar(
            select(PushplusBinding).where(PushplusBinding.user_id == user.id, PushplusBinding.is_active.is_(True))
        )
        can_push = binding is not None or self.notification_service.can_send_pushplus_to_user(user.id)
        binding_name = None
        if binding is not None:
            binding_name = binding.friend_remark or binding.friend_nick_name or f"好友 {binding.friend_id}"
        elif can_push:
            binding_name = "默认管理员个人通道"
        return LimitUpRecipientItem(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            enabled=bool(config.enabled) if config is not None else False,
            can_push=can_push,
            binding_name=binding_name,
        )

    def _report_list_item(self, report: LimitUpAnalysisCache) -> LimitUpReportListItem:
        return LimitUpReportListItem(
            id=report.id,
            trade_date=report.trade_date,
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
            parsed = parse_tushare_date(normalized.get("trade_date"))
            normalized["trade_date"] = parsed.isoformat() if parsed else normalized.get("trade_date")
        return normalized

    def _snapshot_hash(self, context: dict[str, Any]) -> str:
        return hashlib.sha256(self._json_dumps(context).encode("utf-8")).hexdigest()

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _json_loads_dict(self, value: str | None) -> dict[str, Any] | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _json_loads_list(self, value: str | None) -> list[dict[str, Any]]:
        if not value:
            return []
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _avg_decimal(self, values: list[Decimal | None]) -> Decimal | None:
        filtered = [value for value in values if value is not None]
        if not filtered:
            return None
        return sum(filtered, Decimal("0")) / Decimal(len(filtered))

    def _amount_ratio(self, values: list[Decimal | None]) -> Decimal | None:
        filtered = [value for value in values if value is not None]
        if len(filtered) < 6:
            return None
        avg_prev = self._avg_decimal(filtered[-6:-1])
        if not avg_prev:
            return None
        return filtered[-1] / avg_prev

    def _window_return(self, closes: list[Decimal | None], window: int) -> Decimal | None:
        filtered = [value for value in closes if value is not None]
        if len(filtered) <= window or not filtered[-window - 1]:
            return None
        return (filtered[-1] / filtered[-window - 1] - Decimal("1")) * Decimal("100")

    def _decimal_to_float(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    def _now_local(self) -> datetime:
        return datetime.now(LOCAL_TZ)

    def _today_local(self) -> date:
        return self._now_local().date()

    def _now_naive(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def _data_ready_scheduled_at(self, trade_date: date) -> datetime:
        """生成 KPL 数据就绪推送的固定业务计划时间。

        创建日期：2026-05-08
        author: sunshengxian
        """

        # 定时任务在 8-9 点多次轮询 KPL 是否更新；业务计划时间固定为交易日次日
        # 08:30（东八区）并转成项目约定的 UTC naive 入库，确保命中缓存后不会重复推送。
        local_dt = datetime.combine(trade_date + timedelta(days=1), time(8, 30), tzinfo=LOCAL_TZ)
        return local_dt.astimezone(UTC).replace(tzinfo=None)

    def _weekend_replay_scheduled_at(self, replay_date: date) -> datetime:
        """生成周末复推的固定业务计划时间。

        创建日期：2026-05-08
        author: sunshengxian
        """

        # 周六、周日晚上复推同一份周五报告，但两个自然日各只允许发送一次；
        # 固定到配置的东八区小时，避免手动补跑或调度误触发造成重复流水。
        local_dt = datetime.combine(
            replay_date,
            time(self.settings.limit_up_push_weekend_replay_hour, 0),
            tzinfo=LOCAL_TZ,
        )
        return local_dt.astimezone(UTC).replace(tzinfo=None)
