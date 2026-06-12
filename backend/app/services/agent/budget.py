"""Agent 预算与单轮执行状态：迭代上限、材料字符预算、轮内工具配额。

口径（chat-agent-refactor-design-and-plan.md 3.1 / 3.2 / 3.9 节）：
- 轮内配额按工具计数强制，超限返回错误文本让模型自行调整策略，不中断循环；
- 材料预算先对单条工具结果截断，messages 总量超预算时从最早的 tool 消息压缩；
- LlmDailyLimitExceeded 自 llm_client 迁入本模块（设计 2.3），llm_client 反向引用。

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---- 单条工具结果的回填截断口径（设计 3.1"材料预算"）----
SQL_RESULT_MAX_ROWS = 60
SEARCH_SUMMARY_MAX_CHARS = 500
PAGE_TEXT_MAX_CHARS = 6000
PYTHON_STDOUT_MAX_CHARS = 8000
# 单条工具消息回填给模型的字符上限：防止单次超大结果直接挤爆上下文。
TOOL_MESSAGE_MAX_CHARS = 12000

# ---- 轮内工具调用配额（设计 3.2"执行约束"）----
# query_database 与 get_stock_data 共享"取数"配额组，避免模型在两者间来回刷次数。
# 取数组上限 16（2026-06-12 试用反馈两次上调：6→8→16，个股全景分析+出图场景
# 需要多视图取数；本地取数成本低，成本安全网由 LLM 日限额与迭代上限承担）。
DATA_QUOTA_GROUP = "data_fetch"
PER_TURN_TOOL_LIMITS: dict[str, int] = {
    "web_search": 3,
    "fetch_url": 3,
    "run_python": 3,
    "render_chart": 4,
    DATA_QUOTA_GROUP: 16,
}
# 工具名到配额组的映射：未列出的工具按工具名独立计数。
TOOL_QUOTA_GROUPS: dict[str, str] = {
    "query_database": DATA_QUOTA_GROUP,
    "get_stock_data": DATA_QUOTA_GROUP,
}

# 回填给模型的配额耗尽说明（模型据此调整策略）。
QUOTA_EXHAUSTED_MESSAGE = "本轮该工具配额已用尽，请基于已有材料继续，或改用其他工具。"
# 时间线上展示给用户的摘要：避免"配额"这类内部术语让用户困惑（试用反馈问题2）。
QUOTA_EXHAUSTED_SUMMARY = "本轮调用次数已达单轮上限，已基于已有数据继续"


class LlmDailyLimitExceeded(Exception):
    """LLM 项目级日调用限流异常。

    自 llm_service/llm_client 迁入（设计 2.3 删除边界）：作为引擎的预算口径之一
    统一定义在本模块，llm_client 与路由层从这里引用。

    创建日期：2026-05-05
    author: sunshengxian
    """


@dataclass
class ToolTraceItem:
    """单条工具执行轨迹：落库 tool_trace_json 与 done 事件共用的摘要结构。

    创建日期：2026-06-12
    author: claude
    """

    tool: str
    summary: str
    result_summary: str
    ok: bool
    elapsed_ms: float

    def to_payload(self) -> dict[str, Any]:
        """转为落库/下发共用的字典结构。

        创建日期：2026-06-12
        author: claude
        """

        return {
            "tool": self.tool,
            "summary": self.summary,
            "result_summary": self.result_summary,
            "ok": self.ok,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class TurnState:
    """单轮问答内共享的执行状态。

    持有：工具调用计数（按配额组）、已登记图表、工具轨迹、SQL/个股数据完整结果缓存
    （供 run_python 注入沙箱 data/ 目录）、前端透传的阈值推荐上下文。

    创建日期：2026-06-12
    author: claude
    """

    question_id: str = ""
    user_id: int | None = None
    session_id: int | None = None
    # 指标展示上下文：会话标题（问题截 48 字）与用户名，随 LlmCallTrace 落库。
    conversation_title: str | None = None
    user_name: str | None = None
    # 日限额豁免（admin 账户）：路由层按用户角色注入，随 trace 透传给 llm_client。
    llm_limit_exempt: bool = False
    # 配额组 -> 已用次数
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    # 本轮已登记图表 spec 列表（chart_id -> spec 字典，保序）
    charts: list[dict[str, Any]] = field(default_factory=list)
    # 工具轨迹摘要（落库与 done 事件共用）
    tool_trace: list[ToolTraceItem] = field(default_factory=list)
    # query_database 的完整结果缓存：[(序号, 用途, 完整行数组)]，供沙箱数据注入。
    sql_results: list[tuple[int, str, list[dict[str, Any]]]] = field(default_factory=list)
    # get_stock_data 的数据包缓存：[(ts_code, package, 内容字典)]
    stock_packages: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    # 前端透传的阈值推荐上下文（recommend_threshold 零参数工具的取数来源）。
    threshold_context: dict[str, Any] | None = None

    def quota_group(self, tool_name: str) -> str:
        """返回工具所属配额组：未显式分组的工具按自身名字独立计数。

        创建日期：2026-06-12
        author: claude
        """

        return TOOL_QUOTA_GROUPS.get(tool_name, tool_name)

    def remaining_quota(self, tool_name: str) -> int | None:
        """剩余配额：未配置上限的工具返回 None（不限）。

        创建日期：2026-06-12
        author: claude
        """

        group = self.quota_group(tool_name)
        limit = PER_TURN_TOOL_LIMITS.get(group)
        if limit is None:
            return None
        return max(0, limit - self.tool_call_counts.get(group, 0))

    def consume_quota(self, tool_name: str) -> bool:
        """尝试占用一次配额：成功返回 True；配额耗尽返回 False（调用方回填错误文本）。

        创建日期：2026-06-12
        author: claude
        """

        group = self.quota_group(tool_name)
        limit = PER_TURN_TOOL_LIMITS.get(group)
        used = self.tool_call_counts.get(group, 0)
        if limit is not None and used >= limit:
            return False
        self.tool_call_counts[group] = used + 1
        return True

    def next_chart_id(self) -> str:
        """轮内自增图表 id：c1/c2/...（设计 3.5 嵌入协议）。

        创建日期：2026-06-12
        author: claude
        """

        return f"c{len(self.charts) + 1}"


def truncate_text(text: str, max_chars: int, note: str = "（已截断）") -> str:
    """通用文本截断：超限时保留前段并附截断标记，让模型知道材料不完整。

    创建日期：2026-06-12
    author: claude
    """

    if len(text) <= max_chars:
        return text
    return text[:max_chars] + note


def compress_messages_for_budget(
    messages: list[dict[str, Any]],
    budget_chars: int,
) -> list[dict[str, Any]]:
    """messages 总字符超预算时，从最早的 tool 消息开始压缩为一行摘要。

    压缩只针对 role=tool 的消息（工具结果材料），不动 system/user/assistant，
    保证业务规则与对话语义完整；摘要保留工具名与原始长度便于模型自知材料缺失。
    返回新列表，不修改入参（引擎在每次迭代调用前做预算检查）。

    创建日期：2026-06-12
    author: claude
    """

    def total_chars(items: list[dict[str, Any]]) -> int:
        return sum(len(str(item.get("content") or "")) for item in items)

    if total_chars(messages) <= budget_chars:
        return messages
    compressed = [dict(item) for item in messages]
    for item in compressed:
        if total_chars(compressed) <= budget_chars:
            break
        if item.get("role") != "tool":
            continue
        content = str(item.get("content") or "")
        # 已经是摘要的跳过，避免重复压缩。
        if content.startswith("[已省略"):
            continue
        tool_name = item.get("name") or "tool"
        item["content"] = f"[已省略：{tool_name} 的结果原文 {len(content)} 字符，如需请重新调用]"
    return compressed
