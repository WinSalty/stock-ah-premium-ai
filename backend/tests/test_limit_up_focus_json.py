from __future__ import annotations

import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.services.limit_up_push_service import (
    LIMIT_UP_STAGE_CHAIN_FOCUS,
    LIMIT_UP_STAGE_FIRST_BOARD_FOCUS,
    LIMIT_UP_STAGE_HIGH_BOARD_FOCUS,
    LimitUpPushService,
)


def _make_db() -> Session:
    """内存 SQLite 会话（建全表）。

    创建日期：2026-06-13
    author: claude
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _service(db: Session) -> LimitUpPushService:
    """构造打板服务（tushare/notification 走默认，不触网）。"""

    return LimitUpPushService(
        db,
        settings=Settings(
            llm_api_key=None,
            llm_api_key_file=None,
            tushare_token="token",
            tushare_token_file=None,
        ),
    )


_CTX = {"trade_date": date(2026, 6, 12), "market_context": {"emotion_cycle": {}}}
_FOCUS_STAGES = (
    LIMIT_UP_STAGE_FIRST_BOARD_FOCUS,
    LIMIT_UP_STAGE_CHAIN_FOCUS,
    LIMIT_UP_STAGE_HIGH_BOARD_FOCUS,
)


def test_focus_prompts_emit_json_contract() -> None:
    """三个 FOCUS 提示词输出契约已改为 JSON（含 html_fragment + 先验字段），不再要求纯 HTML。"""

    svc = _service(_make_db())
    prompts = [
        svc._first_board_focus_prompt(_CTX, [], {}),
        svc._chain_focus_prompt(_CTX, [], {}),
        svc._high_board_focus_prompt(_CTX, [], {}),
    ]
    for prompt in prompts:
        assert '"html_fragment"' in prompt
        assert "continuation_prob" in prompt
        assert "stock_priors" in prompt
        assert "输出 HTML 片段" not in prompt  # 旧 HTML 输出契约已移除


def test_focus_stage_version_isolated() -> None:
    """FOCUS 阶段提示词版本带 focus-json-v1 后缀，与旧 :v3 缓存物理隔离。"""

    svc = _service(_make_db())
    for stage in _FOCUS_STAGES:
        version = svc._stage_prompt_version(stage)
        assert version.endswith(":focus-json-v1")
        assert ":v3" not in version


def test_fallback_focus_stage_html_and_conservative_priors() -> None:
    """降级兜底产出非空 html_fragment + 保守先验缺省值（不凭空抬概率）。"""

    svc = _service(_make_db())
    payload = svc._fallback_focus_stage(
        LIMIT_UP_STAGE_CHAIN_FOCUS,
        {"selected_chain_stocks": [{"ts_code": "300750.SZ", "name": "宁德", "status": "2连板"}]},
    )
    assert payload["html_fragment"]
    assert payload["continuation_prob"] == "极低"
    assert payload["next_day_premium_prob"] == "极低"
    assert payload["stock_priors"] == []


def test_run_json_stage_valid_json_parsed(monkeypatch) -> None:
    """LLM 返回合法 JSON → 结构化先验与 html_fragment 正确解析，质量项 OK。"""

    db = _make_db()
    svc = _service(db)
    valid = json.dumps(
        {
            "html_fragment": "<h3>两连三连</h3>",
            "continuation_prob": "中",
            "next_day_premium_prob": "高",
            "boost_conditions": ["竞价高开3-5%且放量"],
            "fail_conditions": ["破开盘价"],
            "suggested_hold_thesis": "打板试错断板即出",
            "stock_priors": [{"ts_code": "300750.SZ", "continuation_prob": "中"}],
        }
    )
    monkeypatch.setattr(svc, "_chat_completion_with_reasoning", lambda *a, **k: valid)
    quality: list[dict] = []
    stage_input = {"trade_date": date(2026, 6, 12), "selected_chain_stocks": []}
    payload = svc._run_json_stage(
        LIMIT_UP_STAGE_CHAIN_FOCUS,
        stage_input,
        "sys",
        "user",
        svc._fallback_focus_stage(LIMIT_UP_STAGE_CHAIN_FOCUS, stage_input),
        quality,
    )
    assert payload["html_fragment"] == "<h3>两连三连</h3>"
    assert payload["continuation_prob"] == "中"
    assert payload["stock_priors"][0]["ts_code"] == "300750.SZ"
    assert any(q["status"] == "OK" for q in quality)


def test_run_json_stage_parse_fallback_keeps_html(monkeypatch) -> None:
    """LLM 返回非 JSON → 走兜底(含非空 html_fragment)，质量项 PARSE_FALLBACK，报告仍可 READY。"""

    db = _make_db()
    svc = _service(db)
    monkeypatch.setattr(
        svc, "_chat_completion_with_reasoning", lambda *a, **k: "这不是JSON只是一段说明文字"
    )
    quality: list[dict] = []
    stage_input = {
        "trade_date": date(2026, 6, 12),
        "selected_chain_stocks": [{"ts_code": "300750.SZ", "name": "宁德"}],
    }
    payload = svc._run_json_stage(
        LIMIT_UP_STAGE_CHAIN_FOCUS,
        stage_input,
        "sys",
        "user",
        svc._fallback_focus_stage(LIMIT_UP_STAGE_CHAIN_FOCUS, stage_input),
        quality,
    )
    assert payload.get("parse_fallback") is True
    assert payload["html_fragment"]
    assert any(q["status"] == "PARSE_FALLBACK" for q in quality)


def test_run_json_stage_exception_fallback(monkeypatch) -> None:
    """LLM 调用异常 → error_fallback + FAILED_FALLBACK + 非空 html_fragment（READY 率等价）。"""

    db = _make_db()
    svc = _service(db)

    def _boom(*a, **k):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(svc, "_chat_completion_with_reasoning", _boom)
    quality: list[dict] = []
    stage_input = {
        "trade_date": date(2026, 6, 12),
        "selected_chain_stocks": [{"ts_code": "300750.SZ", "name": "宁德"}],
    }
    payload = svc._run_json_stage(
        LIMIT_UP_STAGE_CHAIN_FOCUS,
        stage_input,
        "sys",
        "user",
        svc._fallback_focus_stage(LIMIT_UP_STAGE_CHAIN_FOCUS, stage_input),
        quality,
    )
    assert payload.get("error_fallback") is True
    assert payload["html_fragment"]
    assert any(q["status"] == "FAILED_FALLBACK" for q in quality)


def test_empty_html_fragment_guard_fills_pipeline(monkeypatch) -> None:
    """JSON 合法但 html_fragment 为空时，收口守卫回退确定性观察表，pipeline 该小节非空。"""

    db = _make_db()
    svc = _service(db)
    context = {
        "trade_date": "2026-06-12",
        "data_quality": [],
        "first_board_context": {"stocks": [], "themes": []},
        "chain_board_context": {
            "stocks": [{"ts_code": "300750.SZ", "name": "宁德", "status": "2连板"}]
        },
        "high_board_context": {"stocks": []},
        "market_context": {"market_emotion": {}, "themes": []},
    }

    def fake_json_stage(stage_key, stage_input, system_prompt, user_prompt, fallback, quality):
        quality.append({"stage_key": stage_key, "status": "OK", "message": "t"})
        if stage_key == "CHAIN_SELECTION":
            return {"selected_stocks": [{"ts_code": "300750.SZ", "name": "宁德"}]}
        if stage_key in {"FIRST_BOARD_SELECTION", "HIGH_BOARD_SELECTION"}:
            return {"selected_stocks": []}
        if stage_key in {"FIRST_BOARD_FOCUS", "CHAIN_FOCUS", "HIGH_BOARD_FOCUS"}:
            return {"html_fragment": "", "stock_priors": []}  # 模型偶发：空 html_fragment
        return {"html_fragment": "<h3>题材</h3>", "theme_candidates": []}

    def fake_text_stage(stage_key, stage_input, system_prompt, user_prompt, quality):
        quality.append({"stage_key": stage_key, "status": "OK", "message": "t"})
        return {"content": "<h2>报告</h2>", "html_fragment": "<h2>报告</h2>"}

    monkeypatch.setattr(svc, "_run_json_stage", fake_json_stage)
    monkeypatch.setattr(svc, "_run_text_stage", fake_text_stage)

    svc._generate_multi_stage_llm_report(context)
    # 守卫把空 html_fragment 回退为确定性观察表，chain 小节非空
    assert str(context["pipeline"]["chain_focus_html"]).strip()
