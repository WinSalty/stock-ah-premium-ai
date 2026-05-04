from __future__ import annotations

import json
from unittest.mock import Mock

from app.core.config import Settings
from app.services.investment_knowledge_service import InvestmentKnowledgeService
from app.services.llm_service import OUT_OF_SCOPE_MESSAGE, LlmService


def test_llm_service_rejects_non_investment_question_before_api_call() -> None:
    """确认非投资问题被本地边界拦截。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key=None, llm_api_key_file=None, llm_model=None),
    )

    answer = service.answer("帮我写一首关于春天的诗")

    assert answer.answer == OUT_OF_SCOPE_MESSAGE
    assert answer.sql is None
    assert answer.rows == []


def test_llm_answer_prompt_loads_classified_investment_knowledge() -> None:
    """确认问答提示词按投资主题加载分类文档。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    prompt = service._answer_prompt(
        "A/H 溢价套利风险框架",
        rows=[],
        context={"conversation_history": [{"role": "user", "content": "先看港股通标的"}]},
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert "A/H 溢价与跨市场价差" in payload["knowledge_categories"]
    assert payload["reference_materials"]
    assert "conversation_history" in payload


def test_preamble_cleaner_removes_json_process_language() -> None:
    """确认回答前缀清理会去掉暴露过程的寒暄。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    cleaned = service._strip_forbidden_preamble(
        "好的，收到您的请求。我将基于提供的 JSON 数据进行回答。\n## 结论\n值得跟踪。"
    )

    assert cleaned.startswith("## 结论")


def test_investment_knowledge_selects_stock_factor_category() -> None:
    """确认选股类问题命中因子文档。

    创建日期：2026-05-04
    author: sunshengxian
    """

    selection = InvestmentKnowledgeService().select("筛选低估值、高股息且 ROE 稳定的股票")

    assert "A 股选股与估值因子" in selection.categories
    assert selection.chunks


def test_default_sql_uses_watchlist_and_correct_ha_discount_direction() -> None:
    """确认关注股票的 H/A 折价问题按 H 股折价方向排序。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    sql = service._default_sql_for_question("我关注的股票里，最近一个交易日哪些 H/A 折价最明显？")

    assert sql is not None
    assert "v_watchlist_opportunity" in sql
    assert "ORDER BY ha_premium_pct ASC" in sql
