from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import Mock

from app.core.config import Settings
from app.services.investment_knowledge_service import InvestmentKnowledgeService
from app.services.llm_service import (
    INVESTMENT_ADVISOR_SYSTEM_PROMPT,
    OUT_OF_SCOPE_MESSAGE,
    SERVICE_INTRO_MESSAGE,
    LlmService,
)


def test_llm_service_rejects_non_investment_question_before_api_call() -> None:
    """确认非投资问题被本地边界拦截。

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


def test_investment_advisor_prompt_allows_professional_opinions() -> None:
    """确认投资顾问提示词允许输出明确研究判断。

    创建日期：2026-05-04
    author: sunshengxian
    """

    assert "评级口径" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "配置倾向" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "阈值和触发条件" in INVESTMENT_ADVISOR_SYSTEM_PROMPT
    assert "不要输出“不构成投资建议”" in INVESTMENT_ADVISOR_SYSTEM_PROMPT


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

    assert "个股深度投资报告" in selection.categories
    assert any("信任修复期" in chunk["content"] for chunk in selection.chunks)


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

    assert service._chat_completion("分析招商银行", model="qwen3.6-max-preview") == "qwen ok"
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer qwen-key"}
    assert captured["payload"]["model"] == "qwen3.6-max-preview"


def test_question_scope_uses_qwen_flash_classifier(monkeypatch) -> None:
    """确认投资问题边界由 Qwen 3.5 Flash 判定，不再依赖关键词命中。

    创建日期：2026-05-04
    author: sunshengxian
    """

    captured_payload: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"is_investment_related":true}'}}]}

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

    assert service._is_investment_related_question("帮我判断这家公司还能不能继续持有")
    assert captured_payload["model"] == "qwen3.5-flash"


def test_service_intro_question_uses_qwen_classifier_and_returns_role_intro(monkeypatch) -> None:
    """确认问候和能力介绍类问题可回答，且边界判定仍走 Qwen Flash。

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
    assert captured_models == ["qwen3.5-flash"]


def test_out_of_scope_message_is_soft_and_actionable() -> None:
    """确认越界问题响应更自然，并提示可改问方向。

    创建日期：2026-05-04
    author: sunshengxian
    """

    assert "不太在我的工作范围里" in OUT_OF_SCOPE_MESSAGE
    assert "你可以问我" in OUT_OF_SCOPE_MESSAGE


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
