from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.investment_knowledge_service import InvestmentKnowledgeService
from app.services.sql_guard_service import SqlGuardError, SqlGuardService

logger = logging.getLogger(__name__)

LLM_CHAT_TIMEOUT_SECONDS = 90.0
LLM_STREAM_TIMEOUT_SECONDS = 240.0
DEFAULT_CHAT_MODEL = "deepseek-v4-flash"
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

QUESTION_CLASSIFIER_SYSTEM_PROMPT = """你是投资问答边界分类器，只判断用户问题是否属于投资研究范围。
投资研究范围包括股票、基金、指数、行业、估值、财报、红利、仓位、风险、
组合配置、A/H 溢价、港股通、宏观与投资策略相关问题；股票代码、公司投研、
阈值建议和投资报告写作也属于范围。
闲聊、编程、娱乐、日常生活、账号操作、违法违规交易和与投资研究无关的问题不属于范围。
只返回 JSON，不要输出解释。格式：{"is_investment_related":true或false}
"""

OUT_OF_SCOPE_MESSAGE = (
    "这个问题超出了投资研究范围。我可以分析股票、行业、估值、A/H 溢价、"
    "港股通、红利、组合配置和风险控制等投资相关问题。"
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

        selected_model = self._normalize_chat_model(model or self.settings.llm_model)
        if not self._is_investment_related_question(question):
            return ChatAnswer(answer=OUT_OF_SCOPE_MESSAGE, sql=None, rows=[])
        endpoint = self._model_endpoint(selected_model)
        if not endpoint.api_key or not endpoint.model:
            return ChatAnswer(
                answer=(
                    f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                    "并确认模型名称后再使用智能问答。"
                ),
                sql=None,
                rows=[],
            )
        sql, rows, prompt = self._prepare_answer(question, context or {}, selected_model)
        answer = self._chat_completion(
            prompt,
            system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
            model=selected_model,
        )
        answer = self._strip_forbidden_preamble(answer)
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

        selected_model = self._normalize_chat_model(model or self.settings.llm_model)
        if not self._is_investment_related_question(question):
            return None, [], iter([OUT_OF_SCOPE_MESSAGE])
        endpoint = self._model_endpoint(selected_model)
        if not endpoint.api_key or not endpoint.model:
            message = (
                f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                "并确认模型名称后再使用智能问答。"
            )
            return None, [], iter([message])
        sql, rows, prompt = self._prepare_answer(question, context or {}, selected_model)
        return sql, rows, self._clean_answer_stream(
            self._chat_completion_stream(
                prompt,
                system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
                model=selected_model,
            )
        )

    def _prepare_answer(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
    ) -> tuple[str | None, list[dict[str, Any]], str]:
        sql: str | None = None
        rows: list[dict[str, Any]] = []
        if self._should_query_data(question, context):
            try:
                sql = self._default_sql_for_question(question, context) or self._generate_sql(
                    question,
                    context,
                    model,
                )
                for attempt in range(2):
                    try:
                        guarded = self.sql_guard.validate(
                            sql,
                            default_limit=self.settings.query_limit_default,
                            max_limit=self.settings.query_limit_max,
                        )
                        rows = self._execute_sql(guarded.sql)
                        sql = guarded.sql
                        break
                    except (SQLAlchemyError, SqlGuardError) as exc:
                        if attempt == 1:
                            raise
                        sql = self._repair_sql(question, context, sql, str(exc), model)
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
        return sql, rows, self._answer_prompt(question, rows, context)

    def _generate_sql(self, question: str, context: dict[str, Any], model: str) -> str:
        prompt = self._sql_prompt(question, context)
        content = self._chat_completion(prompt, system_prompt=SQL_SYSTEM_PROMPT, model=model)
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
    ) -> str:
        history = self._conversation_history(context)
        knowledge = self.knowledge_service.select(question, history=history)
        filters = {
            key: value
            for key, value in context.items()
            if key != "conversation_history" and value not in (None, "", [])
        }
        payload = {
            "user_question": question,
            "conversation_history": history[-8:],
            "filters": filters,
            "market_observations": rows[:200],
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
    ) -> str:
        endpoint = self._model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
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
        with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
        self._raise_for_status(response, endpoint.provider)
        body = response.json()
        return body["choices"][0]["message"]["content"]

    def _chat_completion_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> Iterator[str]:
        endpoint = self._model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
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
                        yield content

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
        content = self._chat_completion(prompt, system_prompt=SQL_SYSTEM_PROMPT, model=model)
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

    def _is_investment_related_question(self, question: str) -> bool:
        if not question.strip():
            return False
        try:
            content = self._chat_completion(
                question.strip()[:1000],
                system_prompt=QUESTION_CLASSIFIER_SYSTEM_PROMPT,
                model=self.settings.qwen_question_classifier_model,
                temperature=0,
            )
            payload = self._extract_json(content)
            return payload.get("is_investment_related") is True
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            logger.error("Qwen 投资问题边界判定失败", exc_info=True)
            return False

    def _should_query_data(self, question: str, context: dict[str, Any]) -> bool:
        if any(context.get(key) for key in ("start_date", "end_date", "ts_code", "only_watchlist")):
            return True
        normalized = question.lower().replace(" ", "")
        if re.search(r"\b\d{6}\.(sh|sz)\b|\b\d{5}\.hk\b", normalized):
            return True
        return any(keyword in normalized for keyword in DATA_INTENT_KEYWORDS)

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
