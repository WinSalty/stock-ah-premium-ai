"""信号侧空仓闸门（确定性风控前置，非 LLM）。

业务意图：用 T 日盘后已算好的市场情绪数值（_market_emotion / _emotion_cycle_metrics），
    经固定阈值表先判硬否决（极端弱市/混沌→空仓），未否决再映射六档情绪周期 sentiment_cycle，
    再映射三档可参与状态 market_state（空仓/谨慎参与/参与）与缺省 action，决定 T+1 是否开新仓。
强约束：
    - 确定性可复算（同输入同输出，无随机/无 LLM），是闭环归因"空仓日反事实回放"的前提；
    - 输入全部为 T 日盘后已知量，不得用 T+1 数据（否则未来函数）；
    - 阈值版本固化 SENTIMENT_GATE_THRESHOLD_VERSION，阈值变更须进版本号；
    - 六档→三档映射单调一致（弱档不可比强档更可参与），导入期断言 + 单测双重保证；
    - 空仓 ⇒ action=放弃；只关"开新仓"，不关平仓（持仓卖出不受闸门影响，由 QMT 侧处理）。
口径说明：v1 输入为全市场盘后聚合指标，硬否决用保守(主板)阈值作用于全市场率；
    创业板单列阈值预留，待情绪指标能按板拆分后启用。

落表映射（阶段3 limit_up_selected_stock 实际列）：sentiment_cycle→sentiment_cycle 列(六档)，
    market_state→market_state 列(三档)，action→action 列；threshold_version/gate_reasons 由阶段7
    收口折叠进行级 JSON（表无独立列）。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 阈值表版本：任一阈值数值变更必须进版本号，复盘据此区分"口径漂移 vs 行情变化"。
SENTIMENT_GATE_THRESHOLD_VERSION = "gate-v1"

# 六档情绪周期（元组顺序即弱→强强度序，单调性断言依赖此序）。
CYCLE_ICE = "冰点"
CYCLE_RECEDE = "退潮"
CYCLE_DIVERGE = "分歧"
CYCLE_START = "启动"
CYCLE_FERMENT = "发酵"
CYCLE_CLIMAX = "高潮"
SENTIMENT_CYCLES = (
    CYCLE_ICE,
    CYCLE_RECEDE,
    CYCLE_DIVERGE,
    CYCLE_START,
    CYCLE_FERMENT,
    CYCLE_CLIMAX,
)

# 三档可参与状态。
STATE_EMPTY = "空仓"
STATE_CAUTION = "谨慎参与"
STATE_PARTICIPATE = "参与"
MARKET_STATES = (STATE_EMPTY, STATE_CAUTION, STATE_PARTICIPATE)

# 顶层缺省 action（"放弃"为空仓档顶层档；行级另有"重点/谨慎/放弃观察"三档）。
ACTION_ABANDON = "放弃"
ACTION_GIVE_UP_WATCH = "放弃观察"
ACTION_CAUTION_WATCH = "谨慎观察"
ACTION_FOCUS_WATCH = "重点观察"
ACTIONS = (ACTION_ABANDON, ACTION_GIVE_UP_WATCH, ACTION_CAUTION_WATCH, ACTION_FOCUS_WATCH)

# 六档 → 三档 固定映射（单调一致，导入期断言）。
_CYCLE_TO_STATE: dict[str, str] = {
    CYCLE_ICE: STATE_EMPTY,
    CYCLE_RECEDE: STATE_EMPTY,
    CYCLE_DIVERGE: STATE_CAUTION,
    CYCLE_START: STATE_CAUTION,
    CYCLE_FERMENT: STATE_PARTICIPATE,
    CYCLE_CLIMAX: STATE_PARTICIPATE,
}
# 三档 → 顶层缺省 action。
_STATE_TO_ACTION: dict[str, str] = {
    STATE_EMPTY: ACTION_ABANDON,
    STATE_CAUTION: ACTION_CAUTION_WATCH,
    STATE_PARTICIPATE: ACTION_FOCUS_WATCH,
}
_STATE_RANK: dict[str, int] = {STATE_EMPTY: 0, STATE_CAUTION: 1, STATE_PARTICIPATE: 2}


def _assert_state_monotonic() -> None:
    """导入期断言：沿 SENTIMENT_CYCLES 弱→强序，可参与度 state_rank 必须非递减。"""

    ranks = [_STATE_RANK[_CYCLE_TO_STATE[c]] for c in SENTIMENT_CYCLES]
    # 相邻成对比较（两序列差 1，故 strict=False；非等长不可用 strict=True）
    for prev, cur in zip(ranks, ranks[1:], strict=False):
        if cur < prev:
            raise ValueError("空仓闸门 cycle→state 映射违背单调一致约束")


_assert_state_monotonic()


@dataclass(frozen=True)
class GateThresholds:
    """主板(保守)+创业板(预留)分列阈值；默认值即固化占位表(TBD 回测对账后定稿)。"""

    # 硬否决阈值（默认对齐 config.limit_up_gate_*）
    broken_rate_veto: float = 45.0  # 炸板率%≥ 该值→空仓
    limit_down_veto: int = 30  # 跌停家数≥ 该值→空仓
    premium_veto: float = -3.0  # 隔日溢价%≤ 该值→空仓
    limit_up_count_veto: int = 15  # 涨停家数≤ 该值→空仓(枯竭)
    advance_1_2_veto: float = 10.0  # 1进2 率%≤ 该值(且分母够)→空仓(断链)
    advance_min_denom: int = 10  # 晋级率分母≥ 该值才作为否决证据(防小样本误杀)
    # 创业板单列(预留，待按板拆分指标后启用)
    broken_rate_veto_gem: float = 55.0
    premium_veto_gem: float = -4.0
    # 六档分类软阈值
    climax_chain: int = 6  # 高潮：最高板≥
    climax_premium: float = 3.0  # 高潮：隔日溢价%≥
    ferment_advance_1_2: float = 40.0  # 发酵：1进2 率%≥
    recede_broken: float = 35.0  # 退潮：炸板率%≥（且溢价<0）
    diverge_broken: float = 25.0  # 分歧：炸板率%≥（且最高板掉头）
    ice_limit_up_count: int = 25  # 冰点：涨停家数≤（且溢价≤0）

    @classmethod
    def from_settings(cls, settings: Any) -> GateThresholds:
        """从 config.limit_up_gate_* 构建硬否决阈值；六档软阈值用默认(暂未入 config)。"""

        return cls(
            broken_rate_veto=settings.limit_up_gate_broken_rate_veto,
            limit_down_veto=settings.limit_up_gate_limit_down_veto,
            premium_veto=settings.limit_up_gate_premium_veto,
            limit_up_count_veto=settings.limit_up_gate_limit_up_count_veto,
            advance_1_2_veto=settings.limit_up_gate_advance_1_2_veto,
            advance_min_denom=settings.limit_up_gate_advance_min_denom,
        )


@dataclass(frozen=True)
class GateDecision:
    """闸门判定产物：可序列化落 limit_up_selected_stock 顶层与每行。"""

    sentiment_cycle: str
    market_state: str
    action: str
    threshold_version: str
    gate_reasons: list[str]
    metrics_snapshot: dict[str, Any]


def map_market_state(cycle: str) -> str:
    """六档 → 三档（单调一致）；非法档抛 ValueError。"""

    if cycle not in _CYCLE_TO_STATE:
        raise ValueError(f"未知 sentiment_cycle: {cycle!r}")
    return _CYCLE_TO_STATE[cycle]


def resolve_action_for_state(market_state: str) -> str:
    """三档 → 顶层缺省 action；非法档抛 ValueError。"""

    if market_state not in _STATE_TO_ACTION:
        raise ValueError(f"未知 market_state: {market_state!r}")
    return _STATE_TO_ACTION[market_state]


def _num(value: Any, default: float = 0.0) -> float:
    """安全转 float；None/非数→default。"""

    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hcc_change_scalar(value: Any) -> Any:
    """抽取「最高板变化」标量（评审 P0-B4）。

    最高板变化的生产者返回 dict{today, previous, change}；闸门分类只需要其中的升降幅 change 标量。
    口径：
    - dict → 取 change（缺 change 键则 None，由下游缺测口径兜底）；
    - 标量/None → 原样返回（兼容历史可能直接给标量 change 的调用方）。
    这样 _num 拿到的恒为标量，hcc 不再被静默归零，「最高板升/降」约束才能真正参与高潮/发酵/分歧判定。
    """
    if isinstance(value, dict):
        return value.get("change")
    return value


def classify_sentiment_cycle(
    metrics: dict[str, Any], thresholds: GateThresholds
) -> tuple[str, list[str]]:
    """无硬否决时的六档分类（确定性，按强度优先短路）。返回 (cycle, reasons)。

    边界：avg 溢价为 None 视为中性(0)，晋级率分母为 0/None 视为无信息。
    """

    luc = _num(metrics.get("limit_up_count"))
    broken = metrics.get("broken_board_rate_pct")
    broken_v = _num(broken, default=-1.0)  # -1 表示未知，不触发 broken 相关分类
    hc = _num(metrics.get("highest_chain"))
    hcc = _num(metrics.get("highest_chain_change"))
    prem_raw = metrics.get("prev_premium_avg_pct_chg")
    prem = _num(prem_raw, default=0.0)
    adv = _num(metrics.get("adv_1_2_rate"))

    th = thresholds
    # 1) 高潮：高度板兑现 + 情绪顶
    if hc >= th.climax_chain and hcc >= 0 and prem >= th.climax_premium:
        return CYCLE_CLIMAX, ["climax_high_chain"]
    # 2) 发酵：接力顺畅 + 赚钱效应明显 + 高度不掉头
    if adv >= th.ferment_advance_1_2 and prem > 0 and hcc >= 0:
        return CYCLE_FERMENT, ["ferment_advance_healthy"]
    # 3) 退潮：炸板高 + 亏钱效应
    if broken_v >= th.recede_broken and prem < 0:
        return CYCLE_RECEDE, ["recede_broken_premium_negative"]
    # 4) 分歧：炸板抬升 + 高度掉头（溢价未深跌）
    if broken_v >= th.diverge_broken and hcc <= 0:
        return CYCLE_DIVERGE, ["diverge_broken_up_chain_down"]
    # 5) 冰点：涨停枯竭 + 无赚钱效应
    if luc <= th.ice_limit_up_count and prem <= 0:
        return CYCLE_ICE, ["ice_low_limit_up"]
    # 6) 启动：冰点后回暖（溢价转正，未强到发酵）
    if prem > 0:
        return CYCLE_START, ["start_premium_positive"]
    # 兜底：混合态偏保守取分歧
    return CYCLE_DIVERGE, ["fallback_diverge"]


def _build_decision(
    cycle: str, metrics: dict[str, Any], reasons: list[str]
) -> GateDecision:
    """合成判定并执行 4.5 一致性断言（违背抛 ValueError，禁止静默放行）。"""

    state = map_market_state(cycle)
    action = resolve_action_for_state(state)
    if cycle not in SENTIMENT_CYCLES:
        raise ValueError(f"非法 sentiment_cycle: {cycle!r}")
    if state not in MARKET_STATES:
        raise ValueError(f"非法 market_state: {state!r}")
    if action not in ACTIONS:
        raise ValueError(f"非法 action: {action!r}")
    # 空仓 ⇒ 顶层 action=放弃 且 cycle∈{冰点,退潮}
    if state == STATE_EMPTY and not (
        action == ACTION_ABANDON and cycle in (CYCLE_ICE, CYCLE_RECEDE)
    ):
        raise ValueError("空仓档一致性断言失败：action 必为放弃且 cycle∈{冰点,退潮}")
    return GateDecision(
        sentiment_cycle=cycle,
        market_state=state,
        action=action,
        threshold_version=SENTIMENT_GATE_THRESHOLD_VERSION,
        gate_reasons=reasons,
        metrics_snapshot=dict(metrics),
    )


def resolve_gate(
    metrics: dict[str, Any], *, thresholds: GateThresholds | None = None
) -> GateDecision:
    """闸门主入口：先硬否决（命中即空仓），未命中再六档分类→三档→action，最后一致性断言。

    metrics 期望键：limit_up_count / broken_board_rate_pct / limit_down_count / highest_chain /
        highest_chain_change / prev_premium_avg_pct_chg / adv_1_2_rate / adv_1_2_denom。
    """

    th = thresholds or GateThresholds()
    reasons: list[str] = []

    luc = _num(metrics.get("limit_up_count"))
    broken = metrics.get("broken_board_rate_pct")
    ld = _num(metrics.get("limit_down_count"))
    hc = _num(metrics.get("highest_chain"))
    prem_raw = metrics.get("prev_premium_avg_pct_chg")
    prem_known = prem_raw is not None
    if not prem_known:
        reasons.append("premium_unknown")
    adv = metrics.get("adv_1_2_rate")
    adv_denom = metrics.get("adv_1_2_denom")

    # --- 硬否决（OR，命中即空仓）---
    veto: list[str] = []
    if broken is not None and _num(broken) >= th.broken_rate_veto:
        veto.append("broken_board_rate_high")
    if ld >= th.limit_down_veto:
        veto.append("limit_down_high")
    if prem_known and _num(prem_raw) <= th.premium_veto:
        veto.append("prev_premium_deep_negative")
    if luc <= th.limit_up_count_veto:
        veto.append("limit_up_count_exhausted")
    # 晋级率断链：须分母≥阈值(防小样本/新股日误杀)
    if (
        adv is not None
        and adv_denom is not None
        and _num(adv_denom) >= th.advance_min_denom
        and _num(adv) <= th.advance_1_2_veto
    ):
        veto.append("advance_chain_broken")

    if veto:
        reasons.extend(veto)
        # 冰点 vs 退潮细分：仅当"涨停枯竭 + 无连板(hc≤2) + 无溢价深跌/跌停恐慌"时判冰点，
        # 其余(含炸板主导、溢价/跌停主导、或枯竭但仍有高板)统一判退潮（对齐 §4.7 注口径）。
        ice_dominant = (
            "limit_up_count_exhausted" in veto
            and hc <= 2
            and not any(
                v in veto for v in ("prev_premium_deep_negative", "limit_down_high")
            )
        )
        cycle = CYCLE_ICE if ice_dominant else CYCLE_RECEDE
        return _build_decision(cycle, metrics, reasons)

    # --- 无否决：六档分类 ---
    cycle, cls_reasons = classify_sentiment_cycle(metrics, th)
    reasons.extend(cls_reasons)
    return _build_decision(cycle, metrics, reasons)


def flatten_gate_inputs(market_emotion: dict[str, Any]) -> dict[str, Any]:
    """从 _market_emotion 产物(含内嵌 emotion_cycle)抽取闸门所需九字段为扁平 dict。

    防御式取键：emotion_cycle / advancement / prev_limit_up_premium 结构缺失时给 None，
    由 resolve_gate 的缺测口径兜底。实际键名以 _emotion_cycle_metrics 产物为准，
    阶段7 接入时对真实 context 校验。
    """

    em = market_emotion or {}
    ec = em.get("emotion_cycle") if isinstance(em.get("emotion_cycle"), dict) else {}
    prem = (
        ec.get("prev_limit_up_premium")
        if isinstance(ec.get("prev_limit_up_premium"), dict)
        else {}
    )
    adv = ec.get("advancement") if isinstance(ec.get("advancement"), dict) else {}
    adv_1_2 = adv.get("1进2") if isinstance(adv.get("1进2"), dict) else {}
    return {
        "limit_up_count": em.get("limit_up_count"),
        "broken_board_rate_pct": ec.get("broken_board_rate_pct"),
        "limit_down_count": em.get("limit_down_count"),
        "highest_chain": em.get("highest_chain"),
        # 评审 P0-B4 修复：highest_chain_change 的生产者(_highest_chain_change)返回的是
        # dict{today, previous, change}，原实现把整个 dict 透传给下游 _num → float(dict) 抛错被吞 →
        # 恒归 0.0，使「高潮/发酵 hcc>=0、分歧 hcc<=0」的最高板升降约束全部失效（最高板掉头仍可判发酵/高潮）。
        # 这里显式抽取标量 change；对 dict / 标量 两种形态都防御（兼容历史可能直接给标量的口径）。
        "highest_chain_change": _hcc_change_scalar(ec.get("highest_chain_change")),
        "prev_premium_avg_pct_chg": prem.get("avg_pct_chg"),
        "adv_1_2_rate": adv_1_2.get("rate_pct"),
        # 分母键名在不同口径下可能为 denom/denominator/base/prev_count，取首个【非 None】命中
        # （用 next-非None 而非 or，避免合法 denom=0 被 falsy 吞掉而丢失"分母为0=无信息"语义）
        "adv_1_2_denom": next(
            (
                v
                for v in (
                    adv_1_2.get("denom"),
                    adv_1_2.get("denominator"),
                    adv_1_2.get("base"),
                    adv_1_2.get("prev_count"),
                )
                if v is not None
            ),
            None,
        ),
    }
