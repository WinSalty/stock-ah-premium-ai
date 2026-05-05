from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.chat import LlmCallMetric
from app.services.investment_knowledge_service import InvestmentKnowledgeService
from app.services.sql_guard_service import SqlGuardError, SqlGuardService

logger = logging.getLogger(__name__)

LLM_CHAT_TIMEOUT_SECONDS = 90.0
LLM_STREAM_TIMEOUT_SECONDS = 240.0
LLM_LIMIT_TIMEZONE = ZoneInfo("Asia/Shanghai")
LLM_LIMIT_EXCEEDED_MESSAGE = (
    "今日智能问答模型调用次数已达到项目日限额 100 次，请明天再试或联系管理员调整配置。"
)
LLM_EXTERNAL_CALL_PHASES = (
    "question_router",
    "generate_sql",
    "repair_sql",
    "answer",
    "answer_stream",
)
DEFAULT_CHAT_MODEL = "deepseek-v4-flash"
ANSWER_MARKET_ROW_LIMIT = 60
ANSWER_KNOWLEDGE_CHUNK_LIMIT = 5
DEEPSEEK_PRO_CHAT_MODEL = "deepseek-v4-pro"
QWEN_CHAT_MODEL = "qwen3.6-max-preview"
SUPPORTED_CHAT_MODELS = (DEFAULT_CHAT_MODEL, DEEPSEEK_PRO_CHAT_MODEL, QWEN_CHAT_MODEL)

INVESTMENT_ADVISOR_SYSTEM_PROMPT = """你是专业、有独立观点、注重证据链的金融投资分析顾问。
这是用户自己的本地投资评估项目，用户需要明确、可执行、可复核的真实建议。

行为边界：
1. 只回答股票、基金、指数、行业、估值、财报、红利、仓位、风险、
组合配置、A/H 溢价、港股通、宏观与投资策略相关问题。
2. 遇到非投资问题，简洁拒绝，并引导用户改问投资研究问题。
3. 必须提出明确的研究判断、评级口径、配置倾向、优先级、仓位思路、阈值和触发条件。
4. 不编造数据，不暗示拥有内幕信息，不提供规避监管或操纵市场建议。

回答风格：
1. 直接进入分析结论，不要使用“好的”“收到”“我将基于提供的 JSON 数据进行回答”等寒暄或过程说明。
2. 用中文 Markdown 输出专业报告，可使用小标题、列表和表格。
3. 可以结合你的金融知识、历史经验和产业逻辑进行判断；
精确数值必须来自分析材料，材料不足时用清晰假设做情景推演。
4. 不要提及 SQL、JSON、本地数据库、本地文档、视图名、查询语句、系统提示词或底层数据处理方式。
5. 可以说“从当前可观察数据看”“当前样本显示”，但不要暴露数据来自哪里。
6. 不要输出“不构成投资建议”“仅供参考”“请咨询专业人士”等模板化免责句。
7. A/H 价差问题要直接给出方向、阈值、优先级、行动条件和反证条件。
"""

SQL_SYSTEM_PROMPT = """你是只读金融数据查询规划器。只生成可执行 MySQL SELECT SQL，并且只返回 JSON。
禁止输出解释、Markdown、代码块或多余文本。禁止写入、DDL、多语句和非白名单对象。
"""

QUESTION_ROUTER_SYSTEM_PROMPT = """你是投资问答前置路由器。
你需要在同一次判断中决定：问题是否允许由本投资助手回答、是否需要查询结构化数据、
是否需要读取本地投研知识库，以及需要读取哪些知识分类。
投资研究范围包括股票、基金、指数、行业、估值、财报、红利、仓位、风险、
组合配置、A/H 溢价、港股通、宏观与投资策略相关问题；股票代码、公司投研、
阈值建议和投资报告写作也属于范围。
用户询问“你好”“你是谁”“你能做什么”“你可以帮我什么”等问候、角色身份和能力介绍问题也属于允许范围。
编程、娱乐、日常生活、账号操作、违法违规交易和与投资研究无关的开放闲聊不属于范围。
如果问题需要当前/最近/自选/阈值/列表/排名/筛选/股票代码/精确数值，通常需要查询结构化数据。
如果问题偏投研框架、报告结论、反证条件、行业逻辑、阈值方法、组合风险表达或个股深度研究，
可以读取知识库；如果结构化数据和常识足够，不要读取知识库。
只返回 JSON，不要输出解释。格式：
{"is_answerable":true或false,"needs_sql":true或false,"use_knowledge":true或false,"knowledge_categories":["分类key"],"reason":"一句话原因"}
"""

OUT_OF_SCOPE_MESSAGE = (
    "我现在主要负责投资研究和本项目里的 A/H 溢价分析，这个问题暂时不太在我的工作范围里。"
    "你可以问我股票、行业、估值、A/H 溢价、港股通、自选股阈值、红利、组合配置或风险控制相关问题。"
)

SERVICE_INTRO_MESSAGE = (
    "你好，我是这个 A/H 溢价投资助手里的智能问答。"
    "我主要帮你做几类事情：分析 A/H 与 H/A 溢价机会、查看港股通和自选股阈值、"
    "解释股票和行业估值、整理投研报告要点、比较候选标的，并把风险、触发条件和反证条件说清楚。"
    "\n\n你可以直接问："
    "\n\n- 最近哪些 AH 标的接近我的阈值？"
    "\n- 招商银行现在更适合持有 A 股还是 H 股？"
    "\n- 帮我用红利、ROE、估值筛一批 A 股候选。"
    "\n- 某只股票当前的核心风险和跟踪指标是什么？"
)

INVESTMENT_KEYWORDS = (
    "投资",
    "股票",
    "a股",
    "h股",
    "港股",
    "美股",
    "基金",
    "债券",
    "指数",
    "行业",
    "宏观",
    "产业",
    "行情",
    "股价",
    "估值",
    "财报",
    "分红",
    "红利",
    "股息",
    "pe",
    "pb",
    "roe",
    "市盈率",
    "市净率",
    "净资产收益率",
    "仓位",
    "组合",
    "配置",
    "收益",
    "回撤",
    "风险",
    "买入",
    "卖出",
    "持有",
    "建仓",
    "减仓",
    "止损",
    "自选股",
    "标的",
    "个股",
    "阈值",
    "机会",
    "策略",
    "低估值",
    "蓝筹",
    "选股",
    "溢价",
    "折价",
    "套利",
    "价差",
    "港股通",
    "沪深港通",
    "汇率",
    "流动性",
    "金融",
    "银行",
    "非银",
    "券商",
    "保险",
    "白酒",
    "五粮液",
    "招商银行",
    "房地产",
    "地产",
    "地方财政",
    "日本",
    "资产负债表",
    "stock",
    "equity",
    "portfolio",
    "valuation",
    "dividend",
)

DATA_INTENT_KEYWORDS = (
    "哪些",
    "哪个",
    "名单",
    "列表",
    "排名",
    "排行",
    "筛选",
    "候选",
    "推荐",
    "最新",
    "最近",
    "当前",
    "今日",
    "今天",
    "交易日",
    "自选",
    "观察",
    "对比",
    "比较",
    "表格",
    "top",
    "pe",
    "pb",
    "roe",
    "股息",
    "分红",
    "溢价",
    "折价",
    "价差",
)
REPORT_ANALYSIS_KEYWORDS = (
    "报告",
    "投资逻辑",
    "买点",
    "反证",
    "验证点",
    "风险",
    "跟踪指标",
    "核心假设",
    "长期投资价值",
)
REALTIME_DATA_KEYWORDS = (
    "最新",
    "当前",
    "今日",
    "今天",
    "最近一个交易日",
    "股价",
    "收盘",
    "行情",
    "列表",
    "排名",
    "筛选",
)
NON_INVESTMENT_KEYWORDS = (
    "写诗",
    "诗",
    "诗歌",
    "作文",
    "菜谱",
    "天气",
    "旅游",
    "电影",
    "游戏",
    "代码",
    "编程",
    "bug",
)


@dataclass(frozen=True)
class ChatAnswer:
    """LLM 问答结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    answer: str
    sql: str | None
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class LlmEndpoint:
    """OpenAI-compatible 模型调用端点。

    创建日期：2026-05-04
    author: sunshengxian
    """

    provider: str
    base_url: str
    api_key: str | None
    model: str


@dataclass(frozen=True)
class LlmCallTrace:
    """LLM 单轮调用日志上下文。

    创建日期：2026-05-05
    author: sunshengxian
    """

    question_id: str
    phase: str
    user_id: int | None = None
    session_id: int | None = None


@dataclass(frozen=True)
class QuestionRoute:
    """问答前置路由结果。

    创建日期：2026-05-05
    author: sunshengxian
    """

    is_answerable: bool
    should_query_data: bool
    use_knowledge: bool
    knowledge_category_keys: tuple[str, ...] = ()
    reason: str = ""


class LlmDailyLimitExceeded(Exception):
    """LLM 项目级日调用限流异常。

    创建日期：2026-05-05
    author: sunshengxian
    """


class LlmService:
    """OpenAI-compatible LLM 问答服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.sql_guard = SqlGuardService()
        self.knowledge_service = InvestmentKnowledgeService()

    def answer(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> ChatAnswer:
        """根据本地数据回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        question_id = self._question_trace_id(question)
        request_context = context or {}
        user_id, session_id = self._trace_scope(request_context)
        started_at = perf_counter()
        selected_model = self._normalize_chat_model(model or self.settings.llm_model)
        if self._is_service_intro_question(question):
            self._log_total_elapsed(
                "sync_intro",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(answer=SERVICE_INTRO_MESSAGE, sql=None, rows=[])
        route = self._route_question(
            question,
            request_context,
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
        )
        if not route.is_answerable:
            self._log_total_elapsed(
                "sync_out_of_scope",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(answer=OUT_OF_SCOPE_MESSAGE, sql=None, rows=[])
        endpoint = self._model_endpoint(selected_model)
        if not endpoint.api_key or not endpoint.model:
            self._log_total_elapsed(
                "sync_not_configured",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(
                answer=(
                    f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                    "并确认模型名称后再使用智能问答。"
                ),
                sql=None,
                rows=[],
            )
        sql, rows, prompt = self._prepare_answer(
            question,
            request_context,
            route,
            selected_model,
            question_id,
            user_id,
            session_id,
        )
        answer = self._chat_completion(
            prompt,
            system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
            model=selected_model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="answer",
                user_id=user_id,
                session_id=session_id,
            ),
        )
        answer = self._strip_forbidden_preamble(answer)
        self._log_total_elapsed(
            "sync_done",
            question_id,
            selected_model,
            started_at,
            len(rows),
            user_id=user_id,
            session_id=session_id,
        )
        return ChatAnswer(answer=answer, sql=sql, rows=rows)

    def stream_answer(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> tuple[str | None, list[dict[str, Any]], Iterator[str]]:
        """根据本地数据流式回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        question_id = self._question_trace_id(question)
        request_context = context or {}
        user_id, session_id = self._trace_scope(request_context)
        started_at = perf_counter()
        selected_model = self._normalize_chat_model(model or self.settings.llm_model)
        if self._is_service_intro_question(question):
            self._log_total_elapsed(
                "stream_intro",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([SERVICE_INTRO_MESSAGE])
        route = self._route_question(
            question,
            request_context,
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
        )
        if not route.is_answerable:
            self._log_total_elapsed(
                "stream_out_of_scope",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([OUT_OF_SCOPE_MESSAGE])
        endpoint = self._model_endpoint(selected_model)
        if not endpoint.api_key or not endpoint.model:
            message = (
                f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                "并确认模型名称后再使用智能问答。"
            )
            self._log_total_elapsed(
                "stream_not_configured",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([message])
        sql, rows, prompt = self._prepare_answer(
            question,
            request_context,
            route,
            selected_model,
            question_id,
            user_id,
            session_id,
        )
        return sql, rows, self._clean_answer_stream(
            self._chat_completion_stream(
                prompt,
                system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
                model=selected_model,
                trace=LlmCallTrace(
                    question_id=question_id,
                    phase="answer_stream",
                    user_id=user_id,
                    session_id=session_id,
                ),
                total_started_at=started_at,
                row_count=len(rows),
            )
        )

    def _prepare_answer(
        self,
        question: str,
        context: dict[str, Any],
        route: QuestionRoute,
        model: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> tuple[str | None, list[dict[str, Any]], str]:
        sql: str | None = None
        rows: list[dict[str, Any]] = []
        if route.should_query_data:
            try:
                sql = self._default_sql_for_question(question, context) or self._generate_sql(
                    question,
                    context,
                    model,
                    question_id,
                    user_id,
                    session_id,
                )
                for attempt in range(2):
                    try:
                        guarded = self.sql_guard.validate(
                            sql,
                            default_limit=self.settings.query_limit_default,
                            max_limit=self.settings.query_limit_max,
                        )
                        sql_started_at = perf_counter()
                        rows = self._execute_sql(guarded.sql)
                        logger.info(
                            "LLM SQL 执行完成 question_id=%s rows=%s elapsed_ms=%.1f",
                            question_id,
                            len(rows),
                            (perf_counter() - sql_started_at) * 1000,
                        )
                        self._record_llm_metric(
                            phase="execute_sql",
                            question_id=question_id,
                            user_id=user_id,
                            session_id=session_id,
                            provider="Database",
                            model=None,
                            elapsed_ms=(perf_counter() - sql_started_at) * 1000,
                            row_count=len(rows),
                            success=True,
                        )
                        sql = guarded.sql
                        break
                    except (SQLAlchemyError, SqlGuardError) as exc:
                        if attempt == 1:
                            raise
                        sql = self._repair_sql(
                            question,
                            context,
                            sql,
                            str(exc),
                            model,
                            question_id,
                            user_id,
                            session_id,
                        )
            except (
                SQLAlchemyError,
                SqlGuardError,
                ValueError,
                json.JSONDecodeError,
                httpx.HTTPError,
            ):
                logger.error("LLM 数据查询准备失败，降级为无精确数据回答", exc_info=True)
                sql = None
                rows = []
        return sql, rows, self._answer_prompt(
            question,
            rows,
            context,
            route,
        )

    def _generate_sql(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> str:
        prompt = self._sql_prompt(question, context)
        content = self._chat_completion(
            prompt,
            system_prompt=SQL_SYSTEM_PROMPT,
            model=model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="generate_sql",
                user_id=user_id,
                session_id=session_id,
            ),
        )
        payload = self._extract_json(content)
        sql = payload.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("LLM 未返回 SQL")
        return sql

    def _generate_answer(
        self,
        question: str,
        sql: str,
        rows: list[dict[str, Any]],
        context: dict[str, Any],
        model: str,
    ) -> str:
        answer = self._chat_completion(
            self._answer_prompt(question, rows, context),
            system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
            model=model,
        )
        return self._strip_forbidden_preamble(answer)

    def _answer_prompt(
        self,
        question: str,
        rows: list[dict[str, Any]],
        context: dict[str, Any],
        route: QuestionRoute | None = None,
    ) -> str:
        history = self._conversation_history(context)
        category_keys = route.knowledge_category_keys if route and route.use_knowledge else ()
        knowledge = self.knowledge_service.select_by_keys(
            category_keys,
            ANSWER_KNOWLEDGE_CHUNK_LIMIT,
        )
        filters = {
            key: value
            for key, value in context.items()
            if key != "conversation_history" and value not in (None, "", [])
        }
        payload = {
            "user_question": question,
            "conversation_history": history[-8:],
            "filters": filters,
            "market_observations": rows[:ANSWER_MARKET_ROW_LIMIT],
            "supplemental_market_observations": self._supporting_data(question, context),
            "knowledge_categories": knowledge.categories,
            "reference_materials": knowledge.chunks,
        }
        return (
            "请根据以下分析材料生成给用户的最终投资研究回答。"
            "材料中的结构化字段和参考内容只供你内部分析，最终回答不得提及材料格式、"
            "底层系统、SQL、JSON、数据库、视图名或文件来源。"
            "若有 market_observations，请优先使用其中的精确数值；"
            "若没有精确数值，可基于 reference_materials 和你的金融知识输出框架性分析，"
            "但不要编造具体行情数字。"
            "不要过度自我设限；在证据足够时可以给出清晰的看多/中性/谨慎判断、"
            "配置优先级、仓位思路和触发条件。"
            "请直接给出结论、表格、投资逻辑、配置建议、执行条件、反证条件和跟踪项。"
            "不要输出模板化免责句或泛泛风险警告。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        result = self.db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]

    def _chat_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
    ) -> str:
        endpoint = self._model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        self._enforce_daily_llm_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": temperature,
        }
        started_at = perf_counter()
        with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
        self._raise_for_status(response, endpoint.provider)
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        self._log_llm_completion(endpoint, trace, started_at, content)
        return content

    def _chat_completion_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        trace: LlmCallTrace | None = None,
        total_started_at: float | None = None,
        row_count: int = 0,
    ) -> Iterator[str]:
        endpoint = self._model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        self._enforce_daily_llm_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        started_at = perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        with httpx.Client(timeout=LLM_STREAM_TIMEOUT_SECONDS) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response, endpoint.provider)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        now = perf_counter()
                        if first_chunk_at is None:
                            first_chunk_at = now
                            self._log_llm_first_chunk(endpoint, trace, started_at)
                        chunk_count += 1
                        char_count += len(content)
                        yield content
        self._log_llm_stream_done(
            endpoint,
            trace,
            started_at,
            first_chunk_at,
            chunk_count,
            char_count,
        )
        if total_started_at is not None and trace is not None:
            self._log_total_elapsed(
                "stream_done",
                trace.question_id,
                endpoint.model,
                total_started_at,
                row_count,
                user_id=trace.user_id,
                session_id=trace.session_id,
            )

    def _normalize_chat_model(self, model: str | None) -> str:
        """转换为 OpenAI-compatible API 支持的模型名。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if not model:
            return DEFAULT_CHAT_MODEL
        normalized = model.strip()
        if normalized.startswith("deepseek-v4-pro"):
            return "deepseek-v4-pro"
        if normalized.startswith("deepseek-v4-flash"):
            return "deepseek-v4-flash"
        return normalized

    def _model_endpoint(self, model: str | None = None) -> LlmEndpoint:
        """根据模型名选择 DeepSeek 或 Qwen 调用端点。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = self._normalize_chat_model(model or self.settings.llm_model)
        if normalized.startswith("qwen"):
            return LlmEndpoint(
                provider="Qwen",
                base_url=self.settings.qwen_base_url,
                api_key=self.settings.resolve_qwen_api_key(),
                model=normalized,
            )
        return LlmEndpoint(
            provider="DeepSeek",
            base_url=self.settings.llm_base_url,
            api_key=self.settings.resolve_llm_api_key(),
            model=normalized,
        )

    def _raise_for_status(self, response: httpx.Response, provider: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            try:
                body = response.text
            except httpx.ResponseNotRead:
                body = response.read().decode("utf-8", errors="replace")
            logger.error(
                "%s API 请求失败 status=%s body=%s",
                provider,
                response.status_code,
                body[:2000],
            )
            raise

    def _enforce_daily_llm_call_limit(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
    ) -> None:
        """检查项目级 LLM 日调用限额。

        创建日期：2026-05-05
        author: sunshengxian
        """

        limit = self.settings.llm_daily_call_limit
        if limit <= 0:
            return
        used_count = self._today_external_llm_call_count()
        if used_count < limit:
            return
        question_id, phase = self._trace_values(trace)
        logger.error(
            "LLM 日调用限额已用尽 question_id=%s phase=%s provider=%s model=%s used=%s limit=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            used_count,
            limit,
        )
        raise LlmDailyLimitExceeded(self._daily_limit_message(limit))

    def _today_external_llm_call_count(self) -> int:
        """统计当天已发生的外部 LLM 主调用次数。

        创建日期：2026-05-05
        author: sunshengxian
        """

        now = datetime.now(LLM_LIMIT_TIMEZONE).replace(tzinfo=None)
        today_start = datetime.combine(now.date(), time.min)
        tomorrow_start = today_start + timedelta(days=1)
        statement = select(func.count(LlmCallMetric.id)).where(
            LlmCallMetric.phase.in_(LLM_EXTERNAL_CALL_PHASES),
            LlmCallMetric.created_at >= today_start,
            LlmCallMetric.created_at < tomorrow_start,
        )
        try:
            raw_count = self.db.scalar(statement)
        except Exception:
            self.db.rollback()
            logger.error("LLM 日调用次数统计失败，临时放行本次模型调用", exc_info=True)
            return 0
        if isinstance(raw_count, int):
            return raw_count
        if isinstance(raw_count, float):
            return int(raw_count)
        return 0

    def _daily_limit_message(self, limit: int) -> str:
        """生成可展示的 LLM 日限流提示。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if limit == 100:
            return LLM_LIMIT_EXCEEDED_MESSAGE
        return (
            f"今日智能问答模型调用次数已达到项目日限额 {limit} 次，"
            "请明天再试或联系管理员调整配置。"
        )

    def _question_trace_id(self, question: str) -> str:
        """生成不暴露问题原文的短追踪 ID。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return f"{abs(hash(question.strip())) % 10_000_000:07d}"

    def _trace_values(
        self,
        trace: LlmCallTrace | None,
    ) -> tuple[str, str]:
        if trace is None:
            return "-", "-"
        return trace.question_id, trace.phase

    def _trace_scope(self, context: dict[str, Any]) -> tuple[int | None, int | None]:
        """从问答上下文读取用户和会话范围。

        创建日期：2026-05-05
        author: sunshengxian
        """

        user_id = self._optional_int(context.get("user_id"))
        session_id = self._optional_int(context.get("session_id"))
        return user_id, session_id

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _record_llm_metric(
        self,
        *,
        phase: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
        provider: str | None,
        model: str | None,
        elapsed_ms: float | None = None,
        first_chunk_ms: float | None = None,
        output_chars: int = 0,
        chunk_count: int = 0,
        row_count: int = 0,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        """记录 LLM 调用耗时指标，失败不影响问答主流程。

        创建日期：2026-05-05
        author: sunshengxian
        """

        metric = LlmCallMetric(
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
            phase=phase,
            provider=provider,
            model=model,
            success=1 if success else 0,
            elapsed_ms=elapsed_ms,
            first_chunk_ms=first_chunk_ms,
            output_chars=output_chars,
            chunk_count=chunk_count,
            row_count=row_count,
            error_message=error_message[:512] if error_message else None,
        )
        try:
            self.db.add(metric)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.error("LLM 调用耗时指标落库失败", exc_info=True)

    def _log_llm_completion(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        content: str,
    ) -> None:
        question_id, phase = self._trace_values(trace)
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 调用完成 question_id=%s phase=%s provider=%s model=%s elapsed_ms=%.1f "
            "output_chars=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            elapsed_ms,
            len(content),
        )
        if trace is not None:
            self._record_llm_metric(
                phase=trace.phase,
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                provider=endpoint.provider,
                model=endpoint.model,
                elapsed_ms=elapsed_ms,
                output_chars=len(content),
                success=True,
            )

    def _log_llm_first_chunk(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
    ) -> None:
        question_id, phase = self._trace_values(trace)
        first_chunk_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 流式首包 question_id=%s phase=%s provider=%s model=%s first_chunk_ms=%.1f",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            first_chunk_ms,
        )
        if trace is not None:
            self._record_llm_metric(
                phase=f"{trace.phase}_first_chunk",
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                provider=endpoint.provider,
                model=endpoint.model,
                first_chunk_ms=first_chunk_ms,
                success=True,
            )

    def _log_llm_stream_done(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        first_chunk_at: float | None,
        chunk_count: int,
        char_count: int,
    ) -> None:
        question_id, phase = self._trace_values(trace)
        elapsed_ms = (perf_counter() - started_at) * 1000
        first_chunk_ms = (first_chunk_at - started_at) * 1000 if first_chunk_at else None
        logger.info(
            "LLM 流式完成 question_id=%s phase=%s provider=%s model=%s elapsed_ms=%.1f "
            "first_chunk_ms=%s chunks=%s output_chars=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            elapsed_ms,
            f"{first_chunk_ms:.1f}" if first_chunk_ms is not None else "-",
            chunk_count,
            char_count,
        )
        if trace is not None:
            self._record_llm_metric(
                phase=trace.phase,
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                provider=endpoint.provider,
                model=endpoint.model,
                elapsed_ms=elapsed_ms,
                first_chunk_ms=first_chunk_ms,
                output_chars=char_count,
                chunk_count=chunk_count,
                success=True,
            )

    def _log_total_elapsed(
        self,
        phase: str,
        question_id: str,
        model: str,
        started_at: float,
        row_count: int = 0,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 问答完成 question_id=%s phase=%s model=%s rows=%s total_elapsed_ms=%.1f",
            question_id,
            phase,
            model,
            row_count,
            elapsed_ms,
        )
        self._record_llm_metric(
            phase=phase,
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
            provider="Internal",
            model=model,
            elapsed_ms=elapsed_ms,
            row_count=row_count,
            success=True,
        )

    def _sql_prompt(self, question: str, context: dict[str, Any]) -> str:
        context_json = json.dumps(
            {
                "question": question,
                "context": context,
                "conversation_history": self._conversation_history(context)[-6:],
            },
            ensure_ascii=False,
            default=str,
        )
        return (
            '你只负责生成只读 MySQL SELECT SQL，必须返回 JSON：{"sql":"..."}。'
            "只能查询这些视图："
            f"{json.dumps(self._schema(), ensure_ascii=False)}。"
            "默认使用官方 AH 比价口径；H/A 字段由官方 A/H 反推；"
            "涉及可操作性时优先查询含 hk_connect 或 watchlist 的视图。"
            "涉及自选、关注、阈值、机会状态或 v_watchlist_opportunity 时，"
            "必须使用 context.user_id 过滤 user_id，禁止查询其他用户自选数据。"
            "涉及 A 股选股、低估值、红利、蓝筹、ROE、PE、PB、股息率时"
            "优先查询 v_stock_selection_latest，"
            "并可用 v_stock_factor_dictionary 解释字段含义。"
            "字段名必须完全来自字段清单；不要使用 stock_name、ha_premium、ah_premium 等不存在字段，"
            "应使用 display_name/a_name/hk_name/name、ha_premium_pct、ah_premium_pct。"
            "不要使用写入、DDL、多语句。问题与上下文如下："
            f"{context_json}"
        )

    def _repair_sql(
        self,
        question: str,
        context: dict[str, Any],
        sql: str,
        error: str,
        model: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> str:
        payload = {
            "question": question,
            "context": context,
            "failed_sql": sql,
            "error": error[:1200],
            "schema": self._schema(),
        }
        prompt = (
            '请修复这个 MySQL SELECT SQL，并只返回 JSON：{"sql":"..."}。'
            "只能使用 schema 中列出的视图和字段名；不要使用写入、DDL、多语句。"
            "常见修正：stock_name 改为 display_name/a_name/hk_name/name；"
            "ha_premium 改为 ha_premium_pct；ah_premium 改为 ah_premium_pct。"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        content = self._chat_completion(
            prompt,
            system_prompt=SQL_SYSTEM_PROMPT,
            model=model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="repair_sql",
                user_id=user_id,
                session_id=session_id,
            ),
        )
        payload = self._extract_json(content)
        repaired_sql = payload.get("sql")
        if not isinstance(repaired_sql, str) or not repaired_sql.strip():
            raise ValueError("LLM 未返回修复后的 SQL")
        return repaired_sql

    def _supporting_data(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, list[dict[str, Any]]] | None:
        if not self._is_ah_arbitrage_question(question) or not self._should_query_supporting_data(
            question
        ):
            return None
        user_id = int((context or {}).get("user_id") or 0)
        user_filter = f"WHERE user_id = {user_id} " if user_id else ""
        queries = {
            "a_discount_h_premium_candidates": (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ha_premium_pct DESC LIMIT 20"
            ),
            "h_discount_a_premium_candidates": (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ah_premium_pct DESC LIMIT 20"
            ),
            "watchlist_opportunities": (
                "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,opportunity_status "
                "FROM v_watchlist_opportunity "
                f"{user_filter}"
                "ORDER BY ABS(distance_to_target_pct) ASC LIMIT 30"
            ),
            "market_distribution": (
                "SELECT COUNT(*) AS total_count,"
                "SUM(ah_premium_pct < 0) AS a_discount_count,"
                "SUM(ha_premium_pct > 0) AS h_premium_count,"
                "MIN(ah_premium_pct) AS min_ah_premium_pct,"
                "MAX(ah_premium_pct) AS max_ah_premium_pct,"
                "MIN(ha_premium_pct) AS min_ha_premium_pct,"
                "MAX(ha_premium_pct) AS max_ha_premium_pct "
                "FROM v_latest_hk_connect_official_ah_premium"
            ),
        }
        supporting_data: dict[str, list[dict[str, Any]]] = {}
        for key, sql in queries.items():
            try:
                supporting_data[key] = self._execute_sql(sql)
            except SQLAlchemyError:
                logger.error("LLM 补充数据查询失败 key=%s", key, exc_info=True)
                supporting_data[key] = []
        return supporting_data

    def _is_ah_arbitrage_question(self, question: str) -> bool:
        keywords = ("ah", "a/h", "h/a", "溢价", "折价", "套利", "价差", "港股通", "a股", "h股")
        normalized = question.lower()
        return any(keyword in normalized for keyword in keywords)

    def _is_stock_selection_question(self, question: str) -> bool:
        normalized = question.lower()
        keywords = (
            "选股",
            "蓝筹",
            "低估值",
            "红利",
            "股息",
            "pe",
            "pb",
            "roe",
            "估值",
            "沪深300",
            "上证50",
            "质量",
        )
        return any(keyword in normalized for keyword in keywords)

    def _default_sql_for_question(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        normalized = question.lower().replace(" ", "").replace("／", "/")
        user_id = int((context or {}).get("user_id") or 0)
        user_filter = f"WHERE user_id = {user_id} " if user_id else ""
        if any(keyword in normalized for keyword in ("自选", "关注", "阈值", "机会状态")):
            if any(keyword in normalized for keyword in ("h/a折价", "h股折价", "h股便宜")):
                return (
                    "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                    "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                    "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                    "opportunity_status "
                    "FROM v_watchlist_opportunity "
                    f"{user_filter}"
                    "ORDER BY ha_premium_pct ASC LIMIT 30"
                )
            if any(keyword in normalized for keyword in ("h/a溢价", "h股溢价", "a股折价")):
                return (
                    "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                    "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                    "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                    "opportunity_status "
                    "FROM v_watchlist_opportunity "
                    f"{user_filter}"
                    "ORDER BY ha_premium_pct DESC LIMIT 30"
                )
            return (
                "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                "opportunity_status "
                "FROM v_watchlist_opportunity "
                f"{user_filter}"
                "ORDER BY ABS(distance_to_target_pct) ASC LIMIT 30"
            )
        if not self._is_ah_arbitrage_question(question):
            if self._is_stock_selection_question(question):
                return (
                    "SELECT factor_date,ts_code,name,industry,selection_tags,selection_score,"
                    "selection_reason,pe_ttm,pb,dividend_yield_ttm,roe,debt_to_assets,"
                    "return_20d,return_60d,return_120d "
                    "FROM v_stock_selection_latest "
                    "ORDER BY selection_score DESC LIMIT 20"
            )
            return None
        if any(keyword in normalized for keyword in ("哪些", "适合", "候选", "推荐", "筛选")):
            if any(
                keyword in normalized
                for keyword in (
                    "a/h溢价",
                    "ah溢价",
                    "a股溢价",
                    "h/a折价",
                    "h股便宜",
                    "h股折价",
                )
            ):
                return (
                    "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                    "ha_premium_pct,is_hk_connect,connect_channels "
                    "FROM v_latest_hk_connect_official_ah_premium "
                    "ORDER BY ah_premium_pct DESC LIMIT 20"
                )
            return (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ha_premium_pct DESC LIMIT 20"
            )
        return None

    def _route_question(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        question_id: str | None = None,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> QuestionRoute:
        if not question.strip():
            return QuestionRoute(
                is_answerable=False,
                should_query_data=False,
                use_knowledge=False,
                reason="空问题",
            )
        context = context or {}
        payload = {
            "question": question.strip()[:1200],
            "conversation_history": self._conversation_history(context)[-4:],
            "frontend_context": {
                key: value
                for key, value in context.items()
                if key != "conversation_history" and value not in (None, "", [])
            },
            "knowledge_catalog": self.knowledge_service.catalog(),
        }
        try:
            content = self._chat_completion(
                json.dumps(payload, ensure_ascii=False, default=str),
                system_prompt=QUESTION_ROUTER_SYSTEM_PROMPT,
                model=self.settings.resolve_qwen_question_router_model(),
                temperature=0,
                trace=LlmCallTrace(
                    question_id=question_id or self._question_trace_id(question),
                    phase="question_router",
                    user_id=user_id,
                    session_id=session_id,
                ),
            )
            payload = self._extract_json(content)
            return self._route_from_payload(payload)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            logger.error("Qwen 问答前置路由失败，降级使用本地兜底规则", exc_info=True)
            return self._local_question_route(question, context)

    def _route_from_payload(self, payload: dict[str, Any]) -> QuestionRoute:
        """把 Qwen 路由 JSON 转换为内部结构。

        创建日期：2026-05-05
        author: sunshengxian
        """

        categories = payload.get("knowledge_categories")
        if not isinstance(categories, list):
            categories = []
        category_keys = tuple(item for item in categories if isinstance(item, str))
        return QuestionRoute(
            is_answerable=payload.get("is_answerable") is True,
            should_query_data=payload.get("needs_sql") is True,
            use_knowledge=payload.get("use_knowledge") is True,
            knowledge_category_keys=category_keys,
            reason=str(payload.get("reason") or ""),
        )

    def _local_question_route(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> QuestionRoute:
        """Qwen 路由不可用时的保守兜底。

        创建日期：2026-05-05
        author: sunshengxian
        """

        local_scope = self._local_question_scope(question)
        if local_scope is False:
            return QuestionRoute(False, False, False, reason="本地规则判定为非投资问题")
        if local_scope is True:
            return QuestionRoute(
                is_answerable=True,
                should_query_data=self._should_query_data(question, context or {}),
                use_knowledge=False,
                reason="Qwen 路由不可用，本地规则放行",
            )
        return QuestionRoute(False, False, False, reason="Qwen 路由不可用且本地规则不确定")

    def _is_investment_related_question(
        self,
        question: str,
        question_id: str | None = None,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> bool:
        return self._route_question(
            question,
            {},
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
        ).is_answerable

    def _local_question_scope(self, question: str) -> bool | None:
        """先用本地规则判断明显问题，减少问答前置 LLM 调用。

        创建日期：2026-05-05
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "").replace("／", "/")
        if self._is_service_intro_question(question):
            return True
        if any(keyword in normalized for keyword in INVESTMENT_KEYWORDS):
            return True
        if any(keyword in normalized for keyword in NON_INVESTMENT_KEYWORDS):
            return False
        return None

    def _is_service_intro_question(self, question: str) -> bool:
        """识别问候、角色身份和能力介绍类问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "")
        intro_keywords = (
            "你好",
            "您好",
            "你是谁",
            "你是啥",
            "你是什么",
            "你可以干嘛",
            "你能干嘛",
            "你会干嘛",
            "你可以做什么",
            "你能做什么",
            "你有什么用",
            "介绍一下你",
            "介绍你自己",
            "你的角色",
            "你的身份",
            "help",
            "whoareyou",
            "whatcanyoudo",
        )
        return any(keyword in normalized for keyword in intro_keywords)

    def _should_query_data(self, question: str, context: dict[str, Any]) -> bool:
        if any(context.get(key) for key in ("start_date", "end_date", "ts_code", "only_watchlist")):
            return True
        normalized = question.lower().replace(" ", "")
        if self._is_report_analysis_question(normalized):
            return False
        if re.search(r"\b\d{6}\.(sh|sz)\b|\b\d{5}\.hk\b", normalized):
            return True
        return any(keyword in normalized for keyword in DATA_INTENT_KEYWORDS)

    def _is_report_analysis_question(self, normalized_question: str) -> bool:
        """识别偏报告/框架的问题，避免无意义 SQL 生成。

        创建日期：2026-05-05
        author: sunshengxian
        """

        has_report_signal = any(
            keyword in normalized_question for keyword in REPORT_ANALYSIS_KEYWORDS
        )
        has_realtime_signal = any(
            keyword in normalized_question for keyword in REALTIME_DATA_KEYWORDS
        )
        return has_report_signal and not has_realtime_signal

    def _should_query_supporting_data(self, question: str) -> bool:
        normalized = question.lower()
        keywords = ("哪些", "候选", "推荐", "筛选", "机会", "价差", "最新", "自选")
        return any(keyword in normalized for keyword in keywords)

    def _conversation_history(self, context: dict[str, Any]) -> list[dict[str, str]]:
        raw_history = context.get("conversation_history") or []
        history: list[dict[str, str]] = []
        if not isinstance(raw_history, list):
            return history
        for item in raw_history[-10:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if (
                role not in {"user", "assistant"}
                or not isinstance(content, str)
                or not content.strip()
            ):
                continue
            history.append({"role": role, "content": content.strip()[:1200]})
        return history

    def _strip_forbidden_preamble(self, answer: str) -> str:
        cleaned = answer.strip()
        preamble_patterns = (
            r"^(好的|收到|当然|可以)[，,。！!\s]*",
            r"^收到.{0,30}(请求|问题)[。.\s]*",
            r"^您的(请求|问题)[。.\s]*",
            r"^我将基于.{0,40}(JSON|SQL|数据|资料|查询结果).{0,80}[。.\n]",
            r"^基于.{0,40}(JSON|SQL|查询结果|提供的数据).{0,80}[。.\n]",
            r"^以下是基于.{0,40}(JSON|SQL|查询结果|提供的数据).{0,80}[。.\n]",
        )
        changed = True
        while changed:
            changed = False
            for pattern in preamble_patterns:
                next_answer = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE).strip()
                if next_answer != cleaned:
                    cleaned = next_answer
                    changed = True
        return cleaned

    def _clean_answer_stream(self, chunks: Iterator[str]) -> Iterator[str]:
        buffer = ""
        emitted = False
        for chunk in chunks:
            if emitted:
                yield chunk
                continue
            buffer += chunk
            if len(buffer) < 240 and "\n\n" not in buffer:
                continue
            cleaned = self._strip_forbidden_preamble(buffer)
            if cleaned:
                yield cleaned
            emitted = True
        if not emitted:
            cleaned = self._strip_forbidden_preamble(buffer)
            if cleaned:
                yield cleaned

    def _schema(self) -> dict[str, str]:
        return {
            "v_latest_official_ah_premium": (
                "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
                "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
                "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
            ),
            "v_official_ah_premium_trend": (
                "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
                "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
                "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
            ),
            "v_latest_hk_connect_official_ah_premium": (
                "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
                "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
                "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
            ),
            "v_watchlist_opportunity": (
                "columns: watchlist_id,user_id,a_ts_code,hk_ts_code,display_name,"
                "preferred_direction,"
                "target_premium_pct,holding_market,sort_order,note,trade_date,a_name,hk_name,"
                "ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                "data_source,source_updated_at,opportunity_status,updated_at"
            ),
            "v_stock_selection_latest": (
                "columns: id,factor_date,ts_code,symbol,name,industry,area,market,selection_tags,"
                "selection_score,selection_reason,is_hs300,is_sse50,is_csi300_value,"
                "is_csi_dividend,is_sse_dividend,is_sz_dividend,close,pct_chg,turnover_rate,"
                "pe_ttm,pb,ps_ttm,dividend_yield_ttm,total_mv,circ_mv,roe,grossprofit_margin,"
                "netprofit_margin,debt_to_assets,revenue_yoy,latest_report_period,return_20d,"
                "return_60d,return_120d,latest_dividend_year,latest_cash_div_tax,"
                "latest_dividend_proc,forecast_type,forecast_summary,data_source,"
                "source_trade_date,created_at,updated_at"
            ),
            "v_stock_selection_history": "columns: same as v_stock_selection_latest",
            "v_stock_factor_dictionary": "columns: field_name,field_label,description,usage_hint",
            "v_latest_ah_premium": "columns: same as v_latest_official_ah_premium",
            "v_ah_premium_trend": "columns: same as v_official_ah_premium_trend",
            "v_sync_health": (
                "columns: dataset,last_status,last_started_at,last_finished_at,last_message"
            ),
            "v_data_quality_issues": "columns: issue_type,issue_level,issue_message,related_key",
        }

    def _extract_json(self, content: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError("LLM 返回内容不是 JSON")
        return json.loads(match.group(0))
