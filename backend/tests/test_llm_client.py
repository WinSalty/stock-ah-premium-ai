"""LlmClient 通用 LLM 客户端单元测试。

将 tests/test_llm_service.py 中"实现已迁入 llm_client、测试入口还挂在 LlmService"的
用例迁移为直接测 LlmClient，覆盖：模型别名归一、端点选择、DeepSeek->Qwen 透明降级、
指标落库、日限额计数口径，以及 messages+tools 新接口（tool_calls 解析、流式分片）。
HTTP 层统一 monkeypatch app.services.llm_client.httpx.Client，全程不发真实外部请求。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models.chat import LlmCallMetric
from app.services.agent.budget import LlmDailyLimitExceeded as BudgetLlmDailyLimitExceeded
from app.services.llm_client import (
    LLM_EXTERNAL_CALL_PHASES,
    LlmCallTrace,
    LlmClient,
    LlmDailyLimitExceeded,
)


def _make_settings(**overrides: Any) -> Settings:
    """构造测试用 Settings：显式 kwargs 且所有 *_api_key_file 置 None。

    业务口径：Settings 的各 *_api_key_file 默认指向本机密钥文件，单测必须显式置 None，
    否则断言结果会随本机文件存在与否漂移；API Key 一律通过 kwargs 直接给值。

    创建日期：2026-06-12
    author: claude
    """

    params: dict[str, Any] = {
        # 所有 *_api_key_file 显式置 None，杜绝单测读取本机真实密钥文件。
        "llm_api_key_file": None,
        "qwen_api_key_file": None,
        "bocha_api_key_file": None,
        "image_gen_api_key_file": None,
    }
    params.update(overrides)
    return Settings(**params)


class _FakeResponse:
    """非流式 HTTP 响应桩：raise_for_status 的成功/失败行为与 httpx 对齐。

    边界条件：status_code >= 400 时抛 httpx.HTTPStatusError 且携带真实 httpx.Response，
    保证 LlmClient 的 fallback 判定（按状态码识别可重试错误）走真实分支。

    创建日期：2026-06-12
    author: claude
    """

    def __init__(self, status_code: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._body = body or {"choices": [{"message": {"content": "ok"}}]}
        self.request = httpx.Request("POST", "https://example.test/chat/completions")

    @property
    def text(self) -> str:
        return json.dumps(self._body, ensure_ascii=False)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "busy",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request, text="busy"),
            )

    def json(self) -> dict[str, Any]:
        return self._body


def _make_fake_client(
    handler: Callable[[str, dict[str, str], dict[str, Any]], _FakeResponse],
) -> type:
    """生成可替换 httpx.Client 的桩类，post 委托给 handler 按请求内容返回响应。

    业务意图：沿用 test_llm_service.py 的 HTTP 层 mock 模式（monkeypatch
    app.services.llm_client.httpx.Client），handler 可按模型名返回 503/200，
    用于驱动双端点 fallback 等真实分支。

    创建日期：2026-06-12
    author: claude
    """

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> _FakeResponse:
            return handler(url, headers, json)

    return FakeClient


def test_deepseek_model_alias_normalizes_to_supported_api_name(monkeypatch) -> None:
    """确认 DeepSeek 历史模型别名（含 [1m] 前缀写法）归一为 API 支持的模型名。

    创建日期：2026-06-12
    author: claude
    """

    client = LlmClient(Mock(), settings=_make_settings(llm_api_key="test-key"))

    # 锁口径：空模型回落默认 flash；带 [1m] 等后缀的别名按前缀归一到正式模型名。
    assert client.normalize_chat_model(None) == "deepseek-v4-flash"
    assert client.normalize_chat_model("deepseek-v4-pro") == "deepseek-v4-pro"
    assert client.normalize_chat_model("deepseek-v4-pro[1m]") == "deepseek-v4-pro"
    assert client.normalize_chat_model("deepseek-v4-flash[1m]") == "deepseek-v4-flash"
    # 非 DeepSeek 模型只做去空白透传，不应被误改写。
    assert client.normalize_chat_model(" qwen3.6-flash ") == "qwen3.6-flash"

    captured_payload: dict[str, Any] = {}

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        captured_payload.update(payload)
        return _FakeResponse()

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    aliased = LlmClient(
        Mock(),
        settings=_make_settings(llm_api_key="test-key", llm_model="deepseek-v4-pro[1m]"),
    )

    assert aliased.chat_completion("招商银行阈值建议") == "ok"
    # 锁口径：实际发给 API 的模型名必须是归一后的正式名，且不携带 reasoning_effort。
    assert captured_payload["model"] == "deepseek-v4-pro"
    assert "reasoning_effort" not in captured_payload


def test_default_chat_model_is_deepseek_flash() -> None:
    """确认默认问答模型仍是 DeepSeek Flash 并走 DeepSeek 端点。

    创建日期：2026-06-12
    author: claude
    """

    client = LlmClient(Mock(), settings=_make_settings(llm_api_key="test-key"))

    endpoint = client.model_endpoint()

    # 锁口径：未显式指定模型时默认 DeepSeek Flash，base_url 与 Key 取 DeepSeek 配置。
    assert endpoint.provider == "DeepSeek"
    assert endpoint.model == "deepseek-v4-flash"
    assert endpoint.base_url == "https://api.deepseek.com"
    assert endpoint.api_key == "test-key"


def test_qwen_chat_model_uses_dashscope_endpoint(monkeypatch) -> None:
    """确认选择 Qwen 模型时使用阿里 DashScope 端点和 Qwen Key。

    创建日期：2026-06-12
    author: claude
    """

    captured: dict[str, Any] = {}

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        captured.update({"url": url, "headers": headers, "payload": payload})
        return _FakeResponse(body={"choices": [{"message": {"content": "qwen ok"}}]})

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    client = LlmClient(
        Mock(),
        settings=_make_settings(llm_api_key="deepseek-key", qwen_api_key="qwen-key"),
    )

    endpoint = client.model_endpoint("qwen3.6-flash")
    # 锁口径：qwen 前缀模型路由到 Qwen 端点，Key 取 qwen_api_key 而不是 DeepSeek Key。
    assert endpoint.provider == "Qwen"
    assert endpoint.api_key == "qwen-key"

    assert client.chat_completion("分析招商银行", model="qwen3.6-flash") == "qwen ok"
    # 锁口径：实际请求 URL 是 DashScope 兼容端点，鉴权头携带 Qwen Key。
    assert captured["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer qwen-key"}
    assert captured["payload"]["model"] == "qwen3.6-flash"


def test_chat_completion_falls_back_to_qwen_when_deepseek_busy(monkeypatch) -> None:
    """确认 DeepSeek 503 时非流式调用透明降级 Qwen，且 response_format 全程透传。

    创建日期：2026-06-12
    author: claude
    """

    calls: list[dict[str, Any]] = []

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        calls.append({"url": url, "payload": payload})
        if payload["model"] == "deepseek-v4-flash":
            # DeepSeek 返回 503：属于可重试状态码，应触发备用端点切换。
            return _FakeResponse(status_code=503)
        return _FakeResponse(body={"choices": [{"message": {"content": "qwen fallback ok"}}]})

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    client = LlmClient(
        Mock(),
        settings=_make_settings(llm_api_key="deepseek-key", qwen_api_key="qwen-key"),
    )

    answer = client.chat_completion(
        "分析招商银行",
        model="deepseek-v4-flash",
        response_format={"type": "json_object"},
    )

    assert answer == "qwen fallback ok"
    # 锁口径：先调 DeepSeek 主端点，503 后只追加一次 Qwen 备用调用，顺序固定。
    assert [call["payload"]["model"] for call in calls] == [
        "deepseek-v4-flash",
        "qwen3.6-flash",
    ]
    # 锁口径：JSON 输出约束在主调用与降级调用中都必须透传，降级不丢结构化约束。
    assert calls[0]["payload"]["response_format"] == {"type": "json_object"}
    assert calls[1]["payload"]["response_format"] == {"type": "json_object"}


def test_chat_completion_metric_is_persisted(monkeypatch) -> None:
    """确认一次成功的非流式调用会把耗时指标完整落库。

    创建日期：2026-06-12
    author: claude
    """

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        return _FakeResponse(body={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        client = LlmClient(db, settings=_make_settings(llm_api_key="test-key"))

        answer = client.chat_completion(
            "招商银行阈值建议",
            trace=LlmCallTrace(
                question_id="1234567",
                phase="answer",
                user_id=9,
                session_id=18,
            ),
        )

        assert answer == "ok"
        metric = db.scalar(select(LlmCallMetric).where(LlmCallMetric.question_id == "1234567"))

        assert metric is not None
        # 锁口径：phase/provider/model/user/session 与 trace 和实际端点一一对应。
        assert metric.phase == "answer"
        assert metric.provider == "DeepSeek"
        assert metric.model == "deepseek-v4-flash"
        assert metric.user_id == 9
        assert metric.session_id == 18
        # 锁口径：output_chars 按返回正文字符数统计，elapsed_ms 必须有值。
        assert metric.output_chars == 2
        assert metric.elapsed_ms is not None
        # 锁口径：phase_label 由 llm_metric_definitions 映射生成，供耗时页直接展示。
        assert metric.phase_label == "非流式回答"
        # 锁口径：request_payload_json 记录真实请求参数，且不得包含鉴权信息。
        request_payload = json.loads(metric.request_payload_json or "{}")
        assert request_payload["model"] == "deepseek-v4-flash"
        assert request_payload["messages"][-1]["content"] == "招商银行阈值建议"
        assert "Authorization" not in (metric.request_payload_json or "")
        assert metric.response_content == "ok"


def test_daily_call_limit_counts_external_main_phases_only() -> None:
    """确认日限额只统计 LLM_EXTERNAL_CALL_PHASES 内的外部主调用 phase。

    创建日期：2026-06-12
    author: claude
    """

    # 锁口径：日限额异常单点定义在 agent.budget，llm_client 仅 re-export 同一个类，
    # 两个 import 路径必须指向同一对象，否则跨模块 except 会失配。
    assert LlmDailyLimitExceeded is BudgetLlmDailyLimitExceeded
    # 锁口径：Agent 引擎迭代调用计入限额；流式首包等派生指标不重复计数。
    assert "agent_iteration" in LLM_EXTERNAL_CALL_PHASES
    assert "answer_stream_first_chunk" not in LLM_EXTERNAL_CALL_PHASES

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    with Session(engine) as db:
        # 预插 1 条主调用 + 1 条首包派生指标：限额 2 下应只算 1 次，放行下一次调用。
        db.add(
            LlmCallMetric(
                question_id="main-answer",
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
        client = LlmClient(
            db,
            settings=_make_settings(llm_api_key="test-key", llm_daily_call_limit=2),
        )
        endpoint = client.model_endpoint()

        # 已用 1 次 < 限额 2：放行，不抛异常。
        client.enforce_daily_call_limit(endpoint, None)

        # 再插 1 条 question_router 主调用：累计 2 次，达到限额。
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

        with pytest.raises(LlmDailyLimitExceeded) as exc_info:
            client.enforce_daily_call_limit(endpoint, None)
        # 锁口径：非默认限额时提示语携带实际配置值，便于运维核对配置。
        assert "2 次" in str(exc_info.value)


def test_chat_completion_messages_parses_tool_calls(monkeypatch) -> None:
    """确认 messages+tools 调用能解析 tool_calls，缺 id 时按序号兜底。

    创建日期：2026-06-12
    author: claude
    """

    captured_payload: dict[str, Any] = {}

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        captured_payload.update(payload)
        return _FakeResponse(
            body={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {
                                        "name": "query_database",
                                        "arguments": '{"sql": "SELECT 1"}',
                                    },
                                },
                                {
                                    # 兼容个别端点缺 id 的场景：应按序号兜底生成 call_1。
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query": "招商银行"}',
                                    },
                                },
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    client = LlmClient(Mock(), settings=_make_settings(llm_api_key="test-key"))
    messages = [{"role": "user", "content": "查招商银行最新溢价"}]
    tools = [
        {
            "type": "function",
            "function": {"name": "query_database", "parameters": {"type": "object"}},
        }
    ]

    result = client.chat_completion_messages(messages, tools=tools)

    # 锁口径：传入 tools 时 payload 必须携带工具目录且 tool_choice 默认 auto。
    assert captured_payload["tools"] == tools
    assert captured_payload["tool_choice"] == "auto"
    assert captured_payload["messages"] == messages
    # 锁口径：纯工具调用响应 content 为 None，由调用方按 tool_calls 继续迭代。
    assert result.content is None
    assert result.provider == "DeepSeek"
    assert result.model == "deepseek-v4-flash"
    assert len(result.tool_calls) == 2
    # 锁口径：带 id 的调用原样保留 call_id，name/arguments_json 与响应一致。
    assert result.tool_calls[0].call_id == "call_abc"
    assert result.tool_calls[0].name == "query_database"
    assert result.tool_calls[0].arguments_json == '{"sql": "SELECT 1"}'
    # 锁口径：缺 id 时按 call_{index} 兜底，保证工具结果回填能与请求配对。
    assert result.tool_calls[1].call_id == "call_1"
    assert result.tool_calls[1].name == "web_search"
    assert result.tool_calls[1].arguments_json == '{"query": "招商银行"}'


def test_chat_completion_messages_falls_back_to_qwen_when_deepseek_busy(monkeypatch) -> None:
    """确认 messages 形态调用在 DeepSeek 503 时同样透明降级 Qwen。

    创建日期：2026-06-12
    author: claude
    """

    calls: list[dict[str, Any]] = []

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        calls.append({"url": url, "payload": payload})
        if payload["model"] == "deepseek-v4-flash":
            return _FakeResponse(status_code=503)
        return _FakeResponse(body={"choices": [{"message": {"content": "qwen ok"}}]})

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    client = LlmClient(
        Mock(),
        settings=_make_settings(llm_api_key="deepseek-key", qwen_api_key="qwen-key"),
    )

    result = client.chat_completion_messages([{"role": "user", "content": "分析招商银行"}])

    # 锁口径：新接口与 prompt 形态共用 fallback 策略，调用顺序固定为主端点->Qwen。
    assert [call["payload"]["model"] for call in calls] == [
        "deepseek-v4-flash",
        "qwen3.6-flash",
    ]
    # 锁口径：降级成功后结果标记实际使用的 Qwen 端点，无工具调用时 tool_calls 为空。
    assert result.content == "qwen ok"
    assert result.provider == "Qwen"
    assert result.model == "qwen3.6-flash"
    assert result.tool_calls == ()


def test_metric_session_factory_writes_metric_in_independent_session(monkeypatch) -> None:
    """确认传入 metric_session_factory 时指标写独立会话，不污染调用方 db。

    创建日期：2026-06-12
    author: claude
    """

    def handler(url: str, headers: dict[str, str], payload: dict[str, Any]) -> _FakeResponse:
        return _FakeResponse(body={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_client.httpx.Client", _make_fake_client(handler))
    # 调用方库与指标库各用一个内存 SQLite，验证指标确实写进了独立会话指向的库。
    caller_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(caller_engine)
    metric_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(metric_engine)
    metric_session_factory = sessionmaker(bind=metric_engine)
    with Session(caller_engine) as db:
        client = LlmClient(
            db,
            settings=_make_settings(llm_api_key="test-key"),
            metric_session_factory=metric_session_factory,
        )

        answer = client.chat_completion(
            "招商银行阈值建议",
            trace=LlmCallTrace(question_id="factory-1", phase="answer", user_id=9, session_id=18),
        )

        assert answer == "ok"
        # 锁口径：调用方会话既无已落库指标也无未提交指标，事务边界不被指标写入打破。
        assert db.scalar(select(func.count(LlmCallMetric.id))) == 0
        assert len(db.new) == 0

    # 锁口径：指标必须出现在独立会话指向的库中，字段与 trace/端点一致。
    with metric_session_factory() as metric_db:
        metric = metric_db.scalar(
            select(LlmCallMetric).where(LlmCallMetric.question_id == "factory-1")
        )
    assert metric is not None
    assert metric.phase == "answer"
    assert metric.provider == "DeepSeek"
    assert metric.response_content == "ok"


def test_chat_completion_stream_messages_yields_chunks_until_done(monkeypatch) -> None:
    """确认 messages 流式调用逐片产出内容、[DONE] 终止并落流式完成指标。

    创建日期：2026-06-12
    author: claude
    """

    captured: dict[str, Any] = {}
    # SSE 行序列：注释行/空行/无 content 的 delta 都应被跳过，[DONE] 后的行不得消费。
    sse_lines = [
        ": keep-alive",
        "",
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        'data: {"choices":[{"delta":{"content":"，世界"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"DONE 之后不应再消费"}}]}',
    ]

    class FakeStreamResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self) -> Iterator[str]:
            yield from sse_lines

    class FakeStreamContext:
        def __enter__(self) -> FakeStreamResponse:
            return FakeStreamResponse()

        def __exit__(self, *args: object) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def stream(
            self,
            method: str,
            url: str,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> FakeStreamContext:
            captured.update({"method": method, "url": url, "payload": json})
            return FakeStreamContext()

    monkeypatch.setattr("app.services.llm_client.httpx.Client", FakeClient)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    completed_models: list[str] = []
    with Session(engine) as db:
        client = LlmClient(db, settings=_make_settings(llm_api_key="test-key"))

        chunks = list(
            client.chat_completion_stream_messages(
                [{"role": "user", "content": "分析招商银行"}],
                trace=LlmCallTrace(question_id="stream-1", phase="answer_stream"),
                on_stream_complete=completed_models.append,
            )
        )

        # 锁口径：只产出有 content 的分片，顺序保持原样，[DONE] 后内容不外漏。
        assert chunks == ["你好", "，世界"]
        # 锁口径：流式请求 payload 必须带 stream=True，模型为归一后的默认模型。
        assert captured["payload"]["stream"] is True
        assert captured["payload"]["model"] == "deepseek-v4-flash"
        # 锁口径：流正常结束后以实际使用的模型名回调一次 on_stream_complete。
        assert completed_models == ["deepseek-v4-flash"]

        first_chunk_metric = db.scalar(
            select(LlmCallMetric).where(LlmCallMetric.phase == "answer_stream_first_chunk")
        )
        done_metric = db.scalar(
            select(LlmCallMetric).where(LlmCallMetric.phase == "answer_stream")
        )

    # 锁口径：首包派生指标单独落一条记录，只记首包耗时。
    assert first_chunk_metric is not None
    assert first_chunk_metric.first_chunk_ms is not None
    # 锁口径：流式完成指标的分片数/字符数按实际产出累计，正文为全量拼接结果。
    assert done_metric is not None
    assert done_metric.chunk_count == 2
    assert done_metric.output_chars == len("你好，世界")
    assert done_metric.response_content == "你好，世界"
    assert done_metric.elapsed_ms is not None
    assert done_metric.first_chunk_ms is not None


def test_daily_call_limit_exempts_admin_and_excludes_admin_usage() -> None:
    """确认 admin 账户豁免日限额，且 admin 产生的调用不计入普通用户的统计口径。

    创建日期：2026-06-12
    author: claude
    """

    from app.db.models.auth import AppUser
    from app.services.llm_client import LlmCallTrace

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    with Session(engine) as db:
        admin = AppUser(username="admin", password_hash="h", role="ADMIN", is_active=True)
        normal = AppUser(username="alice", password_hash="h", role="USER", is_active=True)
        db.add_all([admin, normal])
        db.commit()
        db.refresh(admin)
        db.refresh(normal)

        def metric(qid: str, user_id: int | None) -> LlmCallMetric:
            return LlmCallMetric(
                question_id=qid,
                user_id=user_id,
                phase="agent_iteration",
                provider="DeepSeek",
                model="deepseek-v4-pro",
                created_at=today,
                updated_at=today,
            )

        # admin 已产生 3 次调用、普通用户 1 次、user_id 缺失 1 次（保守计入）。
        db.add_all(
            [
                metric("adm-1", admin.id),
                metric("adm-2", admin.id),
                metric("adm-3", admin.id),
                metric("usr-1", normal.id),
                metric("sys-1", None),
            ]
        )
        db.commit()

        client = LlmClient(
            db,
            settings=_make_settings(llm_api_key="test-key", llm_daily_call_limit=2),
        )
        endpoint = client.model_endpoint()

        # 统计口径：admin 的 3 次被排除，仅普通用户 1 次 + 无主 1 次 = 2 次，达到限额。
        normal_trace = LlmCallTrace(question_id="q-normal", phase="agent_iteration",
                                    user_id=normal.id)
        with pytest.raises(LlmDailyLimitExceeded):
            client.enforce_daily_call_limit(endpoint, normal_trace)

        # admin 豁免：同样的超限状态下带豁免标记的调用直接放行。
        admin_trace = LlmCallTrace(question_id="q-admin", phase="agent_iteration",
                                   user_id=admin.id, exempt_daily_limit=True)
        client.enforce_daily_call_limit(endpoint, admin_trace)
