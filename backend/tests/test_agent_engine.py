"""问答 Agent 引擎核心单元测试。

覆盖口径（chat-agent-refactor-design-and-plan.md 3.1 节主循环）：
- 主循环事件流：无工具直答、单次工具调用、迭代耗尽强制收尾；
- 失败口径：工具异常/入参非法转错误文本回填、配额耗尽、日限额与通用异常的
  ErrorEvent 终态收敛；
- 预算压缩：仅压缩 role=tool 消息且不改动 system/user；
- 消息组装：历史窗口清洗（最近 10 条、单条 1200 字）与阈值上下文注入提示。
全部用例 mock LlmClient 的 messages 接口，不发任何真实 HTTP 请求。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock

from app.core.config import Settings
from app.services.agent.budget import LlmDailyLimitExceeded, compress_messages_for_budget
from app.services.agent.engine import (
    CHAT_FAILURE_MESSAGE,
    FORCE_FINISH_INSTRUCTION,
    AgentEngine,
)
from app.services.agent.events import (
    ChartEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    ToolResultEvent,
    ToolStartEvent,
)
from app.services.agent.tool_registry import ToolResult, ToolSpec
from app.services.llm_client import LlmChatResult, LlmToolCallRequest


def _settings(**overrides: Any) -> Settings:
    """构造与本机密钥文件完全隔离的测试配置。

    所有 *_api_key_file 显式置 None，避免测试读取开发机真实 key 文件；
    其余字段按需通过 overrides 覆盖（如 agent_max_iterations）。

    创建日期：2026-06-12
    author: claude
    """

    defaults: dict[str, Any] = {
        "llm_api_key": "test-key",
        "llm_api_key_file": None,
        "llm_model": "test-model",
        "qwen_api_key": None,
        "qwen_api_key_file": None,
        "bocha_api_key": None,
        "bocha_api_key_file": None,
        "image_gen_api_key": None,
        "image_gen_api_key_file": None,
        "tushare_token": None,
        "tushare_token_file": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _chat_result(
    content: str | None = None,
    tool_calls: tuple[LlmToolCallRequest, ...] = (),
) -> LlmChatResult:
    """构造非流式 messages 调用的结构化响应测试数据。

    创建日期：2026-06-12
    author: claude
    """

    return LlmChatResult(
        content=content,
        tool_calls=tool_calls,
        provider="DeepSeek",
        model="test-model",
    )


class FakeLlmClient:
    """LlmClient 测试替身：按队列回放非流式结果并记录两类调用入参。

    results 中放 LlmChatResult 按序返回；放异常实例则在调用时抛出，
    用于模拟日限额与服务端不可恢复错误。

    创建日期：2026-06-12
    author: claude
    """

    def __init__(self, results: list[Any], chunks: list[str] | None = None) -> None:
        self.results = list(results)
        self.chunks = chunks or []
        self.chat_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []
        self.metric_calls: list[dict[str, Any]] = []

    def record_metric(self, **kwargs: Any) -> None:
        """记录引擎每次工具执行写入的指标入参（测试中不落库）。

        创建日期：2026-06-12
        author: claude
        """

        self.metric_calls.append(kwargs)

    def chat_completion_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LlmChatResult:
        """记录入参快照后回放队列中的下一个结果（或抛出预置异常）。

        创建日期：2026-06-12
        author: claude
        """

        # 引擎会持续向同一个 messages 列表追加消息，必须逐条浅拷贝留快照。
        self.chat_calls.append(
            {"messages": [dict(item) for item in messages], "tools": tools, "model": model}
        )
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def chat_completion_stream_messages(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ):
        """记录流式调用入参快照后返回预置增量文本迭代器。

        创建日期：2026-06-12
        author: claude
        """

        self.stream_calls.append(
            {"messages": [dict(item) for item in messages], "model": model}
        )
        return iter(self.chunks)


def _fake_tool(name: str = "fake_tool", handler: Any = None) -> ToolSpec:
    """构造最小可执行的 fake 工具规格，handler 缺省返回成功结果。

    创建日期：2026-06-12
    author: claude
    """

    def default_handler(args: dict[str, Any], state: Any) -> ToolResult:
        return ToolResult(ok=True, payload="工具材料", summary="返回 1 行")

    return ToolSpec(
        name=name,
        description="测试工具",
        parameters={"type": "object", "properties": {}},
        handler=handler or default_handler,
        summarize=lambda args: f"调用{name}",
    )


def _make_engine(
    monkeypatch: Any,
    fake_client: FakeLlmClient,
    tools: list[ToolSpec] | None = None,
    settings: Settings | None = None,
    captured: dict[str, Any] | None = None,
) -> AgentEngine:
    """构造注入 fake 工具目录与 fake LlmClient 的引擎实例。

    通过 monkeypatch 替换引擎模块内的 build_tools，确保不触碰真实工具实现；
    captured 非空时记录引擎传给 build_tools 的 turn_state 供断言。

    创建日期：2026-06-12
    author: claude
    """

    def fake_build_tools(db: Any, settings_arg: Any, turn_state: Any) -> list[ToolSpec]:
        if captured is not None:
            captured["turn_state"] = turn_state
        return tools or []

    monkeypatch.setattr("app.services.agent.engine.build_tools", fake_build_tools)
    engine = AgentEngine(Mock(), settings=settings or _settings())
    engine.llm_client = fake_client  # type: ignore[assignment]
    return engine


def test_engine_answers_directly_without_tool_calls(monkeypatch) -> None:
    """确认无工具调用时引擎直接流式作答，事件序列为 delta...done。

    创建日期：2026-06-12
    author: claude
    """

    fake_client = FakeLlmClient(results=[_chat_result(content="你好")], chunks=["你好", "世界"])
    engine = _make_engine(monkeypatch, fake_client)

    events = list(engine.run("打个招呼"))

    assert [event.type for event in events] == ["delta", "delta", "done"]
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].answer == "你好世界"
    assert events[-1].tool_trace == []
    # 无可用工具时引擎应以纯对话模式调用（tools=None）。
    assert fake_client.chat_calls[0]["tools"] is None
    assert len(fake_client.stream_calls) == 1


def test_engine_executes_single_tool_call_then_answers(monkeypatch) -> None:
    """确认一次工具调用后收尾作答：事件顺序、轨迹长度与 role=tool 消息回填。

    创建日期：2026-06-12
    author: claude
    """

    tool_call = LlmToolCallRequest(
        call_id="call_1", name="fake_tool", arguments_json='{"x": 1}'
    )
    fake_client = FakeLlmClient(
        results=[_chat_result(tool_calls=(tool_call,)), _chat_result(content="答案")],
        chunks=["答", "案"],
    )
    engine = _make_engine(monkeypatch, fake_client, tools=[_fake_tool()])

    events = list(engine.run("用工具查一下"))

    assert [event.type for event in events] == [
        "tool_start",
        "tool_result",
        "delta",
        "delta",
        "done",
    ]
    assert isinstance(events[0], ToolStartEvent)
    assert events[0].summary == "调用fake_tool"
    assert isinstance(events[1], ToolResultEvent)
    assert events[1].ok is True
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert len(done.tool_trace) == 1
    assert done.tool_trace[0]["tool"] == "fake_tool"
    # 第二次非流式调用的 messages 必须含 assistant 的 tool_calls 与配对的 tool 回填。
    second_messages = fake_client.chat_calls[1]["messages"]
    assistant = second_messages[-2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["function"]["name"] == "fake_tool"
    tool_message = second_messages[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["content"] == "工具材料"
    # 每次工具执行写一条 phase=tool_* 的审计指标。
    assert len(fake_client.metric_calls) == 1
    assert fake_client.metric_calls[0]["phase"] == "tool_fake_tool"
    assert fake_client.metric_calls[0]["success"] is True


def test_engine_forces_final_answer_when_iterations_exhausted(monkeypatch) -> None:
    """确认迭代耗尽后仍走流式收尾，且末尾注入强制收尾 system 指令。

    创建日期：2026-06-12
    author: claude
    """

    def make_call(index: int) -> LlmToolCallRequest:
        return LlmToolCallRequest(
            call_id=f"call_{index}", name="fake_tool", arguments_json="{}"
        )

    fake_client = FakeLlmClient(
        results=[
            _chat_result(tool_calls=(make_call(1),)),
            _chat_result(tool_calls=(make_call(2),)),
        ],
        chunks=["基于已有材料的结论"],
    )
    engine = _make_engine(
        monkeypatch,
        fake_client,
        tools=[_fake_tool()],
        settings=_settings(agent_max_iterations=2),
    )

    events = list(engine.run("一直调用工具"))

    # 两轮迭代后不再发起第三次非流式调用，直接进入强制收尾流式作答。
    assert len(fake_client.chat_calls) == 2
    assert len(fake_client.stream_calls) == 1
    last_message = fake_client.stream_calls[0]["messages"][-1]
    assert last_message == {"role": "system", "content": FORCE_FINISH_INSTRUCTION}
    assert events[-1].type == "done"
    assert events[-1].answer == "基于已有材料的结论"


def test_engine_converts_tool_exception_to_error_text(monkeypatch) -> None:
    """确认工具 handler 抛异常时转错误文本回填、循环继续、引擎不抛异常。

    创建日期：2026-06-12
    author: claude
    """

    def broken_handler(args: dict[str, Any], state: Any) -> ToolResult:
        raise RuntimeError("工具内部错误")

    tool_call = LlmToolCallRequest(call_id="call_1", name="fake_tool", arguments_json="{}")
    fake_client = FakeLlmClient(
        results=[_chat_result(tool_calls=(tool_call,)), _chat_result(content="收尾")],
        chunks=["收尾"],
    )
    engine = _make_engine(
        monkeypatch, fake_client, tools=[_fake_tool(handler=broken_handler)]
    )

    events = list(engine.run("触发工具异常"))

    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(tool_results) == 1
    assert tool_results[0].ok is False
    assert tool_results[0].summary == "执行失败"
    # 错误文本回填给模型（含异常类型），引擎继续走到正常 done 终态。
    tool_message = fake_client.chat_calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "工具执行失败" in tool_message["content"]
    assert "RuntimeError" in tool_message["content"]
    assert events[-1].type == "done"


def test_engine_rejects_invalid_tool_arguments_json(monkeypatch) -> None:
    """确认工具入参 JSON 非法时回填解析失败文本且 ok=False。

    创建日期：2026-06-12
    author: claude
    """

    tool_call = LlmToolCallRequest(
        call_id="call_1", name="fake_tool", arguments_json="not json"
    )
    fake_client = FakeLlmClient(
        results=[_chat_result(tool_calls=(tool_call,)), _chat_result(content="收尾")],
        chunks=["收尾"],
    )
    engine = _make_engine(monkeypatch, fake_client, tools=[_fake_tool()])

    events = list(engine.run("入参非法"))

    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert tool_results[0].ok is False
    assert tool_results[0].summary == "入参解析失败"
    # summarize 同样解析失败：tool_start 摘要退回工具名。
    starts = [event for event in events if isinstance(event, ToolStartEvent)]
    assert starts[0].summary == "fake_tool"
    tool_message = fake_client.chat_calls[1]["messages"][-1]
    assert "工具入参 JSON 解析失败" in tool_message["content"]
    assert events[-1].type == "done"


def test_engine_enforces_per_turn_tool_quota(monkeypatch) -> None:
    """确认 web_search 连续调用 4 次时第 4 次被配额拦截（上限 3）。

    创建日期：2026-06-12
    author: claude
    """

    calls = tuple(
        LlmToolCallRequest(call_id=f"call_{index}", name="web_search", arguments_json="{}")
        for index in range(1, 5)
    )
    fake_client = FakeLlmClient(
        results=[_chat_result(tool_calls=calls), _chat_result(content="收尾")],
        chunks=["收尾"],
    )
    engine = _make_engine(monkeypatch, fake_client, tools=[_fake_tool(name="web_search")])

    events = list(engine.run("反复搜索"))

    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert [event.ok for event in tool_results] == [True, True, True, False]
    assert tool_results[3].summary == "本轮配额已用尽"
    # 第 4 次的回填 payload 必须告知模型配额已用尽，让其调整策略。
    tool_messages = [
        item for item in fake_client.chat_calls[1]["messages"] if item["role"] == "tool"
    ]
    assert len(tool_messages) == 4
    assert "配额已用尽" in tool_messages[3]["content"]
    assert events[-1].type == "done"


def test_engine_converts_daily_limit_to_single_error_event(monkeypatch) -> None:
    """确认日限额异常转为单个 error 事件，answer 取异常文本。

    创建日期：2026-06-12
    author: claude
    """

    fake_client = FakeLlmClient(results=[LlmDailyLimitExceeded("限额")])
    engine = _make_engine(monkeypatch, fake_client)

    events = list(engine.run("触发限额"))

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].type == "error"
    assert events[0].answer == "限额"
    # kind 供路由层映射 429 限流契约。
    assert events[0].kind == "daily_limit"


def test_engine_converts_unexpected_exception_to_failure_message(monkeypatch) -> None:
    """确认不可恢复异常统一收敛为 error 事件且 answer 为兜底失败文案。

    创建日期：2026-06-12
    author: claude
    """

    fake_client = FakeLlmClient(results=[RuntimeError("服务端崩了")])
    engine = _make_engine(monkeypatch, fake_client)

    events = list(engine.run("触发异常"))

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].answer == CHAT_FAILURE_MESSAGE
    assert events[0].kind == "general"


def test_compress_messages_only_squashes_tool_messages() -> None:
    """确认超预算时只压缩最早的 role=tool 消息，system/user 原样保留。

    创建日期：2026-06-12
    author: claude
    """

    messages = [
        {"role": "system", "content": "系统规则"},
        {"role": "user", "content": "问题"},
        {"role": "tool", "name": "query_database", "content": "x" * 200},
        {"role": "tool", "name": "get_stock_data", "content": "y" * 100},
        {"role": "assistant", "content": "回答"},
    ]

    compressed = compress_messages_for_budget(messages, budget_chars=200)

    assert compressed[0]["content"] == "系统规则"
    assert compressed[1]["content"] == "问题"
    # 最早的 tool 消息被压缩为含工具名与原始长度的一行摘要。
    assert compressed[2]["content"].startswith("[已省略")
    assert "query_database" in compressed[2]["content"]
    assert "200 字符" in compressed[2]["content"]
    # 压缩第一条后已回到预算内，第二条 tool 消息保持原文。
    assert compressed[3]["content"] == "y" * 100
    assert compressed[4]["content"] == "回答"
    # 返回新列表，不得修改入参。
    assert messages[2]["content"] == "x" * 200


def test_compress_messages_returns_original_when_within_budget() -> None:
    """确认未超预算时 messages 原样返回（不复制、不改写）。

    创建日期：2026-06-12
    author: claude
    """

    messages = [
        {"role": "system", "content": "系统规则"},
        {"role": "tool", "name": "query_database", "content": "材料"},
    ]

    assert compress_messages_for_budget(messages, budget_chars=10000) is messages


def test_engine_cleans_history_window(monkeypatch) -> None:
    """确认历史窗口只保留最近 10 条 user/assistant 且超长内容被截断。

    创建日期：2026-06-12
    author: claude
    """

    history: list[dict[str, Any]] = []
    for index in range(1, 13):
        role = "user" if index % 2 else "assistant"
        history.append({"role": role, "content": f"历史{index}"})
    # 第 12 条改为 1500 字超长文本，校验单条 1200 字截断口径。
    history[11] = {"role": "assistant", "content": "x" * 1500}
    # 混入非 user/assistant 角色，应被整体过滤而不占历史窗口名额。
    history.insert(5, {"role": "system", "content": "系统消息应被过滤"})
    history.insert(0, {"role": "tool", "content": "工具消息应被过滤"})

    fake_client = FakeLlmClient(results=[_chat_result(content="好")], chunks=["好"])
    engine = _make_engine(monkeypatch, fake_client)

    list(engine.run("新问题", context={"conversation_history": history}))

    messages = fake_client.chat_calls[0]["messages"]
    window = messages[1:-1]
    assert len(window) == 10
    assert {item["role"] for item in window} <= {"user", "assistant"}
    # 12 条有效历史只保留最近 10 条：从"历史3"开始。
    assert window[0]["content"] == "历史3"
    assert window[-1]["content"] == "x" * 1200 + "（已截断）"


def test_engine_injects_threshold_context_into_turn_state(monkeypatch) -> None:
    """确认阈值推荐上下文写入 turn_state 且用户消息含工具调用提示。

    创建日期：2026-06-12
    author: claude
    """

    threshold_payload = {
        "name": "招商银行",
        "direction": "HA",
        "metric_premium_pct": "9.6",
        "premium_median_60": "8.6",
        "premium_p80_60": "11.6",
        "premium_percentile_60": "62",
    }
    captured: dict[str, Any] = {}
    fake_client = FakeLlmClient(results=[_chat_result(content="好")], chunks=["好"])
    engine = _make_engine(monkeypatch, fake_client, captured=captured)

    list(
        engine.run(
            "帮我推荐阈值",
            context={"threshold_recommendation": threshold_payload},
        )
    )

    assert captured["turn_state"].threshold_context == threshold_payload
    user_message = fake_client.chat_calls[0]["messages"][-1]
    assert user_message["role"] == "user"
    assert "recommend_threshold" in user_message["content"]
    assert "招商银行" in user_message["content"]


def test_agent_events_to_payload_are_json_serializable() -> None:
    """确认各事件 to_payload 均含 type 字段且可被 json.dumps 序列化。

    创建日期：2026-06-12
    author: claude
    """

    events = [
        ToolStartEvent(tool="web_search", summary="搜索：美联储议息"),
        ToolResultEvent(tool="web_search", ok=False, summary="失败", elapsed_ms=1.5),
        ChartEvent(chart_id="c1", spec={"type": "line"}),
        DeltaEvent(content="增量"),
        DoneEvent(answer="完整回答", charts=[{"type": "line"}], tool_trace=[{"tool": "t"}]),
        ErrorEvent(answer="失败文案"),
    ]
    expected_types = ["tool_start", "tool_result", "chart", "delta", "done", "error"]

    for event, expected_type in zip(events, expected_types, strict=True):
        payload = event.to_payload()
        assert payload["type"] == expected_type
        json.dumps(payload, ensure_ascii=False)
