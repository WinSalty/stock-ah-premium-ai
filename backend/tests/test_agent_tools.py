"""问答 Agent 工具层单元测试。

覆盖口径：
- 阈值确定性公式数值回归（与旧 llm_service 实现一致，S1-2 验收标准）；
- recommend_threshold 工具的上下文缺失与正常计算两条路径；
- query_database 工具在内存 SQLite + 真实 SqlGuardService 下的成功/拒绝/报错；
- get_stock_data 工具的识别、歧义、数量上限与数据包别名归一（mock 解析与编排器）；
- ToolRegistry 的 OpenAI 规格输出、未知工具兜底与摘要退回；
- build_system_prompt 的数据字典与能力声明动态拼装。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.agent.budget import TurnState
from app.services.agent.prompts import build_system_prompt
from app.services.agent.tool_registry import ToolCall, ToolRegistry, ToolResult, ToolSpec
from app.services.agent.tools.database import build_query_database_tool
from app.services.agent.tools.market_data import build_get_stock_data_tool
from app.services.agent.tools.threshold import (
    build_recommend_threshold_tool,
    calculate_threshold_recommendation,
    format_threshold_number,
)
from app.services.market_data_orchestrator import MarketDataEnsureResult
from app.services.stock_identity_resolver import StockIdentity, StockResolveResult


def _settings(**overrides: Any) -> Settings:
    """构造与本机密钥文件完全隔离的测试配置。

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


# ----------------------------------------------------------------------
# 阈值确定性公式：数值回归（对照旧 llm_service 实现的断言口径）
# ----------------------------------------------------------------------


def test_threshold_formula_base_anchor_matches_legacy() -> None:
    """确认 60 日分位齐全时取 median + 0.65 * (p80 - median)，与旧实现一致。

    创建日期：2026-06-12
    author: claude
    """

    result = calculate_threshold_recommendation(
        {
            "direction": "HA",
            "metric_premium_pct": "9.6",
            "premium_median_60": "8.6",
            "premium_p80_60": "11.6",
            "premium_percentile_60": "62",
        }
    )

    assert format_threshold_number(result.threshold_pct) == "10.55"
    assert result.reason_code == "base_formula"
    assert result.direction == "HA"
    assert result.direction_label == "H/A"


def test_threshold_formula_takes_current_when_percentile_above_80() -> None:
    """确认分位高于 80% 时取基础锚点与当前溢价的较高值（max 取 12）。

    创建日期：2026-06-12
    author: claude
    """

    result = calculate_threshold_recommendation(
        {
            "direction": "HA",
            "metric_premium_pct": "12.0",
            "premium_median_60": "8.6",
            "premium_p80_60": "11.6",
            "premium_percentile_60": "85",
        }
    )

    assert result.reason_code == "current_above_p80"
    assert result.threshold_pct == Decimal("12.00")
    assert format_threshold_number(result.threshold_pct) == "12"


def test_threshold_formula_median_current_only_fallback() -> None:
    """确认缺 80% 分位时取 median + 0.5 * abs(current - median) 折中锚点。

    创建日期：2026-06-12
    author: claude
    """

    result = calculate_threshold_recommendation(
        {"metric_premium_pct": "10", "premium_median_60": "8"}
    )

    assert result.reason_code == "median_current_only"
    assert format_threshold_number(result.threshold_pct) == "9"


def test_threshold_formula_missing_history_buffers() -> None:
    """确认历史分位缺失时按通道与当前值大小选择 3/4/5 个百分点保守缓冲。

    边界口径：有通道缓冲 3；无通道缓冲 4；|current| >= 30 时缓冲 5；
    current 为负时缓冲取负方向（阈值向下留量）。

    创建日期：2026-06-12
    author: claude
    """

    with_channel = calculate_threshold_recommendation(
        {"metric_premium_pct": "10", "connect_channels": "沪深"}
    )
    without_channel = calculate_threshold_recommendation({"metric_premium_pct": "10"})
    large_current = calculate_threshold_recommendation(
        {"metric_premium_pct": "35", "connect_channels": "沪"}
    )
    negative_current = calculate_threshold_recommendation(
        {"metric_premium_pct": "-10", "connect_channels": "沪"}
    )

    assert with_channel.reason_code == "missing_history"
    assert format_threshold_number(with_channel.threshold_pct) == "13"
    assert format_threshold_number(without_channel.threshold_pct) == "14"
    assert format_threshold_number(large_current.threshold_pct) == "40"
    assert format_threshold_number(negative_current.threshold_pct) == "-13"


def test_threshold_formula_missing_current_returns_zero() -> None:
    """确认当前溢价缺失时给 0% 观察阈值并要求补齐行情后复核。

    创建日期：2026-06-12
    author: claude
    """

    result = calculate_threshold_recommendation({})

    assert result.reason_code == "missing_current"
    assert result.threshold_pct == Decimal("0.00")
    assert format_threshold_number(result.threshold_pct) == "0"
    # direction 缺省按 HA 收敛。
    assert result.direction == "HA"


# ----------------------------------------------------------------------
# recommend_threshold 工具
# ----------------------------------------------------------------------


def test_recommend_threshold_tool_fails_without_context() -> None:
    """确认轮内无阈值上下文时工具返回 ok=False 并说明缺口。

    创建日期：2026-06-12
    author: claude
    """

    turn_state = TurnState(question_id="q-1")
    tool = build_recommend_threshold_tool(turn_state)

    result = tool.handler({}, turn_state)

    assert result.ok is False
    assert "阈值推荐上下文" in result.payload


def test_recommend_threshold_tool_returns_structured_json() -> None:
    """确认有上下文时 payload 为 JSON 且含推荐阈值与输入回显。

    创建日期：2026-06-12
    author: claude
    """

    turn_state = TurnState(
        question_id="q-1",
        threshold_context={
            "name": "招商银行",
            "direction": "HA",
            "metric_premium_pct": "9.6",
            "premium_median_60": "8.6",
            "premium_p80_60": "11.6",
            "premium_percentile_60": "62",
        },
    )
    tool = build_recommend_threshold_tool(turn_state)

    result = tool.handler({}, turn_state)

    assert result.ok is True
    body = json.loads(result.payload)
    assert body["recommended_threshold_pct"] == "10.55"
    assert body["reason_code"] == "base_formula"
    assert body["stock_name"] == "招商银行"
    assert body["inputs"]["premium_median_60"] == "8.6"
    assert "10.55%" in result.summary
    # 工具描述与摘要应携带股票名，便于模型与界面理解上下文归属。
    assert "招商银行" in tool.description
    assert tool.summarize({}) == "计算招商银行的建议阈值"


# ----------------------------------------------------------------------
# query_database 工具（内存 SQLite + 真实 SqlGuardService）
# ----------------------------------------------------------------------


def _sqlite_session_with_premium_view() -> Session:
    """构造含白名单视图同名表的内存 SQLite 会话并预插 2 行数据。

    SQLite 中直接用普通表顶替 MySQL 视图：SqlGuard 只看表名白名单，
    执行层不区分视图与表，足以覆盖工具的真实执行路径。

    创建日期：2026-06-12
    author: claude
    """

    engine = create_engine("sqlite:///:memory:")
    db = Session(engine)
    db.execute(
        text(
            "CREATE TABLE v_latest_ah_premium ("
            "a_ts_code VARCHAR(16), a_name VARCHAR(64), ha_premium_pct REAL)"
        )
    )
    db.execute(
        text(
            "INSERT INTO v_latest_ah_premium VALUES "
            "('600036.SH', '招商银行', 12.5), ('601318.SH', '中国平安', 8.0)"
        )
    )
    db.commit()
    return db


def test_query_database_tool_executes_select_and_caches_rows() -> None:
    """确认合法 SELECT 正常执行：payload 含行数、完整行缓存进 turn_state。

    创建日期：2026-06-12
    author: claude
    """

    db = _sqlite_session_with_premium_view()
    turn_state = TurnState(question_id="q-1", user_id=7)
    tool = build_query_database_tool(db, turn_state)

    result = tool.handler(
        {
            "sql": (
                "SELECT a_ts_code, ha_premium_pct FROM v_latest_ah_premium "
                "ORDER BY ha_premium_pct DESC"
            ),
            "purpose": "查询最新溢价",
        },
        turn_state,
    )

    assert result.ok is True
    assert "共 2 行" in result.payload
    assert result.summary == "返回 2 行"
    # 完整结果按 (序号, 用途, 行数组) 缓存，供 run_python 沙箱注入。
    assert len(turn_state.sql_results) == 1
    index, purpose, rows = turn_state.sql_results[0]
    assert (index, purpose) == (1, "查询最新溢价")
    assert len(rows) == 2
    assert rows[0]["a_ts_code"] == "600036.SH"


def test_query_database_tool_rejects_write_statement() -> None:
    """确认写操作 SQL 被 SqlGuard 拒绝且原因回填给模型。

    创建日期：2026-06-12
    author: claude
    """

    db = _sqlite_session_with_premium_view()
    turn_state = TurnState(question_id="q-1")
    tool = build_query_database_tool(db, turn_state)

    result = tool.handler(
        {"sql": "DELETE FROM v_latest_ah_premium", "purpose": "删数据"},
        turn_state,
    )

    assert result.ok is False
    assert "安全校验" in result.payload
    assert result.summary == "SQL 校验未通过"
    assert turn_state.sql_results == []


def test_query_database_tool_returns_execution_error_text() -> None:
    """确认执行报错（查询不存在的列）时回填执行失败信息供模型修正。

    创建日期：2026-06-12
    author: claude
    """

    db = _sqlite_session_with_premium_view()
    turn_state = TurnState(question_id="q-1")
    tool = build_query_database_tool(db, turn_state)

    result = tool.handler(
        {
            "sql": "SELECT no_such_column FROM v_latest_ah_premium",
            "purpose": "触发执行错误",
        },
        turn_state,
    )

    assert result.ok is False
    assert "执行失败" in result.payload
    assert result.summary == "SQL 执行失败"


# ----------------------------------------------------------------------
# get_stock_data 工具（mock 识别器与编排器）
# ----------------------------------------------------------------------


def _identity(ts_code: str = "600036.SH", name: str = "招商银行") -> StockIdentity:
    """构造 A 股身份测试数据（market 取主板，非 HK 前缀）。

    创建日期：2026-06-12
    author: claude
    """

    return StockIdentity(
        ts_code=ts_code,
        symbol=ts_code.split(".", 1)[0],
        name=name,
        market="主板",
    )


def _ensure_result(cache_hit: bool = True) -> MarketDataEnsureResult:
    """构造编排器返回的成功补数结果。

    创建日期：2026-06-12
    author: claude
    """

    return MarketDataEnsureResult(
        stock=None,
        stocks=(),
        packages=("quote_valuation",),
        context={"scope": "A_STOCK_SINGLE", "ts_code": "600036.SH"},
        fetched_rows=0 if cache_hit else 5,
        cache_hit=cache_hit,
        status="COMPLETED",
    )


def _patch_market_data(
    monkeypatch: Any,
    resolve_map: dict[str, StockResolveResult],
    ensure_result: MarketDataEnsureResult | None = None,
) -> dict[str, Any]:
    """替换 market_data 模块内的识别器与编排器，返回捕获入参的字典。

    创建日期：2026-06-12
    author: claude
    """

    captured: dict[str, Any] = {}

    class FakeResolver:
        """StockIdentityResolver 测试替身：按映射表回放解析结果。

        创建日期：2026-06-12
        author: claude
        """

        def __init__(self, db: Any) -> None:
            pass

        def resolve(self, stock: str) -> StockResolveResult:
            return resolve_map[stock]

    class FakeOrchestrator:
        """MarketDataOrchestrator 测试替身：记录补数需求并回放固定结果。

        创建日期：2026-06-12
        author: claude
        """

        def __init__(self, db: Any) -> None:
            pass

        def ensure_for_question(self, **kwargs: Any) -> MarketDataEnsureResult:
            captured.update(kwargs)
            assert ensure_result is not None, "本用例不应触达编排器"
            return ensure_result

    monkeypatch.setattr(
        "app.services.agent.tools.market_data.StockIdentityResolver", FakeResolver
    )
    monkeypatch.setattr(
        "app.services.agent.tools.market_data.MarketDataOrchestrator", FakeOrchestrator
    )
    return captured


def test_get_stock_data_tool_returns_cache_hit_payload(monkeypatch) -> None:
    """确认正常路径返回缓存命中文案并缓存数据包供沙箱使用。

    创建日期：2026-06-12
    author: claude
    """

    captured = _patch_market_data(
        monkeypatch,
        {"招商银行": StockResolveResult(identity=_identity())},
        _ensure_result(cache_hit=True),
    )
    turn_state = TurnState(question_id="q-1", user_id=7)
    tool = build_get_stock_data_tool(Mock(), turn_state)

    result = tool.handler(
        {"stocks": ["招商银行"], "packages": ["quote_valuation"]}, turn_state
    )

    assert result.ok is True
    assert "命中本地缓存" in result.payload
    assert "命中本地缓存" in result.summary
    demands = captured["data_demands"]
    assert len(demands) == 1
    assert demands[0].ts_code == "600036.SH"
    assert demands[0].market == "A"
    assert demands[0].packages == ("quote_valuation",)
    assert turn_state.stock_packages == [
        ("600036.SH", "quote_valuation", _ensure_result(cache_hit=True).context)
    ]


def test_get_stock_data_tool_reports_ambiguous_candidates(monkeypatch) -> None:
    """确认股票名歧义时返回候选清单 ok=False 且不触达编排器。

    创建日期：2026-06-12
    author: claude
    """

    candidates = (
        _identity("600036.SH", "招商银行"),
        _identity("001979.SZ", "招商蛇口"),
    )
    captured = _patch_market_data(
        monkeypatch,
        {
            "招商": StockResolveResult(
                identity=None,
                ambiguous_candidates=candidates,
                reason="名称命中多只股票",
            )
        },
    )
    turn_state = TurnState(question_id="q-1")
    tool = build_get_stock_data_tool(Mock(), turn_state)

    result = tool.handler({"stocks": ["招商"], "packages": ["quote_valuation"]}, turn_state)

    assert result.ok is False
    assert "无法确认" in result.payload
    assert "招商银行（600036.SH）" in result.payload
    assert "招商蛇口（001979.SZ）" in result.payload
    assert result.summary == "股票识别待确认"
    # 识别失败必须在编排器之前短路，不发起任何补数。
    assert captured == {}


def test_get_stock_data_tool_rejects_unknown_package(monkeypatch) -> None:
    """确认未知数据包名直接拒绝并回显可用包清单。

    创建日期：2026-06-12
    author: claude
    """

    _patch_market_data(monkeypatch, {})
    turn_state = TurnState(question_id="q-1")
    tool = build_get_stock_data_tool(Mock(), turn_state)

    result = tool.handler({"stocks": ["招商银行"], "packages": ["no_such_pkg"]}, turn_state)

    assert result.ok is False
    assert "数据包 no_such_pkg 不存在" in result.payload
    assert "quote_valuation" in result.payload


def test_get_stock_data_tool_rejects_more_than_five_stocks(monkeypatch) -> None:
    """确认单次超过 5 只股票时要求拆分调用。

    创建日期：2026-06-12
    author: claude
    """

    _patch_market_data(monkeypatch, {})
    turn_state = TurnState(question_id="q-1")
    tool = build_get_stock_data_tool(Mock(), turn_state)

    result = tool.handler(
        {
            "stocks": [f"股票{index}" for index in range(6)],
            "packages": ["quote_valuation"],
        },
        turn_state,
    )

    assert result.ok is False
    assert "最多查询 5 只股票" in result.payload
    assert result.summary == "股票数量超限"


def test_get_stock_data_tool_normalizes_capital_flow_alias(monkeypatch) -> None:
    """确认对外包名 capital_flow 归一为内部 capital_flow_light 传给编排器。

    创建日期：2026-06-12
    author: claude
    """

    captured = _patch_market_data(
        monkeypatch,
        {"招商银行": StockResolveResult(identity=_identity())},
        _ensure_result(),
    )
    turn_state = TurnState(question_id="q-1")
    tool = build_get_stock_data_tool(Mock(), turn_state)

    result = tool.handler(
        {"stocks": ["招商银行"], "packages": ["capital_flow"]}, turn_state
    )

    assert result.ok is True
    assert captured["data_demands"][0].packages == ("capital_flow_light",)


# ----------------------------------------------------------------------
# ToolRegistry
# ----------------------------------------------------------------------


def _registry_tool(name: str = "demo_tool", capability_note: str = "") -> ToolSpec:
    """构造注册表测试用的最小工具规格。

    创建日期：2026-06-12
    author: claude
    """

    return ToolSpec(
        name=name,
        description=f"{name} 描述",
        parameters={"type": "object", "properties": {}},
        handler=lambda args, state: ToolResult(ok=True, payload="ok", summary="完成"),
        summarize=lambda args: f"摘要：{args['topic']}",
        capability_note=capability_note,
    )


def test_tool_registry_specs_use_openai_function_format() -> None:
    """确认 specs() 输出 OpenAI function calling 的 tools 数组结构。

    创建日期：2026-06-12
    author: claude
    """

    registry = ToolRegistry([_registry_tool()])

    specs = registry.specs()

    assert specs == [
        {
            "type": "function",
            "function": {
                "name": "demo_tool",
                "description": "demo_tool 描述",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_tool_registry_rejects_unknown_tool() -> None:
    """确认执行未注册工具时返回 ok=False 的引导文本而不抛异常。

    创建日期：2026-06-12
    author: claude
    """

    registry = ToolRegistry([_registry_tool()])

    result = registry.execute(
        ToolCall(call_id="c1", name="no_such_tool", arguments_json="{}"),
        TurnState(question_id="q-1"),
    )

    assert result.ok is False
    assert "不存在或当前不可用" in result.payload
    assert result.summary == "工具不可用"


def test_tool_registry_summarize_falls_back_to_tool_name() -> None:
    """确认 summarize 在入参解析失败时退回工具名兜底。

    创建日期：2026-06-12
    author: claude
    """

    registry = ToolRegistry([_registry_tool()])

    summary = registry.summarize(
        ToolCall(call_id="c1", name="demo_tool", arguments_json="not json")
    )

    assert summary == "demo_tool"


# ----------------------------------------------------------------------
# build_system_prompt
# ----------------------------------------------------------------------


def test_system_prompt_contains_data_catalog_and_offline_note() -> None:
    """确认系统提示词含数据字典关键视图，且无 web_search 时声明无联网能力。

    创建日期：2026-06-12
    author: claude
    """

    registry = ToolRegistry(
        [_registry_tool("query_database", capability_note="query_database：只读取数。")]
    )

    prompt = build_system_prompt(registry, _settings())

    assert "v_watchlist_opportunity" in prompt
    assert "当前无联网能力" in prompt
    assert "- query_database：只读取数。" in prompt


def test_system_prompt_omits_offline_note_when_web_search_available() -> None:
    """确认注册了 web_search 时不再声明无联网能力，能力随 capability_note 拼装。

    创建日期：2026-06-12
    author: claude
    """

    registry = ToolRegistry(
        [_registry_tool("web_search", capability_note="web_search：联网搜索时效信息。")]
    )

    prompt = build_system_prompt(registry, _settings())

    assert "当前无联网能力" not in prompt
    assert "- web_search：联网搜索时效信息。" in prompt
    assert "当前可用能力" in prompt
