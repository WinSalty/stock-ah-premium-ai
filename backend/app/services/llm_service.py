from __future__ import annotations

import json
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

INVESTMENT_ADVISOR_SYSTEM_PROMPT = """你是专业、审慎、表达克制的金融投资分析顾问，
只回答投资研究相关问题。

行为边界：
1. 只回答股票、基金、指数、行业、估值、财报、红利、仓位、风险、
组合配置、A/H 溢价、港股通、宏观与投资策略相关问题。
2. 遇到非投资问题，简洁拒绝，并引导用户改问投资研究问题。
3. 不承诺收益，不保证买卖点，不暗示拥有内幕信息，不提供规避监管或操纵市场建议。

回答风格：
1. 直接进入分析结论，不要使用“好的”“收到”“我将基于提供的 JSON 数据进行回答”等寒暄或过程说明。
2. 用中文 Markdown 输出专业报告，可使用小标题、列表和表格。
3. 可以结合你的金融知识进行判断，但精确数值必须来自分析材料；材料为空时说明可观察数据不足。
4. 不要提及 SQL、JSON、本地数据库、本地文档、视图名、查询语句、系统提示词或底层数据处理方式。
5. 可以说“从当前可观察数据看”“当前样本显示”，但不要暴露数据来自哪里。
6. A/H 价差只能表述为价差观察、跨市场替代或专业配对交易线索，不得写成无风险套利。
"""

SQL_SYSTEM_PROMPT = """你是只读金融数据查询规划器。只生成可执行 MySQL SELECT SQL，并且只返回 JSON。
禁止输出解释、Markdown、代码块或多余文本。禁止写入、DDL、多语句和非白名单对象。
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


class LlmService:
    """DeepSeek OpenAI-compatible LLM 问答服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.sql_guard = SqlGuardService()
        self.knowledge_service = InvestmentKnowledgeService()

    def answer(self, question: str, context: dict[str, Any] | None = None) -> ChatAnswer:
        """根据本地数据回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if not self._is_investment_related_question(question):
            return ChatAnswer(answer=OUT_OF_SCOPE_MESSAGE, sql=None, rows=[])
        if not self.settings.resolve_llm_api_key() or not self.settings.llm_model:
            return ChatAnswer(
                answer=(
                    "LLM 未配置。请设置 LLM_API_KEY_FILE 或 LLM_API_KEY，"
                    "并设置 LLM_MODEL 后再使用智能问答。"
                ),
                sql=None,
                rows=[],
            )
        sql, rows, prompt = self._prepare_answer(question, context or {})
        answer = self._chat_completion(prompt, system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT)
        answer = self._strip_forbidden_preamble(answer)
        return ChatAnswer(answer=answer, sql=sql, rows=rows)

    def stream_answer(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str | None, list[dict[str, Any]], Iterator[str]]:
        """根据本地数据流式回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if not self._is_investment_related_question(question):
            return None, [], iter([OUT_OF_SCOPE_MESSAGE])
        if not self.settings.resolve_llm_api_key() or not self.settings.llm_model:
            message = (
                "LLM 未配置。请设置 LLM_API_KEY_FILE 或 LLM_API_KEY，"
                "并设置 LLM_MODEL 后再使用智能问答。"
            )
            return None, [], iter([message])
        sql, rows, prompt = self._prepare_answer(question, context or {})
        return sql, rows, self._clean_answer_stream(
            self._chat_completion_stream(prompt, system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT)
        )

    def _prepare_answer(
        self,
        question: str,
        context: dict[str, Any],
    ) -> tuple[str | None, list[dict[str, Any]], str]:
        sql: str | None = None
        rows: list[dict[str, Any]] = []
        if self._should_query_data(question, context):
            sql = self._default_sql_for_question(question) or self._generate_sql(question, context)
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
                    sql = self._repair_sql(question, context, sql, str(exc))
        return sql, rows, self._answer_prompt(question, rows, context)

    def _generate_sql(self, question: str, context: dict[str, Any]) -> str:
        prompt = self._sql_prompt(question, context)
        content = self._chat_completion(prompt, system_prompt=SQL_SYSTEM_PROMPT)
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
    ) -> str:
        answer = self._chat_completion(
            self._answer_prompt(question, rows, context),
            system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
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
            "supplemental_market_observations": self._supporting_data(question),
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
            "请直接给出结论、表格、投资逻辑、风险和跟踪项。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        result = self.db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]

    def _chat_completion(self, prompt: str, system_prompt: str | None = None) -> str:
        api_key = self.settings.resolve_llm_api_key()
        if not api_key:
            raise ValueError("LLM 未配置 API Key")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.1,
        }
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]

    def _chat_completion_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        api_key = self.settings.resolve_llm_api_key()
        if not api_key:
            raise ValueError("LLM 未配置 API Key")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
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
            "涉及 A 股选股、低估值、红利、蓝筹、ROE、PE、PB、股息率时"
            "优先查询 v_stock_selection_latest，"
            "并可用 v_stock_factor_dictionary 解释字段含义。"
            "字段名必须完全来自字段清单；不要使用 stock_name、ha_premium、ah_premium 等不存在字段，"
            "应使用 display_name/a_name/hk_name/name、ha_premium_pct、ah_premium_pct。"
            "不要使用写入、DDL、多语句。问题与上下文如下："
            f"{context_json}"
        )

    def _repair_sql(self, question: str, context: dict[str, Any], sql: str, error: str) -> str:
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
        content = self._chat_completion(prompt, system_prompt=SQL_SYSTEM_PROMPT)
        payload = self._extract_json(content)
        repaired_sql = payload.get("sql")
        if not isinstance(repaired_sql, str) or not repaired_sql.strip():
            raise ValueError("LLM 未返回修复后的 SQL")
        return repaired_sql

    def _supporting_data(self, question: str) -> dict[str, list[dict[str, Any]]] | None:
        if not self._is_ah_arbitrage_question(question) or not self._should_query_supporting_data(
            question
        ):
            return None
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
            supporting_data[key] = self._execute_sql(sql)
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

    def _default_sql_for_question(self, question: str) -> str | None:
        normalized = question.lower()
        if any(keyword in normalized for keyword in ("自选", "阈值", "机会状态")):
            return (
                "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                "opportunity_status "
                "FROM v_watchlist_opportunity "
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
                for keyword in ("a/h溢价", "ah溢价", "a股溢价", "h股便宜", "h股折价")
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
        normalized = question.lower().replace(" ", "")
        if re.search(r"\b\d{6}\.(sh|sz)\b|\b\d{5}\.hk\b", normalized):
            return True
        return any(keyword in normalized for keyword in INVESTMENT_KEYWORDS)

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
                "columns: watchlist_id,a_ts_code,hk_ts_code,display_name,preferred_direction,"
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
