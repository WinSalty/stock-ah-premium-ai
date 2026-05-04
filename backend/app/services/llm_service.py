from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.sql_guard_service import SqlGuardService


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
    """OpenAI-compatible LLM 问答服务。

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

        if not self.settings.llm_api_key or not self.settings.llm_model:
            return ChatAnswer(
                answer="LLM 未配置。请设置 LLM_API_KEY 和 LLM_MODEL 后再使用智能问答。",
                sql=None,
                rows=[],
            )
        sql = self._generate_sql(question, context or {})
        guarded = self.sql_guard.validate(
            sql,
            default_limit=self.settings.query_limit_default,
            max_limit=self.settings.query_limit_max,
        )
        rows = self._execute_sql(guarded.sql)
        answer = self._generate_answer(question, guarded.sql, rows, context or {})
        return ChatAnswer(answer=answer, sql=guarded.sql, rows=rows)

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
        payload = {
            "question": question,
            "sql": sql,
            "rows": rows[:50],
            "context": context,
        }
        prompt = (
            "你是金融数据分析助手。请基于 JSON 数据用中文回答，说明数据口径；"
            "不要编造结果，数据为空时明确说明。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        return self._chat_completion(prompt)

    def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        result = self.db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]

    def _chat_completion(self, prompt: str) -> str:
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
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

    def _sql_prompt(self, question: str, context: dict[str, Any]) -> str:
        schema = {
            "v_latest_official_ah_premium": "最新交易日官方 AH/H/A 溢价结果，含港股通通道",
            "v_official_ah_premium_trend": "官方 AH/H/A 溢价历史趋势",
            "v_latest_hk_connect_official_ah_premium": "最新交易日且港股通可操作的官方溢价结果",
            "v_watchlist_opportunity": "自选股机会状态，含阈值、距离、通道和来源",
            "v_latest_ah_premium": "兼容旧名称，实际同最新官方 AH/H/A 溢价结果",
            "v_ah_premium_trend": "兼容旧名称，实际同官方 AH/H/A 溢价历史趋势",
            "v_sync_health": "数据同步运行状态",
            "v_data_quality_issues": "数据质量问题",
        }
        context_json = json.dumps(
            {"question": question, "context": context},
            ensure_ascii=False,
            default=str,
        )
        return (
            "你只负责生成只读 MySQL SELECT SQL，必须返回 JSON：{\"sql\":\"...\"}。"
            "只能查询这些视图："
            f"{json.dumps(schema, ensure_ascii=False)}。"
            "默认使用官方 AH 比价口径；H/A 字段由官方 A/H 反推；"
            "涉及可操作性时优先查询含 hk_connect 或 watchlist 的视图。"
            "不要使用写入、DDL、多语句。问题与上下文如下："
            f"{context_json}"
        )

    def _extract_json(self, content: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError("LLM 返回内容不是 JSON")
        return json.loads(match.group(0))
