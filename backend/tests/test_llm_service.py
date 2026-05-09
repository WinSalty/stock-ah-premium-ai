from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models.chat import LlmCallMetric
from app.services.investment_knowledge_service import InvestmentKnowledgeService
from app.services.llm_service import (
    INVESTMENT_ADVISOR_SYSTEM_PROMPT,
    LLM_LIMIT_EXCEEDED_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    QUESTION_ROUTER_SYSTEM_PROMPT,
    SERVICE_INTRO_MESSAGE,
    LlmCallTrace,
    LlmDailyLimitExceeded,
    LlmEndpoint,
    LlmService,
    QuestionRoute,
)
from app.services.market_data_orchestrator import MAX_MARKET_DATA_STOCKS, MarketDataDemand


def test_llm_service_rejects_unsafe_question_before_api_call() -> None:
    """确认违法违规和敏感信息问题仍会被本地边界拦截。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            llm_model=None,
            qwen_api_key=None,
            qwen_api_key_file=None,
        ),
    )

    answer = service.answer("帮我绕过风控做内幕交易")

    assert answer.answer == OUT_OF_SCOPE_MESSAGE
    assert answer.sql is None
    assert answer.rows == []


def test_llm_answer_prompt_loads_routed_investment_knowledge() -> None:
    """确认问答提示词按前置路由选择加载知识库分类。

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
        route=QuestionRoute(
            is_answerable=True,
            should_query_data=False,
            use_knowledge=True,
            knowledge_category_keys=("ah_premium",),
        ),
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert "A/H 溢价与跨市场价差" in payload["knowledge_categories"]
    assert payload["reference_materials"]
    assert "conversation_history" in payload


def test_llm_answer_prompt_can_skip_investment_knowledge() -> None:
    """确认前置路由判断不需要知识库时不会塞参考材料。

    创建日期：2026-05-05
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    prompt = service._answer_prompt(
        "我自选里哪些最接近阈值？",
        rows=[{"display_name": "招商银行", "distance_to_target_pct": "0.5"}],
        context={},
        route=QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            use_knowledge=False,
        ),
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert payload["knowledge_categories"] == []
    assert payload["reference_materials"] == []


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


def test_threshold_recommendation_markdown_normalizer_breaks_stuck_headings() -> None:
    """确认阈值推荐会把粘在正文后的二级标题拆成独立段落。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    cleaned = service._normalize_threshold_recommendation_markdown(
        "## 最终答案\n\n"
        "建议将 H/A 目标阈值设为 -44.35%。 ## 推荐理由\n"
        "1. 历史分位锁定。 ## 执行条件\n"
        "- 触发条件：价差回归。"
    )

    assert "。 ## 推荐理由" not in cleaned
    assert "。 ## 执行条件" not in cleaned
    assert "设为 -44.35%。\n\n## 推荐理由\n\n1. 历史分位锁定。" in cleaned
    assert "历史分位锁定。\n\n## 执行条件\n\n- 触发条件：价差回归。" in cleaned


def test_threshold_recommendation_prompt_requires_standalone_headings() -> None:
    """确认阈值推荐提示词明确要求小节标题单独占行。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    prompt = service._threshold_recommendation_prompt(
        "为招商银行推荐 H/A 目标阈值",
        {
            "threshold_recommendation": {
                "name": "招商银行",
                "direction": "HA",
                "metric_premium_pct": "-46.81",
                "premium_median_60": "-44.75",
                "premium_p80_60": "-44.13",
            }
        },
    )

    assert "不要把二级标题接在正文同一行" in prompt
    assert "三个标题都要单独占一行，标题前后空一行" in prompt


def test_investment_advisor_prompt_allows_professional_opinions() -> None:
    """确认投资顾问提示词允许输出明确研究判断。

    创建日期：2026-05-04
    author: sunshengxian
    """

    assert "评级口径" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "配置倾向" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "阈值和触发条件" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "不要把整条结论或多句长文本全部加粗" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "不要输出“不构成投资建议”" in INVESTMENT_ADVISOR_SYSTEM_PROMPT


def test_clear_investment_question_uses_default_deepseek_router(monkeypatch) -> None:
    """确认投资问题默认跟随 DeepSeek 问答模型做前置路由。

    创建日期：2026-05-05
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="test-key",
            llm_api_key_file=None,
            llm_model="deepseek-v4-flash",
        ),
    )

    captured: dict[str, object] = {}

    def fake_chat_completion(
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
    ) -> str:
        captured["model"] = model
        captured["prompt"] = prompt
        captured["phase"] = trace.phase if trace else None
        return (
            '{"is_answerable":true,"needs_sql":false,"use_knowledge":true,'
            '"knowledge_categories":["ah_premium"],"reason":"需要 A/H 价差框架"}'
        )

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    route = service._route_question("招商银行现在估值怎么看")

    assert route.is_answerable is True
    assert route.should_query_data is False
    assert route.use_knowledge is True
    assert route.knowledge_category_keys == ("ah_premium",)
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["phase"] == "question_router"
    assert "knowledge_catalog" in str(captured["prompt"])


def test_question_router_prompt_requires_multi_package_evidence_chain() -> None:
    """确认路由提示词要求单股研究主动组合多个证据包。

    创建日期：2026-05-09
    author: sunshengxian
    """

    assert "不要把单股研究压缩成一个数据包" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "A 股数据包含义" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "quote_valuation：日线行情" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert (
        "financial_statement：利润表、资产负债表、现金流量表、财务指标"
        in QUESTION_ROUTER_SYSTEM_PROMPT
    )
    assert "business_profile：主营业务产品/地区构成" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "dividend_forecast：分红方案" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "shareholder_governance：前十大股东、前十大流通股东" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "capital_flow_light：近端个股资金流向" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "个股投资分析报告" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert (
        "quote_valuation、\nfinancial_statement、business_profile、dividend_forecast、shareholder_governance"
        in QUESTION_ROUTER_SYSTEM_PROMPT
    )


def test_question_router_prompt_requires_accounting_review_packages() -> None:
    """确认财报异常和报表更改问题会提示路由主动要三类校验包。

    创建日期：2026-05-09
    author: sunshengxian
    """

    assert "财务报表大幅更改" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert "会计政策/会计估计变更" in QUESTION_ROUTER_SYSTEM_PROMPT
    assert (
        "必须选择 financial_statement、business_profile、\nshareholder_governance"
        in QUESTION_ROUTER_SYSTEM_PROMPT
    )


def test_route_from_payload_accepts_market_data_demands() -> None:
    """确认前置路由可以声明单股白名单数据包需求。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    route = service._route_from_payload(
        {
            "is_answerable": True,
            "needs_sql": False,
            "use_knowledge": True,
            "knowledge_categories": ["ah_premium", "unknown_legacy_category"],
            "data_demands": [
                {
                    "market": "A",
                    "ts_code": "600036.SH",
                    "packages": [
                        "quote_valuation",
                        "financial_statement",
                        "business_profile",
                        "shareholder_governance",
                        "capital_flow_light",
                        "danger_api",
                    ],
                }
            ],
        }
    )

    assert route.data_demands[0].ts_code == "600036.SH"
    assert route.data_demands[0].packages == (
        "quote_valuation",
        "financial_statement",
        "business_profile",
        "shareholder_governance",
        "capital_flow_light",
    )
    assert route.knowledge_category_keys == ("ah_premium",)


def test_route_from_payload_accepts_hk_financial_demand_only() -> None:
    """确认港股路由需求只能保留港股财务包，避免触发未接入的数据域。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    route = service._route_from_payload(
        {
            "is_answerable": True,
            "needs_sql": False,
            "use_knowledge": False,
            "data_demands": [
                {
                    "market": "HK",
                    "ts_code": "02380.HK",
                    "packages": ["quote_valuation", "financial_statement", "capital_flow_light"],
                }
            ],
        }
    )

    assert route.data_demands[0].ts_code == "02380.HK"
    assert route.data_demands[0].market == "HK"
    assert route.data_demands[0].packages == ("financial_statement",)


def test_route_from_payload_downgrades_hk_non_financial_packages() -> None:
    """确认港股路由即便误报非财务包，也会在本地降级为受控财务包。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    route = service._route_from_payload(
        {
            "is_answerable": True,
            "needs_sql": False,
            "use_knowledge": False,
            "data_demands": [
                {
                    "market": "HK",
                    "ts_code": "02380.HK",
                    "packages": ["quote_valuation", "capital_flow_light"],
                }
            ],
        }
    )

    assert route.data_demands[0].packages == ("financial_statement",)


def test_route_from_payload_accepts_up_to_five_market_data_demands() -> None:
    """确认前置路由最多接收 5 只股票的白名单补数需求。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    route = service._route_from_payload(
        {
            "is_answerable": True,
            "needs_sql": False,
            "use_knowledge": False,
            "data_demands": [
                {"ts_code": f"00000{index}.SZ", "packages": ["quote_valuation"]}
                for index in range(1, 7)
            ],
        }
    )

    assert len(route.data_demands) == MAX_MARKET_DATA_STOCKS
    assert route.data_demands[-1].ts_code == "000005.SZ"


def test_answer_prompt_includes_market_data_context_and_report_instruction() -> None:
    """确认个股报告提示词会携带市场上下文并强调专业分析方法。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    prompt = service._answer_prompt(
        "招商银行投资分析报告",
        rows=[],
        context={},
        market_data_context={"stock": {"ts_code": "600036.SH"}, "context": {"latest": []}},
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert payload["market_data_context"]["stock"]["ts_code"] == "600036.SH"
    assert "扣非净利润" in prompt
    assert "经营现金流覆盖" in prompt
    assert "主营业务构成" in prompt
    assert "资金流只用于解释短期交易情绪" in prompt
    assert "最近 24 期" in prompt
    assert "market_data_context，请优先使用其中的补数上下文作为主证据" in prompt
    assert "不得据此判断没有财务数据" in prompt
    assert "第二块必须先给关键财务趋势表" in prompt
    assert "A 股和港股都要优先选取收入" in prompt
    assert "15000 积分" not in prompt
    assert "随查询减少的余额" not in prompt


def test_data_only_answer_shows_24_financial_periods() -> None:
    """确认财务问数会展示 24 期上下文，不再被旧的 20 行展示上限截断。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    rows = [
        {
            "ts_code": "601225.SH",
            "name": "陕西煤业",
            "end_date": f"202{i // 4}-{((i % 4) + 1) * 3:02d}-30",
            "roe": i,
        }
        for i in range(24)
    ]

    answer = service._data_only_answer(
        "给我展示陕西煤业最近 24 期财务摘要数据",
        rows=[],
        market_data_context={"context": {"financial_periods": rows}},
    )

    assert answer.count("| 601225.SH |") == 24
    assert "前 20 行" not in answer


def test_report_analysis_question_prefers_structured_stock_data() -> None:
    """确认个股报告问题退出本地报告依赖后会优先查询结构化数据。

    创建日期：2026-05-05
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    question = "寒武纪 688256 深度价值投资怎么看？"

    assert service._should_query_data(question, {}) is True


def test_prepare_answer_skips_sql_when_market_data_context_exists(monkeypatch) -> None:
    """确认个股按需补数成功后不会再额外生成通用 SQL。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    monkeypatch.setattr(
        service,
        "_ensure_market_data_context",
        lambda *args, **kwargs: {
            "scope": "HK_STOCK_SINGLE",
            "financial_periods": [{"ts_code": "00700.HK", "end_date": "2025-12-31"}],
        },
    )

    def fail_generate_sql(*args, **kwargs):
        raise AssertionError("已有按需补数上下文时不应生成通用 SQL")

    monkeypatch.setattr(service, "_generate_sql", fail_generate_sql)

    sql, rows, prompt = service._prepare_answer(
        "分析一下腾讯",
        {},
        QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            use_knowledge=False,
            data_demands=(
                MarketDataDemand("00700.HK", ("financial_statement",), market="HK"),
            ),
        ),
        "test-model",
        "trace-test",
        None,
        None,
    )

    payload = json.loads(prompt.split("\n", 1)[1])
    assert sql is None
    assert rows == []
    assert payload["market_data_context"]["scope"] == "HK_STOCK_SINGLE"


def test_llm_trace_id_is_unique_for_each_question_turn() -> None:
    """确认相同问题在不同轮问答中也会生成不同追踪 ID。

    创建日期：2026-05-06
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    first_trace_id = service._new_trace_id()
    second_trace_id = service._new_trace_id()

    assert first_trace_id != second_trace_id
    assert len(first_trace_id) == 32
    assert len(second_trace_id) == 32


def test_investment_knowledge_selects_stock_factor_category() -> None:
    """确认选股类问题命中因子文档。

    创建日期：2026-05-04
    author: sunshengxian
    """

    selection = InvestmentKnowledgeService().select("筛选低估值、高股息且 ROE 稳定的股票")

    assert "A 股选股与估值因子" in selection.categories
    assert selection.chunks


def test_investment_knowledge_reads_docx_reports(tmp_path: Path) -> None:
    """确认 LLM 知识服务仍可读取非个股分类中的 docx 材料。

    创建日期：2026-05-04
    author: sunshengxian
    """

    report_path = tmp_path / "ah-premium" / "cmb-ah-premium-arbitrage-report-2026.docx"
    _write_minimal_docx(
        report_path,
        paragraphs=(
            "招商银行 A/H 倒挂与融资套利约束",
            "核心结论：价差只能作为择边信号，需要同时检查港股通、融资成本和汇率。",
        ),
    )

    selection = InvestmentKnowledgeService(doc_root=tmp_path).select("招商银行 AH 价差怎么做择边？")

    assert "A/H 溢价与跨市场价差" in selection.categories
    assert any("择边信号" in chunk["content"] for chunk in selection.chunks)


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


def test_investment_knowledge_selects_threshold_recommendation_logic() -> None:
    """确认阈值推荐问题命中稳定推荐逻辑文档。

    创建日期：2026-05-04
    author: sunshengxian
    """

    selection = InvestmentKnowledgeService().select("招商银行 H/A 目标阈值应该设多少？")

    assert "A/H 溢价与跨市场价差" in selection.categories
    assert any("统一计算框架" in chunk["content"] for chunk in selection.chunks)


def test_threshold_recommendation_fast_path_skips_router_and_market_data(monkeypatch) -> None:
    """确认结构化阈值推荐走快路径，不再触发路由、消歧、补数和辅助视图。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    monkeypatch.setattr(
        service,
        "_route_question",
        Mock(side_effect=AssertionError("threshold fast path should skip router")),
    )
    monkeypatch.setattr(
        service,
        "_ensure_market_data_context",
        Mock(side_effect=AssertionError("threshold fast path should skip market data")),
    )
    captured_prompt: dict[str, str] = {}

    def fake_chat_completion(
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
    ) -> str:
        captured_prompt["prompt"] = prompt
        captured_prompt["phase"] = trace.phase if trace else ""
        return "## 最终答案\n\n建议将 H/A 目标阈值设为 10.55%。"

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    answer = service.answer(
        "为招商银行推荐 H/A 目标阈值",
        context={
            "threshold_recommendation": {
                "name": "招商银行",
                "direction": "HA",
                "metric_premium_pct": "9.8",
                "premium_median_60": "8.6",
                "premium_p80_60": "11.6",
                "premium_percentile_60": "72",
            }
        },
    )

    assert answer.sql is None
    assert answer.rows == []
    assert "10.55" in captured_prompt["prompt"]
    assert captured_prompt["phase"] == "threshold_answer"


def test_threshold_recommendation_uses_deterministic_formula() -> None:
    """确认阈值公式按 60 日中位数和 80% 分位稳定计算。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    result = service._calculate_threshold_recommendation(
        {
            "threshold_recommendation": {
                "direction": "HA",
                "metric_premium_pct": "9.8",
                "premium_median_60": "8.6",
                "premium_p80_60": "11.6",
                "premium_percentile_60": "72",
            }
        }
    )

    assert service._format_threshold_number(result.threshold_pct) == "10.55"
    assert result.reason_code == "base_formula"


def test_threshold_recommendation_stream_fast_path_logs_stream_phase(monkeypatch) -> None:
    """确认阈值推荐流式快路径使用专用阶段，便于耗时追踪。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    captured: dict[str, str] = {}

    def fake_chat_completion_stream(
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        trace: LlmCallTrace | None = None,
        total_started_at: float | None = None,
        row_count: int = 0,
        total_phase: str = "stream_done",
    ) -> Iterator[str]:
        captured["phase"] = trace.phase if trace else ""
        yield "## 最终答案\n\n"
        yield "建议将 H/A 目标阈值设为 10.55%。"

    monkeypatch.setattr(service, "_chat_completion_stream", fake_chat_completion_stream)

    sql, rows, chunks = service.stream_answer(
        "为招商银行推荐 H/A 目标阈值",
        context={
            "threshold_recommendation": {
                "name": "招商银行",
                "direction": "HA",
                "metric_premium_pct": "9.8",
                "premium_median_60": "8.6",
                "premium_p80_60": "11.6",
                "premium_percentile_60": "72",
            }
        },
    )

    assert sql is None
    assert rows == []
    assert "10.55" in "".join(chunks)
    assert captured["phase"] == "threshold_answer_stream"


def test_deepseek_model_alias_uses_supported_api_name(monkeypatch) -> None:
    """确认 DeepSeek 历史模型别名会转换为 API 支持的模型名。

    创建日期：2026-05-04
    author: sunshengxian
    """

    captured_payload: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeClient)
    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="test-key",
            llm_api_key_file=None,
            llm_model="deepseek-v4-pro[1m]",
        ),
    )

    assert service._chat_completion("招商银行阈值建议") == "ok"
    assert captured_payload["model"] == "deepseek-v4-pro"
    assert "reasoning_effort" not in captured_payload


def test_default_chat_model_is_deepseek_flash() -> None:
    """确认默认问答模型仍使用 DeepSeek Flash。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="test-key",
            llm_api_key_file=None,
        ),
    )

    endpoint = service._model_endpoint()

    assert endpoint.provider == "DeepSeek"
    assert endpoint.model == "deepseek-v4-flash"


def test_qwen_chat_model_uses_qwen_endpoint(monkeypatch) -> None:
    """确认选择 Qwen 模型时使用阿里 DashScope 端点和 Qwen Key。

    创建日期：2026-05-04
    author: sunshengxian
    """

    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "qwen ok"}}]}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeClient)
    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="deepseek-key",
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
        ),
    )

    assert service._chat_completion("分析招商银行", model="qwen3.6-flash") == "qwen ok"
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer qwen-key"}
    assert captured["payload"]["model"] == "qwen3.6-flash"


def test_uncertain_question_scope_uses_default_deepseek_router(monkeypatch) -> None:
    """确认本地规则不确定时默认使用 DeepSeek 路由。

    创建日期：2026-05-04
    author: sunshengxian
    """

    captured_payload: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"is_answerable":true,"needs_sql":false,'
                                '"use_knowledge":false,"knowledge_categories":[],'
                                '"reason":"允许回答"}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeClient)
    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="deepseek-key",
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
        ),
    )

    assert service._is_investment_related_question("这件事是否值得继续推进")
    assert captured_payload["model"] == "deepseek-v4-flash"


def test_question_router_falls_back_to_qwen_when_deepseek_busy(monkeypatch) -> None:
    """确认问题路由遇到 DeepSeek 临时繁忙时透明切换到 Qwen。

    创建日期：2026-05-08
    author: sunshengxian
    """

    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, status_code: int, content: str) -> None:
            self.status_code = status_code
            self._content = content
            self.request = httpx.Request("POST", "https://example.test/chat/completions")

        @property
        def text(self) -> str:
            return self._content

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "busy",
                    request=self.request,
                    response=httpx.Response(
                        self.status_code,
                        request=self.request,
                        text=self._content,
                    ),
                )

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"is_answerable":true,"needs_sql":false,'
                                '"use_knowledge":true,"knowledge_categories":["ah_premium"],'
                                '"reason":"备用模型路由成功"}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            calls.append({"url": url, "headers": headers, "payload": json})
            if json["model"] == "deepseek-v4-flash":
                return FakeResponse(503, "Service is too busy")
            return FakeResponse(200, "ok")

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeClient)
    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="deepseek-key",
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
        ),
    )

    route = service._route_question("招商银行现在估值怎么看")

    assert route.is_answerable is True
    assert route.use_knowledge is True
    assert route.knowledge_category_keys == ("ah_premium",)
    assert [call["payload"]["model"] for call in calls] == [
        "deepseek-v4-flash",
        "qwen3.6-flash",
    ]


def test_deepseek_busy_falls_back_to_qwen(monkeypatch) -> None:
    """确认 DeepSeek 临时繁忙时自动切换到 Qwen。

    创建日期：2026-05-08
    author: sunshengxian
    """

    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, status_code: int, content: str) -> None:
            self.status_code = status_code
            self._content = content
            self.request = httpx.Request("POST", "https://example.test/chat/completions")

        @property
        def text(self) -> str:
            return self._content

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "busy",
                    request=self.request,
                    response=httpx.Response(
                        self.status_code,
                        request=self.request,
                        text=self._content,
                    ),
                )

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "qwen fallback ok"}}]}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            calls.append({"url": url, "headers": headers, "payload": json})
            if json["model"] == "deepseek-v4-flash":
                return FakeResponse(503, "Service is too busy")
            return FakeResponse(200, "ok")

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeClient)
    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="deepseek-key",
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
        ),
    )

    answer = service._chat_completion("分析招商银行", model="deepseek-v4-flash")

    assert answer == "qwen fallback ok"
    assert [call["payload"]["model"] for call in calls] == ["deepseek-v4-flash", "qwen3.6-flash"]


def test_threshold_stream_falls_back_to_local_formula_on_model_error() -> None:
    """确认阈值推荐流式模型失败时仍返回本地公式结果。

    创建日期：2026-05-08
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    def broken_chunks() -> Iterator[str]:
        request = httpx.Request("POST", "https://example.test/chat/completions")
        raise httpx.HTTPStatusError(
            "busy",
            request=request,
            response=httpx.Response(503, request=request, text="busy"),
        )
        yield ""

    answer = "".join(
        service._fallback_threshold_stream(
            broken_chunks(),
            {
                "threshold_recommendation": {
                    "name": "招商银行",
                    "direction": "HA",
                    "metric_premium_pct": "9.8",
                    "premium_median_60": "8.6",
                    "premium_p80_60": "11.6",
                }
            },
            "threshold-test",
        )
    )

    assert "建议将招商银行的 H/A 目标阈值设为 10.55%" in answer


def test_service_intro_question_skips_classifier_and_returns_role_intro(monkeypatch) -> None:
    """确认问候和能力介绍类问题本地放行，不等待分类 LLM。

    创建日期：2026-05-04
    author: sunshengxian
    """

    captured_models: list[str | None] = []

    def fake_chat_completion(
        self: LlmService,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: object | None = None,
    ) -> str:
        captured_models.append(model)
        return '{"is_investment_related":true}'

    monkeypatch.setattr(LlmService, "_chat_completion", fake_chat_completion)
    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
        ),
    )

    answer = service.answer("你好，你可以干嘛")

    assert answer.answer == SERVICE_INTRO_MESSAGE
    assert answer.rows == []
    assert captured_models == []


def test_out_of_scope_message_is_soft_and_actionable() -> None:
    """确认越界问题响应更自然，并提示可改问方向。

    创建日期：2026-05-04
    author: sunshengxian
    """

    assert "敏感信息" in OUT_OF_SCOPE_MESSAGE
    assert "通用知识" in OUT_OF_SCOPE_MESSAGE


def test_llm_completion_metric_is_persisted() -> None:
    """确认 LLM 调用耗时指标会落库。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = LlmService(
            db,
            settings=Settings(llm_api_key="test-key", llm_api_key_file=None),
        )

        service._log_llm_completion(
            LlmEndpoint(
                provider="Qwen",
                base_url="https://example.test",
                api_key="test-key",
                model="qwen3.6-flash",
            ),
            LlmCallTrace(
                question_id="1234567",
                phase="answer",
                user_id=9,
                session_id=18,
            ),
            perf_counter() - 0.01,
            "ok",
            '{"model":"qwen3.6-flash"}',
        )

        metric = db.scalar(select(LlmCallMetric).where(LlmCallMetric.question_id == "1234567"))

    assert metric is not None
    assert metric.phase == "answer"
    assert metric.provider == "Qwen"
    assert metric.model == "qwen3.6-flash"
    assert metric.user_id == 9
    assert metric.session_id == 18
    assert metric.output_chars == 2
    assert metric.elapsed_ms is not None
    assert metric.phase_label == "非流式回答"
    assert metric.request_payload_json == '{"model":"qwen3.6-flash"}'
    assert metric.response_content == "ok"


def test_daily_llm_call_limit_counts_external_main_phases_only() -> None:
    """确认项目级日限流只统计真实外部模型主调用。

    创建日期：2026-05-05
    author: sunshengxian
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    with Session(engine) as db:
        for index in range(99):
            db.add(
                LlmCallMetric(
                    question_id=f"q{index}",
                    phase="answer",
                    provider="DeepSeek",
                    model="deepseek-v4-flash",
                    created_at=today,
                    updated_at=today,
                )
            )
        db.add(
            LlmCallMetric(
                question_id="first-chunk",
                phase="answer_stream_first_chunk",
                provider="DeepSeek",
                model="deepseek-v4-flash",
                created_at=today,
                updated_at=today,
            )
        )
        db.commit()
        service = LlmService(
            db,
            settings=Settings(llm_api_key="test-key", llm_api_key_file=None),
        )
        endpoint = LlmEndpoint(
            provider="DeepSeek",
            base_url="https://example.test",
            api_key="test-key",
            model="deepseek-v4-flash",
        )

        service._enforce_daily_llm_call_limit(endpoint, None)
        db.add(
            LlmCallMetric(
                question_id="router",
                phase="question_router",
                provider="Qwen",
                model="qwen3.6-flash",
                created_at=today,
                updated_at=today,
            )
        )
        db.commit()

        try:
            service._enforce_daily_llm_call_limit(endpoint, None)
        except LlmDailyLimitExceeded as exc:
            assert str(exc) == LLM_LIMIT_EXCEEDED_MESSAGE
        else:
            raise AssertionError("daily LLM limit should be enforced")


def _write_minimal_docx(path: Path, paragraphs: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as docx_file:
        docx_file.writestr("word/document.xml", document_xml)


def test_general_direct_question_is_allowed_without_investment_boundary() -> None:
    """确认翻译和通用知识问答不再被投资边界误拦截。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    route = QuestionRoute(is_answerable=True, should_query_data=False, use_knowledge=False)

    assert service._is_general_direct_question("把这句话翻译成英文：利润质量很重要", route) is True


def test_data_only_answer_returns_table_without_analysis_prompt() -> None:
    """确认只要数据场景直接返回 Markdown 表格和后续数据类型提示。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    answer = service._data_only_answer(
        "我只要数据不要你分析",
        [
            {
                "ts_code": "600036.SH",
                "name": "招商银行",
                "end_date": "2026-03-31",
                "n_income_attr_p": "37852000000",
                "profit_dedt": "35000000000",
            }
        ],
        None,
    )

    assert "| 股票代码 | 名称 | 报告期 | 归母净利润 | 扣非净利润 |" in answer
    assert "需要分析时直接告诉我" in answer
    assert "核心结论" not in answer


def test_financial_data_question_is_data_only_without_explicit_only_keyword() -> None:
    """确认用户直接索要财报数据时进入问数模式，不再误生成投资报告。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    assert service._is_data_only_question("给我近三年招商银行的财报数据") is True
    assert service._is_data_only_question("给我近三年招商银行投资收益数据") is True
    assert service._is_data_only_question("分析招商银行近三年的财报数据") is False


def test_data_only_answer_prefers_tushare_context_for_financial_question() -> None:
    """确认财报问数优先展示按需补数上下文中的最新 Tushare 报告期。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    answer = service._data_only_answer(
        "给我近三年招商银行的财报数据",
        [{"ts_code": "600036.SH", "name": "招商银行", "end_date": "2024-12-31"}],
        {
            "context": {
                "financial_periods": [
                    {"ts_code": "600036.SH", "name": "招商银行", "end_date": "2026-03-31"}
                ]
            }
        },
    )

    assert "2026-03-31" in answer
    assert "2024-12-31" not in answer


def test_stock_report_instruction_requires_profit_quality_checks() -> None:
    """确认个股分析报告提示词强调扣非、投资收益和现金流核验。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    instruction = service._stock_report_instruction("拉卡拉投资分析报告", {"status": "COMPLETED"})

    assert "扣非净利润" in instruction
    assert "投资收益" in instruction
    assert "经营现金流覆盖" in instruction
    assert "主营业务构成" in instruction
    assert "股东治理" in instruction
    assert "不要因为表面估值低就自动给乐观结论" in instruction
