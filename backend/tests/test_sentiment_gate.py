from __future__ import annotations

import pytest

from app.services.sentiment_gate import (
    ACTION_ABANDON,
    CYCLE_CLIMAX,
    CYCLE_DIVERGE,
    CYCLE_FERMENT,
    CYCLE_ICE,
    CYCLE_RECEDE,
    CYCLE_START,
    SENTIMENT_GATE_THRESHOLD_VERSION,
    STATE_EMPTY,
    GateThresholds,
    classify_sentiment_cycle,
    flatten_gate_inputs,
    map_market_state,
    resolve_gate,
)

_TH = GateThresholds()


def _m(**kw):
    """构造一份"健康无否决"的基线指标，再按需覆盖。"""

    base = {
        "limit_up_count": 60,
        "broken_board_rate_pct": 10.0,
        "limit_down_count": 3,
        "highest_chain": 3,
        "highest_chain_change": 0,
        "prev_premium_avg_pct_chg": 1.0,
        "adv_1_2_rate": 30.0,
        "adv_1_2_denom": 20,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 评审 P0-B4：highest_chain_change 是 dict，flatten 须抽出 change 标量（原恒被 _num 归 0）
# ---------------------------------------------------------------------------
def test_flatten_extracts_highest_chain_change_scalar():
    """市场情绪产物里 emotion_cycle.highest_chain_change 是 dict{today,previous,change}，
    flatten_gate_inputs 必须抽出 change 标量，而非把整 dict 透传（下游 _num 会静默归 0）。"""
    market_emotion = {
        "limit_up_count": 60,
        "limit_down_count": 3,
        "highest_chain": 5,
        "emotion_cycle": {
            "highest_chain_change": {"today": 5, "previous": 8, "change": -3},
            "broken_board_rate_pct": 10.0,
            "prev_limit_up_premium": {"avg_pct_chg": 1.0},
            "advancement": {"1进2": {"rate_pct": 30.0, "denom": 20}},
        },
    }
    flat = flatten_gate_inputs(market_emotion)
    assert flat["highest_chain_change"] == -3   # 抽出 change，而非整个 dict（旧实现→0）


def test_flatten_hcc_scalar_and_missing_defense():
    """标量直接透传；dict 缺 change 键 → None（交缺测口径兜底），不抛错。"""
    assert (
        flatten_gate_inputs({"emotion_cycle": {"highest_chain_change": -2}})["highest_chain_change"]
        == -2
    )
    assert (
        flatten_gate_inputs({"emotion_cycle": {"highest_chain_change": {"today": 1}}})[
            "highest_chain_change"
        ]
        is None
    )


def test_climax_blocked_when_highest_chain_turns_down():
    """最高板掉头(hcc<0)→不应判高潮（即便 hc/prem 达高潮线）。
    修复前 hcc 恒 0(>=0)，高度掉头仍会被判高潮/发酵，放行开仓；修复后 hcc 真实参与判定。"""
    cycle, _ = classify_sentiment_cycle(
        _m(
            highest_chain=_TH.climax_chain,
            highest_chain_change=-2,           # 最高板较昨日下降
            prev_premium_avg_pct_chg=_TH.climax_premium,
        ),
        _TH,
    )
    assert cycle != CYCLE_CLIMAX


def test_six_cycle_classification_branches() -> None:
    """六档分类：构造分别落入各档的输入（均不触发硬否决）。"""

    assert classify_sentiment_cycle(
        _m(
            highest_chain=7,
            highest_chain_change=1,
            prev_premium_avg_pct_chg=5.0,
            adv_1_2_rate=50.0,
        ),
        _TH,
    )[0] == CYCLE_CLIMAX
    assert classify_sentiment_cycle(
        _m(
            highest_chain=4,
            prev_premium_avg_pct_chg=2.0,
            adv_1_2_rate=50.0,
            highest_chain_change=0,
        ),
        _TH,
    )[0] == CYCLE_FERMENT
    assert classify_sentiment_cycle(
        _m(broken_board_rate_pct=38.0, prev_premium_avg_pct_chg=-1.0, highest_chain_change=-1),
        _TH,
    )[0] == CYCLE_RECEDE
    assert classify_sentiment_cycle(
        _m(broken_board_rate_pct=28.0, highest_chain_change=-1, prev_premium_avg_pct_chg=0.5,
           adv_1_2_rate=30.0),
        _TH,
    )[0] == CYCLE_DIVERGE
    assert classify_sentiment_cycle(
        _m(limit_up_count=20, prev_premium_avg_pct_chg=-0.5, broken_board_rate_pct=10.0,
           highest_chain=1),
        _TH,
    )[0] == CYCLE_ICE
    assert classify_sentiment_cycle(
        _m(limit_up_count=40, prev_premium_avg_pct_chg=1.5, adv_1_2_rate=20.0,
           broken_board_rate_pct=10.0),
        _TH,
    )[0] == CYCLE_START


def test_hard_veto_priority() -> None:
    """硬否决命中即空仓，cycle∈{冰点,退潮}，action=放弃，gate_reasons 记录命中项。"""

    cases = [
        ({"broken_board_rate_pct": 50.0}, "broken_board_rate_high"),
        ({"limit_down_count": 35}, "limit_down_high"),
        ({"prev_premium_avg_pct_chg": -5.0}, "prev_premium_deep_negative"),
        ({"adv_1_2_rate": 5.0, "adv_1_2_denom": 20}, "advance_chain_broken"),
    ]
    for override, reason in cases:
        d = resolve_gate(_m(**override))
        assert d.market_state == STATE_EMPTY
        assert d.action == ACTION_ABANDON
        assert d.sentiment_cycle in (CYCLE_ICE, CYCLE_RECEDE)
        assert reason in d.gate_reasons


def test_limit_up_exhausted_maps_to_ice() -> None:
    """仅涨停枯竭(无连板)→ 冰点空仓（与溢价/跌停主导的退潮区分）。"""

    d = resolve_gate(_m(limit_up_count=10, highest_chain=1, prev_premium_avg_pct_chg=0.2,
                        broken_board_rate_pct=10.0, limit_down_count=3))
    assert d.sentiment_cycle == CYCLE_ICE
    assert d.market_state == STATE_EMPTY
    assert "limit_up_count_exhausted" in d.gate_reasons


def test_missing_premium_neutral_not_empty() -> None:
    """隔日溢价缺测→标 premium_unknown、按中性处理，不误判空仓。"""

    d = resolve_gate(_m(prev_premium_avg_pct_chg=None, limit_up_count=50,
                        broken_board_rate_pct=10.0, limit_down_count=2))
    assert "premium_unknown" in d.gate_reasons
    assert d.market_state != STATE_EMPTY


def test_advance_denom_none_no_veto() -> None:
    """晋级率分母缺失→不作为断链否决证据（防小样本/新股日误杀）。"""

    d = resolve_gate(_m(adv_1_2_rate=5.0, adv_1_2_denom=None, prev_premium_avg_pct_chg=1.0,
                        limit_up_count=50))
    assert "advance_chain_broken" not in d.gate_reasons
    assert d.market_state != STATE_EMPTY


def test_empty_implies_abandon_and_version() -> None:
    """空仓档顶层 action 恒为放弃；产物带固化 threshold_version。"""

    d = resolve_gate(_m(broken_board_rate_pct=60.0))
    assert d.market_state == STATE_EMPTY and d.action == ACTION_ABANDON
    assert d.threshold_version == SENTIMENT_GATE_THRESHOLD_VERSION


def test_deterministic_repeatable() -> None:
    """确定性：同输入连续调用结果完全相等（含 gate_reasons 顺序）。"""

    metrics = _m(broken_board_rate_pct=38.0, prev_premium_avg_pct_chg=-1.0)
    d1 = resolve_gate(metrics)
    d2 = resolve_gate(metrics)
    assert (d1.sentiment_cycle, d1.market_state, d1.action, d1.gate_reasons) == (
        d2.sentiment_cycle,
        d2.market_state,
        d2.action,
        d2.gate_reasons,
    )


def test_map_market_state_rejects_unknown() -> None:
    """非法 cycle → ValueError（取值域封闭）。"""

    with pytest.raises(ValueError):
        map_market_state("不存在的档")


def test_monotonic_assert_catches_broken_mapping(monkeypatch) -> None:
    """篡改 cycle→state 映射使其违背单调性 → _assert_state_monotonic 抛 ValueError（护栏）。"""

    import app.services.sentiment_gate as sg

    broken = dict(sg._CYCLE_TO_STATE)
    broken[sg.CYCLE_CLIMAX] = sg.STATE_EMPTY  # 最强档反而空仓 → 弱→强序非递减被破坏
    monkeypatch.setattr(sg, "_CYCLE_TO_STATE", broken)
    with pytest.raises(ValueError):
        sg._assert_state_monotonic()
