from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import desc, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.db.models.market import ADailyBasic, ADailyQuote, ATradeCalendar
from app.db.models.notification import (
    LimitUpAnalysisCache,
    LimitUpAnalysisStageCache,
    LimitUpPushDelivery,
    LimitUpPushRecipient,
    LimitUpReportShare,
    LimitUpStockSupplementCache,
    PushplusBinding,
)
from app.schemas.limit_up_push import (
    LimitUpDeliveryItem,
    LimitUpPublicReportDetail,
    LimitUpRecipientItem,
    LimitUpRecipientUpdateRequest,
    LimitUpReportDetail,
    LimitUpReportListItem,
    LimitUpShareItem,
    LimitUpShareResponse,
)
from app.services.date_utils import format_tushare_date, parse_tushare_date
from app.services.decimal_utils import to_decimal
from app.services.llm_client import LLM_CHAT_TIMEOUT_SECONDS
from app.services.llm_metric_definitions import phase_description, phase_label
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
# 建议阶段独立指标 phase：与 limit_up_analysis 同为直连调用、不计问答日限额，
# 单列 phase 便于在 LLM 耗时页区分报告生成与建议生成的成功率/耗时。
LIMIT_UP_ADVICE_LLM_PHASE = "limit_up_advice"
LIMIT_UP_LLM_TITLE = "打板数据推送"
# 投资建议状态机：附加产物状态，与报告本体 status 解耦，建议失败不影响报告 READY。
ADVICE_STATUS_PENDING = "PENDING"
ADVICE_STATUS_GENERATING = "GENERATING"
ADVICE_STATUS_READY = "READY"
ADVICE_STATUS_FAILED = "FAILED"
# 旧报告（多阶段改造前、无 pipeline 结构化结果）兜底材料上限：
# content_markdown 实为整篇 HTML 报告原文，体积远大于结构化输入，必须截断控制 token。
LIMIT_UP_ADVICE_FALLBACK_MATERIAL_MAX_CHARS = 12000
KPL_REQUIRED_API = "kpl_list"
KPL_TAG_LIMIT_UP = "涨停"
KPL_TAG_BROKEN = "炸板"
KPL_TAG_LIMIT_DOWN = "跌停"
KPL_TAGS_FOR_CYCLE = (KPL_TAG_BROKEN, KPL_TAG_LIMIT_DOWN)
# LLM 上下文条数上限统一集中管理；这些上限控制报告可读性和 token 体积，后续调大/调小时避免漏改。
LIMIT_UP_CONTEXT_STOCK_LIMIT = 360
LIMIT_UP_CONTEXT_RAW_LIMIT_STEP_LIMIT = 160
LIMIT_UP_CONTEXT_RAW_TOP_LIST_LIMIT = 240
LIMIT_UP_CONTEXT_RAW_CPT_LIST_LIMIT = 160
LIMIT_UP_CONTEXT_FOCUS_STOCK_LIMIT = 160
LIMIT_UP_CONTEXT_THEME_LIMIT = 80
LIMIT_UP_CONTEXT_CAPITAL_SIGNAL_LIMIT = 160
LIMIT_UP_CONTEXT_BOARD_STATUS_LIMIT = 40
LIMIT_UP_STAGE_FIRST_BOARD = "FIRST_BOARD"
# 首板个股精选扩展：FIRST_BOARD 阶段保持题材级结论不变，
# 个股精选与重点分析拆成两个独立阶段，避免破坏既有阶段的缓存键、JSON 结构与兜底逻辑。
LIMIT_UP_STAGE_FIRST_BOARD_SELECTION = "FIRST_BOARD_SELECTION"
LIMIT_UP_STAGE_FIRST_BOARD_FOCUS = "FIRST_BOARD_FOCUS"
LIMIT_UP_STAGE_CHAIN_SELECTION = "CHAIN_SELECTION"
LIMIT_UP_STAGE_HIGH_BOARD_SELECTION = "HIGH_BOARD_SELECTION"
LIMIT_UP_STAGE_CHAIN_FOCUS = "CHAIN_FOCUS"
LIMIT_UP_STAGE_HIGH_BOARD_FOCUS = "HIGH_BOARD_FOCUS"
LIMIT_UP_STAGE_FINAL_REPORT = "FINAL_REPORT"
# 投资建议阶段：报告 READY 后的附加阶段，基于 pipeline 结构化结果生成结论化建议；
# 失败不影响报告本体，由推送/发布层按降级开关处理。
LIMIT_UP_STAGE_INVESTMENT_ADVICE = "INVESTMENT_ADVICE"
LIMIT_UP_SUPPLEMENT_STATUS_READY = "READY"
LIMIT_UP_SUPPLEMENT_STATUS_PARTIAL = "PARTIAL"
LIMIT_UP_SUPPLEMENT_STATUS_FAILED = "FAILED"
# LLM 失败响应会写入指标表辅助排查；
# 截断上限只限制错误诊断文本，不影响正常报告正文入库。
LLM_ERROR_RESPONSE_LOG_LIMIT = 4000
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
DAILY_BASIC_FIELDS = (
    "ts_code",
    "trade_date",
    "turnover_rate",
    "volume_ratio",
    "total_mv",
    "circ_mv",
)
CYQ_PERF_FIELDS = (
    "ts_code",
    "trade_date",
    "his_low",
    "his_high",
    "cost_5pct",
    "cost_15pct",
    "cost_50pct",
    "cost_85pct",
    "cost_95pct",
    "weight_avg",
    "winner_rate",
)
CYQ_CHIPS_FIELDS = ("ts_code", "trade_date", "price", "percent")


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
        existing_ready = self._latest_ready_analysis(trade_date)
        if existing_ready is not None:
            # 早盘轮询只需要把同一交易日的 READY 报告推送出去；
            # 上游补数或行序扰动不应触发重复 LLM 生成，手动强制重算另走人工入口。
            return existing_ready, self.push_report(
                existing_ready.id,
                DELIVERY_KIND_DATA_READY,
                self._data_ready_scheduled_at(trade_date),
            )
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
        existing = self._analysis_for_snapshot(trade_date, snapshot_hash)
        if existing is not None:
            if existing.status == ANALYSIS_STATUS_READY:
                return existing
            if (
                existing.status == ANALYSIS_STATUS_GENERATING
                and not self._is_generating_stale(existing)
            ):
                return existing
            analysis = existing
            self._reset_analysis_for_retry(analysis, trade_date, context, data_quality)
        else:
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
            # GENERATING 僵死判断只比较应用写入的 UTC-naive 时间，避免依赖数据库服务器时区。
            analysis.updated_at = self._now_naive()
            self.db.add(analysis)
            try:
                self.db.commit()
                self.db.refresh(analysis)
            except IntegrityError:
                self.db.rollback()
                analysis = self._analysis_for_snapshot(trade_date, snapshot_hash)
                if analysis is None:
                    raise
                if analysis.status == ANALYSIS_STATUS_READY:
                    return analysis
                if (
                    analysis.status == ANALYSIS_STATUS_GENERATING
                    and not self._is_generating_stale(analysis)
                ):
                    return analysis
                self._reset_analysis_for_retry(analysis, trade_date, context, data_quality)
        try:
            self._active_limit_up_analysis_id = analysis.id
            content_html, content_markdown = self._generate_llm_report(context)
        except Exception as exc:
            analysis.status = ANALYSIS_STATUS_FAILED
            analysis.error_message = str(exc)[:1000]
            self.db.commit()
            logger.error("打板 LLM 报告生成失败 trade_date=%s", trade_date, exc_info=True)
            raise
        finally:
            self._active_limit_up_analysis_id = None
        analysis.content_html = content_html
        analysis.content_markdown = content_markdown
        analysis.context_json = self._json_dumps(context)
        analysis.data_quality_json = self._json_dumps(context.get("data_quality") or data_quality)
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
        """向所有启用接收人推送指定报告。

        创建日期：2026-05-08
        author: sunshengxian
        """

        analysis = self.db.get(LimitUpAnalysisCache, analysis_id)
        if (
            analysis is None
            or analysis.status != ANALYSIS_STATUS_READY
            or not analysis.content_html
        ):
            raise LimitUpPushError("报告不存在或尚未生成完成")
        # 内容模式收口：建议回填下沉到这里而非各调度入口，
        # 定时、周末复推、手动推送、历史报告补推走同一条回填与降级路径。
        resolved_content = self._resolve_push_content(analysis, scheduled_kind)
        if resolved_content is None:
            # 定时入口本轮跳过（建议生成中或失败且降级关闭），不建流水，下轮轮询重试。
            logger.info(
                "打板推送本轮跳过：建议未就绪 analysis_id=%s advice_status=%s kind=%s",
                analysis.id,
                analysis.advice_status,
                scheduled_kind,
            )
            return 0
        push_title, push_content = resolved_content
        recipients = self._enabled_recipients(
            target_user_ids,
            require_weekend_replay=scheduled_kind
            in {DELIVERY_KIND_SATURDAY_REPLAY, DELIVERY_KIND_SUNDAY_REPLAY},
        )
        if target_user_ids is not None and not recipients:
            raise LimitUpPushError("请选择已配置且启用的接收人")
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
                    push_title,
                    push_content,
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

    def _resolve_push_content(
        self,
        analysis: LimitUpAnalysisCache,
        scheduled_kind: str,
    ) -> tuple[str, str] | None:
        """按内容模式解析推送标题与正文，必要时同步回填建议。

        返回 None 表示定时入口本轮跳过（不建流水，下轮轮询重试）；
        MANUAL 入口不静默跳过，未就绪场景直接抛出明确错误供管理员处置。
        REPORT 模式是严格回滚通道：不触发建议生成、不写建议列，与重构前行为一致。

        创建日期：2026-06-12
        author: claude
        """

        mode = (self.settings.limit_up_push_content_mode or "ADVICE").strip().upper()
        if mode != "ADVICE":
            return analysis.title, str(analysis.content_html or "")
        is_manual = scheduled_kind == DELIVERY_KIND_MANUAL
        if analysis.advice_status != ADVICE_STATUS_READY or not analysis.advice_html:
            if is_manual:
                # MANUAL：PENDING 现场回填（含存量历史报告）；GENERATING 也交给 ensure
                # 内部裁决——未僵死直接返回（落到下方"生成中"提示），僵死则接管恢复，
                # 避免进程崩溃后手动推送被永久卡死；FAILED 不自动重试，
                # 由管理员经重生成端点修复后再推，避免手动重复推送触发重复 LLM 调用。
                if analysis.advice_status in {
                    ADVICE_STATUS_PENDING,
                    ADVICE_STATUS_GENERATING,
                }:
                    self.ensure_advice_for_analysis(analysis)
            else:
                # 定时入口：PENDING 回填、FAILED 冷却重试、僵死 GENERATING 接管，
                # 全部由 ensure_advice_for_analysis 内部裁决，这里不重复判断。
                self.ensure_advice_for_analysis(analysis)
        if analysis.advice_status == ADVICE_STATUS_READY and analysis.advice_html:
            return self._advice_title(analysis.trade_date), analysis.advice_html
        if analysis.advice_status == ADVICE_STATUS_FAILED:
            if self.settings.limit_up_push_advice_fallback_to_report:
                # 降级保交付：建议失败时退回整报，流水照常推进，降级痕迹由
                # pipeline.stage_quality 的 FAILED_FALLBACK 质量项承载。
                return analysis.title, str(analysis.content_html or "")
            if is_manual:
                raise LimitUpPushError("投资建议生成失败且降级推送已关闭，请先重新生成建议")
            return None
        if is_manual:
            raise LimitUpPushError("投资建议正在生成中，请稍后重试")
        return None

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
        kind = (
            DELIVERY_KIND_SATURDAY_REPLAY if today.weekday() == 5 else DELIVERY_KIND_SUNDAY_REPLAY
        )
        return analysis, self.push_report(
            analysis.id, kind, self._weekend_replay_scheduled_at(today)
        )

    def ensure_advice_for_analysis(
        self,
        analysis: LimitUpAnalysisCache,
        force: bool = False,
    ) -> LimitUpAnalysisCache:
        """为 READY 报告生成或回填投资建议（附加产物，失败不影响报告本体）。

        幂等与并发口径：
        - advice READY 直接返回，不重调 LLM；
        - 生成前以条件更新抢占 GENERATING 锁——早盘轮询与雪球调度会并发进入本方法，
          阶段缓存唯一键只保证落库幂等，拦不住并发窗口内的重复 LLM 调用；
        - 他方持有未僵死的 GENERATING 时直接返回；僵死（超过 stale 阈值）允许接管重跑；
        - FAILED 在冷却窗口内不自动重试，防止雪球每分钟调度放大为全天重试；
          force=True（管理员重生成端点）绕过 READY 幂等与冷却。

        创建日期：2026-06-12
        author: claude
        """

        if analysis.status != ANALYSIS_STATUS_READY or not analysis.content_html:
            # 建议依附于已完成报告；未 READY 时不生成，由报告链路自身重试。
            return analysis
        if not force:
            if analysis.advice_status == ADVICE_STATUS_READY and analysis.advice_html:
                return analysis
            if analysis.advice_status == ADVICE_STATUS_GENERATING and not self._is_advice_stale(
                analysis
            ):
                return analysis
            if analysis.advice_status == ADVICE_STATUS_FAILED and not self._advice_cooldown_passed(
                analysis
            ):
                return analysis
        if not self._claim_advice_generation(analysis):
            # 抢占失败说明并发方已接管，本方刷新后直接返回，避免双倍 LLM 调用。
            return analysis
        advice_input, from_report_fallback = self._build_advice_input(analysis)
        stage_quality: list[dict[str, Any]] = []
        try:
            self._active_limit_up_analysis_id = analysis.id
            payload = self._run_text_stage(
                LIMIT_UP_STAGE_INVESTMENT_ADVICE,
                advice_input,
                self._stage_system_prompt("短线投资建议顾问"),
                self._investment_advice_prompt(advice_input, from_report_fallback),
                stage_quality,
                llm_phase=LIMIT_UP_ADVICE_LLM_PHASE,
                # force 重生成必须真正重调 LLM：同输入哈希的 READY 阶段缓存若不跳过，
                # 质量不满意场景会原样返回旧内容，端点回复"已重新生成"即构成误导。
                skip_cache=force,
            )
            # 判空只看 LLM 原始输出 content：html_fragment 对空串会包装出 "<p></p>"，
            # 若回退它判空守卫会变成死代码，空白建议将被置 READY 推送/发布出去。
            raw_advice = str(payload.get("content") or "")
            if not raw_advice.strip():
                raise LimitUpPushError("投资建议输出为空")
        except Exception as exc:
            # 建议失败只标记建议态：报告保持 READY，推送层按降级开关决定推整报或跳过；
            # 质量项写入 pipeline.stage_quality 以点亮列表页 has_stage_fallback 标识。
            analysis.advice_status = ADVICE_STATUS_FAILED
            analysis.advice_error = str(exc)[:1000]
            analysis.updated_at = self._now_naive()
            self._append_advice_failure_quality(analysis, str(exc)[:300])
            self.db.commit()
            logger.error(
                "打板投资建议生成失败 analysis_id=%s trade_date=%s",
                analysis.id,
                analysis.trade_date,
                exc_info=True,
            )
            return analysis
        finally:
            self._active_limit_up_analysis_id = None
        analysis.advice_html = self._normalize_report_html(raw_advice)
        analysis.advice_markdown = raw_advice
        analysis.advice_status = ADVICE_STATUS_READY
        analysis.advice_generated_at = self._now_naive()
        analysis.advice_error = None
        analysis.updated_at = self._now_naive()
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def _claim_advice_generation(self, analysis: LimitUpAnalysisCache) -> bool:
        """以数据库条件更新抢占建议生成权（CAS 语义）。

        以当前内存中的 advice_status 作为比较值：并发方若已先行改写该状态，
        本次 UPDATE 影响行数为 0，视为抢占失败。抢占成功后立即 commit，
        让其它入口能读到 GENERATING 并退出。

        创建日期：2026-06-12
        author: claude
        """

        current_status = analysis.advice_status or ADVICE_STATUS_PENDING
        conditions = [
            LimitUpAnalysisCache.id == analysis.id,
            LimitUpAnalysisCache.advice_status == current_status,
        ]
        if current_status == ADVICE_STATUS_GENERATING:
            # 僵死接管/force 场景的比较值与目标值同为 GENERATING，单纯状态比较会让
            # 所有并发接管方 rowcount 都为 1（同值更新也算匹配）；附加旧 updated_at
            # 比较后，先抢到的一方改写 updated_at，其余方条件失配即抢占失败。
            conditions.append(LimitUpAnalysisCache.updated_at == analysis.updated_at)
        result = self.db.execute(
            update(LimitUpAnalysisCache)
            .where(*conditions)
            .values(advice_status=ADVICE_STATUS_GENERATING, updated_at=self._now_naive())
        )
        self.db.commit()
        self.db.refresh(analysis)
        return bool(result.rowcount)

    def _is_advice_stale(self, analysis: LimitUpAnalysisCache) -> bool:
        """判断建议 GENERATING 是否僵死（进程崩溃等导致锁未释放）。

        与报告僵死判定同口径：比较应用写入的 UTC-naive updated_at，
        阈值复用 limit_up_push_generating_stale_minutes，避免依赖数据库时区。

        创建日期：2026-06-12
        author: claude
        """

        threshold_minutes = max(1, self.settings.limit_up_push_generating_stale_minutes)
        updated_at = analysis.updated_at or analysis.created_at
        if updated_at is None:
            return True
        return self._now_naive() - updated_at > timedelta(minutes=threshold_minutes)

    def _advice_cooldown_passed(self, analysis: LimitUpAnalysisCache) -> bool:
        """判断建议 FAILED 后冷却窗口是否已过（窗口内不自动重试）。

        早盘轮询窗口仅 8-9 点共 12 次，叠加冷却后当日自动重试次数有界；
        管理员强制重生成（force=True）不经过本判断。

        创建日期：2026-06-12
        author: claude
        """

        threshold_minutes = max(1, self.settings.limit_up_push_generating_stale_minutes)
        updated_at = analysis.updated_at or analysis.created_at
        if updated_at is None:
            return True
        return self._now_naive() - updated_at > timedelta(minutes=threshold_minutes)

    def _build_advice_input(
        self, analysis: LimitUpAnalysisCache
    ) -> tuple[dict[str, Any], bool]:
        """组装建议阶段输入材料。

        优先使用 pipeline 结构化结果（与最终报告同源，含首板/两三连/高连板入选与筹码摘要）；
        旧报告（多阶段改造前生成、无 pipeline）退化为整报正文提取口径，
        返回值第二项标记是否走了兜底路径，供提示词切换指令段。

        创建日期：2026-06-12
        author: claude
        """

        context = self._json_loads_dict(analysis.context_json) or {}
        pipeline = context.get("pipeline") if isinstance(context, dict) else None
        pipeline = pipeline if isinstance(pipeline, dict) else {}
        has_structured = bool(
            pipeline.get("selected_chain_stocks")
            or pipeline.get("selected_high_board_stocks")
            or pipeline.get("selected_first_board_stocks")
        )
        if has_structured:
            supplements = (
                pipeline.get("stock_supplements")
                if isinstance(pipeline.get("stock_supplements"), dict)
                else {}
            )
            return (
                {
                    "trade_date": analysis.trade_date.isoformat(),
                    "market_context": context.get("market_context") or {},
                    "first_board": pipeline.get("first_board") or {},
                    "selected_first_board_stocks": self._stocks_for_final_prompt(
                        list(pipeline.get("selected_first_board_stocks") or []), supplements
                    ),
                    "selected_chain_stocks": self._stocks_for_final_prompt(
                        list(pipeline.get("selected_chain_stocks") or []), supplements
                    ),
                    "selected_high_board_stocks": self._stocks_for_final_prompt(
                        list(pipeline.get("selected_high_board_stocks") or []), supplements
                    ),
                    "first_board_focus_html": pipeline.get("first_board_focus_html"),
                    "chain_focus_html": pipeline.get("chain_focus_html"),
                    "high_board_focus_html": pipeline.get("high_board_focus_html"),
                },
                False,
            )
        # 兜底材料：content_markdown 实为 FINAL_REPORT 阶段原始输出（整篇 HTML 报告），
        # 先剥代码块围栏再截断，控制 token 体积。
        raw_report = str(analysis.content_markdown or analysis.content_html or "")
        stripped = raw_report.strip()
        stripped = re.sub(r"^```(?:html)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        return (
            {
                "trade_date": analysis.trade_date.isoformat(),
                "report_html": stripped[:LIMIT_UP_ADVICE_FALLBACK_MATERIAL_MAX_CHARS],
            },
            True,
        )

    def _investment_advice_prompt(
        self, advice_input: dict[str, Any], from_report_fallback: bool
    ) -> str:
        """生成投资建议阶段提示词。

        内容口径对齐问答"风险高收益型推荐"：风险段前置、候选分层、
        每只标的给晋级逻辑与竞价触发/失败条件、禁止模板化免责句但必须有真实风险提示段、
        不暴露底层数据来源；载体按推送渠道约束直接产 HTML。

        创建日期：2026-06-12
        author: claude
        """

        if from_report_fallback:
            material_note = (
                "输入材料是一篇完整打板复盘 HTML 报告原文，"
                "请从报告正文提取观察标的、晋级理由、触发条件和风险后再给结论。"
            )
        else:
            material_note = (
                "输入材料是打板分析的结构化阶段结果："
                "selected_first_board_stocks（首板精选）、selected_chain_stocks（两三连）、"
                "selected_high_board_stocks（高连板）含入选评分与筹码摘要，"
                "market_context.emotion_cycle 含情绪周期数值。"
            )
        return (
            "请基于以下打板分析结果，输出一份次日可执行的高风险短线投资建议，"
            "读者是接受高波动、高回撤的进取型投资者。" + material_note + "\n"
            "结构硬约束（顺序固定）：\n"
            "1. 风险提示段必须置于全文最前：给出当日情绪周期定位、整体仓位态度，"
            "并明确提示高波动、高回撤与失败风险；"
            "禁止输出\"不构成投资建议\"\"仅供参考\"等模板化免责句。\n"
            "2. 核心结论：3 到 5 条要点，给出当日参与或观望的总判断。\n"
            "3. 候选标的分层：按重点观察/谨慎观察/放弃观察分层，每只不超过 100 字，"
            "必须含晋级逻辑、次日竞价触发条件（竞价弱于多少放弃、合理低吸区间、"
            "过高开警惕点）、失败/止损条件和筹码压力提示；"
            "首板候选单列小节，并明确提示首板次日溢价失败率高于连板接力，"
            "参与方式与试错幅度须更克制；名单为空的小节保留并说明当日无候选。\n"
            "4. 反证信号：明确什么情况下整套建议作废。\n"
            "数据纪律：退潮期、分歧期默认下调所有接力评级，冰点期只输出观察清单不给参与建议；"
            "精确数值必须来自输入材料，缺失标注不确定性，不编造；"
            "不要提及 JSON、阶段、数据库、报告流水线等底层数据来源。\n"
            "只输出纯 HTML 片段，使用 h2/h3、p、ul、ol、table、strong，"
            "不要 Markdown 代码块，不要 html/body；总篇幅显著短于完整复盘报告，"
            "适合微信单屏到三屏阅读。\n\n"
            f"输入材料：\n{self._json_dumps(advice_input)}"
        )

    def _append_advice_failure_quality(
        self, analysis: LimitUpAnalysisCache, message: str
    ) -> None:
        """把建议失败质量项写入 context_json.pipeline.stage_quality。

        列表页降级标识 _has_stage_fallback 只读取 pipeline.stage_quality，
        写入其它位置不会点亮；旧报告无 pipeline 时补建仅含 stage_quality 的空结构。

        创建日期：2026-06-12
        author: claude
        """

        context = self._json_loads_dict(analysis.context_json) or {}
        pipeline = context.get("pipeline") if isinstance(context, dict) else None
        if not isinstance(pipeline, dict):
            pipeline = {}
        stage_quality = pipeline.get("stage_quality")
        if not isinstance(stage_quality, list):
            stage_quality = []
        stage_quality.append(
            self._stage_quality_item(
                LIMIT_UP_STAGE_INVESTMENT_ADVICE, "FAILED_FALLBACK", message
            )
        )
        pipeline["stage_quality"] = stage_quality
        context["pipeline"] = pipeline
        analysis.context_json = self._json_dumps(context)

    def _advice_title(self, trade_date: date) -> str:
        """生成投资建议推送标题（与整报标题区分，明示高风险属性）。

        创建日期：2026-06-12
        author: claude
        """

        return f"{trade_date:%Y-%m-%d} 打板投资建议（高风险）"

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
            statement.order_by(
                desc(LimitUpAnalysisCache.trade_date), desc(LimitUpAnalysisCache.id)
            ).limit(limit)
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
        context = self._json_loads_dict(report.context_json)
        pipeline = context.get("pipeline") if isinstance(context, dict) else None
        pipeline = pipeline if isinstance(pipeline, dict) else {}
        return LimitUpReportDetail(
            **self._report_list_item(report).model_dump(),
            content_html=report.content_html,
            content_markdown=report.content_markdown,
            advice_html=report.advice_html,
            advice_markdown=report.advice_markdown,
            advice_generated_at=report.advice_generated_at,
            advice_error=report.advice_error,
            context=context,
            data_quality=self._json_loads_list(report.data_quality_json),
            stage_quality=self._json_loads_list(
                self._json_dumps(pipeline.get("stage_quality") or [])
            ),
            selected_first_board_stocks=list(pipeline.get("selected_first_board_stocks") or []),
            selected_chain_stocks=list(pipeline.get("selected_chain_stocks") or []),
            selected_high_board_stocks=list(pipeline.get("selected_high_board_stocks") or []),
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
        users = self.db.scalars(
            select(AppUser).where(AppUser.is_active.is_(True)).order_by(AppUser.id)
        ).all()
        return [self._recipient_item(user, configs.get(user.id)) for user in users]

    def update_recipients(
        self, payload: LimitUpRecipientUpdateRequest, operator: AppUser
    ) -> list[LimitUpRecipientItem]:
        """保存管理员维护的系统用户接收人配置。

        创建日期：2026-05-08
        author: sunshengxian
        """

        requested = {item.user_id: item for item in payload.recipients}
        users = {
            user.id: user
            for user in self.db.scalars(
                select(AppUser).where(AppUser.id.in_(requested.keys()))
            ).all()
        } if requested else {}
        for user_id, item in requested.items():
            user = users.get(user_id)
            if user is None or not user.is_active:
                raise LimitUpPushError(f"接收用户不存在或已停用：{user_id}")
            config = self.db.scalar(
                select(LimitUpPushRecipient).where(LimitUpPushRecipient.user_id == user_id)
            )
            if config is None:
                config = LimitUpPushRecipient(
                    user_id=user_id,
                    enabled=item.enabled,
                    weekend_replay_enabled=item.weekend_replay_enabled,
                    created_by_user_id=operator.id,
                    updated_by_user_id=operator.id,
                )
                self.db.add(config)
            else:
                config.enabled = item.enabled
                config.weekend_replay_enabled = item.weekend_replay_enabled
                config.updated_by_user_id = operator.id
            self._sync_recipient_menu_permission(user, item.enabled)
        self.db.commit()
        return self.list_recipients()

    def create_report_share(
        self,
        report_id: int,
        expires_in_hours: int | None,
        operator: AppUser,
        share_base_url: str,
    ) -> LimitUpShareResponse:
        """为已生成报告创建临时公开分享链接。

        创建日期：2026-05-09
        author: sunshengxian
        """

        report = self._get_shareable_report(report_id)
        # expires_in_hours 为空表示永久链接；
        # 有限期链接使用 UTC-naive 时间入库，保持与项目其它时间字段一致。
        expires_at = (
            self._now_naive() + timedelta(hours=expires_in_hours) if expires_in_hours else None
        )
        token = self._new_share_token()
        share = LimitUpReportShare(
            analysis_id=report.id,
            share_token=token,
            expires_at=expires_at,
            created_by_user_id=operator.id,
        )
        self.db.add(share)
        self.db.commit()
        self.db.refresh(share)
        return LimitUpShareResponse(
            token=token,
            share_url=f"{share_base_url.rstrip('/')}/limit-up-share/{token}",
            expires_at=expires_at,
            permanent=expires_at is None,
        )

    def list_report_shares(self, report_id: int, share_base_url: str) -> list[LimitUpShareItem]:
        """查询指定报告已生成的分享链接。

        创建日期：2026-05-09
        author: sunshengxian
        """

        self._get_shareable_report(report_id)
        # 分享链接按创建时间倒序展示，便于管理员再次点击“分享”时先看到最近生成的链接。
        shares = self.db.scalars(
            select(LimitUpReportShare)
            .where(LimitUpReportShare.analysis_id == report_id)
            .order_by(desc(LimitUpReportShare.id))
        ).all()
        return [self._share_item(share, share_base_url) for share in shares]

    def revoke_report_share(
        self,
        report_id: int,
        share_id: int,
        share_base_url: str,
    ) -> LimitUpShareItem:
        """将指定分享链接标记为失效。

        创建日期：2026-05-09
        author: sunshengxian
        """

        self._get_shareable_report(report_id)
        share = self.db.scalar(
            select(LimitUpReportShare).where(
                LimitUpReportShare.id == share_id,
                LimitUpReportShare.analysis_id == report_id,
            )
        )
        if share is None:
            raise LimitUpPushError("分享链接不存在")
        # 失效操作保持幂等：已失效链接再次点击不会报错，只返回当前状态，避免前端重复提交造成误提示。
        if share.revoked_at is None:
            share.revoked_at = self._now_naive()
            self.db.commit()
            self.db.refresh(share)
        return self._share_item(share, share_base_url)

    def get_public_report(self, token: str) -> LimitUpPublicReportDetail:
        """按临时分享 token 读取公开报告。

        创建日期：2026-05-09
        author: sunshengxian
        """

        normalized_token = token.strip()
        if not normalized_token:
            raise LimitUpPushError("分享链接无效或已过期")
        now = self._now_naive()
        row = self.db.execute(
            select(LimitUpReportShare, LimitUpAnalysisCache)
            .join(LimitUpAnalysisCache, LimitUpAnalysisCache.id == LimitUpReportShare.analysis_id)
            .where(
                LimitUpReportShare.share_token == normalized_token,
                LimitUpReportShare.revoked_at.is_(None),
                or_(LimitUpReportShare.expires_at.is_(None), LimitUpReportShare.expires_at > now),
                LimitUpAnalysisCache.status == ANALYSIS_STATUS_READY,
            )
            .limit(1)
        ).first()
        if row is None:
            raise LimitUpPushError("分享链接无效或已过期")
        share, report = row
        if not report.content_html:
            raise LimitUpPushError("分享报告内容为空")
        # 公开查看只记录访问次数和最近访问时间，不要求登录；
        # 该统计用于管理员判断临时分享是否仍被使用。
        share.view_count += 1
        share.last_viewed_at = now
        self.db.commit()
        return LimitUpPublicReportDetail(
            title=report.title,
            trade_date=report.trade_date,
            content_html=report.content_html,
            generated_at=report.generated_at,
            expires_at=share.expires_at,
            permanent=share.expires_at is None,
        )

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
            {"trade_date": trade_date_str, "tag": KPL_TAG_LIMIT_UP},
            KPL_FIELDS,
            quality,
            required=True,
        )
        if not kpl_rows:
            return {"data_ready": False, "context": {}, "data_quality": quality}
        optional_payload: dict[str, list[dict[str, Any]]] = {}
        for tag in KPL_TAGS_FOR_CYCLE:
            # 官方文档说明 kpl_list 的 tag 默认是“涨停”；这里仍显式拉取炸板/跌停池，
            # 既固定涨停池口径，也为炸板率和数据质量提示提供独立数据来源。
            optional_payload[f"kpl_list_{tag}"] = self._safe_query(
                KPL_REQUIRED_API,
                {"trade_date": trade_date_str, "tag": tag},
                KPL_FIELDS,
                quality,
                required=False,
                quality_api_name=f"kpl_list:{tag}",
            )
        prev_trade_date = self._previous_a_trade_date(trade_date)
        if prev_trade_date is not None:
            prev_trade_date_str = format_tushare_date(prev_trade_date)
            optional_payload["prev_kpl_list"] = self._safe_query(
                KPL_REQUIRED_API,
                {"trade_date": prev_trade_date_str, "tag": KPL_TAG_LIMIT_UP},
                KPL_FIELDS,
                quality,
                required=False,
                quality_api_name="kpl_list:prev_limit_up",
            )
        optional_payload["prev_trade_date"] = [
            {"trade_date": prev_trade_date.isoformat()}
        ] if prev_trade_date is not None else []
        for api_name, extra_params, fields in OPTIONAL_APIS:
            params = {"trade_date": trade_date_str, **extra_params}
            optional_payload[api_name] = self._safe_query(
                api_name, params, fields, quality, required=False
            )
        focus_codes = self._focus_ts_codes(kpl_rows, optional_payload)
        technical = self._technical_indicators(focus_codes, trade_date, quality)
        prev_quotes = self._daily_quotes_for_codes(
            [str(row.get("ts_code") or "") for row in optional_payload.get("prev_kpl_list", [])],
            trade_date,
        )
        context = self._assemble_context(
            trade_date, kpl_rows, optional_payload, technical, quality, prev_quotes
        )
        return {"data_ready": True, "context": context, "data_quality": quality}

    def _safe_query(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: tuple[str, ...],
        quality: list[dict[str, Any]],
        required: bool,
        quality_api_name: str | None = None,
    ) -> list[dict[str, Any]]:
        # 所有 Tushare 请求都由白名单常量构造，运行时只注入交易日和固定口径；
        # 权限不足或接口延迟时写入 data_quality，必需接口为空才阻止报告生成。
        quality_name = quality_api_name or api_name
        try:
            result = self.tushare_client.query(api_name, params=params, fields=list(fields))
        except Exception as exc:
            quality.append(DataQualityItem(quality_name, "FAILED", 0, str(exc)[:300]).to_dict())
            if required:
                logger.info("必需打板接口暂不可用 api=%s params=%s", api_name, params)
            return []
        rows = [self._normalize_api_row(row) for row in result.rows]
        filtered_rows = [row for row in rows if not self._is_st_stock_row(row)]
        st_filtered_count = len(rows) - len(filtered_rows)
        quality_message = (
            f"raw_rows={len(rows)}; st_filtered={st_filtered_count}" if st_filtered_count else None
        )
        quality.append(
            DataQualityItem(
                quality_name,
                "OK" if filtered_rows else "EMPTY",
                len(filtered_rows),
                quality_message,
            ).to_dict()
        )
        return filtered_rows

    def _previous_a_trade_date(self, trade_date: date) -> date | None:
        """读取指定交易日前一个 A 股交易日。

        创建日期：2026-06-10
        author: sunshengxian
        """

        # 情绪周期对照必须基于交易日而不是自然日，避免周末或节假日前后把空日期当昨日。
        return self.db.scalar(
            select(ATradeCalendar.cal_date)
            .where(ATradeCalendar.cal_date < trade_date, ATradeCalendar.is_open == 1)
            .order_by(desc(ATradeCalendar.cal_date))
            .limit(1)
        )

    def _daily_quotes_for_codes(
        self, ts_codes: list[str], trade_date: date
    ) -> dict[str, dict[str, Any]]:
        """批量读取昨日涨停股在报告交易日的行情。

        创建日期：2026-06-10
        author: sunshengxian
        """

        codes = sorted({code for code in ts_codes if code})
        if not codes:
            return {}
        # 昨日涨停溢价只需要当日开盘和涨跌幅，本地日线表有缺口时返回空映射，
        # 情绪指标会标记样本数不足而不会阻断报告生成。
        rows = self.db.scalars(
            select(ADailyQuote).where(
                ADailyQuote.ts_code.in_(codes), ADailyQuote.trade_date == trade_date
            )
        ).all()
        return {
            row.ts_code: {
                "ts_code": row.ts_code,
                "trade_date": row.trade_date.isoformat(),
                "open": row.open,
                "pre_close": row.pre_close,
                "pct_chg": row.pct_chg,
            }
            for row in rows
        }

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
        start_date = trade_date - timedelta(
            days=max(20, self.settings.limit_up_push_indicator_days)
        )
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
                f"local_rows={sum(len(rows) for rows in local_daily.values())}; "
                f"fallback_codes={len(daily_missing)}; errors={error_count}",
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
            select(ADailyBasic).where(
                ADailyBasic.ts_code.in_(ts_codes), ADailyBasic.trade_date == trade_date
            )
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
            quality.append(
                DataQualityItem("daily_basic", "OK", len(grouped), "source=local").to_dict()
            )
            return grouped
        # daily_basic 本地库可能尚未完整同步；按交易日批量拉一次全市场最新估值指标，
        # 再只保留关注股票，避免逐股请求造成调度延迟和接口压力。
        rows = self._query_indicator_api(
            "daily_basic",
            {"trade_date": format_tushare_date(trade_date)},
            DAILY_BASIC_FIELDS,
        )
        if rows is None:
            quality.append(
                DataQualityItem(
                    "daily_basic", "FAILED", len(grouped), "batch_query_failed"
                ).to_dict()
            )
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
            logger.info(
                "打板技术指标接口暂不可用 api=%s ts_code=%s", api_name, params.get("ts_code")
            )
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
        closes = [
            to_decimal(row.get("close"))
            for row in rows
            if to_decimal(row.get("close")) is not None
        ]
        amounts = [
            to_decimal(row.get("amount"))
            for row in rows
            if to_decimal(row.get("amount")) is not None
        ]
        latest = rows[-1] if rows else {}
        latest_basic = (
            sorted(basic_rows, key=lambda item: str(item.get("trade_date") or ""))[-1]
            if basic_rows
            else {}
        )
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
        prev_quotes: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        compact_rows = [
            self._compact_stock_row(row, technical.get(str(row.get("ts_code") or "")))
            for row in kpl_rows[:LIMIT_UP_CONTEXT_STOCK_LIMIT]
        ]
        focus = self._focus_rows(kpl_rows, optional_payload, technical)
        themes = self._theme_summary(compact_rows, optional_payload.get("limit_cpt_list", []))
        market_emotion = self._market_emotion(kpl_rows, optional_payload, prev_quotes or {})
        capital_signals = self._capital_signals(kpl_rows, optional_payload.get("top_list", []))
        board_status = self._board_status_summary(kpl_rows)
        raw_limit_step = optional_payload.get("limit_step", [])[
            :LIMIT_UP_CONTEXT_RAW_LIMIT_STEP_LIMIT
        ]
        raw_top_list = optional_payload.get("top_list", [])[:LIMIT_UP_CONTEXT_RAW_TOP_LIST_LIMIT]
        raw_cpt_list = optional_payload.get("limit_cpt_list", [])[
            :LIMIT_UP_CONTEXT_RAW_CPT_LIST_LIMIT
        ]
        raw_supplement = {
            "limit_step": raw_limit_step,
            "top_list": raw_top_list,
            "limit_cpt_list": raw_cpt_list,
        }
        context = {
            "trade_date": trade_date.isoformat(),
            "data_sources": [item["api_name"] for item in quality if item.get("status") == "OK"],
            "market_emotion": market_emotion,
            "themes": themes,
            "focus_stocks": focus,
            "board_status": board_status,
            "capital_signals": capital_signals,
            "limit_up_stocks": compact_rows,
            "raw_supplement": raw_supplement,
            "data_quality": quality,
        }
        # 多阶段报告需要把大涨停池按首板、两三连、高连板拆开；
        # 旧字段继续保留给现有页面和测试，新增分层上下文只服务新 pipeline。
        context["first_board_context"] = {
            "stocks": self._stocks_by_board_level(compact_rows, max_level=1),
            "themes": themes,
            "market_emotion": market_emotion,
        }
        context["chain_board_context"] = {
            "stocks": self._stocks_by_board_level(compact_rows, levels={2, 3}),
            "stocks_by_limit_type": self._stocks_by_limit_type(
                self._stocks_by_board_level(compact_rows, levels={2, 3})
            ),
            "capital_signals": capital_signals,
            "themes": themes,
            "market_emotion": market_emotion,
        }
        context["high_board_context"] = {
            "stocks": self._stocks_by_board_level(compact_rows, min_level=4),
            "stocks_by_limit_type": self._stocks_by_limit_type(
                self._stocks_by_board_level(compact_rows, min_level=4)
            ),
            "capital_signals": capital_signals,
            "themes": themes,
            "market_emotion": market_emotion,
        }
        context["market_context"] = {
            "market_emotion": market_emotion,
            "emotion_cycle": market_emotion.get("emotion_cycle"),
            "board_status": board_status,
            "themes": themes[:20],
            "data_quality": quality,
        }
        return context

    def _stocks_by_board_level(
        self,
        rows: list[dict[str, Any]],
        levels: set[int] | None = None,
        min_level: int | None = None,
        max_level: int | None = None,
    ) -> list[dict[str, Any]]:
        """按连板层级过滤股票行。

        创建日期：2026-06-05
        author: sunshengxian
        """

        selected: list[dict[str, Any]] = []
        for row in rows:
            level = self._board_level(row)
            if level <= 0:
                continue
            if levels is not None and level not in levels:
                continue
            if min_level is not None and level < min_level:
                continue
            if max_level is not None and level > max_level:
                continue
            selected.append(row)
        return selected

    def _board_level(self, row: dict[str, Any]) -> int:
        """从 KPL 状态文本中识别首板、连板和“N天M板”层级。

        创建日期：2026-06-05
        author: sunshengxian
        """

        status = str(
            row.get("status")
            or row.get("tag")
            or row.get("board_status")
            or row.get("up_stat")
            or ""
        )
        day_board_match = re.search(r"\d+\s*天\s*(\d+)\s*板", status)
        if day_board_match:
            return int(day_board_match.group(1))
        match = re.search(r"(\d+)\s*连", status)
        if match:
            return int(match.group(1))
        # tag 只代表 KPL 查询口径，不能证明该行一定是首板；
        # 缺少 status 时按未识别处理，避免上游字段缺失时把未知股票混入首板池。
        if "首" in status or "1连" in status or "一连" in status:
            return 1
        return 0

    def _stocks_by_limit_type(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """按 10cm/20cm 等涨停制度分组候选股票。

        创建日期：2026-06-10
        author: sunshengxian
        """

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("limit_type") or "unknown")
            grouped.setdefault(key, []).append(row)
        return grouped

    def _focus_ts_codes(
        self,
        kpl_rows: list[dict[str, Any]],
        optional_payload: dict[str, list[dict[str, Any]]],
    ) -> list[str]:
        seen: set[str] = set()
        codes: list[str] = []
        for row in kpl_rows:
            # 技术指标补数与分层上下文共用 _board_level 口径，
            # 避免“N天M板”进了候选池却缺少 technical。
            if self._board_level(row) >= 1:
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
        return [
            self._compact_stock_row(row, technical.get(str(row.get("ts_code") or "")))
            for row in rows[:LIMIT_UP_CONTEXT_FOCUS_STOCK_LIMIT]
        ]

    def _compact_stock_row(
        self, row: dict[str, Any], indicator: dict[str, Any] | None
    ) -> dict[str, Any]:
        """压缩单只涨停股字段并补充封流比等衍生指标。

        创建日期：2026-06-10
        author: sunshengxian
        """

        indicator = indicator or {}
        limit_order = to_decimal(row.get("limit_order") or row.get("fd_amount"))
        free_float = to_decimal(
            row.get("free_float") or row.get("float_mv") or indicator.get("circ_mv")
        )
        seal_ratio = self._safe_pct_ratio(limit_order, free_float)
        compact = {
            "ts_code": row.get("ts_code"),
            "name": row.get("name"),
            "status": row.get("status"),
            "tag": row.get("tag"),
            "theme": row.get("theme"),
            "board_level": self._board_level(row),
            "limit_type": self._limit_type(row),
            "market_type": row.get("market_type"),
            "limit_up_reason": row.get("lu_desc"),
            "first_limit_time": row.get("lu_time") or row.get("first_time"),
            "last_limit_time": row.get("last_time"),
            "open_time": row.get("open_time"),
            "open_times": row.get("open_times"),
            "limit_order": row.get("limit_order"),
            "max_limit_order": row.get("lu_limit_order"),
            "seal_ratio_pct": self._decimal_to_float(seal_ratio),
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
            "technical": indicator,
        }
        return compact

    def _theme_summary(
        self, kpl_rows: list[dict[str, Any]], cpt_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        counter: dict[str, dict[str, Any]] = {}
        for row in kpl_rows:
            themes = [
                item.strip()
                for item in re.split(r"[,，;；/、]", str(row.get("theme") or ""))
                if item.strip()
            ]
            for theme in themes or ["未标注题材"]:
                bucket = counter.setdefault(
                    theme,
                    {"theme": theme, "stock_count": 0, "stocks": [], "reasons": [], "ladder": []},
                )
                bucket["stock_count"] += 1
                if len(bucket["stocks"]) < 12:
                    bucket["stocks"].append(row.get("name") or row.get("ts_code"))
                reason = row.get("limit_up_reason") or row.get("lu_desc")
                if reason and len(bucket["reasons"]) < 8:
                    bucket["reasons"].append(reason)
                bucket["ladder"].append(
                    {
                        "ts_code": row.get("ts_code"),
                        "name": row.get("name"),
                        "board_level": row.get("board_level") or self._board_level(row),
                        "limit_type": row.get("limit_type") or self._limit_type(row),
                        "seal_ratio_pct": row.get("seal_ratio_pct"),
                    }
                )
        cpt_by_name = {str(row.get("name") or ""): row for row in cpt_rows}
        themes = sorted(counter.values(), key=lambda item: item["stock_count"], reverse=True)
        for item in themes:
            # 题材内梯队只保留前 5 个高辨识度位置，帮助模型判断龙一、龙二和补位关系。
            item["ladder"] = sorted(
                item["ladder"],
                key=lambda stock: (
                    int(stock.get("board_level") or 0),
                    float(stock.get("seal_ratio_pct") or 0),
                ),
                reverse=True,
            )[:5]
            item["board_stats"] = cpt_by_name.get(item["theme"], {})
        return themes[:LIMIT_UP_CONTEXT_THEME_LIMIT]

    def _capital_signals(
        self, kpl_rows: list[dict[str, Any]], top_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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
        return sorted(signals, key=lambda item: float(item.get("net_amount") or 0), reverse=True)[
            :LIMIT_UP_CONTEXT_CAPITAL_SIGNAL_LIMIT
        ]

    def _board_status_summary(self, kpl_rows: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, int] = {}
        for row in kpl_rows:
            key = str(row.get("status") or row.get("tag") or "未标注")
            summary[key] = summary.get(key, 0) + 1
        return {
            "counts": summary,
            "top_status": sorted(summary.items(), key=lambda item: item[1], reverse=True)[
                :LIMIT_UP_CONTEXT_BOARD_STATUS_LIMIT
            ],
        }

    def _market_emotion(
        self,
        kpl_rows: list[dict[str, Any]],
        optional_payload: dict[str, list[dict[str, Any]]],
        prev_quotes: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        levels = [self._board_level(row) for row in kpl_rows]
        valid_levels = [level for level in levels if level > 0]
        ladder_distribution = self._ladder_distribution(valid_levels)
        broken_rows = optional_payload.get(f"kpl_list_{KPL_TAG_BROKEN}", [])
        prev_rows = optional_payload.get("prev_kpl_list", [])
        prev_date_rows = optional_payload.get("prev_trade_date", [])
        emotion_cycle = self._emotion_cycle_metrics(
            today_rows=kpl_rows,
            broken_rows=broken_rows,
            prev_rows=prev_rows,
            prev_quotes=prev_quotes or {},
            prev_trade_date=str(prev_date_rows[0].get("trade_date")) if prev_date_rows else None,
        )
        return {
            "kpl_row_count": len(kpl_rows),
            "limit_up_count": len(kpl_rows),
            "second_board_count": sum(1 for level in valid_levels if level == 2),
            "third_board_count": sum(1 for level in valid_levels if level == 3),
            "chain_ladder_count": len(optional_payload.get("limit_step", [])),
            "highest_chain": max(valid_levels) if valid_levels else None,
            "unrecognized_board_count": len([level for level in levels if level <= 0]),
            "ladder_distribution": ladder_distribution,
            "broken_board_count": len(broken_rows),
            "limit_down_count": len(optional_payload.get(f"kpl_list_{KPL_TAG_LIMIT_DOWN}", [])),
            "emotion_cycle": emotion_cycle,
        }

    def _ladder_distribution(self, levels: list[int]) -> dict[str, int]:
        """按板高生成连板梯队分布。

        创建日期：2026-06-10
        author: sunshengxian
        """

        distribution: dict[str, int] = {}
        for level in levels:
            key = f"{level}板" if level < 4 else "4板+"
            distribution[key] = distribution.get(key, 0) + 1
        return distribution

    def _emotion_cycle_metrics(
        self,
        today_rows: list[dict[str, Any]],
        broken_rows: list[dict[str, Any]],
        prev_rows: list[dict[str, Any]],
        prev_quotes: dict[str, dict[str, Any]],
        prev_trade_date: str | None,
    ) -> dict[str, Any]:
        """计算炸板率、晋级率和昨日涨停溢价等情绪周期指标。

        创建日期：2026-06-10
        author: sunshengxian
        """

        today_levels = {str(row.get("ts_code") or ""): self._board_level(row) for row in today_rows}
        prev_levels = {str(row.get("ts_code") or ""): self._board_level(row) for row in prev_rows}
        advancement: dict[str, dict[str, Any]] = {}
        for base_level in (1, 2, 3):
            prev_codes = {
                code for code, level in prev_levels.items() if code and level == base_level
            }
            advanced = [code for code in prev_codes if today_levels.get(code) == base_level + 1]
            advancement[f"{base_level}进{base_level + 1}"] = {
                "prev_count": len(prev_codes),
                "advanced_count": len(advanced),
                "rate_pct": self._decimal_to_float(
                    self._safe_pct_ratio(Decimal(len(advanced)), Decimal(len(prev_codes)))
                ),
            }
        quote_metrics = self._prev_limit_up_premium_metrics(prev_rows, prev_quotes)
        today_codes = self._row_code_set(today_rows)
        broken_codes = self._row_code_set(broken_rows)
        broken_only_codes = broken_codes - today_codes
        denominator_codes = today_codes | broken_codes
        denominator_count = (
            len(denominator_codes) if denominator_codes else len(today_rows) + len(broken_rows)
        )
        broken_numerator_count = len(broken_only_codes) if broken_codes else 0
        broken_rate = self._safe_pct_ratio(
            Decimal(broken_numerator_count), Decimal(denominator_count)
        )
        return {
            "prev_trade_date": prev_trade_date,
            "broken_board_count": len(broken_rows),
            "broken_board_unique_count": len(broken_codes),
            "broken_board_only_count": broken_numerator_count,
            "limit_up_or_broken_unique_count": denominator_count,
            "broken_board_rate_pct": self._decimal_to_float(broken_rate),
            "broken_board_rate_scope": "炸板池剔除已回封涨停代码后 / 涨停与炸板代码并集",
            "advancement": advancement,
            "prev_limit_up_premium": quote_metrics,
            "highest_chain_change": self._highest_chain_change(today_rows, prev_rows),
        }

    def _row_code_set(self, rows: list[dict[str, Any]]) -> set[str]:
        """提取股票代码集合，用于跨池去重统计。

        创建日期：2026-06-11
        author: sunshengxian
        """

        # Tushare 多个 KPL tag 池可能存在回封股票交集；情绪指标按代码集合去重，避免重复计数。
        return {
            str(row.get("ts_code") or "").strip()
            for row in rows
            if str(row.get("ts_code") or "").strip()
        }

    def _prev_limit_up_premium_metrics(
        self,
        prev_rows: list[dict[str, Any]],
        prev_quotes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """统计昨日涨停股今日平均涨幅和高开率。

        创建日期：2026-06-10
        author: sunshengxian
        """

        pct_values: list[Decimal] = []
        high_open_count = 0
        sample_count = 0
        prev_codes = sorted(
            {str(row.get("ts_code") or "") for row in prev_rows if row.get("ts_code")}
        )
        for code in prev_codes:
            quote = prev_quotes.get(code)
            if not quote:
                continue
            pct = to_decimal(quote.get("pct_chg"))
            if pct is not None:
                pct_values.append(pct)
            open_price = to_decimal(quote.get("open"))
            pre_close = to_decimal(quote.get("pre_close"))
            if open_price is not None and pre_close is not None:
                sample_count += 1
                if open_price > pre_close:
                    high_open_count += 1
        return {
            "prev_limit_up_count": len(prev_codes),
            "quote_sample_count": len(pct_values),
            "high_open_sample_count": sample_count,
            "avg_pct_chg": self._decimal_to_float(self._avg_decimal(pct_values)),
            "high_open_rate_pct": self._decimal_to_float(
                self._safe_pct_ratio(Decimal(high_open_count), Decimal(sample_count))
            ),
        }

    def _highest_chain_change(
        self, today_rows: list[dict[str, Any]], prev_rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """比较今日和昨日最高连板高度变化。

        创建日期：2026-06-10
        author: sunshengxian
        """

        today_high = max([self._board_level(row) for row in today_rows], default=0) or None
        prev_high = max([self._board_level(row) for row in prev_rows], default=0) or None
        change = (
            today_high - prev_high if today_high is not None and prev_high is not None else None
        )
        return {"today": today_high, "previous": prev_high, "change": change}

    def _safe_pct_ratio(
        self, numerator: Decimal | None, denominator: Decimal | None
    ) -> Decimal | None:
        """把两个金额或数量安全转换为百分比。

        创建日期：2026-06-10
        author: sunshengxian
        """

        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator * Decimal("100")

    def _limit_type(self, row: dict[str, Any]) -> str:
        """识别 10cm/20cm 等涨停制度。

        创建日期：2026-06-10
        author: sunshengxian
        """

        raw_market_type = str(row.get("market_type") or "").lower()
        code = str(row.get("ts_code") or "")
        if "20" in raw_market_type or code.startswith(("300", "301", "688")):
            return "20cm"
        if "30" in raw_market_type or code.startswith(("8", "4", "920")):
            return "30cm"
        return "10cm"

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _generate_llm_report(self, context: dict[str, Any]) -> tuple[str, str]:
        """生成多阶段打板报告。

        创建日期：2026-06-05
        author: sunshengxian
        """

        # 报告生成拆成多个小上下文阶段，避免把首板、两连三连、高连板和补充原始数据一次性塞给 LLM；
        # 各阶段输出会写回 context.pipeline，供后台详情页展示选股名单和阶段质量。
        return self._generate_multi_stage_llm_report(context)

    def _generate_multi_stage_llm_report(self, context: dict[str, Any]) -> tuple[str, str]:
        """按首板、两三连、高连和最终汇总多轮生成报告。

        创建日期：2026-06-05
        author: sunshengxian
        """

        trade_date = self._context_trade_date(context)
        stage_quality: list[dict[str, Any]] = []
        first_board = self._run_json_stage(
            LIMIT_UP_STAGE_FIRST_BOARD,
            {
                "trade_date": context.get("trade_date"),
                "first_board_context": context.get("first_board_context") or {},
                "market_context": context.get("market_context") or {},
            },
            self._stage_system_prompt("首板题材发酵分析师"),
            self._first_board_prompt(context),
            self._fallback_first_board_stage(context),
            stage_quality,
        )
        # 首板个股精选：在题材级结论之后挑选少量首板重点标的（默认上限 5），
        # 与两三连/高连板共用筹码补数与重点分析链路；强题材代表股优先，由提示词约束。
        selected_first_board = self._select_stage_stocks(
            self._run_json_stage(
                LIMIT_UP_STAGE_FIRST_BOARD_SELECTION,
                {
                    "trade_date": context.get("trade_date"),
                    "first_board_context": context.get("first_board_context") or {},
                    "theme_candidates": first_board.get("theme_candidates") or [],
                },
                self._stage_system_prompt("首板重点个股筛选分析师"),
                self._first_board_selection_prompt(context, first_board),
                self._fallback_selection_stage(
                    context.get("first_board_context") or {},
                    self.settings.limit_up_push_first_board_focus_stock_limit,
                    "first_board",
                ),
                stage_quality,
            ),
            list((context.get("first_board_context") or {}).get("stocks") or []),
            self.settings.limit_up_push_first_board_focus_stock_limit,
        )
        selected_chain = self._select_stage_stocks(
            self._run_json_stage(
                LIMIT_UP_STAGE_CHAIN_SELECTION,
                {
                    "trade_date": context.get("trade_date"),
                    "chain_board_context": context.get("chain_board_context") or {},
                },
                self._stage_system_prompt("两连三连候选筛选分析师"),
                self._chain_selection_prompt(context),
                self._fallback_selection_stage(
                    context.get("chain_board_context") or {},
                    self.settings.limit_up_push_chain_focus_stock_limit,
                    "chain",
                ),
                stage_quality,
            ),
            list((context.get("chain_board_context") or {}).get("stocks") or []),
            self.settings.limit_up_push_chain_focus_stock_limit,
        )
        selected_high = self._select_stage_stocks(
            self._run_json_stage(
                LIMIT_UP_STAGE_HIGH_BOARD_SELECTION,
                {
                    "trade_date": context.get("trade_date"),
                    "high_board_context": context.get("high_board_context") or {},
                },
                self._stage_system_prompt("高连板与龙头筛选分析师"),
                self._high_board_selection_prompt(context),
                self._fallback_selection_stage(
                    context.get("high_board_context") or {},
                    self.settings.limit_up_push_high_board_focus_stock_limit,
                    "high_board",
                ),
                stage_quality,
            ),
            list((context.get("high_board_context") or {}).get("stocks") or []),
            self.settings.limit_up_push_high_board_focus_stock_limit,
        )
        # 补数去重集合扩入首板入选（5+20+10）；仅入选股触发 cyq 接口，单股失败不阻塞。
        supplement_map = self._build_selected_stock_supplements(
            trade_date,
            self._dedupe_selected_stocks(
                [*selected_first_board, *selected_chain, *selected_high]
            ),
            stage_quality,
        )
        first_board_focus = self._run_text_stage(
            LIMIT_UP_STAGE_FIRST_BOARD_FOCUS,
            {
                "trade_date": context.get("trade_date"),
                "selected_first_board_stocks": selected_first_board,
                "supplements": supplement_map,
                "market_context": context.get("market_context") or {},
            },
            self._stage_system_prompt("首板重点个股分析师"),
            self._first_board_focus_prompt(context, selected_first_board, supplement_map),
            stage_quality,
        )
        chain_focus = self._run_text_stage(
            LIMIT_UP_STAGE_CHAIN_FOCUS,
            {
                "trade_date": context.get("trade_date"),
                "selected_chain_stocks": selected_chain,
                "supplements": supplement_map,
                "market_context": context.get("market_context") or {},
            },
            self._stage_system_prompt("两连三连重点接力分析师"),
            self._chain_focus_prompt(context, selected_chain, supplement_map),
            stage_quality,
        )
        high_focus = self._run_text_stage(
            LIMIT_UP_STAGE_HIGH_BOARD_FOCUS,
            {
                "trade_date": context.get("trade_date"),
                "selected_high_board_stocks": selected_high,
                "supplements": supplement_map,
                "market_context": context.get("market_context") or {},
            },
            self._stage_system_prompt("高连板龙头周期分析师"),
            self._high_board_focus_prompt(context, selected_high, supplement_map),
            stage_quality,
        )
        final_input = {
            "trade_date": context.get("trade_date"),
            "market_context": context.get("market_context") or {},
            "first_board": first_board,
            "selected_first_board_stocks": self._stocks_for_final_prompt(
                selected_first_board, supplement_map
            ),
            "selected_chain_stocks": self._stocks_for_final_prompt(selected_chain, supplement_map),
            "selected_high_board_stocks": self._stocks_for_final_prompt(
                selected_high, supplement_map
            ),
            "first_board_focus_html": first_board_focus.get("html_fragment"),
            "chain_focus_html": chain_focus.get("html_fragment"),
            "high_board_focus_html": high_focus.get("html_fragment"),
        }
        final_stage = self._run_text_stage(
            LIMIT_UP_STAGE_FINAL_REPORT,
            final_input,
            self._limit_up_system_prompt(),
            self._final_report_prompt(final_input),
            stage_quality,
        )
        context["pipeline"] = {
            "version": self.settings.limit_up_push_final_prompt_version,
            "selected_first_board_stocks": selected_first_board,
            "selected_chain_stocks": selected_chain,
            "selected_high_board_stocks": selected_high,
            "stage_quality": stage_quality,
            "first_board": first_board,
            "first_board_focus_html": first_board_focus.get("html_fragment"),
            "chain_focus_html": chain_focus.get("html_fragment"),
            "high_board_focus_html": high_focus.get("html_fragment"),
            "stock_supplements": supplement_map,
        }
        context["data_quality"] = [*(context.get("data_quality") or []), *stage_quality]
        raw_report = str(final_stage.get("content") or final_stage.get("html_fragment") or "")
        return self._normalize_report_html(raw_report), raw_report

    def _run_json_stage(
        self,
        stage_key: str,
        stage_input: dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        fallback_payload: dict[str, Any],
        stage_quality: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """执行要求 JSON 输出的阶段，失败时使用确定性兜底。

        创建日期：2026-06-05
        author: sunshengxian
        """

        cached = self._stage_cache_payload(stage_key, stage_input)
        if cached is not None:
            stage_quality.append(self._stage_quality_item(stage_key, "CACHE_HIT", "复用阶段缓存"))
            return cached
        try:
            content = self._chat_completion_with_reasoning(
                user_prompt, system_prompt, json_mode=True
            )
            payload = self._extract_json_payload(content)
            if payload is None:
                payload = fallback_payload
                payload["parse_fallback"] = True
                stage_quality.append(
                    self._stage_quality_item(
                        stage_key, "PARSE_FALLBACK", "LLM JSON 解析失败，使用确定性兜底"
                    )
                )
            else:
                stage_quality.append(
                    self._stage_quality_item(stage_key, "OK", "阶段 LLM 输出已解析")
                )
            payload.setdefault("raw_content", content)
            self._save_stage_cache(stage_key, stage_input, payload, payload.get("html_fragment"))
            return payload
        except Exception as exc:
            fallback_payload["error_fallback"] = True
            fallback_payload["error_message"] = str(exc)[:300]
            stage_quality.append(
                self._stage_quality_item(stage_key, "FAILED_FALLBACK", str(exc)[:300])
            )
            self._save_stage_cache(
                stage_key,
                stage_input,
                fallback_payload,
                fallback_payload.get("html_fragment"),
                failed=True,
            )
            return fallback_payload

    def _run_text_stage(
        self,
        stage_key: str,
        stage_input: dict[str, Any],
        system_prompt: str,
        user_prompt: str,
        stage_quality: list[dict[str, Any]],
        llm_phase: str = LIMIT_UP_LLM_PHASE,
        skip_cache: bool = False,
    ) -> dict[str, Any]:
        """执行 HTML 或自然语言输出阶段。

        skip_cache=True 时跳过缓存读取强制重调 LLM（管理员对建议质量不满意的重生成场景），
        新结果仍写回同键缓存行覆盖旧内容。

        创建日期：2026-06-05
        author: sunshengxian
        """

        cached = None if skip_cache else self._stage_cache_payload(stage_key, stage_input)
        if cached is not None:
            stage_quality.append(self._stage_quality_item(stage_key, "CACHE_HIT", "复用阶段缓存"))
            return cached
        try:
            content = self._chat_completion_with_reasoning(
                user_prompt, system_prompt, phase=llm_phase
            )
        except Exception as exc:
            # 重点分析类文本阶段失败可降级为确定性观察表，报告仍能 READY；
            # FINAL_REPORT 等合成阶段失败必须抛出，让整份报告进入 FAILED 重试。
            if stage_key not in {
                LIMIT_UP_STAGE_FIRST_BOARD_FOCUS,
                LIMIT_UP_STAGE_CHAIN_FOCUS,
                LIMIT_UP_STAGE_HIGH_BOARD_FOCUS,
            }:
                raise
            payload = self._fallback_text_stage(stage_key, stage_input, str(exc)[:300])
            stage_quality.append(
                self._stage_quality_item(stage_key, "FAILED_FALLBACK", str(exc)[:300])
            )
            self._save_stage_cache(
                stage_key, stage_input, payload, payload["html_fragment"], failed=True
            )
            return payload
        payload = {"content": content, "html_fragment": self._html_fragment(content)}
        stage_quality.append(self._stage_quality_item(stage_key, "OK", "阶段 HTML 已生成"))
        self._save_stage_cache(stage_key, stage_input, payload, payload["html_fragment"])
        return payload

    def _fallback_text_stage(
        self, stage_key: str, stage_input: dict[str, Any], error_message: str
    ) -> dict[str, Any]:
        """构造重点分析文本阶段的确定性降级 HTML。

        创建日期：2026-06-10
        author: sunshengxian
        """

        rows = (
            stage_input.get("selected_first_board_stocks")
            or stage_input.get("selected_chain_stocks")
            or stage_input.get("selected_high_board_stocks")
            or []
        )
        # 降级表标题按阶段区分，便于在报告中辨认是哪个重点阶段降级。
        if stage_key == LIMIT_UP_STAGE_FIRST_BOARD_FOCUS:
            title = "首板重点个股观察"
        elif stage_key == LIMIT_UP_STAGE_CHAIN_FOCUS:
            title = "两连三连重点接力"
        else:
            title = "高连板与龙头观察"
        table_rows = []
        for row in rows:
            selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
            code = str(row.get("ts_code") or "")
            supplement = (
                (stage_input.get("supplements") or {}).get(code, {})
                if isinstance(stage_input.get("supplements"), dict)
                else {}
            )
            cyq_summary = supplement.get("cyq_summary") if isinstance(supplement, dict) else {}
            reason_text = str(
                selection.get("selection_reason")
                or selection.get("leader_role")
                or "按确定性规则保留观察"
            )
            premium_text = str((cyq_summary or {}).get("next_day_premium_bias") or "缺失")
            table_rows.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('name') or code))}</td>"
                f"<td>{html.escape(str(row.get('status') or '未识别'))}</td>"
                f"<td>{html.escape(str(row.get('theme') or '未标注'))}</td>"
                f"<td>{html.escape(reason_text)}</td>"
                f"<td>{html.escape(premium_text)}</td>"
                "</tr>"
            )
        body = "".join(table_rows) or "<tr><td colspan=\"5\">暂无入选标的</td></tr>"
        fragment = (
            f"<h3>{title}</h3>"
            "<p>LLM 重点分析不可用，已按入选理由、连板状态和筹码摘要生成降级观察表。"
            f"错误摘要：{html.escape(error_message)}</p>"
            "<table><thead><tr><th>股票</th><th>状态</th><th>题材</th><th>保留原因</th><th>筹码溢价</th></tr></thead><tbody>"
            f"{body}</tbody></table>"
        )
        return {
            "content": fragment,
            "html_fragment": fragment,
            "error_fallback": True,
            "error_message": error_message,
        }

    def _stage_cache_payload(
        self, stage_key: str, stage_input: dict[str, Any]
    ) -> dict[str, Any] | None:
        """按阶段输入哈希读取 READY 缓存。

        创建日期：2026-06-05
        author: sunshengxian
        """

        if not self.settings.limit_up_push_stage_cache_enabled:
            return None
        row = self.db.scalar(
            select(LimitUpAnalysisStageCache)
            .where(
                LimitUpAnalysisStageCache.trade_date == self._context_trade_date(stage_input),
                LimitUpAnalysisStageCache.stage_key == stage_key,
                LimitUpAnalysisStageCache.model == self.settings.limit_up_push_model,
                LimitUpAnalysisStageCache.prompt_version == self._stage_prompt_version(stage_key),
                LimitUpAnalysisStageCache.input_hash == self._snapshot_hash(stage_input),
                LimitUpAnalysisStageCache.status == ANALYSIS_STATUS_READY,
            )
            .order_by(desc(LimitUpAnalysisStageCache.id))
            .limit(1)
        )
        if row is None:
            return None
        payload = self._json_loads_dict(row.output_json)
        return payload if isinstance(payload, dict) else None

    def _save_stage_cache(
        self,
        stage_key: str,
        stage_input: dict[str, Any],
        payload: dict[str, Any],
        content_html: str | None,
        failed: bool = False,
    ) -> None:
        """写入阶段缓存并保持同输入幂等。

        创建日期：2026-06-05
        author: sunshengxian
        """

        if not self.settings.limit_up_push_stage_cache_enabled:
            return
        input_hash = self._snapshot_hash(stage_input)
        cache = self.db.scalar(
            select(LimitUpAnalysisStageCache)
            .where(
                LimitUpAnalysisStageCache.trade_date == self._context_trade_date(stage_input),
                LimitUpAnalysisStageCache.stage_key == stage_key,
                LimitUpAnalysisStageCache.model == self.settings.limit_up_push_model,
                LimitUpAnalysisStageCache.prompt_version == self._stage_prompt_version(stage_key),
                LimitUpAnalysisStageCache.input_hash == input_hash,
            )
            .limit(1)
        )
        if cache is None:
            cache = LimitUpAnalysisStageCache(
                analysis_id=getattr(self, "_active_limit_up_analysis_id", None),
                trade_date=self._context_trade_date(stage_input),
                stage_key=stage_key,
                model=self.settings.limit_up_push_model,
                prompt_version=self._stage_prompt_version(stage_key),
                input_hash=input_hash,
            )
            self.db.add(cache)
        cache.status = ANALYSIS_STATUS_FAILED if failed else ANALYSIS_STATUS_READY
        cache.output_json = self._json_dumps(payload)
        cache.content_html = content_html
        cache.error_message = str(payload.get("error_message") or "")[:1000] if failed else None
        cache.generated_at = self._now_naive()
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()

    def _stage_system_prompt(self, role_name: str) -> str:
        """生成多阶段分析的系统提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        return (
            f"你是专注 A 股短线生态的{role_name}。"
            "只能基于输入数据分析，不编造精确数值；数据缺失时说明不确定性。"
            "先参考 emotion_cycle 判断启动期/发酵期/高潮期/分歧期/退潮期/冰点期，"
            "并用周期定位约束个股结论；退潮或冰点不得给出激进接力口径。"
            "涉及推荐或观察名单时必须提示高波动、断板、回撤和流动性风险。"
        )

    def _first_board_prompt(self, context: dict[str, Any]) -> str:
        """生成首板题材发酵阶段提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        stage_input = {
            "first_board_context": context.get("first_board_context"),
            "market_context": context.get("market_context"),
        }
        return (
            "请只分析首板题材发酵价值，不要逐股长篇展开。输出严格 JSON："
            "{\"html_fragment\":\"HTML片段\",\"theme_candidates\":[{\"theme\":\"题材\","
            "\"representative_stocks\":[\"股票\"],\"fermentation_value\":\"强/中/弱\","
            "\"reason\":\"理由\"}],\"risk_flags\":[\"风险\"]}。\n\n"
            f"输入数据：\n{self._json_dumps(stage_input)}"
        )

    def _first_board_selection_prompt(
        self, context: dict[str, Any], first_board: dict[str, Any]
    ) -> str:
        """生成首板重点个股筛选提示词。

        首板池远大于连板池且次日溢价不确定性更高，因此上限默认 5 只、强调"宁缺毋滥"；
        题材发酵价值取自 FIRST_BOARD 阶段输出，强题材代表股优先入选。

        创建日期：2026-06-12
        author: claude
        """

        limit = self.settings.limit_up_push_first_board_focus_stock_limit
        stage_input = {
            "first_board_context": context.get("first_board_context") or {},
            "theme_candidates": first_board.get("theme_candidates") or [],
        }
        return (
            f"请从首板（当日首次涨停）股票中挑选最多 {limit} 只重点观察标的，宁缺毋滥，"
            "不强制选满；首板次日溢价失败率高于连板接力，只保留题材发酵价值高、"
            "有晋级二板潜力的标的。筛选维度：题材发酵价值与题材内卡位"
            "（theme_candidates 中 fermentation_value 为强的题材代表股优先）、"
            "封板质量(封流比+首封时间+开板次数)、资金信号、辨识度与晋级二板潜力；"
            "尾盘 14:30 后首封或多次开板需降级或剔除。"
            "输出严格 JSON：{\"selected_stocks\":[{\"ts_code\":\"代码\",\"name\":\"名称\","
            "\"board_status\":\"首板\",\"theme\":\"题材\",\"theme_role\":\"题材龙头/板块前排/跟风\","
            "\"score_detail\":{\"theme_position\":\"强/中/弱\",\"seal_quality\":\"强/中/弱\",\"capital_signal\":\"强/中/弱\",\"promotion_potential\":\"强/中/弱\"},"
            "\"selection_reason\":\"入选理由\",\"priority\":1}],\"excluded_summary\":\"剔除摘要\"}。\n\n"
            f"输入数据：\n{self._json_dumps(stage_input)}"
        )

    def _first_board_focus_prompt(
        self,
        context: dict[str, Any],
        selected_first_board: list[dict[str, Any]],
        supplements: dict[str, Any],
    ) -> str:
        """生成首板重点个股分析提示词。

        口径对齐两三连重点阶段（每股限 150 字、必须输出次日竞价观察清单），
        并额外要求强调首板接力的更高不确定性，避免被读成低风险建议。

        创建日期：2026-06-12
        author: claude
        """

        stage_input = {
            "selected_first_board_stocks": selected_first_board,
            "supplements": supplements,
            "market_context": context.get("market_context"),
        }
        return (
            "请重点分析入选的首板股票，每只不超过 150 字，禁止复述输入原文。"
            "分别覆盖题材发酵逻辑、晋级二板可能性、下一个交易日溢价可能性、"
            "触发条件、失败/止损条件、筹码压力和风险提示。"
            "必须输出次日竞价观察清单：给出竞价弱于多少放弃、合理高开区间、过高开警惕点。"
            "必须显著提示首板接力的不确定性高于连板接力，参与方式与试错幅度要更克制；"
            "用 emotion_cycle 约束口径，退潮或冰点只给观察不给参与建议。"
            "输出 HTML 片段，使用 h3、p、ul、table、strong，不要输出 html/body。\n\n"
            f"输入数据：\n{self._json_dumps(stage_input)}"
        )

    def _chain_selection_prompt(self, context: dict[str, Any]) -> str:
        """生成两连三连候选筛选提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        limit = self.settings.limit_up_push_chain_focus_stock_limit
        return (
            f"请从两连、三连股票中挑选最多 {limit} 只进入筹码补数和重点分析。"
            "如果总数不超过上限，可以全部入选，也可以剔除明显弱票；如果超过上限，"
            "按题材地位、封板质量(封流比+首封时间+开板次数)、资金信号、筹码/技术状态和辨识度筛选。"
            "20cm 连板按更高空间等级评估，但要同步下调断板回撤容忍度；尾盘 14:30 后首封需降级。"
            "输出严格 JSON：{\"selected_stocks\":[{\"ts_code\":\"代码\",\"name\":\"名称\","
            "\"board_status\":\"2连板/3连板\",\"theme\":\"题材\",\"theme_role\":\"板块前排/龙头/跟风\","
            "\"score_detail\":{\"theme_position\":\"强/中/弱\",\"seal_quality\":\"强/中/弱\",\"capital_signal\":\"强/中/弱\",\"chip_or_technical\":\"强/中/弱\"},"
            "\"selection_reason\":\"入选理由\",\"priority\":1}],\"excluded_summary\":\"剔除摘要\"}。\n\n"
            f"输入数据：\n{self._json_dumps(context.get('chain_board_context') or {})}"
        )

    def _high_board_selection_prompt(self, context: dict[str, Any]) -> str:
        """生成高连板候选筛选提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        limit = self.settings.limit_up_push_high_board_focus_stock_limit
        return (
            f"请从四连及以上、空间板、题材龙头和高辨识度股票中挑选最多 {limit} 只高连板重点标的。"
            "必须同时判断空间地位、题材带动性、高位风险、20cm/10cm制度差异和首封时间质量。"
            "输出严格 JSON："
            "{\"selected_stocks\":[{\"ts_code\":\"代码\",\"name\":\"名称\",\"board_status\":\"5连板\","
            "\"theme\":\"题材\",\"leader_role\":\"空间板/题材龙头/高辨识度\","
            "\"score_detail\":{\"space_status\":\"强/中/弱\",\"theme_leadership\":\"强/中/弱\",\"seal_quality\":\"强/中/弱\",\"risk_control\":\"强/中/弱\"},"
            "\"selection_reason\":\"入选理由\",\"risk_level\":\"高/中/低\"}],"
            "\"high_board_cycle_view\":\"高连板周期判断\"}。\n\n"
            f"输入数据：\n{self._json_dumps(context.get('high_board_context') or {})}"
        )

    def _chain_focus_prompt(
        self,
        context: dict[str, Any],
        selected_chain: list[dict[str, Any]],
        supplements: dict[str, Any],
    ) -> str:
        """生成两连三连重点分析提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        stage_input = {
            "selected_chain_stocks": selected_chain,
            "supplements": supplements,
            "market_context": context.get("market_context"),
        }
        return (
            "请重点分析入选的两连、三连股票，每只不超过 150 字，禁止复述输入原文。"
            "分别覆盖晋级三板/四板可能性、下一个交易日溢价可能性、触发条件、失败条件、筹码压力和风险提示。"
            "必须输出次日竞价观察清单：给出竞价弱于多少放弃、合理高开区间、过高开警惕点。"
            "20cm 标的要提示更深断板回撤，尾盘首封或多次开板要降级。"
            "输出 HTML 片段，使用 h3、p、ul、table、strong，不要输出 html/body。\n\n"
            f"输入数据：\n{self._json_dumps(stage_input)}"
        )

    def _high_board_focus_prompt(
        self,
        context: dict[str, Any],
        selected_high: list[dict[str, Any]],
        supplements: dict[str, Any],
    ) -> str:
        """生成高连板与龙头重点分析提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        stage_input = {
            "selected_high_board_stocks": selected_high,
            "supplements": supplements,
            "market_context": context.get("market_context"),
        }
        return (
            "请分析入选高连板和龙头标的，每只不超过 150 字，"
            "允许给出重点观察、谨慎观察、放弃观察分层，"
            "但必须显著提示高位接力、断板、回撤和流动性风险。重点判断空间板地位、"
            "题材带动性、分歧承接和下一个交易日溢价/冲高可能性。"
            "必须输出次日竞价观察清单，并用 emotion_cycle 约束高位接力口径。输出 HTML 片段，"
            "不要输出 html/body。\n\n"
            f"输入数据：\n{self._json_dumps(stage_input)}"
        )

    def _final_report_prompt(self, final_input: dict[str, Any]) -> str:
        """生成最终报告合成提示词。

        创建日期：2026-06-05
        author: sunshengxian
        """

        return (
            "请把以下阶段结果合成为一份完整中文打板复盘 HTML 报告。必须先根据 emotion_cycle 判断"
            "启动期/发酵期/高潮期/分歧期/退潮期/冰点期，并说明依据；随后包含："
            "市场情绪概览、首板题材发酵价值与首板重点个股、"
            "两连三连重点观察与次日竞价/溢价判断、"
            "高连板与龙头接力观察、反证信号和风险提示、最后总结。"
            "首板重点个股小节使用 selected_first_board_stocks 与 first_board_focus_html，"
            "并提示首板接力不确定性高于连板接力；该名单为空时保留小节并说明当日无首板精选。"
            "只输出纯 HTML 片段，使用 h2/h3、p、ul、ol、table、strong，"
            "不要 Markdown 代码块，不要 html/body。\n\n"
            f"阶段结果：\n{self._json_dumps(final_input)}"
        )

    def _fallback_first_board_stage(self, context: dict[str, Any]) -> dict[str, Any]:
        """构造首板分析兜底输出。

        创建日期：2026-06-05
        author: sunshengxian
        """

        themes = list((context.get("first_board_context") or {}).get("themes") or [])[:10]
        rows = [
            {
                "theme": item.get("theme"),
                "representative_stocks": item.get("stocks") or [],
                "fermentation_value": "待观察",
                "reason": "LLM 阶段不可用，按题材涨停数量保留观察线索。",
            }
            for item in themes
            if isinstance(item, dict)
        ]
        return {
            "html_fragment": (
                "<h3>首板题材发酵</h3>"
                "<p>首板阶段使用题材聚合兜底，重点观察涨停数量靠前的题材是否继续扩散。</p>"
            ),
            "theme_candidates": rows,
            "risk_flags": ["首板题材仅代表当日发酵线索，不代表次日延续。"],
        }

    def _fallback_selection_stage(
        self,
        board_context: dict[str, Any],
        limit: int,
        selection_type: str,
    ) -> dict[str, Any]:
        """构造候选筛选兜底输出。

        创建日期：2026-06-05
        author: sunshengxian
        """

        rows = self._fallback_rank_stocks(list(board_context.get("stocks") or []), limit)
        selected = [
            {
                "ts_code": row.get("ts_code"),
                "name": row.get("name"),
                "board_status": row.get("status"),
                "theme": row.get("theme"),
                "selection_reason": "LLM 筛选不可用，按连板高度、封单和短线技术强度兜底入选。",
                "priority": index + 1,
            }
            for index, row in enumerate(rows)
        ]
        return {
            "selected_stocks": selected,
            "excluded_summary": f"{selection_type} 使用确定性排序兜底筛选。",
        }

    def _select_stage_stocks(
        self,
        payload: dict[str, Any],
        source_rows: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        """把 LLM 候选结果映射回原始股票行并强制数量上限。

        创建日期：2026-06-05
        author: sunshengxian
        """

        by_code = {str(row.get("ts_code") or ""): row for row in source_rows}
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in payload.get("selected_stocks") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("ts_code") or "").strip()
            if not code or code in seen or code not in by_code:
                continue
            row = {**by_code[code], "selection": item}
            seen.add(code)
            selected.append(row)
            if len(selected) >= max(limit, 1):
                break
        if selected:
            return selected
        # LLM 成功输出且显式给出空名单（如首板"宁缺毋滥"、弱市日无可选标的）必须被尊重，
        # 让报告与建议的"当日无候选"分支可达；只有解析失败/调用异常的兜底 payload，
        # 或返回的代码全部无法映射回原始行（疑似幻觉代码）时才走确定性排序兜底。
        is_fallback_payload = bool(
            payload.get("parse_fallback") or payload.get("error_fallback")
        )
        if payload.get("selected_stocks") == [] and not is_fallback_payload:
            return []
        return self._fallback_rank_stocks(source_rows, limit)

    def _fallback_rank_stocks(self, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """按确定性规则兜底排序重点股票。

        创建日期：2026-06-05
        author: sunshengxian
        """

        def score(row: dict[str, Any]) -> tuple[int, float, float, float]:
            technical = row.get("technical") if isinstance(row.get("technical"), dict) else {}
            return (
                self._board_level(row),
                float(row.get("limit_order") or row.get("max_limit_order") or 0),
                float(technical.get("amount_ratio_5d") or 0),
                float(row.get("turnover_rate") or 0),
            )

        # 兜底排序偏向更高连板、更强封单和更活跃量能，保证 LLM JSON 失败时仍能产出可解释候选池。
        return sorted(rows, key=score, reverse=True)[: max(limit, 1)]

    def _stocks_for_final_prompt(
        self, rows: list[dict[str, Any]], supplements: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """压缩最终合成阶段所需的入选股票字段。

        创建日期：2026-06-10
        author: sunshengxian
        """

        compact: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("ts_code") or "")
            supplement = supplements.get(code, {}) if isinstance(supplements, dict) else {}
            cyq_summary = supplement.get("cyq_summary") if isinstance(supplement, dict) else {}
            selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
            compact.append(
                {
                    "ts_code": code,
                    "name": row.get("name"),
                    "status": row.get("status"),
                    "board_level": row.get("board_level"),
                    "limit_type": row.get("limit_type"),
                    "theme": row.get("theme"),
                    "selection": selection,
                    "seal_ratio_pct": row.get("seal_ratio_pct"),
                    "first_limit_time": row.get("first_limit_time"),
                    "open_times": row.get("open_times"),
                    "cyq_summary": {
                        "next_day_premium_bias": (cyq_summary or {}).get("next_day_premium_bias"),
                        "upper_chip_pressure_pct": (cyq_summary or {}).get(
                            "upper_chip_pressure_pct"
                        ),
                    },
                }
            )
        return compact

    def _dedupe_selected_stocks(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """候选股票去重，避免重复调用筹码接口。

        创建日期：2026-06-05
        author: sunshengxian
        """

        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("ts_code") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            result.append(row)
        return result

    def _build_selected_stock_supplements(
        self,
        trade_date: date,
        rows: list[dict[str, Any]],
        stage_quality: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """为入选股票按需补充筹码摘要。

        创建日期：2026-06-05
        author: sunshengxian
        """

        supplements: dict[str, Any] = {}
        for row in rows:
            code = str(row.get("ts_code") or "").strip()
            if not code:
                continue
            supplements[code] = self._stock_supplement(trade_date, row)
        stage_quality.append(
            self._stage_quality_item(
                "CYQ_SUPPLEMENT",
                "OK" if supplements else "EMPTY",
                f"入选股票补数数量={len(supplements)}",
            )
        )
        return supplements

    def _stock_supplement(self, trade_date: date, row: dict[str, Any]) -> dict[str, Any]:
        """读取或生成单股筹码补数摘要。

        创建日期：2026-06-05
        author: sunshengxian
        """

        code = str(row.get("ts_code") or "")
        start_date = trade_date - timedelta(
            days=max(self.settings.limit_up_push_cyq_lookback_days, 1)
        )
        cached = self.db.scalar(
            select(LimitUpStockSupplementCache)
            .where(
                LimitUpStockSupplementCache.trade_date == trade_date,
                LimitUpStockSupplementCache.ts_code == code,
                LimitUpStockSupplementCache.start_date == start_date,
                LimitUpStockSupplementCache.end_date == trade_date,
            )
            .limit(1)
        )
        if cached is not None and cached.status in {
            LIMIT_UP_SUPPLEMENT_STATUS_READY,
            LIMIT_UP_SUPPLEMENT_STATUS_PARTIAL,
        }:
            return {
                "status": cached.status,
                "cyq_perf": self._json_loads_list(cached.cyq_perf_json),
                "cyq_summary": self._json_loads_dict(cached.cyq_chips_summary_json),
                "data_quality": self._json_loads_list(cached.data_quality_json),
            }
        quality: list[dict[str, Any]] = []
        perf_rows = self._query_cyq_api(
            "cyq_perf", code, start_date, trade_date, CYQ_PERF_FIELDS, quality
        )
        chips_rows = self._query_cyq_api(
            "cyq_chips", code, start_date, trade_date, CYQ_CHIPS_FIELDS, quality
        )
        summary = self._cyq_summary(row, perf_rows, chips_rows)
        status = (
            LIMIT_UP_SUPPLEMENT_STATUS_READY
            if perf_rows and chips_rows
            else (
                LIMIT_UP_SUPPLEMENT_STATUS_PARTIAL
                if perf_rows or chips_rows
                else LIMIT_UP_SUPPLEMENT_STATUS_FAILED
            )
        )
        cache = cached or LimitUpStockSupplementCache(
            trade_date=trade_date,
            ts_code=code,
            start_date=start_date,
            end_date=trade_date,
        )
        if cached is None:
            self.db.add(cache)
        cache.cyq_perf_json = self._json_dumps(perf_rows)
        cache.cyq_chips_summary_json = self._json_dumps(summary)
        cache.data_quality_json = self._json_dumps(quality)
        cache.status = status
        cache.error_message = (
            None
            if status != LIMIT_UP_SUPPLEMENT_STATUS_FAILED
            else "cyq_perf 与 cyq_chips 均无可用数据"
        )
        self.db.commit()
        return {
            "status": status,
            "cyq_perf": perf_rows,
            "cyq_summary": summary,
            "data_quality": quality,
        }

    def _query_cyq_api(
        self,
        api_name: str,
        ts_code: str,
        start_date: date,
        end_date: date,
        fields: tuple[str, ...],
        quality: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """调用筹码接口并记录单股质量。

        创建日期：2026-06-05
        author: sunshengxian
        """

        try:
            result = self.tushare_client.query(
                api_name,
                params={
                    "ts_code": ts_code,
                    "start_date": format_tushare_date(start_date),
                    "end_date": format_tushare_date(end_date),
                },
                fields=list(fields),
            )
        except Exception as exc:
            quality.append(DataQualityItem(api_name, "FAILED", 0, str(exc)[:300]).to_dict())
            return []
        rows = [self._normalize_api_row(item) for item in result.rows]
        quality.append(DataQualityItem(api_name, "OK" if rows else "EMPTY", len(rows)).to_dict())
        return rows

    def _cyq_summary(
        self,
        stock_row: dict[str, Any],
        perf_rows: list[dict[str, Any]],
        chips_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把筹码分布压缩为 LLM 可消费摘要。

        创建日期：2026-06-05
        author: sunshengxian
        """

        sorted_perf = sorted(perf_rows, key=lambda item: str(item.get("trade_date") or ""))
        latest_perf = sorted_perf[-1] if sorted_perf else {}
        first_perf = sorted_perf[0] if sorted_perf else {}
        technical = (
            stock_row.get("technical") if isinstance(stock_row.get("technical"), dict) else {}
        )
        close = to_decimal(technical.get("close") or stock_row.get("close"))
        weight_avg = to_decimal(latest_perf.get("weight_avg"))
        winner_latest = to_decimal(latest_perf.get("winner_rate"))
        winner_first = to_decimal(first_perf.get("winner_rate"))
        latest_chip_date = max((str(row.get("trade_date") or "") for row in chips_rows), default="")
        latest_chips = [
            row for row in chips_rows if str(row.get("trade_date") or "") == latest_chip_date
        ]
        upper_pressure = self._chip_percent_sum(latest_chips, close, above=True)
        top3_percent = sorted(
            [to_decimal(row.get("percent")) or Decimal("0") for row in latest_chips],
            reverse=True,
        )[:3]
        close_to_weight_avg = None
        if close and weight_avg:
            close_to_weight_avg = (close / weight_avg - Decimal("1")) * Decimal("100")
        if winner_latest is not None and winner_first is not None:
            winner_trend = (
                "上升"
                if winner_latest > winner_first
                else "下降" if winner_latest < winner_first else "稳定"
            )
        else:
            winner_trend = "缺失"
        concentration_total = sum(top3_percent, Decimal("0"))
        concentration = (
            "集中" if concentration_total >= Decimal("50") else "分散" if latest_chips else "缺失"
        )
        if upper_pressure is None:
            premium_bias = "缺失"
        elif upper_pressure <= Decimal("25"):
            premium_bias = "偏友好"
        elif upper_pressure <= Decimal("45"):
            premium_bias = "中性"
        else:
            premium_bias = "压力较大"
        return {
            "cyq_perf_latest": latest_perf,
            "winner_rate_trend": winner_trend,
            "close_to_weight_avg_pct": self._decimal_to_float(close_to_weight_avg),
            "upper_chip_pressure_pct": self._decimal_to_float(upper_pressure),
            "chip_concentration": concentration,
            "next_day_premium_bias": premium_bias,
            "summary": "筹码摘要基于 cyq_perf 最新胜率和 cyq_chips 最新价格分布压缩生成。",
        }

    def _chip_percent_sum(
        self,
        rows: list[dict[str, Any]],
        close: Decimal | None,
        above: bool,
    ) -> Decimal | None:
        """计算现价上方或下方筹码占比。

        创建日期：2026-06-05
        author: sunshengxian
        """

        if close is None or not rows:
            return None
        total = Decimal("0")
        for row in rows:
            price = to_decimal(row.get("price"))
            percent = to_decimal(row.get("percent")) or Decimal("0")
            if price is None:
                continue
            if above and price > close:
                total += percent
            elif not above and price <= close:
                total += percent
        return total

    def _extract_json_payload(self, content: str) -> dict[str, Any] | None:
        """从 LLM 响应中提取 JSON 对象。

        创建日期：2026-06-05
        author: sunshengxian
        """

        stripped = content.strip()
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _html_fragment(self, content: str) -> str:
        """把阶段文本整理为可嵌入最终报告的 HTML 片段。

        创建日期：2026-06-05
        author: sunshengxian
        """

        stripped = content.strip()
        stripped = re.sub(r"^```(?:html)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        if "<" in stripped and ">" in stripped:
            return stripped
        return (
            "<p>" + html.escape(stripped).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        )

    def _stage_quality_item(self, stage_key: str, status: str, message: str) -> dict[str, Any]:
        """生成阶段质量记录。

        创建日期：2026-06-05
        author: sunshengxian
        """

        return {"stage_key": stage_key, "status": status, "message": message}

    # 阶段版本后缀映射：仅调整单一阶段提示词时 bump 对应条目，不影响其余阶段缓存；
    # 未列出的阶段回退统一后缀 v3，保证既有阶段版本串不因结构重构而隐性变化。
    _STAGE_PROMPT_VERSION_SUFFIXES: dict[str, str] = {
        LIMIT_UP_STAGE_INVESTMENT_ADVICE: "advice-v1",
    }

    def _stage_prompt_version(self, stage_key: str) -> str:
        """生成阶段提示词版本。

        创建日期：2026-06-05
        author: sunshengxian
        """

        suffix = self._STAGE_PROMPT_VERSION_SUFFIXES.get(stage_key, "v3")
        return f"{self.settings.limit_up_push_final_prompt_version}:{stage_key.lower()}:{suffix}"

    def _context_trade_date(self, context: dict[str, Any]) -> date:
        """从任意阶段输入中解析报告交易日。

        创建日期：2026-06-05
        author: sunshengxian
        """

        raw_trade_date = context.get("trade_date")
        if isinstance(raw_trade_date, date):
            return raw_trade_date
        # 上下文交易日可能来自 Tushare 原始字段（YYYYMMDD），也可能来自接口序列化后的 ISO 日期；
        # 这里仅做格式兼容，不做时区偏移，避免把东八区交易日误修正成相邻自然日。
        if isinstance(raw_trade_date, str) and raw_trade_date:
            try:
                parsed = parse_tushare_date(raw_trade_date)
            except ValueError:
                parsed = None
            if parsed:
                return parsed
            try:
                return date.fromisoformat(raw_trade_date)
            except ValueError:
                return self._today_local()
        return self._today_local()


    def _chat_completion_with_reasoning(
        self,
        prompt: str,
        system_prompt: str,
        json_mode: bool = False,
        phase: str = LIMIT_UP_LLM_PHASE,
    ) -> str:
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
        if json_mode:
            # JSON 阶段向兼容接口声明结构化输出约束，正则抽取仅作为二道防线。
            payload["response_format"] = {"type": "json_object"}
        request_payload_json = self._json_dumps(payload)
        question_id = uuid4().hex
        started_at = perf_counter()
        response_body_text: str | None = None
        try:
            with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS * 2) as client:
                response = client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
            response_body_text = response.text
            try:
                body = response.json()
            except json.JSONDecodeError as exc:
                raise LimitUpPushError(
                    self._llm_response_error_message(response, response_body_text, None)
                ) from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise LimitUpPushError(
                    self._llm_response_error_message(response, response_body_text, body)
                ) from exc
            content = self._chat_completion_content(response, response_body_text, body)
        except Exception as exc:
            self._record_llm_metric(
                question_id,
                False,
                started_at,
                request_payload_json,
                self._truncate_llm_response(response_body_text),
                str(exc)[:500],
                phase=phase,
            )
            raise
        self._record_llm_metric(
            question_id, True, started_at, request_payload_json, content, None, phase=phase
        )
        return str(content or "")

    def _record_llm_metric(
        self,
        question_id: str,
        success: bool,
        started_at: float,
        request_payload_json: str,
        response_content: str | None,
        error_message: str | None,
        phase: str = LIMIT_UP_LLM_PHASE,
    ) -> None:
        # phase 默认保持 limit_up_analysis 兼容既有阶段；建议阶段传 limit_up_advice 单列统计。
        metric = LlmCallMetric(
            question_id=question_id,
            conversation_title=LIMIT_UP_LLM_TITLE,
            phase=phase,
            phase_label=phase_label(phase),
            phase_description=phase_description(phase),
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
        """生成打板报告系统提示词。

        创建日期：2026-05-08
        author: sunshengxian
        """

        return (
            "你是专注 A 股打板、连板生态和短线题材周期的复盘分析师。\n"
            "你会阅读系统提供的结构化数据，输出适合 PushPlus 长 HTML 展示的完整中文报告。\n"
            "\n"
            "要求：\n"
            "1. 你正在合成多轮分析结果：首板题材发酵、两连三连候选、筹码补数、"
            "高连板候选和最终重点分析。\n"
            "2. 重点分析涨停质量、题材强度、市场情绪周期、个股地位、二连三连晋级可能性、"
            "高连板龙头地位、资金接力、筹码压力、下一个交易日溢价可能性和失败信号。\n"
            "3. 必须分别列出“两连板”“三连板”表格，\n"
            "   表格至少包含股票、题材/原因、封板或连板状态、强弱观察字段；\n"
            "   若某类数据为空，也要保留小节并说明缺失原因或不确定性。\n"
            "4. 两连板、三连板都必须在表格后做重点分析：\n"
            "   两连板关注晋级三板条件，三连板关注空间板地位、分歧承接和断板风险。\n"
            "   首板可根据题材发酵价值简述，不强制输出表格。\n"
            "5. 高连板部分允许给出重点观察、谨慎观察和放弃观察分层，"
            "但必须显著提示高位接力、断板、回撤和流动性风险。\n"
            "6. 如果输入包含 cyq_perf 或 cyq_chips 筹码摘要，"
            "要把获利盘、成本中枢、上方筹码压力和次日溢价阻力纳入判断。\n"
            "7. 必须先根据 emotion_cycle（炸板率、晋级率、昨日涨停溢价、最高板变化）"
            "定位启动期/发酵期/高潮期/分歧期/退潮期/冰点期，并让个股观察与周期定位一致。\n"
            "8. 可以自由组织报告结构，不需要机械打分；"
            "但必须给出清晰的后续观察条件、反证条件和风险点。\n"
            "9. 不编造材料中没有的精确数值；数据缺失时说明不确定性，不要假装已经看到。\n"
            "10. 输出纯 HTML 片段，不要 Markdown 代码块，不要包裹 html/body 标签。\n"
            "11. HTML 需要适合微信阅读：使用 h2/h3、p、ul、ol、table、strong，避免脚本和外链样式。"
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
            "line-height:1.72;color:#14202e;background:#f7f8f4;padding:14px;\">"
            "<div style=\"max-width:760px;margin:0 auto;background:#fff;border:1px solid #dfe6da;"
            "border-radius:10px;padding:18px;\">"
            f"{body}"
            "</div></div>"
        )

    def _is_generating_stale(self, analysis: LimitUpAnalysisCache) -> bool:
        """判断 GENERATING 报告是否已经超过可恢复阈值。

        创建日期：2026-06-10
        author: sunshengxian
        """

        threshold_minutes = max(1, self.settings.limit_up_push_generating_stale_minutes)
        updated_at = analysis.updated_at or analysis.created_at
        if updated_at is None:
            return True
        # 进入 GENERATING 时会由应用主动写入 UTC-naive updated_at；
        # 这里继续使用 _now_naive 比较，避免数据库服务器时区不同导致正在生成的报告被误判僵死。
        return self._now_naive() - updated_at > timedelta(minutes=threshold_minutes)

    def _analysis_for_snapshot(
        self,
        trade_date: date,
        snapshot_hash: str,
    ) -> LimitUpAnalysisCache | None:
        return self.db.scalar(
            select(LimitUpAnalysisCache)
            .where(
                LimitUpAnalysisCache.trade_date == trade_date,
                LimitUpAnalysisCache.model == self.settings.limit_up_push_model,
                LimitUpAnalysisCache.prompt_version == self.settings.limit_up_push_prompt_version,
                LimitUpAnalysisCache.data_snapshot_hash == snapshot_hash,
            )
            .order_by(desc(LimitUpAnalysisCache.id))
            .limit(1)
        )

    def _reset_analysis_for_retry(
        self,
        analysis: LimitUpAnalysisCache,
        trade_date: date,
        context: dict[str, Any],
        data_quality: list[dict[str, Any]],
    ) -> None:
        # 同一数据快照的 FAILED/PENDING 记录复用原主键重跑，避免唯一键挡住后续轮询；
        # 重置正文和错误字段后先提交 GENERATING，使并发请求能读到“正在生成”并退出。
        analysis.status = ANALYSIS_STATUS_GENERATING
        analysis.title = f"{trade_date:%Y-%m-%d} A股涨停打板复盘"
        analysis.context_json = self._json_dumps(context)
        analysis.data_quality_json = self._json_dumps(data_quality)
        analysis.content_html = None
        analysis.content_markdown = None
        analysis.generated_at = None
        analysis.error_message = None
        analysis.updated_at = self._now_naive()
        self.db.commit()
        self.db.refresh(analysis)

    def _chat_completion_content(
        self,
        response: httpx.Response,
        response_text: str | None,
        body: Any,
    ) -> str:
        if not isinstance(body, dict):
            raise LimitUpPushError(
                self._llm_response_error_message(response, response_text, body)
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LimitUpPushError(
                self._llm_response_error_message(response, response_text, body)
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LimitUpPushError(
                self._llm_response_error_message(response, response_text, body)
            )
        message = first_choice.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise LimitUpPushError(
                self._llm_response_error_message(response, response_text, body)
            )
        return str(message.get("content") or "")

    def _llm_response_error_message(
        self,
        response: httpx.Response,
        response_text: str | None,
        body: Any,
    ) -> str:
        # 兼容接口异常时通常会返回 error/message/code 而不是 choices；
        # 错误摘要保留状态码和截断响应体，方便运维从指标表直接定位上游原因。
        details: list[str] = [f"DeepSeek 响应缺少有效 choices status={response.status_code}"]
        if isinstance(body, dict):
            error_payload = body.get("error")
            if isinstance(error_payload, dict):
                error_message = (
                    error_payload.get("message")
                    or error_payload.get("code")
                    or error_payload.get("type")
                )
                if error_message:
                    details.append(f"error={error_message}")
            else:
                message = body.get("message") or body.get("code")
                if message:
                    details.append(f"message={message}")
        truncated = self._truncate_llm_response(response_text)
        if truncated:
            details.append(f"body={truncated}")
        return "; ".join(details)

    def _truncate_llm_response(self, response_text: str | None) -> str | None:
        if not response_text:
            return None
        return response_text[:LLM_ERROR_RESPONSE_LOG_LIMIT]

    def _latest_ready_analysis(self, trade_date: date) -> LimitUpAnalysisCache | None:
        return self.db.scalar(
            select(LimitUpAnalysisCache)
            .where(
                LimitUpAnalysisCache.trade_date == trade_date,
                LimitUpAnalysisCache.status == ANALYSIS_STATUS_READY,
                LimitUpAnalysisCache.model == self.settings.limit_up_push_model,
                LimitUpAnalysisCache.prompt_version == self.settings.limit_up_push_prompt_version,
            )
            .order_by(desc(LimitUpAnalysisCache.id))
            .limit(1)
        )

    def _enabled_recipients(
        self,
        target_user_ids: list[int] | None = None,
        require_weekend_replay: bool = False,
    ) -> list[LimitUpPushRecipient]:
        statement = select(LimitUpPushRecipient).where(LimitUpPushRecipient.enabled.is_(True))
        if require_weekend_replay:
            statement = statement.where(LimitUpPushRecipient.weekend_replay_enabled.is_(True))
        if target_user_ids is not None:
            unique_ids = sorted({user_id for user_id in target_user_ids if user_id > 0})
            if not unique_ids:
                return []
            statement = statement.where(LimitUpPushRecipient.user_id.in_(unique_ids))
        # 手动指定接收人也必须先由管理员配置并启用，不能绕过接收人白名单；
        # 周末复推额外遵循接收人自己的晚间复推开关，常规数据就绪推送继续覆盖全部启用接收人。
        return list(self.db.scalars(statement.order_by(LimitUpPushRecipient.id)).all())

    def _sync_recipient_menu_permission(self, user: AppUser, enabled: bool) -> None:
        """同步接收人的打板推送菜单权限。

        创建日期：2026-05-08
        author: sunshengxian
        """

        from app.services.auth_service import ROLE_ADMIN

        permissions = self._load_user_menu_permissions(user)
        if enabled and "limit_up_push" not in permissions:
            permissions.append("limit_up_push")
        elif not enabled and user.role != ROLE_ADMIN:
            # 接收人停用后撤销普通用户菜单入口；管理员保留管理权限，避免误操作导致管理页消失。
            permissions = [item for item in permissions if item != "limit_up_push"]
        user.menu_permissions_json = self._dump_ordered_menu_permissions(permissions)

    def _load_user_menu_permissions(self, user: AppUser) -> list[str]:
        """读取用户当前菜单权限并过滤未知值。

        创建日期：2026-05-08
        author: sunshengxian
        """

        from app.services.auth_service import AuthService

        # 复用 AuthService 的白名单和菜单顺序，确保自动授权不会引入未知菜单；
        # 用户尚无自定义权限时按角色默认值起步，再叠加或撤销打板推送入口。
        return AuthService(self.db, self.settings).get_user_permissions(user)

    def _dump_ordered_menu_permissions(self, permissions: list[str]) -> str:
        """按系统菜单顺序序列化权限。

        创建日期：2026-05-08
        author: sunshengxian
        """

        from app.services.auth_service import AuthService

        ordered = AuthService(self.db, self.settings).sanitize_permissions(permissions)
        return self._json_dumps(ordered)

    def _delivery_for_business_plan(
        self,
        analysis: LimitUpAnalysisCache,
        user_id: int,
        scheduled_kind: str,
        scheduled_at: datetime,
    ) -> LimitUpPushDelivery | None:
        """按交易日和计划口径查找已存在推送流水。

        创建日期：2026-06-10
        author: sunshengxian
        """

        if scheduled_kind == DELIVERY_KIND_MANUAL:
            return None
        # 仓库暂未建立迁移目录，先在服务层用 trade_date+kind+user 查重，
        # 避免同一交易日因为新 analysis_id 生成而重复推送。
        return self.db.scalar(
            select(LimitUpPushDelivery)
            .join(LimitUpAnalysisCache, LimitUpAnalysisCache.id == LimitUpPushDelivery.analysis_id)
            .where(
                LimitUpAnalysisCache.trade_date == analysis.trade_date,
                LimitUpPushDelivery.user_id == user_id,
                LimitUpPushDelivery.scheduled_kind == scheduled_kind,
                LimitUpPushDelivery.scheduled_at == scheduled_at,
            )
            .order_by(desc(LimitUpPushDelivery.id))
            .limit(1)
        )

    def _get_or_create_delivery(
        self,
        analysis: LimitUpAnalysisCache,
        user_id: int,
        scheduled_kind: str,
        scheduled_at: datetime,
    ) -> LimitUpPushDelivery:
        existing_plan = self._delivery_for_business_plan(
            analysis, user_id, scheduled_kind, scheduled_at
        )
        if existing_plan is not None:
            return existing_plan
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
            .where(
                PushplusMessageLog.user_id == user_id,
                PushplusMessageLog.push_message_id == message_id,
            )
            .order_by(desc(PushplusMessageLog.id))
            .limit(1)
        )
        return log

    def _recipient_item(
        self, user: AppUser, config: LimitUpPushRecipient | None
    ) -> LimitUpRecipientItem:
        binding = self.db.scalar(
            select(PushplusBinding).where(
                PushplusBinding.user_id == user.id, PushplusBinding.is_active.is_(True)
            )
        )
        can_push = (
            binding is not None
            or self.notification_service.can_send_pushplus_to_user(user.id)
        )
        binding_name = None
        if binding is not None:
            binding_name = (
                binding.friend_remark or binding.friend_nick_name or f"好友 {binding.friend_id}"
            )
        elif can_push:
            binding_name = "默认管理员个人通道"
        return LimitUpRecipientItem(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            enabled=bool(config.enabled) if config is not None else False,
            weekend_replay_enabled=(
                bool(config.weekend_replay_enabled) if config is not None else True
            ),
            can_push=can_push,
            binding_name=binding_name,
        )

    def _get_shareable_report(self, report_id: int) -> LimitUpAnalysisCache:
        """读取可分享的已生成报告。

        创建日期：2026-05-09
        author: sunshengxian
        """

        report = self.db.get(LimitUpAnalysisCache, report_id)
        if report is None or report.status != ANALYSIS_STATUS_READY or not report.content_html:
            raise LimitUpPushError("只能管理已生成完成的报告分享")
        return report

    def _share_item(self, share: LimitUpReportShare, share_base_url: str) -> LimitUpShareItem:
        """转换分享链接管理响应。

        创建日期：2026-05-09
        author: sunshengxian
        """

        now = self._now_naive()
        if share.revoked_at is not None:
            status = "REVOKED"
        elif share.expires_at is not None and share.expires_at <= now:
            status = "EXPIRED"
        else:
            status = "ACTIVE"
        return LimitUpShareItem(
            id=share.id,
            token=share.share_token,
            share_url=f"{share_base_url.rstrip('/')}/limit-up-share/{share.share_token}",
            expires_at=share.expires_at,
            permanent=share.expires_at is None,
            status=status,
            view_count=share.view_count,
            revoked_at=share.revoked_at,
            last_viewed_at=share.last_viewed_at,
            created_at=share.created_at,
            updated_at=share.updated_at,
        )

    def _new_share_token(self) -> str:
        """生成不与现有分享冲突的随机 token。

        创建日期：2026-05-09
        author: sunshengxian
        """

        # token 只作为临时查看凭据，不承载报告 ID 或用户信息；发生极小概率冲突时重新生成。
        while True:
            token = secrets.token_urlsafe(24)
            exists = self.db.scalar(
                select(LimitUpReportShare.id)
                .where(LimitUpReportShare.share_token == token)
                .limit(1)
            )
            if exists is None:
                return token

    def _report_list_item(self, report: LimitUpAnalysisCache) -> LimitUpReportListItem:
        context = self._json_loads_dict(report.context_json)
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
            has_stage_fallback=self._has_stage_fallback(context),
            advice_status=report.advice_status or ADVICE_STATUS_PENDING,
        )

    def _has_stage_fallback(self, context: dict[str, Any]) -> bool:
        """判断报告生成阶段是否发生过确定性降级。

        创建日期：2026-06-11
        author: sunshengxian
        """

        # 重点文本阶段降级后报告仍可 READY；列表直接暴露标识，方便管理员决定是否手动重跑。
        pipeline = context.get("pipeline") if isinstance(context, dict) else None
        pipeline = pipeline if isinstance(pipeline, dict) else {}
        stage_quality = pipeline.get("stage_quality") or []
        return any(
            isinstance(item, dict) and item.get("status") == "FAILED_FALLBACK"
            for item in stage_quality
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
            normalized["trade_date"] = (
                parsed.isoformat() if parsed else normalized.get("trade_date")
            )
        return normalized

    def _is_st_stock_row(self, row: dict[str, Any]) -> bool:
        """判断 Tushare 个股行是否为 ST 股票。

        创建日期：2026-06-01
        author: sunshengxian
        """

        if not row.get("ts_code"):
            return False
        name = str(row.get("name") or "").strip().upper().replace(" ", "")
        # ST 过滤只作用于含 ts_code 的个股行；概念/题材接口的 name 是板块名，不能按 ST 字样误删。
        return "ST" in name

    def _snapshot_hash(self, context: dict[str, Any]) -> str:
        return hashlib.sha256(
            self._json_dumps(self._canonicalize_for_hash(context)).encode("utf-8")
        ).hexdigest()

    def _canonicalize_for_hash(self, value: Any) -> Any:
        """递归规范化快照对象，避免列表行序扰动哈希。

        创建日期：2026-06-10
        author: sunshengxian
        """

        if isinstance(value, dict):
            return {key: self._canonicalize_for_hash(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            normalized = [self._canonicalize_for_hash(item) for item in value]
            return sorted(normalized, key=self._canonical_sort_key)
        return value

    def _canonical_sort_key(self, value: Any) -> str:
        """为规范化后的列表元素生成稳定排序键。

        创建日期：2026-06-10
        author: sunshengxian
        """

        if isinstance(value, dict):
            primary = [
                str(value.get("trade_date") or ""),
                str(value.get("ts_code") or ""),
                str(value.get("stage_key") or ""),
                str(value.get("theme") or value.get("name") or ""),
                str(value.get("scheduled_kind") or ""),
            ]
            return "|".join(primary) + "|" + self._json_dumps(value)
        return self._json_dumps(value)

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
