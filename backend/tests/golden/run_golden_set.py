"""金标集跑批器：对问答引擎逐条执行金标用例并产出命中率报告。

设计口径（chat-agent-refactor-design-and-plan.md 第五节 / 第八节修订 10）：
- 依赖真实 LLM 调用并产生费用，不进 CI；由使用者在 dev 环境择机手动跑批。
- 全量 60+ 条用例 × 单轮多次外部调用会超过 llm_daily_call_limit 单日上限，
  因此必须支持 --category/--ids/--limit 子集采样与 --resume 断点续跑；
  命中日限额（LlmDailyLimitExceeded）时立即优雅中止并保留断点。
- 工具类断言（tools_any_of 等）只对 Agent 引擎有意义；对旧链路基线跑批记 n/a。
- 文本类断言只做宽松特征匹配，无法机判的项标 REVIEW 交人工复核，不直接判 FAIL。

用法（在 backend 目录、激活 .venv 后）：
    python tests/golden/run_golden_set.py --engine auto --limit 10
    python tests/golden/run_golden_set.py --category refusal,service_intro
    python tests/golden/run_golden_set.py --resume --report-tag baseline

创建日期：2026-06-12
author: claude
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GOLDEN_DIR = Path(__file__).resolve().parent
BACKEND_DIR = GOLDEN_DIR.parent.parent
# 默认报告输出目录：跑批产物属运行时数据，放 .runtime 不进 git；
# 需要归档的基线报告由使用者人工挑选后复制到 resources/doc/。
DEFAULT_REPORT_DIR = BACKEND_DIR.parent / ".runtime" / "golden-reports"

sys.path.insert(0, str(BACKEND_DIR))

# 拒答特征词：命中任意一个即认为模型执行了"拒答/越界"口径。
# 旧链路是固定文案（OUT_OF_SCOPE_MESSAGE），新引擎由提示词约束，因此用宽松特征集。
REFUSAL_MARKERS = (
    "仅支持",
    "只支持",
    "无法回答",
    "无法提供",
    "不能协助",
    "无法协助",
    "违法违规",
    "不在服务范围",
    "超出了本助手",
    "与投资分析无关",
    "请提问与投资",
    "暂不支持",
)
# 偏好澄清特征词：回答应在反问用户的风险偏好而不是直接荐股。
PREFERENCE_MARKERS = ("风险偏好", "保守型", "高收益型", "激进型")


def _now_east8() -> datetime:
    """统一东八区 naive 时间，与项目时间口径一致。

    创建日期：2026-06-12
    author: claude
    """

    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def load_cases(path: Path) -> list[dict[str, Any]]:
    """读取金标用例文件并返回 cases 列表。

    创建日期：2026-06-12
    author: claude
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["cases"]


def build_context(case: dict[str, Any], user_id: int) -> dict[str, Any]:
    """按用例构造引擎 context：注入用户、会话历史与前端透传上下文。

    历史消息直接经 conversation_history 注入而不真实落库，
    避免为铺垫历史额外消耗 LLM 调用。

    创建日期：2026-06-12
    author: claude
    """

    context: dict[str, Any] = {"user_id": user_id, "session_id": None}
    history = case.get("history") or []
    if history:
        context["conversation_history"] = history
    extra = case.get("context") or {}
    context.update(extra)
    return context


def run_case_legacy(db, settings, case: dict[str, Any], user_id: int) -> dict[str, Any]:
    """旧链路执行单条用例（旧链路已随阶段 1 S1-7 退役）。

    如需补跑旧链路基线：git checkout pre-agent-refactor 后在旧版本工作区执行
    `./scripts/run-golden-set.sh --engine legacy --report-tag baseline`。

    创建日期：2026-06-12
    author: claude
    """

    raise RuntimeError(
        "旧问答链路已退役（llm_service.py 已删除）。"
        "补跑基线请切换到 git tag pre-agent-refactor 后执行 --engine legacy。"
    )


def run_case_agent(db, settings, case: dict[str, Any], user_id: int) -> dict[str, Any]:
    """Agent 引擎执行单条用例：消费事件流，聚合回答文本与工具调用轨迹。

    创建日期：2026-06-12
    author: claude
    """

    from app.services.agent.engine import AgentEngine

    engine = AgentEngine(db, settings=settings)
    answer_parts: list[str] = []
    tools: list[str] = []
    charts = 0
    for event in engine.run(case["question"], build_context(case, user_id)):
        event_type = getattr(event, "type", None) or (
            event.get("type") if isinstance(event, dict) else None
        )
        payload = event if isinstance(event, dict) else event.__dict__
        if event_type == "tool_start":
            tools.append(str(payload.get("tool")))
        elif event_type == "chart":
            charts += 1
        elif event_type == "delta":
            answer_parts.append(str(payload.get("content") or ""))
        elif event_type in {"done", "error"}:
            # done/error 的 answer 字段是最终落库口径，优先采用。
            final = payload.get("answer")
            if final:
                answer_parts = [str(final)]
    return {"answer": "".join(answer_parts), "tools": tools, "charts": charts, "engine": "agent"}


def evaluate(case: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """对照 expect 评估单条结果：返回逐项 verdict 与整体 PASS/FAIL/REVIEW。

    机判原则：能客观判定的（拒答、关键词、工具集合）给 PASS/FAIL；
    答案质量类无法机判，整体不因此降级——失败项留给人工复核。

    创建日期：2026-06-12
    author: claude
    """

    expect = case.get("expect", {})
    answer = outcome.get("answer") or ""
    tools = outcome.get("tools") or []
    is_agent = outcome.get("engine") == "agent"
    checks: dict[str, str] = {}

    refused = any(marker in answer for marker in REFUSAL_MARKERS)
    if "answerable" in expect:
        if expect["answerable"]:
            checks["answerable"] = "FAIL" if refused or not answer.strip() else "PASS"
        else:
            checks["answerable"] = "PASS" if refused else "REVIEW"

    if "ask_preference" in expect:
        asked = any(marker in answer for marker in PREFERENCE_MARKERS) and "？" in answer
        if expect["ask_preference"]:
            checks["ask_preference"] = "PASS" if asked else "FAIL"
        else:
            # 不应反问：出现澄清特征且回答中没有任何推荐结论时判 FAIL。
            checks["ask_preference"] = "FAIL" if asked and len(answer) < 200 else "PASS"

    for key in ("tools_any_of", "tools_forbidden", "web_search", "chart"):
        if key not in expect:
            continue
        if not is_agent:
            checks[key] = "N/A"
            continue
        if key == "tools_any_of":
            checks[key] = "PASS" if set(expect[key]) & set(tools) else "FAIL"
        elif key == "tools_forbidden":
            hit = set(expect[key]) & set(tools)
            checks[key] = "FAIL" if hit else "PASS"
        elif key == "web_search":
            used = "web_search" in tools
            checks[key] = "PASS" if used == bool(expect[key]) else "FAIL"
        elif key == "chart":
            drew = (outcome.get("charts") or 0) > 0 or "{{chart:" in answer
            checks[key] = "PASS" if drew == bool(expect[key]) else "FAIL"

    if "answer_contains_any" in expect:
        hit = any(kw in answer for kw in expect["answer_contains_any"])
        checks["answer_contains_any"] = "PASS" if hit else "REVIEW"
    if "answer_must_not_contain" in expect:
        bad = [kw for kw in expect["answer_must_not_contain"] if kw in answer]
        checks["answer_must_not_contain"] = "FAIL" if bad else "PASS"
    if expect.get("risk_banner"):
        banner = any(kw in answer for kw in ("风险", "波动", "亏损"))
        checks["risk_banner"] = "PASS" if banner else "FAIL"

    if any(v == "FAIL" for v in checks.values()):
        overall = "FAIL"
    elif any(v == "REVIEW" for v in checks.values()):
        overall = "REVIEW"
    else:
        overall = "PASS"
    return {"overall": overall, "checks": checks}


def write_report(report_path: Path, results: list[dict[str, Any]], engine: str) -> None:
    """聚合结果生成 Markdown 报告：按类别统计命中率 + 逐条明细。

    创建日期：2026-06-12
    author: claude
    """

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_category.setdefault(item["category"], []).append(item)
    lines = [
        "# 金标集跑批报告",
        "",
        f"- 跑批时间：{_now_east8():%Y-%m-%d %H:%M:%S}（东八区）",
        f"- 引擎：{engine}",
        f"- 用例数：{len(results)}",
        "",
        "## 按类别命中率",
        "",
        "| 类别 | 用例数 | PASS | REVIEW | FAIL | ERROR |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for category in sorted(by_category):
        items = by_category[category]
        counts = {key: sum(1 for i in items if i["overall"] == key) for key in
                  ("PASS", "REVIEW", "FAIL", "ERROR")}
        lines.append(
            f"| {category} | {len(items)} | {counts['PASS']} | {counts['REVIEW']} "
            f"| {counts['FAIL']} | {counts['ERROR']} |"
        )
    lines += ["", "## 逐条明细", ""]
    for item in results:
        lines.append(f"### {item['id']}（{item['category']}）— {item['overall']}")
        lines.append("")
        lines.append(f"- 问题：{item['question']}")
        if item.get("tools"):
            lines.append(f"- 工具轨迹：{' → '.join(item['tools'])}")
        for check, verdict in (item.get("checks") or {}).items():
            lines.append(f"- {check}: {verdict}")
        if item.get("error"):
            lines.append(f"- 异常：{item['error']}")
        answer_preview = (item.get("answer") or "").replace("\n", " ")[:300]
        lines.append(f"- 回答摘录：{answer_preview}")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """跑批入口：解析参数、过滤用例、逐条执行并落盘断点与报告。

    创建日期：2026-06-12
    author: claude
    """

    parser = argparse.ArgumentParser(description="问答金标集跑批器")
    parser.add_argument("--engine", default="auto", choices=["auto", "legacy", "agent"],
                        help="auto 优先用 Agent 引擎，未就绪时回落旧链路")
    parser.add_argument("--category", default=None, help="逗号分隔的类别过滤")
    parser.add_argument("--ids", default=None, help="逗号分隔的用例 id 过滤")
    parser.add_argument("--limit", type=int, default=None, help="最多执行多少条（采样跑批）")
    parser.add_argument("--resume", action="store_true",
                        help="断点续跑：跳过 checkpoint 中已完成的用例")
    parser.add_argument("--report-tag", default=None, help="报告文件名后缀标记（如 baseline）")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--user-id", type=int, default=1,
                        help="以哪个用户身份执行（影响自选股类用例）")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    cases = load_cases(GOLDEN_DIR / "chat_golden_set.json")
    if args.category:
        wanted = set(args.category.split(","))
        cases = [c for c in cases if c["category"] in wanted]
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = report_dir / "golden-checkpoint.jsonl"

    done_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    if args.resume and checkpoint_path.exists():
        # 断点续跑：已完成用例直接计入本次报告，不重复烧 LLM 调用。
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            done_ids.add(item["id"])
            results.append(item)
    elif checkpoint_path.exists():
        checkpoint_path.unlink()

    engine_mode = args.engine
    if engine_mode == "auto":
        try:
            import app.services.agent.engine  # noqa: F401

            engine_mode = "agent"
        except ImportError:
            engine_mode = "legacy"
    print(f"[golden] 引擎={engine_mode} 用例数={len(cases)} 已完成断点={len(done_ids)}")

    aborted = None
    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
        for index, case in enumerate(cases, start=1):
            if case["id"] in done_ids:
                continue
            print(f"[golden] ({index}/{len(cases)}) {case['id']} {case['question'][:40]}")
            db = SessionLocal()
            try:
                if engine_mode == "agent":
                    outcome = run_case_agent(db, settings, case, args.user_id)
                else:
                    outcome = run_case_legacy(db, settings, case, args.user_id)
                verdict = evaluate(case, outcome)
                item = {
                    "id": case["id"], "category": case["category"],
                    "question": case["question"], "answer": outcome.get("answer"),
                    "tools": outcome.get("tools"), "overall": verdict["overall"],
                    "checks": verdict["checks"],
                }
            except Exception as exc:  # noqa: BLE001
                # 日限额是预期中止信号：保留断点供次日 --resume 续跑；其余异常记 ERROR 继续。
                if type(exc).__name__ == "LlmDailyLimitExceeded":
                    aborted = f"日限额中止：{exc}"
                    print(f"[golden] {aborted}")
                    break
                item = {
                    "id": case["id"], "category": case["category"],
                    "question": case["question"], "answer": None, "tools": [],
                    "overall": "ERROR", "checks": {},
                    "error": "".join(traceback.format_exception_only(exc)).strip(),
                }
            finally:
                db.close()
            results.append(item)
            checkpoint.write(json.dumps(item, ensure_ascii=False) + "\n")
            checkpoint.flush()

    tag = f"-{args.report_tag}" if args.report_tag else ""
    report_path = report_dir / f"golden-report-{_now_east8():%Y%m%d-%H%M%S}-{engine_mode}{tag}.md"
    write_report(report_path, results, engine_mode)
    print(f"[golden] 报告已写入 {report_path}")
    if aborted:
        print(f"[golden] 注意：{aborted}；可于次日使用 --resume 续跑剩余用例")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
