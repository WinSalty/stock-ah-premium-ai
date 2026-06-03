from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from time import perf_counter
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models.chat import LlmCallMetric
from app.db.models.market import AStockBasic, HKStockBasic
from app.services.llm_service import (
    DIVIDEND_REINVESTMENT_ANSWER_MODE,
    DIVIDEND_REINVESTMENT_SQL_POLICY,
    FOLLOW_UP_ASSISTANT_SYSTEM_PROMPT,
    FOLLOW_UP_ROUTER_SYSTEM_PROMPT,
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


def test_llm_answer_prompt_omits_static_material_payload() -> None:
    """确认回答提示词不再注入额外静态材料分类或参考内容。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    service._supporting_data = Mock(return_value={})  # type: ignore[method-assign]

    prompt = service._answer_prompt(
        "我自选里哪些最接近阈值？",
        rows=[{"display_name": "招商银行", "distance_to_target_pct": "0.5"}],
        context={},
        route=QuestionRoute(is_answerable=True, should_query_data=True),
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert set(payload) >= {
        "user_question",
        "conversation_history",
        "filters",
        "market_observations",
        "supplemental_market_observations",
        "market_data_context",
    }
    assert "静态材料" in payload["material_source_policy"]
    assert "历史研报" in payload["material_source_policy"]

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
        captured["system_prompt"] = system_prompt
        captured["phase"] = trace.phase if trace else None
        return (
            '{"is_answerable":true,"needs_sql":false,'
            '"reason":"允许回答"}'
        )

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    route = service._route_question("招商银行现在估值怎么看")

    assert route.is_answerable is True
    assert route.should_query_data is False
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["phase"] == "question_router"
    assert "A 股数据包含义" in str(captured["system_prompt"])


def test_question_router_payload_omits_local_stock_candidates(monkeypatch) -> None:
    """确认前置路由不再携带本地候选，股票代码识别交给独立直识别阶段。

    创建日期：2026-06-02
    author: codex
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            AStockBasic(
                ts_code="600036.SH",
                symbol="600036",
                name="招商银行",
                industry="银行",
                list_status="L",
            )
        )
        db.commit()
        service = LlmService(
            db,
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
            captured["prompt"] = prompt
            return (
                '{"is_answerable":true,"needs_sql":false,'
                '"answer_mode":"stock_research",'
                '"data_demands":[{"market":"A","ts_code":"600036.SH",'
                '"packages":["quote_valuation","financial_statement"],'
                '"intent":"stock_research"}],"reason":"模型直接识别招商银行"}'
            )

        monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

        route = service._route_question("招商银行现在怎么看")

    payload = json.loads(str(captured["prompt"]))
    assert "stock_candidates" not in payload
    assert route.answer_mode == "stock_research"
    assert route.data_demands[0].packages == ("quote_valuation", "financial_statement")


def test_question_router_prompt_requires_multi_package_evidence_chain() -> None:
    """确认路由提示词要求单股研究主动组合多个证据包。

    创建日期：2026-05-09
    author: sunshengxian
    """

    assert "数据包分类是内部证据菜单" in QUESTION_ROUTER_SYSTEM_PROMPT
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
    assert "A/H 或港股通择边问题" in QUESTION_ROUTER_SYSTEM_PROMPT


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
            "answer_mode": "stock_research",
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
    assert route.answer_mode == "stock_research"
    assert route.data_demands[0].packages == (
        "quote_valuation",
        "financial_statement",
        "business_profile",
        "shareholder_governance",
        "capital_flow_light",
    )


def test_route_from_payload_requires_answer_mode() -> None:
    """确认新版前置路由必须显式返回 answer_mode。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    try:
        service._route_from_payload(
            {
                "is_answerable": True,
                "needs_sql": True,
                "data_demands": [
                    {
                        "market": "HK",
                        "ts_code": "01810.HK",
                        "packages": ["financial_statement"],
                        "intent": "stock_research",
                    }
                ],
                "reason": "用户请求分析小米集团，属于港股投资分析，需要结构化财务数据支撑。",
            }
        )
    except ValueError as exc:
        assert "answer_mode" in str(exc)
    else:
        raise AssertionError("answer_mode should be required")


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
            "answer_mode": "stock_research",
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
            "answer_mode": "stock_research",
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
            "answer_mode": "stock_research",
            "data_demands": [
                {"ts_code": f"00000{index}.SZ", "packages": ["quote_valuation"]}
                for index in range(1, 7)
            ],
        }
    )

    assert len(route.data_demands) == MAX_MARKET_DATA_STOCKS
    assert route.data_demands[-1].ts_code == "000005.SZ"


def test_route_prefers_direct_llm_stock_code_extraction(monkeypatch) -> None:
    """确认个股研究会先让 LLM 直接识别股票代码，再用本地基础表验真。

    创建日期：2026-06-02
    author: codex
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AStockBasic(ts_code="601101.SH", symbol="601101", name="昊华能源", list_status="L"))
        db.commit()
        service = LlmService(
            db,
            settings=Settings(
                llm_api_key="test-key",
                llm_api_key_file=None,
                llm_model="deepseek-v4-flash",
            ),
        )

        def fake_chat_completion(
            prompt: str,
            system_prompt: str | None = None,
            model: str | None = None,
            temperature: float = 0.1,
            trace: LlmCallTrace | None = None,
            response_format: dict[str, str] | None = None,
        ) -> str:
            if trace and trace.phase == "stock_disambiguation":
                raise AssertionError("直接识别成功时不应再进入候选消歧")
            assert trace is not None
            assert trace.phase == "stock_code_extraction"
            assert response_format == {"type": "json_object"}
            return (
                '{"items":[{"name":"昊华能源","ts_code":"601101.SH",'
                '"market":"SH","confidence":1.0}],'
                '"ambiguous":false,"reason":"明确命中昊华能源"}'
            )

        monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

        route = service._route_with_semantic_stocks(
            "帮我分析一下昊华能源",
            {},
            QuestionRoute(
                is_answerable=True,
                should_query_data=True,
                answer_mode="stock_research",
            ),
            "trace-direct",
            None,
            None,
        )

    assert route.data_demands[0].ts_code == "601101.SH"
    assert route.data_demands[0].market == "A"
    assert route.data_demands[0].packages == (
        "quote_valuation",
        "financial_statement",
        "business_profile",
        "dividend_forecast",
        "shareholder_governance",
    )


def test_direct_llm_stock_code_extraction_normalizes_hk_code(monkeypatch) -> None:
    """确认 LLM 返回的四位港股代码会补零，并通过港股基础表校验。

    创建日期：2026-06-02
    author: codex
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(HKStockBasic(ts_code="02380.HK", name="中国电力", list_status="L"))
        db.commit()
        service = LlmService(
            db,
            settings=Settings(
                llm_api_key="test-key",
                llm_api_key_file=None,
                llm_model="deepseek-v4-flash",
            ),
        )

        def fake_chat_completion(
            prompt: str,
            system_prompt: str | None = None,
            model: str | None = None,
            temperature: float = 0.1,
            trace: LlmCallTrace | None = None,
            response_format: dict[str, str] | None = None,
        ) -> str:
            assert response_format == {"type": "json_object"}
            return (
                '{"items":[{"name":"中国电力","ts_code":"2380.HK",'
                '"market":"HK","confidence":0.9}],'
                '"ambiguous":false,"reason":"识别为港股中国电力"}'
            )

        monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

        route = service._route_with_semantic_stocks(
            "给我看看中国电力",
            {},
            QuestionRoute(
                is_answerable=True,
                should_query_data=True,
                answer_mode="stock_research",
            ),
            "trace-hk",
            None,
            None,
        )

    assert route.data_demands[0].ts_code == "02380.HK"
    assert route.data_demands[0].market == "HK"
    assert route.data_demands[0].packages == ("financial_statement",)


def test_ambiguous_direct_stock_extraction_falls_back_to_candidates(monkeypatch) -> None:
    """确认“平安”等歧义简称不会裸信 LLM 直识别，会回落本地候选消歧。

    创建日期：2026-06-02
    author: codex
    """

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                AStockBasic(ts_code="000001.SZ", symbol="000001", name="平安银行", list_status="L"),
                AStockBasic(ts_code="601318.SH", symbol="601318", name="中国平安", list_status="L"),
            ]
        )
        db.commit()
        service = LlmService(
            db,
            settings=Settings(
                llm_api_key="test-key",
                llm_api_key_file=None,
                llm_model="deepseek-v4-flash",
            ),
        )
        phases: list[str] = []

        def fake_chat_completion(
            prompt: str,
            system_prompt: str | None = None,
            model: str | None = None,
            temperature: float = 0.1,
            trace: LlmCallTrace | None = None,
            response_format: dict[str, str] | None = None,
        ) -> str:
            assert response_format == {"type": "json_object"}
            phase = trace.phase if trace else ""
            phases.append(phase)
            if phase == "stock_code_extraction":
                return (
                    '{"items":[{"name":"中国平安","ts_code":"601318.SH",'
                    '"market":"A","confidence":0.9}],'
                    '"ambiguous":true,"reason":"平安可能指多只股票"}'
                )
            if phase == "stock_disambiguation":
                return (
                    '{"selected_ts_codes":["601318.SH"],'
                    '"confidence":0.8,"reason":"候选内选择中国平安"}'
                )
            raise AssertionError(f"unexpected phase {phase}")

        monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

        route = service._route_with_semantic_stocks(
            "平安怎么看",
            {},
            QuestionRoute(
                is_answerable=True,
                should_query_data=True,
                answer_mode="stock_research",
            ),
            "trace-ambiguous",
            None,
            None,
        )

    assert phases == ["stock_code_extraction", "stock_disambiguation"]
    assert route.data_demands[0].ts_code == "601318.SH"


def test_answer_prompt_includes_market_data_context_and_report_instruction() -> None:
    """确认个股报告提示词会携带市场上下文并强调专业分析方法。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    service._supporting_data = Mock(return_value={})  # type: ignore[method-assign]

    prompt = service._answer_prompt(
        "招商银行投资分析报告",
        rows=[],
        context={},
        route=QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            answer_mode="stock_research",
        ),
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
    assert "answer_style_policy" in payload
    assert "充分的个股研究结构" in payload["answer_style_policy"]
    assert "15000 积分" not in prompt
    assert "随查询减少的余额" not in prompt


def test_answer_prompt_keeps_open_question_structure_flexible() -> None:
    """确认开放投研问题不再被强制套用完整个股报告模板。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    service._supporting_data = Mock(return_value={})  # type: ignore[method-assign]

    prompt = service._answer_prompt(
        "AH 溢价机会接下来怎么看？",
        rows=[],
        context={},
        route=QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            answer_mode="open_research",
        ),
        market_data_context={
            "context": {
                "scope": "CROSS_MARKET_MULTI",
                "items": [],
                "ah_cross_market": [],
            }
        },
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert "开放投研问答" in payload["answer_style_policy"]
    assert "不要机械套完整个股报告模板" in payload["answer_style_policy"]
    assert "如果这是个股投资分析报告" not in prompt
    assert "第二块必须先给关键财务趋势表" in prompt


def test_answer_prompt_uses_stock_research_mode_for_plain_company_analysis() -> None:
    """确认“分析小米集团”这类个股分析会使用充分个股研究结构。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    service._supporting_data = Mock(return_value={})  # type: ignore[method-assign]

    prompt = service._answer_prompt(
        "分析小米集团",
        rows=[],
        context={},
        route=QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            answer_mode="stock_research",
            data_demands=(MarketDataDemand("01810.HK", ("financial_statement",), market="HK"),),
            reason="用户请求分析小米集团，属于港股投资分析，需要结构化财务数据支撑。",
        ),
        market_data_context={
            "status": "COMPLETED",
            "context": {"scope": "HK_STOCK_SINGLE", "financial_periods": [{}, {}, {}]},
        },
    )
    payload = json.loads(prompt.split("\n", 1)[1])

    assert payload["answer_mode"] == "stock_research"
    assert "充分的个股研究结构" in payload["answer_style_policy"]
    assert "如果这是个股投资分析报告" in prompt
    assert "扣非净利润" in prompt


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


def test_follow_up_question_skips_router_and_market_data(monkeypatch) -> None:
    """确认语义分流为追问时，会直接结合历史回答且不触发数据路由。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    monkeypatch.setattr(
        service,
        "_route_question",
        Mock(side_effect=AssertionError("追问不应进入问题路由")),
    )
    monkeypatch.setattr(
        service,
        "_ensure_market_data_context",
        Mock(side_effect=AssertionError("追问不应触发按需补数")),
    )
    captured: dict[str, str] = {}

    def fake_chat_completion(
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
    ) -> str:
        if system_prompt == FOLLOW_UP_ROUTER_SYSTEM_PROMPT:
            captured["router_prompt"] = prompt
            return '{"turn_type":"follow_up","confidence":0.92,"reason":"质疑前文定性"}'
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt or ""
        captured["phase"] = trace.phase if trace else ""
        return "这确实更像对前文判断的修正。"

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    answer = service.answer(
        "难道不是2025年全年财报大幅调低收入利润，属于主动的盈余管理行为？",
        context={
            "conversation_history": [
                {"role": "user", "content": "帮我分析一下五粮液的2026年一季报"},
                {"role": "assistant", "content": "前文回答认为需要谨慎看待财报调整。"},
            ]
        },
    )

    assert answer.sql is None
    assert answer.rows == []
    assert "修正" in answer.answer
    assert captured["system_prompt"] == FOLLOW_UP_ASSISTANT_SYSTEM_PROMPT
    assert captured["phase"] == "follow_up_answer"
    assert "current_message" in captured["router_prompt"]
    assert "conversation_history" in captured["prompt"]
    assert "积分" in captured["prompt"]


def test_same_session_new_analysis_from_llm_classifier_still_uses_router(monkeypatch) -> None:
    """确认语义分流为新任务时，即便仍在同会话也继续走原数据路由。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    captured: dict[str, str] = {}

    def fake_route_question(
        question: str,
        context: dict[str, object] | None = None,
        question_id: str | None = None,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> QuestionRoute:
        captured["question"] = question
        return QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            data_demands=(MarketDataDemand("000858.SZ", ("financial_statement",), market="A"),),
        )

    monkeypatch.setattr(service, "_route_question", fake_route_question)
    monkeypatch.setattr(
        service,
        "_prepare_answer",
        lambda *args, **kwargs: (None, [], "请回答新分析"),
    )
    monkeypatch.setattr(
        service,
        "_chat_completion",
        lambda *args, **kwargs: (
            '{"turn_type":"new_task","confidence":0.88,"reason":"用户切换到新的独立分析"}'
            if kwargs.get("system_prompt") == FOLLOW_UP_ROUTER_SYSTEM_PROMPT
            else "新分析回答"
        ),
    )

    answer = service.answer(
        "刚才先放一边，帮我分析一下五粮液的2026年一季报",
        context={
            "conversation_history": [
                {"role": "user", "content": "刚才招商银行怎么看？"},
                {"role": "assistant", "content": "招商银行回答。"},
            ]
        },
    )

    assert captured["question"].startswith("刚才先放一边")
    assert answer.answer == "新分析回答"


def test_follow_up_classifier_failure_falls_back_to_data_router(monkeypatch) -> None:
    """确认追问分流器异常时按新任务处理，避免误跳过结构化数据准备。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    captured: dict[str, str] = {}

    def fake_chat_completion(*args, **kwargs) -> str:
        if kwargs.get("system_prompt") == FOLLOW_UP_ROUTER_SYSTEM_PROMPT:
            raise ValueError("bad router json")
        return "正常路由后的回答"

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    def fake_route_question(question: str, *args, **kwargs) -> QuestionRoute:
        captured["question"] = question
        return QuestionRoute(is_answerable=True, should_query_data=False)

    monkeypatch.setattr(
        service,
        "_route_question",
        fake_route_question,
    )
    monkeypatch.setattr(
        service,
        "_prepare_answer",
        lambda *args, **kwargs: (None, [], "路由提示词"),
    )

    answer = service.answer(
        "这个是不是还要看现金流？",
        context={
            "conversation_history": [
                {"role": "user", "content": "帮我分析五粮液"},
                {"role": "assistant", "content": "前文回答。"},
            ]
        },
    )

    assert captured["question"] == "这个是不是还要看现金流？"
    assert answer.answer == "正常路由后的回答"


def test_follow_up_prompt_avoids_report_format_contract() -> None:
    """确认追问提示词只保留轻约束，不再注入完整报告格式契约。

    创建日期：2026-05-09
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    prompt = service._follow_up_answer_prompt(
        "难道不是主动盈余管理？",
        {
            "conversation_history": [
                {"role": "user", "content": "帮我分析五粮液"},
                {"role": "assistant", "content": "前文报告。"},
            ]
        },
    )

    assert "conversation_history" in prompt
    assert "不要暴露内部数据来源" in prompt
    assert "第一块 `## 一、核心结论`" not in prompt
    assert "市场数据上下文" not in prompt


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


def test_dividend_reinvestment_question_forces_sql_route(monkeypatch) -> None:
    """确认分红再投筛选问题进入专用 SQL 路由，不触发个股补数。

    创建日期：2026-06-03
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    def fake_chat_completion(
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
    ) -> str:
        return (
            '{"is_answerable":true,"needs_sql":true,'
            '"answer_mode":"stock_research",'
            '"data_demands":[{"market":"A","ts_code":"600036.SH","packages":["quote_valuation"]}],'
            '"reason":"模型误判为普通个股研究"}'
        )

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    route = service._route_question("近十年平均年化大于10%，roe大于2%，pe小于7的股票有哪些？")

    assert route.answer_mode == DIVIDEND_REINVESTMENT_ANSWER_MODE
    assert route.should_query_data is True
    assert route.data_demands == ()


def test_dividend_reinvestment_detail_question_skips_follow_up_router(monkeypatch) -> None:
    """确认年度明细短追问继续走 SQL，不被普通追问快路径截走。

    创建日期：2026-06-03
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    monkeypatch.setattr(
        service,
        "_chat_completion",
        Mock(side_effect=AssertionError("dividend detail should skip follow-up router")),
    )

    assert (
        service._is_follow_up_question(
            "招商银行 年度明细",
            {
                "conversation_history": [
                    {"role": "user", "content": "近十年平均年化大于10%的股票有哪些？"},
                    {"role": "assistant", "content": "## 一、筛选结论\n\n- 招商银行命中。"},
                ]
            },
        )
        is False
    )


def test_dividend_reinvestment_schema_and_sql_prompt_are_exposed() -> None:
    """确认 SQL 生成提示词包含分红再投入表结构和查询口径。

    创建日期：2026-06-03
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    schema = service._schema()
    prompt = service._sql_prompt("招商银行 年度明细", {})

    assert "dividend_reinvestment_backtest_summary" in schema
    assert "dividend_reinvestment_backtest_yearly" in schema
    assert "ten_year_avg_annualized_return_pct" in schema["dividend_reinvestment_backtest_summary"]
    assert "year_end_trade_date" in schema["dividend_reinvestment_backtest_yearly"]
    assert DIVIDEND_REINVESTMENT_SQL_POLICY in prompt
    assert "SUCCESS" in DIVIDEND_REINVESTMENT_SQL_POLICY


def test_dividend_reinvestment_sql_status_accepts_success_batches() -> None:
    """确认 LLM 写死 COMPLETED 时会兼容服务器历史 SUCCESS 批次。

    创建日期：2026-06-03
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    sql = service._normalize_dividend_reinvestment_sql(
        "SELECT s.ten_year_avg_annualized_return_pct "
        "FROM dividend_reinvestment_backtest_summary s "
        "JOIN dividend_reinvestment_backtest_run r ON s.run_id = r.id "
        "WHERE s.ts_code = '600036.SH' AND r.status = 'COMPLETED' "
        "ORDER BY r.finished_at DESC, r.id DESC LIMIT 1"
    )

    assert "r.status IN ('COMPLETED', 'SUCCESS')" in sql


def test_dividend_reinvestment_answer_prompt_contains_markdown_example() -> None:
    """确认分红再投回答阶段提供合法 Markdown 表格示例。

    创建日期：2026-06-03
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    service._supporting_data = Mock(return_value={})  # type: ignore[method-assign]

    prompt = service._answer_prompt(
        "近十年平均年化大于10%，roe大于2%，pe小于7的股票有哪些？",
        rows=[
            {
                "ts_code": "600036.SH",
                "name": "招商银行",
                "ten_year_avg_annualized_return_pct": "10.5",
                "latest_roe": "15.2",
                "latest_pe": "6.8",
            }
        ],
        context={},
        route=QuestionRoute(
            is_answerable=True,
            should_query_data=True,
            answer_mode=DIVIDEND_REINVESTMENT_ANSWER_MODE,
        ),
    )

    assert "分红再投回答 Markdown 示例" in prompt
    assert "| 股票代码 | 名称 | 近十年平均年化 | 最新ROE | 最新PE | 投资观察 |" in prompt


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
                                '"answer_mode":"open_research",'
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
                                '"answer_mode":"stock_research",'
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
    assert [call["payload"]["model"] for call in calls] == [
        "deepseek-v4-flash",
        "qwen3.6-flash",
        "deepseek-v4-flash",
        "qwen3.6-flash",
    ]
    assert calls[2]["payload"].get("response_format") == {"type": "json_object"}


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


def test_general_direct_question_is_allowed_without_investment_boundary() -> None:
    """确认翻译和通用知识问答不再被投资边界误拦截。

    创建日期：2026-05-07
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )
    route = QuestionRoute(is_answerable=True, should_query_data=False)

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
