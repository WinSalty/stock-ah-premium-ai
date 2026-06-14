"""龙头战法增强层（确定性后处理层，非 LLM）。

业务意图：在多阶段 LLM 流水线产出 selected_*_stocks 之后、报告 READY 之前，对每只入选股
    做一次纯规则计算，产出"龙头强度数值分 + 各维度子分 + 角色 + 战法/形态/动作 + 可成交性"，
    供 QMT 闭环复盘按强度/角色/战法分组归因。
设计取向：
    - 纯函数风格，只依赖入参（compact 股票行 dict + 同日候选集），不持有 DB/LLM/Tushare 客户端，
      便于单测与回测离线复用；
    - 六维子分先各自归一到 [0,1]（按【板宽】分形态：主板 10cm / 创业板 20cm，分布差异大不可混算），
      再用可插拔聚合器（v1 线性，权重 TBD 由回测校准）合成 0-100 分；
    - 缺测值（open_times/bid_*/cyq 等真实为 None）按"中性偏保守"处理并在 detail 留痕，
      绝不把 None 当 0 抬分。
口径对齐落表（阶段3 limit_up_selected_stock 实际列）：
    leader_strength_score → 同名列；各维子分/分位/置信/imputed/version → strength_dim_json；
    主角色+候选 → role_tags(list)；strategy_family/setup/action → 同名列；
    可成交性 → tradable_flag(TRADABLE/WATCH)。
    （阶段3 表用 strength_dim_json/role_tags，本层把 pctl/role_confidence/role_text 等
    折叠进 strength_dim_json，不另加列。）

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

# 板宽分形态：创业板 20cm、主板 10cm（由 ts_code 前缀可靠推断，不依赖噪声字段 limit_type）。
_GEM_PREFIXES = frozenset({"300", "301"})

# v1 线性聚合权重（占位，TBD 由回测校准；五正一负，position 为"安全度"正向等价于位置风险负向）。
WEIGHTS_V1: dict[str, float] = {
    "seal": 0.25,
    "theme": 0.20,
    "height": 0.15,
    "money": 0.15,
    "position": 0.15,
    "recognition": 0.10,
}

# 角色枚举（中军字面 MID_ARMY 暂定，文案统一后再 bump version 迁移）。
ROLE_MAIN_LEADER = "MAIN_LEADER"
ROLE_SECTOR_LEADER = "SECTOR_LEADER"
ROLE_MID_ARMY = "MID_ARMY"
ROLE_ASSIST = "ASSIST"
ROLE_STRAGGLER = "STRAGGLER"

# 战法族中文映射（setup 标签用）。
_STRATEGY_CN = {"DABAN": "打板", "BANLU": "半路", "DIXI": "低吸"}
# 操作档：与阶段3 落表列 action 及 LLM 投资建议分层【同口径中文】（重点/谨慎/放弃观察），
# 便于报告/建议/信号三处口径一致与交叉核对，不另造英文枚举。
ACTION_FOCUS = "重点观察"
ACTION_CAUTION = "谨慎观察"
ACTION_GIVE_UP = "放弃观察"


@dataclass(frozen=True)
class LeaderScore:
    """单只票的龙头战法增强结果（映射到 limit_up_selected_stock 的本层产出列）。"""

    leader_strength_score: Decimal  # 0-100 综合分
    strength_dim_json: dict[str, Any]  # 六维子分 + 分位 + 角色置信/候选 + imputed 痕迹 + version
    role_tags: list[str]  # 主角色在首位，后接候选角色
    strategy_family: str  # DABAN/BANLU/DIXI
    setup: str  # 形态组合标签
    action: str  # 重点观察/谨慎观察/放弃观察（同阶段3 表列与 LLM 分层口径）
    tradable_flag: str  # TRADABLE 可参与 / WATCH 看得到买不进（一字/秒封）


@dataclass
class ScoringContext:
    """同日候选集派生的打分上下文（分形态分布 + 当日最高板）。"""

    # 按板宽分组的字段升序分布，用于分位归一
    seal_dist: dict[str, list[float]] = field(default_factory=dict)
    amount_ratio_dist: dict[str, list[float]] = field(default_factory=dict)
    first_time_dist: dict[str, list[int]] = field(default_factory=dict)
    max_board_level: int = 1
    # 题材 → 该题材内最高连板高度，用于板块龙头判定
    theme_max_board: dict[str, int] = field(default_factory=dict)


def board_width(ts_code: str) -> str:
    """按代码前缀返回板宽：创业板 20cm，主板 10cm（北交/科创已被 universe 排除）。"""

    return "20cm" if (ts_code or "")[:3] in _GEM_PREFIXES else "10cm"


def _first_limit_seconds(raw: str | None) -> int | None:
    """首封时间 'HH:MM:SS' → 距 09:30 的秒数（越小越早越强）；非法/缺失返回 None。"""

    if not raw or not isinstance(raw, str):
        return None
    parts = raw.split(":")
    if len(parts) < 2:
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return (hh * 3600 + mm * 60 + ss) - (9 * 3600 + 30 * 60)


def _pct_rank(value: float | None, sorted_values: list[float]) -> float | None:
    """value 在升序分布中的分位 [0,1]（越大分位越高）；缺失或空分布返回 None。"""

    if value is None or not sorted_values:
        return None
    idx = bisect.bisect_right(sorted_values, value)
    return idx / len(sorted_values)


def _as_float(value: Any) -> float | None:
    """安全转 float；None/非数返回 None（区分真实缺失与 0）。"""

    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _technical(row: dict[str, Any]) -> dict[str, Any]:
    tech = row.get("technical")
    return tech if isinstance(tech, dict) else {}


def build_scoring_context(rows: list[dict[str, Any]]) -> ScoringContext:
    """从同日候选集构建分形态分布与当日最高板（分位归一的基准）。

    说明：为分位稳定，调用方应尽量传入当日较大候选集（如全涨停池或全 focus 集）。
    """

    ctx = ScoringContext()
    seal: dict[str, list[float]] = {"10cm": [], "20cm": []}
    amt: dict[str, list[float]] = {"10cm": [], "20cm": []}
    ftime: dict[str, list[int]] = {"10cm": [], "20cm": []}
    for row in rows:
        width = board_width(row.get("ts_code", ""))
        sr = _as_float(row.get("seal_ratio_pct"))
        if sr is not None:
            seal[width].append(sr)
        ar = _as_float(_technical(row).get("amount_ratio_5d"))
        if ar is not None:
            amt[width].append(ar)
        ft = _first_limit_seconds(row.get("first_limit_time"))
        if ft is not None:
            ftime[width].append(ft)
        bl = row.get("board_level")
        if isinstance(bl, int) and bl > ctx.max_board_level:
            ctx.max_board_level = bl
        theme = row.get("theme") or row.get("limit_up_reason")
        if theme and isinstance(bl, int):
            ctx.theme_max_board[theme] = max(ctx.theme_max_board.get(theme, 0), bl)
    for d in (seal, amt, ftime):
        for w in d:
            d[w].sort()
    ctx.seal_dist = seal
    ctx.amount_ratio_dist = amt
    ctx.first_time_dist = ftime
    return ctx


# ---------------- 六维子分（全部归一到 [0,1]，缺测在 detail 留痕） ----------------


def _seal_quality_subscore(row, width, ctx, detail) -> float:
    """① 封板质量：封流比(分位) + 首封时间(越早越好) + 开板次数(越少越好)。"""

    parts: list[tuple[float, float]] = []  # (子项分, 权重)
    sr = _as_float(row.get("seal_ratio_pct"))
    sr_pct = _pct_rank(sr, ctx.seal_dist.get(width, []))
    if sr_pct is None:
        detail["seal_ratio_imputed"] = True
        parts.append((0.5, 0.5))  # 中性
    else:
        parts.append((sr_pct, 0.5))
    ft = _first_limit_seconds(row.get("first_limit_time"))
    ft_pct = _pct_rank(ft, ctx.first_time_dist.get(width, []))
    if ft_pct is None:
        parts.append((0.5, 0.3))
    else:
        parts.append((1.0 - ft_pct, 0.3))  # 越早(秒数小,分位低)→分越高
    open_times = row.get("open_times")
    if open_times is None:
        detail["open_times_imputed"] = True
        parts.append((0.5, 0.2))  # 真实缺测→中性，绝不当 0
    else:
        ot = _as_float(open_times) or 0.0
        parts.append((1.0 / (1.0 + ot), 0.2))  # 0 次=1.0，随次数衰减
    return sum(s * w for s, w in parts) / sum(w for _, w in parts)


def _theme_ladder_subscore(row, ctx, detail) -> float:
    """② 题材梯队：承接 LLM 角色枚举 + 该票所属题材的梯队强度。"""

    selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
    role_hint = f"{selection.get('theme_role', '')}{selection.get('leader_role', '')}"
    base = 0.5
    if any(k in role_hint for k in ("龙头", "空间板")):
        base = 0.9
    elif "前排" in role_hint:
        base = 0.7
    elif "跟风" in role_hint:
        base = 0.35
    # 叠加题材梯队完整度：该票所属题材最高板越高，梯队越强
    theme = row.get("theme") or row.get("limit_up_reason")
    theme_top = ctx.theme_max_board.get(theme, 1) if theme else 1
    ladder = min(theme_top / max(ctx.max_board_level, 1), 1.0)
    return min(0.7 * base + 0.3 * ladder, 1.0)


def _height_subscore(row, ctx) -> float:
    """③ 相对高度：对当日全市场最高板归一（首板低基准、空间板高基准）。"""

    bl = row.get("board_level")
    if not isinstance(bl, int) or bl < 1:
        return 0.3
    return min(bl / max(ctx.max_board_level, 1), 1.0)


def _money_subscore(row, width, ctx, detail) -> float:
    """④ 资金：量比(分位) + 换手倒 U（过低缩量、过高分歧都不满分）。

    v1 暂不消费竞价承接信号 bid_*（真实数据多为 None，详见 §3.4 第2条）；
    待竞价数据补齐后再加竞价承接子项并标 bid_imputed，当前不把 None 当 0。
    """

    ar = _as_float(_technical(row).get("amount_ratio_5d"))
    ar_pct = _pct_rank(ar, ctx.amount_ratio_dist.get(width, []))
    if ar_pct is None:
        detail["amount_ratio_imputed"] = True
        ar_pct = 0.5
    tr = _as_float(row.get("turnover_rate"))
    if tr is None:
        detail["turnover_imputed"] = True
        turn_score = 0.5
    else:
        # 倒 U：健康换手区间(经验 5%-25%)给高分，过低缩量/过高天量都降分
        if tr <= 0:
            turn_score = 0.2
        elif tr < 5:
            turn_score = 0.4 + 0.6 * (tr / 5)
        elif tr <= 25:
            turn_score = 1.0
        else:
            turn_score = max(0.3, 1.0 - (tr - 25) / 50)
    return 0.6 * ar_pct + 0.4 * turn_score


def _position_safety_subscore(row, ctx, detail) -> float:
    """⑤ 位置筹码（安全度，越安全越高；等价于位置风险负向）：上方套牢越重/位置越高→越低。"""

    selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
    cyq = selection.get("cyq_summary") if isinstance(selection.get("cyq_summary"), dict) else {}
    if not cyq:
        cyq = row.get("cyq_summary") if isinstance(row.get("cyq_summary"), dict) else {}
    upper = _as_float(cyq.get("upper_chip_pressure_pct"))
    if upper is None:
        detail["chip_imputed"] = True
        chip_safety = 0.5  # 缺筹码→中性偏保守，不奖励也不重罚
    else:
        chip_safety = max(0.0, 1.0 - min(upper, 100.0) / 100.0)  # 上方压力越大越不安全
    # 位置：相对高度越高位置越危险（与③高度的"奖励"形成对冲，共同建模高位风险）
    bl = row.get("board_level") if isinstance(row.get("board_level"), int) else 1
    height_ratio = min(bl / max(ctx.max_board_level, 1), 1.0)
    pos_safety = 1.0 - 0.5 * height_ratio
    return 0.6 * chip_safety + 0.4 * pos_safety


# 子维度强弱 → 分值映射（评审 P1#6）：强=1.0 / 中=0.5 / 弱=0.0。
# dict 顺序即字符串兜底口径下的判定优先级（保留"强"优先，与历史一致）。
_STRENGTH_VALUE = {"强": 1.0, "中": 0.5, "弱": 0.0}


def _score_detail_strength(detail) -> float | None:
    """把 score_detail 的强弱映射到 [0,1]（评审 P1#6）。

    score_detail 的生产契约是【嵌套 dict】：{theme_position, seal_quality, capital_signal,
    promotion_potential}，各取 强/中/弱。原实现对整个 dict 做 str() 后判「强 in 字符串」，
    str(dict) 几乎必同时含 强/中/弱 三字 → 只要任一子维度为'强'即满分(强恒胜)，丧失区分度。
    这里按四子维度强弱取均值（强=1/中=0.5/弱=0），真实反映"几维强、几维弱"。
    兼容：
    - 嵌套 dict（生产）：取所有可解析子维度值的均值；
    - 字符串（历史/兜底夹具）：含 强→1.0 / 中→0.5 / 弱→0.0（取首个命中，保留旧粗口径语义）；
    - 其它/空 → None（无可解析强弱信息）。
    """
    if isinstance(detail, dict):
        vals = [
            _STRENGTH_VALUE[v]
            for v in detail.values()
            if isinstance(v, str) and v in _STRENGTH_VALUE
        ]
        return sum(vals) / len(vals) if vals else None
    if isinstance(detail, str) and detail:
        for k, v in _STRENGTH_VALUE.items():
            if k in detail:
                return v
    return None


def _recognition_subscore(row) -> float:
    """⑥ 辨识度：承接 LLM 强中弱评级与角色，市场记忆点/共识（评审 P1#6 修复嵌套 dict 解析）。

    保留原 if/elif 结构与输出档位(0.9/0.6/0.3/0.5)及「强档 OR 强角色 → 0.9」的优先级，
    仅把「detail 是否强/中/弱」由对整 dict 的 str() 子串判定，改为按四子维度强弱均值分档：
    avg>=0.67→强、0.34<=avg<0.67→中、avg<0.34→弱。这样 {强,弱,弱,弱} 不再被判强(原会满分)。
    """
    selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
    role_hint = f"{selection.get('theme_role', '')}{selection.get('leader_role', '')}"

    avg = _score_detail_strength(selection.get("score_detail"))  # [0,1] 或 None
    detail_strong = avg is not None and avg >= 0.67
    detail_mid = avg is not None and 0.34 <= avg < 0.67
    detail_weak = avg is not None and avg < 0.34

    if detail_strong or any(k in role_hint for k in ("龙头", "空间板")):
        return 0.9
    if detail_mid or "前排" in role_hint:
        return 0.6
    if detail_weak or "跟风" in role_hint:
        return 0.3
    return 0.5


def _aggregate_linear(subscores: dict[str, float], weights: dict[str, float]) -> float:
    """v1 线性聚合（可插拔；v2 可换单调约束树/分桶，不动六维子分计算）。"""

    total_w = sum(weights.values())
    # 用 .get 兜底缺失子分键（提升可插拔聚合器健壮性：v2 自定义 weights 含未知键不致 KeyError）
    return sum(subscores.get(k, 0.5) * weights[k] for k in weights) / total_w if total_w else 0.0


def _tradable_flag(row, detail) -> str:
    """可成交性：确认一字/秒封(开盘即封死全天未开)→ WATCH 看得到买不进；否则 TRADABLE。

    一字判定强依赖 open_times/first_limit_time 真实性：仅在确证一字/秒封时标 WATCH；
    缺测在 detail 留痕由回测口径兜底，不乐观判可成交。
    """

    open_times = row.get("open_times")
    ft = _first_limit_seconds(row.get("first_limit_time"))
    ot = int(_as_float(open_times) or 0) if open_times is not None else None
    # 确认一字/秒封：开板次数真实为 0 且开盘 30 秒内封死
    if ot == 0 and ft is not None and ft <= 30:
        return "WATCH"
    if open_times is None and ft is not None and ft <= 5:
        # 缺开板次数但首封在开盘 5 秒内，疑似一字，保守标 WATCH 并留痕
        detail["tradable_suspect_yiziban"] = True
        return "WATCH"
    return "TRADABLE"


def _determine_role(row, ctx, strength_pctl) -> tuple[list[str], float, str | None]:
    """主角色 + 置信 + 候选；确定性优先 + LLM 佐证。"""

    bl = row.get("board_level") if isinstance(row.get("board_level"), int) else 1
    selection = row.get("selection") if isinstance(row.get("selection"), dict) else {}
    role_hint = f"{selection.get('theme_role', '')}{selection.get('leader_role', '')}"
    theme = row.get("theme") or row.get("limit_up_reason")
    theme_top = ctx.theme_max_board.get(theme, bl) if theme else bl
    candidates: list[tuple[str, float]] = []

    # 总龙头：当日最高板，且 LLM 含空间板/题材龙头佐证
    if bl >= ctx.max_board_level and ctx.max_board_level >= 2:
        conf = 0.9 if any(k in role_hint for k in ("空间板", "龙头")) else 0.6
        candidates.append((ROLE_MAIN_LEADER, conf))
    # 板块龙头：题材内最高板
    if theme and bl >= theme_top and bl >= 2:
        conf = 0.9 if any(k in role_hint for k in ("龙头", "前排")) else 0.6
        candidates.append((ROLE_SECTOR_LEADER, conf))
    # 卡位助攻：LLM 文本含卡位/助攻
    if any(k in role_hint for k in ("卡位", "助攻", "补涨")):
        candidates.append((ROLE_ASSIST, 0.5))
    # 跟风/弱：LLM 明确"跟风"标记 → 杂毛（不因小样本分位偏高而误判中军）
    if not candidates and "跟风" in role_hint:
        candidates.append((ROLE_STRAGGLER, 0.8))
    # 中军：非最高板但强度分位靠前
    if not candidates and strength_pctl is not None and strength_pctl >= 0.6:
        candidates.append((ROLE_MID_ARMY, 0.55))
    # 杂毛兜底：强度分位明显靠后
    if not candidates:
        conf = 0.8 if (strength_pctl is not None and strength_pctl < 0.4) else 0.4
        candidates.append((ROLE_STRAGGLER, conf))

    candidates.sort(key=lambda x: x[1], reverse=True)
    primary, primary_conf = candidates[0]
    role_text = selection.get("selection_reason") if primary == ROLE_ASSIST else None
    return [c for c, _ in candidates], primary_conf, role_text


def _strategy_and_action(
    row, score_0_100, position_safety, tradable_flag, detail
) -> tuple[str, str, str]:
    """战法族 strategy_family + 形态 setup + 操作档 action。"""

    bl = row.get("board_level") if isinstance(row.get("board_level"), int) else 1
    ft = _first_limit_seconds(row.get("first_limit_time"))
    open_times = row.get("open_times")
    # 战法族：早盘强封死→打板；高位连板次日多走低吸/龙回头；其余半路
    if ft is not None and ft <= 60 and (open_times is None or int(_as_float(open_times) or 0) == 0):
        strategy_family = "DABAN"
    elif bl >= 4:
        strategy_family = "DIXI"
    else:
        strategy_family = "BANLU"
    # 形态：战法 × 高度 组合
    height_tag = "首板" if bl <= 1 else ("连板" if bl <= 3 else "高位")
    setup = f"{height_tag}{_STRATEGY_CN[strategy_family]}"
    # 操作档：强度 + 位置安全 + 可成交性（中文档位，与阶段3 表列 action 同口径）
    if tradable_flag == "WATCH":
        action = ACTION_GIVE_UP if bl >= 5 else ACTION_CAUTION  # 一字买不进，高位放弃、其余谨慎
    elif score_0_100 >= 65 and position_safety >= 0.5:
        action = ACTION_FOCUS
    elif score_0_100 >= 45:
        action = ACTION_CAUTION
    else:
        action = ACTION_GIVE_UP
    return strategy_family, setup, action


def score_stock(
    row: dict[str, Any],
    ctx: ScoringContext,
    *,
    scoring_version: str,
    weights: dict[str, float] | None = None,
    strength_pctl: float | None = None,
) -> LeaderScore:
    """对单只票打分（需先 build_scoring_context 得到同日分布）。"""

    weights = weights or WEIGHTS_V1
    width = board_width(row.get("ts_code", ""))
    detail: dict[str, Any] = {"scoring_version": scoring_version, "board_width": width}

    subscores = {
        "seal": _seal_quality_subscore(row, width, ctx, detail),
        "theme": _theme_ladder_subscore(row, ctx, detail),
        "height": _height_subscore(row, ctx),
        "money": _money_subscore(row, width, ctx, detail),
        "position": _position_safety_subscore(row, ctx, detail),
        "recognition": _recognition_subscore(row),
    }
    detail["subscores"] = {k: round(v, 4) for k, v in subscores.items()}
    raw = _aggregate_linear(subscores, weights)
    score_0_100 = round(raw * 100, 2)
    detail["leader_strength_pctl"] = strength_pctl

    role_tags, role_conf, role_text = _determine_role(row, ctx, strength_pctl)
    detail["role_confidence"] = role_conf
    if role_text:
        detail["role_text"] = role_text

    tradable = _tradable_flag(row, detail)
    strategy_family, setup, action = _strategy_and_action(
        row, score_0_100, subscores["position"], tradable, detail
    )

    return LeaderScore(
        leader_strength_score=Decimal(str(score_0_100)),
        strength_dim_json=detail,
        role_tags=role_tags,
        strategy_family=strategy_family,
        setup=setup,
        action=action,
        tradable_flag=tradable,
    )


def score_stocks(
    rows: list[dict[str, Any]],
    *,
    scoring_version: str,
    weights: dict[str, float] | None = None,
) -> list[LeaderScore]:
    """对同日候选集整体打分：先建分布与分位，再逐票打分（分位用于角色判定）。

    返回顺序与入参 rows 一致。
    v1 强度分位仅按 board_width 分组；§3.2.4 的"同 board_level 段再细分"留待回测校准时引入。
    用法提示：为分位/题材梯队稳定，应传入当日较大候选集（如全涨停池），而非仅少量 selected。
    """

    if not rows:
        return []
    ctx = build_scoring_context(rows)
    # 先算原始强度分用于分位（同 board_width 内分位，跨日可比）
    raw_scores: list[float] = []
    width_of: list[str] = []
    for row in rows:
        width = board_width(row.get("ts_code", ""))
        width_of.append(width)
        detail: dict[str, Any] = {}
        subs = {
            "seal": _seal_quality_subscore(row, width, ctx, detail),
            "theme": _theme_ladder_subscore(row, ctx, detail),
            "height": _height_subscore(row, ctx),
            "money": _money_subscore(row, width, ctx, detail),
            "position": _position_safety_subscore(row, ctx, detail),
            "recognition": _recognition_subscore(row),
        }
        raw_scores.append(_aggregate_linear(subs, weights or WEIGHTS_V1))
    # 按 board_width 分组算分位
    grouped: dict[str, list[float]] = {}
    for w, s in zip(width_of, raw_scores, strict=True):
        grouped.setdefault(w, []).append(s)
    for w in grouped:
        grouped[w].sort()
    results: list[LeaderScore] = []
    for row, w, s in zip(rows, width_of, raw_scores, strict=True):
        pctl = _pct_rank(s, grouped[w])
        results.append(
            score_stock(
                row,
                ctx,
                scoring_version=scoring_version,
                weights=weights,
                strength_pctl=pctl,
            )
        )
    # 总龙头唯一化：并列最高板可能多只被判 MAIN_LEADER，仅保留强度最高者，
    # 其余降为板块龙头（避免同一日出现多个"总龙头"，对齐 §3.3 并列断头口径）。
    leader_idx = [
        i for i, r in enumerate(results) if r.role_tags and r.role_tags[0] == ROLE_MAIN_LEADER
    ]
    if len(leader_idx) > 1:
        top = max(leader_idx, key=lambda i: results[i].leader_strength_score)
        for i in leader_idx:
            if i == top:
                continue
            demoted = [t for t in results[i].role_tags if t != ROLE_MAIN_LEADER]
            if ROLE_SECTOR_LEADER not in demoted:
                demoted.insert(0, ROLE_SECTOR_LEADER)
            results[i].role_tags[:] = demoted  # 原地改 list（frozen dataclass 仅禁属性重赋值）
    return results
