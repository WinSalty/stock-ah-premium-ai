from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InvestmentKnowledgeCategory:
    """投资知识分类配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    key: str
    title: str
    keywords: tuple[str, ...]
    documents: tuple[str, ...]
    max_chunks: int = 3


@dataclass(frozen=True)
class InvestmentKnowledgeSelection:
    """按问题检索出的投资知识片段。

    创建日期：2026-05-04
    author: sunshengxian
    """

    categories: list[str]
    chunks: list[dict[str, str]]


class InvestmentKnowledgeService:
    """面向 LLM 问答的投资类文档分类检索服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    categories = (
        InvestmentKnowledgeCategory(
            key="ah_premium",
            title="A/H 溢价与跨市场价差",
            keywords=(
                "ah",
                "a/h",
                "h/a",
                "溢价",
                "折价",
                "套利",
                "价差",
                "港股通",
                "a股",
                "h股",
                "沪深港通",
                "互联互通",
            ),
            documents=("ah-premium-cross-market.md",),
            max_chunks=4,
        ),
        InvestmentKnowledgeCategory(
            key="stock_selection",
            title="A 股选股与估值因子",
            keywords=(
                "选股",
                "蓝筹",
                "低估值",
                "红利",
                "股息",
                "pe",
                "pb",
                "roe",
                "估值",
                "财务",
                "因子",
                "沪深300",
                "上证50",
                "质量",
            ),
            documents=("stock-selection-valuation.md",),
            max_chunks=4,
        ),
        InvestmentKnowledgeCategory(
            key="risk_framework",
            title="组合风险与报告框架",
            keywords=(
                "风险",
                "仓位",
                "组合",
                "配置",
                "止损",
                "回撤",
                "税费",
                "汇率",
                "流动性",
                "报告",
                "建议",
                "策略",
            ),
            documents=("portfolio-risk-reporting.md",),
            max_chunks=3,
        ),
    )

    def __init__(self, doc_root: Path | None = None) -> None:
        self.doc_root = doc_root or (
            Path(__file__).resolve().parents[3] / "resources" / "doc" / "investment"
        )

    def select(
        self,
        question: str,
        history: Iterable[dict[str, str]] | None = None,
        max_total_chunks: int = 8,
    ) -> InvestmentKnowledgeSelection:
        """按问题和上下文命中投资知识分类。

        创建日期：2026-05-04
        author: sunshengxian
        """

        signal = self._normalize(
            "\n".join(
                [
                    question,
                    *[
                        item.get("content", "")
                        for item in (history or [])
                        if item.get("role") in {"user", "assistant"}
                    ],
                ]
            )
        )
        matched = [
            category
            for category in self.categories
            if any(self._normalize(keyword) in signal for keyword in category.keywords)
        ]
        if not matched:
            matched = [self.categories[-1]]

        chunks: list[dict[str, str]] = []
        for category in matched:
            for document in category.documents:
                chunks.extend(self._read_document_chunks(category, document)[: category.max_chunks])
                if len(chunks) >= max_total_chunks:
                    break
            if len(chunks) >= max_total_chunks:
                break

        return InvestmentKnowledgeSelection(
            categories=[category.title for category in matched],
            chunks=chunks[:max_total_chunks],
        )

    def _read_document_chunks(
        self,
        category: InvestmentKnowledgeCategory,
        document: str,
    ) -> list[dict[str, str]]:
        path = self.doc_root / document
        if not path.exists():
            return []
        content = path.read_text(encoding="utf-8")
        chunks = [chunk.strip() for chunk in re.split(r"\n(?=##\s+)", content) if chunk.strip()]
        return [
            {
                "category": category.title,
                "title": self._chunk_title(chunk),
                "content": chunk[:2400],
            }
            for chunk in chunks
        ]

    def _chunk_title(self, chunk: str) -> str:
        first_line = chunk.splitlines()[0].strip()
        return first_line.lstrip("#").strip() or "投资分析材料"

    def _normalize(self, value: str) -> str:
        return value.lower().replace("／", "/").replace(" ", "")
