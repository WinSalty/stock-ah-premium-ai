from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock
from zoneinfo import ZoneInfo

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
    SERVICE_INTRO_MESSAGE,
    LlmCallTrace,
    LlmDailyLimitExceeded,
    LlmEndpoint,
    LlmService,
    QuestionRoute,
)
from app.services.market_data_orchestrator import MAX_MARKET_DATA_STOCKS


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


def test_investment_advisor_prompt_allows_professional_opinions() -> None:
    """确认投资顾问提示词允许输出明确研究判断。

    创建日期：2026-05-04
    author: sunshengxian
    """

    assert "评级口径" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "配置倾向" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "阈值和触发条件" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "不要输出“不构成投资建议”" in INVESTMENT_ADVISOR_SYSTEM_PROMPT


def test_clear_investment_question_uses_unified_deepseek_router(monkeypatch) -> None:
    """确认投资问题通过统一 DeepSeek 路由返回前置信息。

    创建日期：2026-05-05
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="test-key",
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
            llm_model="test-model",
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
            '"knowledge_categories":["company_research"],"reason":"需要公司投研框架"}'
        )

    monkeypatch.setattr(service, "_chat_completion", fake_chat_completion)

    route = service._route_question("招商银行现在估值怎么看")

    assert route.is_answerable is True
    assert route.should_query_data is False
    assert route.use_knowledge is True
    assert route.knowledge_category_keys == ("company_research",)
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["phase"] == "question_router"
    assert "knowledge_catalog" in str(captured["prompt"])


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
            "knowledge_categories": ["company_research"],
            "data_demands": [
                {
                    "market": "A",
                    "ts_code": "600036.SH",
                    "packages": ["quote_valuation", "financial_statement", "danger_api"],
                }
            ],
        }
    )

    assert route.data_demands[0].ts_code == "600036.SH"
    assert route.data_demands[0].packages == ("quote_valuation", "financial_statement")


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


def test_report_analysis_question_skips_data_query() -> None:
    """确认报告分析类问题优先走知识材料，不触发 SQL 生成。

    创建日期：2026-05-05
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(llm_api_key="test-key", llm_api_key_file=None, llm_model="test-model"),
    )

    question = "寒武纪深度价值投资报告的核心买点和反证条件是什么？"

    assert service._should_query_data(question, {}) is False


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
    """确认 LLM 知识服务可以读取分类目录中的 docx 投研报告。

    创建日期：2026-05-04
    author: sunshengxian
    """

    report_path = tmp_path / "company-research" / "五粮液股票投资报告_2026.docx"
    _write_minimal_docx(
        report_path,
        paragraphs=(
            "五粮液（000858.SZ）股票投资报告",
            "投资结论：公司处于信任修复期，需要跟踪批价、库存和现金流。",
        ),
    )

    selection = InvestmentKnowledgeService(doc_root=tmp_path).select("五粮液当前投资价值如何")

    assert "五粮液深度投资报告" in selection.categories
    assert any("信任修复期" in chunk["content"] for chunk in selection.chunks)


def test_investment_knowledge_selects_company_value_reports() -> None:
    """确认新增公司价值投资报告会进入个股深度投资知识分类。

    创建日期：2026-05-05
    author: sunshengxian
    """

    selection = InvestmentKnowledgeService().select("寒武纪 688256 深度价值投资怎么看")

    assert "寒武纪深度价值投资报告" in selection.categories
    assert any(
        "寒武纪" in chunk["title"] or "寒武纪" in chunk["content"]
        for chunk in selection.chunks
    )


def test_investment_knowledge_expands_company_report_globs(tmp_path: Path) -> None:
    """确认公司研究分类可从稳定子目录通配读取报告。

    创建日期：2026-05-05
    author: sunshengxian
    """

    report_path = tmp_path / "company-research" / "value-investing-2026" / "寒武纪报告.docx"
    _write_minimal_docx(
        report_path,
        paragraphs=(
            "寒武纪（688256.SH）深度价值投资分析报告",
            "核心验证点：收入放量、毛利率和客户结构改善。",
        ),
    )

    selection = InvestmentKnowledgeService(doc_root=tmp_path).select("寒武纪价值投资怎么看")

    assert "寒武纪深度价值投资报告" in selection.categories
    assert any("核心验证点" in chunk["content"] for chunk in selection.chunks)


def test_company_research_legacy_key_filters_unrelated_reports() -> None:
    """确认旧 company_research 分类不会给无专属报告公司塞其他个股报告。

    创建日期：2026-05-07
    author: sunshengxian
    """

    selection = InvestmentKnowledgeService().select_by_keys(
        ["company_research"],
        question="拉卡拉这家公司怎么样？分析业务模式和投资价值",
    )

    assert "个股深度投资报告" in selection.categories
    assert selection.chunks == []


def test_company_research_legacy_key_keeps_exact_company_report() -> None:
    """确认旧 company_research 分类在命中同公司时仍保留专业报告材料。

    创建日期：2026-05-07
    author: sunshengxian
    """

    selection = InvestmentKnowledgeService().select_by_keys(
        ["company_research"],
        question="寒武纪 688256 投资价值怎么看",
    )

    assert any("寒武纪" in chunk["title"] for chunk in selection.chunks)


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
    """确认默认问答模型使用 DeepSeek Flash。

    创建日期：2026-05-04
    author: sunshengxian
    """

    service = LlmService(
        Mock(),
        settings=Settings(
            llm_api_key="test-key",
            llm_api_key_file=None,
            qwen_api_key="qwen-key",
            qwen_api_key_file=None,
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


def test_uncertain_question_scope_uses_deepseek_flash_router(monkeypatch) -> None:
    """确认本地规则不确定时使用 DeepSeek Flash 路由。

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

    assert "| ts_code | name | end_date | n_income_attr_p | profit_dedt |" in answer
    assert "需要分析时直接告诉我" in answer
    assert "核心结论" not in answer


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
    assert "不要因为表面估值低就自动给乐观结论" in instruction
