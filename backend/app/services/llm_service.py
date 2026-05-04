from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.sql_guard_service import SqlGuardError, SqlGuardService


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

    def answer(self, question: str, context: dict[str, Any] | None = None) -> ChatAnswer:
        """根据本地数据回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

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
        answer = self._chat_completion(prompt)
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

        if not self.settings.resolve_llm_api_key() or not self.settings.llm_model:
            message = (
                "LLM 未配置。请设置 LLM_API_KEY_FILE 或 LLM_API_KEY，"
                "并设置 LLM_MODEL 后再使用智能问答。"
            )
            return None, [], iter([message])
        sql, rows, prompt = self._prepare_answer(question, context or {})
        return sql, rows, self._chat_completion_stream(prompt)

    def _prepare_answer(
        self,
        question: str,
        context: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]], str]:
        sql = self._default_sql_for_question(question) or self._generate_sql(question, context)
        for attempt in range(2):
            try:
                guarded = self.sql_guard.validate(
                    sql,
                    default_limit=self.settings.query_limit_default,
                    max_limit=self.settings.query_limit_max,
                )
                rows = self._execute_sql(guarded.sql)
                break
            except (SQLAlchemyError, SqlGuardError) as exc:
                if attempt == 1:
                    raise
                sql = self._repair_sql(question, context, sql, str(exc))
        return guarded.sql, rows, self._answer_prompt(question, guarded.sql, rows, context)

    def _generate_sql(self, question: str, context: dict[str, Any]) -> str:
        prompt = self._sql_prompt(question, context)
        content = self._chat_completion(prompt)
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
        return self._chat_completion(self._answer_prompt(question, sql, rows, context))

    def _answer_prompt(
        self,
        question: str,
        sql: str,
        rows: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> str:
        payload = {
            "question": question,
            "sql": sql,
            "rows": rows[:200],
            "supporting_data": self._supporting_data(question),
            "research_context": self._research_context(question),
            "context": context,
        }
        return (
            "你是金融数据分析助手。请基于 JSON 数据用中文 Markdown 回答，"
            "可以使用小标题、列表和表格；说明数据口径；不要编造结果，"
            "数据为空时明确说明。涉及 AH 溢价套利时，要区分“价差观察、"
            "配对交易设想、港股通可操作性、卖空/融资/汇率/税费限制”，"
            "不得把价差直接说成无风险套利。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        result = self.db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]

    def _chat_completion(self, prompt: str) -> str:
        api_key = self.settings.resolve_llm_api_key()
        if not api_key:
            raise ValueError("LLM 未配置 API Key")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": self.settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]

    def _chat_completion_stream(self, prompt: str) -> Iterator[str]:
        api_key = self.settings.resolve_llm_api_key()
        if not api_key:
            raise ValueError("LLM 未配置 API Key")
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": self.settings.llm_model,
            "messages": [{"role": "user", "content": prompt}],
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
            {"question": question, "context": context},
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
        content = self._chat_completion(prompt)
        payload = self._extract_json(content)
        repaired_sql = payload.get("sql")
        if not isinstance(repaired_sql, str) or not repaired_sql.strip():
            raise ValueError("LLM 未返回修复后的 SQL")
        return repaired_sql

    def _supporting_data(self, question: str) -> dict[str, list[dict[str, Any]]] | None:
        if not self._is_ah_arbitrage_question(question):
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

    def _research_context(self, question: str) -> list[str]:
        if not self._is_ah_arbitrage_question(question):
            return []
        doc_path = (
            Path(__file__).resolve().parents[3]
            / "resources"
            / "doc"
            / "ah-premium-arbitrage-research-2026.md"
        )
        if not doc_path.exists():
            return []
        content = doc_path.read_text(encoding="utf-8")
        chunks = [chunk.strip() for chunk in content.split("\n## ") if chunk.strip()]
        return chunks[:6]

    def _is_ah_arbitrage_question(self, question: str) -> bool:
        keywords = ("ah", "a/h", "h/a", "溢价", "折价", "套利", "价差", "港股通", "a股", "h股")
        normalized = question.lower()
        return any(keyword in normalized for keyword in keywords)

    def _default_sql_for_question(self, question: str) -> str | None:
        if not self._is_ah_arbitrage_question(question):
            return None
        normalized = question.lower()
        if any(keyword in normalized for keyword in ("哪些", "适合", "候选", "推荐", "筛选")):
            return (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ha_premium_pct DESC LIMIT 20"
            )
        return None

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
