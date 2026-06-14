from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.limit_up_leader_scoring_service import (
    ROLE_MAIN_LEADER,
    ROLE_STRAGGLER,
    board_width,
    build_scoring_context,
    score_stock,
    score_stocks,
)

_VER = "leader-scoring-test"


def _strong_leader() -> dict[str, Any]:
    """强龙头：当日最高板、早封、封流比高、量能健康、LLM 龙头/空间板。"""

    return {
        "ts_code": "300999.SZ",
        "name": "龙头股",
        "board_level": 5,
        "limit_type": "20cm",
        "seal_ratio_pct": 15.0,
        "first_limit_time": "09:31:00",
        "open_times": 0,
        "turnover_rate": 15.0,
        "theme": "人工智能",
        "technical": {"amount_ratio_5d": 3.0},
        "selection": {"theme_role": "龙头", "leader_role": "空间板", "score_detail": "强"},
    }


def _weak_follower() -> dict[str, Any]:
    """弱跟风：首板、晚封、封流比低、天量分歧、LLM 跟风/弱。"""

    return {
        "ts_code": "600001.SH",
        "name": "跟风股",
        "board_level": 1,
        "limit_type": "10cm",
        "seal_ratio_pct": 1.0,
        "first_limit_time": "14:30:00",
        "open_times": 3,
        "turnover_rate": 35.0,
        "theme": "人工智能",
        "technical": {"amount_ratio_5d": 1.0},
        "selection": {"theme_role": "跟风", "score_detail": "弱"},
    }


def test_board_width_by_prefix() -> None:
    """板宽由代码前缀推断：创业板 20cm，主板 10cm。"""

    assert board_width("300750.SZ") == "20cm"
    assert board_width("301001.SZ") == "20cm"
    assert board_width("600519.SH") == "10cm"
    assert board_width("000001.SZ") == "10cm"


def test_strong_beats_weak_and_roles() -> None:
    """强龙头综合分显著高于弱跟风，角色判定符合预期，分数落 [0,100]。"""

    rows = [_strong_leader(), _weak_follower()]
    strong, weak = score_stocks(rows, scoring_version=_VER)
    assert Decimal("0") <= weak.leader_strength_score <= Decimal("100")
    assert Decimal("0") <= strong.leader_strength_score <= Decimal("100")
    assert strong.leader_strength_score > weak.leader_strength_score
    # 强者为当日最高板 + 空间板 → 总龙头候选；弱者强度分位靠后 → 杂毛
    assert ROLE_MAIN_LEADER in strong.role_tags
    assert weak.role_tags[0] == ROLE_STRAGGLER
    # 强者可成交(非一字: 首封 09:31 已超 30s)，弱者也可成交
    assert strong.tradable_flag == "TRADABLE"
    # 子分与版本均落痕
    assert "subscores" in strong.strength_dim_json
    assert strong.strength_dim_json["scoring_version"] == _VER


def test_yiziban_marked_watch() -> None:
    """开盘即封死(open_times=0 且 09:30:00 首封)判一字 → WATCH 看得到买不进。"""

    row = _strong_leader()
    row["first_limit_time"] = "09:30:00"
    row["open_times"] = 0
    [score] = score_stocks([row], scoring_version=_VER)
    assert score.tradable_flag == "WATCH"


def test_open_times_none_imputed_not_zero() -> None:
    """open_times 真实缺测 → 留痕 imputed，不得当 0（0=全天未开板=强势）。"""

    row = _strong_leader()
    row["open_times"] = None
    ctx = build_scoring_context([row])
    score = score_stock(row, ctx, scoring_version=_VER, strength_pctl=0.9)
    assert score.strength_dim_json.get("open_times_imputed") is True


def test_seal_ratio_missing_imputed() -> None:
    """封流比缺失 → 封板质量子项退化并留痕，不报错。"""

    row = _weak_follower()
    row["seal_ratio_pct"] = None
    ctx = build_scoring_context([row])
    score = score_stock(row, ctx, scoring_version=_VER, strength_pctl=0.2)
    assert score.strength_dim_json.get("seal_ratio_imputed") is True
    assert Decimal("0") <= score.leader_strength_score <= Decimal("100")


def test_action_enum_values() -> None:
    """action 取中文三档（与阶段3 表列 action 及 LLM 分层口径一致），strategy_family 三族。"""

    rows = [_strong_leader(), _weak_follower()]
    for score in score_stocks(rows, scoring_version=_VER):
        assert score.action in {"重点观察", "谨慎观察", "放弃观察"}
        assert score.strategy_family in {"DABAN", "BANLU", "DIXI"}


def test_main_leader_unique_when_tie() -> None:
    """并列最高板多只时，仅强度最高者为总龙头，其余降板块龙头（不出现多个总龙头）。"""

    strong = _strong_leader()
    peer = _strong_leader()
    peer["ts_code"] = "300888.SZ"
    peer["name"] = "次龙头"
    peer["seal_ratio_pct"] = 3.0
    peer["first_limit_time"] = "11:00:00"
    peer["selection"] = {"theme_role": "前排"}
    results = score_stocks([strong, peer], scoring_version=_VER)
    leaders = [r for r in results if r.role_tags and r.role_tags[0] == ROLE_MAIN_LEADER]
    assert len(leaders) == 1
    assert leaders[0].leader_strength_score == max(r.leader_strength_score for r in results)


def test_recognition_subscore_nested_dict_not_strong_dominant():
    """评审 P1#6：score_detail 嵌套 dict 时，按四维强弱均值分档，不再'任一维强即满分'。"""
    from app.services.limit_up_leader_scoring_service import _recognition_subscore

    # 仅一维强、三维弱 → 弱档 0.3（原实现会因 str(dict) 含'强'判 0.9）
    one_strong = {"selection": {"score_detail": {
        "theme_position": "强", "seal_quality": "弱",
        "capital_signal": "弱", "promotion_potential": "弱"}}}
    assert _recognition_subscore(one_strong) == 0.3
    # 全强 → 强档 0.9
    all_strong = {"selection": {"score_detail": {
        "a": "强", "b": "强", "c": "强", "d": "强"}}}
    assert _recognition_subscore(all_strong) == 0.9
    # 二中二弱 → avg=0.25 → 弱档 0.3
    mid_weak = {"selection": {"score_detail": {
        "a": "中", "b": "中", "c": "弱", "d": "弱"}}}
    assert _recognition_subscore(mid_weak) == 0.3
    # 字符串兜底兼容：含'强' → 0.9（保留历史粗口径）
    assert _recognition_subscore({"selection": {"score_detail": "强势"}}) == 0.9
