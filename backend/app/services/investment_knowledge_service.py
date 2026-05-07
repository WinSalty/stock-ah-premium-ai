from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

DOC_CHUNK_LIMIT = 2400
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


@dataclass(frozen=True)
class InvestmentKnowledgeCategory:
    """投资知识分类配置。

    创建日期：2026-05-04
    author: sunshengxian
    """

    key: str
    title: str
    summary: str
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
            summary="A/H 与 H/A 溢价、折价、港股通可操作性、跨市场替代、阈值设置和配对交易边界。",
            keywords=(
                "ah",
                "a/h",
                "h/a",
                "溢价",
                "折价",
                "套利",
                "价差",
                "阈值",
                "目标",
                "港股通",
                "a股",
                "h股",
                "沪深港通",
                "互联互通",
            ),
            documents=(
                "ah-premium/threshold-recommendation-logic.md",
                "ah-premium/ah-premium-cross-market.md",
                "ah-premium/ah-arbitrage-principle-and-llm-guide.md",
                "ah-premium/ah-premium-arbitrage-research-2026.md",
                # A/H 研究材料允许按分类批量扩展，新增 DOCX 后无需逐个改代码登记。
                "ah-premium/*.docx",
            ),
            max_chunks=9,
        ),
        InvestmentKnowledgeCategory(
            key="stock_selection",
            title="A 股选股与估值因子",
            summary="A 股蓝筹、低估值、高股息、ROE、PE/PB、质量因子和选股字段解释。",
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
            documents=("stock-selection/stock-selection-valuation.md",),
            max_chunks=4,
        ),
        InvestmentKnowledgeCategory(
            key="financial_sector",
            title="银行与非银长期投资",
            summary="银行、券商、保险等金融资产的长期投资框架、比较维度和配置逻辑。",
            keywords=(
                "银行",
                "非银",
                "非银行",
                "券商",
                "保险",
                "招商银行",
                "宁波银行",
                "杭州银行",
                "江苏银行",
                "成都银行",
                "兴业银行",
                "平安银行",
                "中国移动",
                "长期投资",
            ),
            documents=("financial-sector/A股长期投资分析_银行与非银行_对话整理.docx",),
            max_chunks=5,
        ),
        InvestmentKnowledgeCategory(
            key="company_wuliangye",
            title="五粮液深度投资报告",
            summary="五粮液、高端白酒、渠道库存、批价、现金流、分红和信任修复研究。",
            keywords=(
                "五粮液",
                "000858",
                "白酒",
                "高端白酒",
                "消费",
                "食品饮料",
            ),
            documents=("company-research/五粮液股票投资报告_2026.docx",),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_gree",
            title="格力电器深度价值投资报告",
            summary="格力电器、白电、空调、高股息、成熟制造业现金流和与美的对比。",
            keywords=(
                "格力",
                "格力电器",
                "000651",
                "家电",
                "白电",
                "空调",
                "高股息",
            ),
            documents=("company-research/value-investing-2026/gree_deep_value_report_2026.docx",),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_china_shenhua",
            title="中国神华深度价值投资报告",
            summary="中国神华、煤炭、电力、铁路港口一体化、红利资产和 H 股折价研究。",
            keywords=(
                "中国神华",
                "601088",
                "01088",
                "煤炭",
                "综合能源",
                "红利资产",
            ),
            documents=(
                "company-research/value-investing-2026/中国神华深度价值投资分析报告_完整版_2026版.docx",
            ),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_catl",
            title="宁德时代深度价值投资报告",
            summary="宁德时代、动力电池、储能、全球电池龙头和成长估值再评估。",
            keywords=(
                "宁德时代",
                "300750",
                "动力电池",
                "储能",
                "电池龙头",
            ),
            documents=("company-research/value-investing-2026/宁德时代深度价值投资分析报告_2026版.docx",),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_byd",
            title="比亚迪深度价值投资报告",
            summary="比亚迪、新能源汽车、整车、动力电池、垂直一体化和全球化研究。",
            keywords=(
                "比亚迪",
                "002594",
                "新能源汽车",
                "整车",
                "垂直一体化",
            ),
            documents=("company-research/value-investing-2026/比亚迪深度价值投资分析报告_2026版.docx",),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_yangtze_power",
            title="长江电力深度价值投资报告",
            summary="长江电力、水电、现金流、公用事业属性、分红和防御配置研究。",
            keywords=(
                "长江电力",
                "600900",
                "水电",
                "公用事业",
                "防御配置",
            ),
            documents=("company-research/value-investing-2026/长江电力深度价值投资分析报告_2026版.docx",),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_cambricon",
            title="寒武纪深度价值投资报告",
            summary="寒武纪、国产 AI 芯片、算力、成长股估值兑现和高估值风险研究。",
            keywords=(
                "寒武纪",
                "688256",
                "ai芯片",
                "AI芯片",
                "国产算力",
                "算力",
            ),
            documents=("company-research/value-investing-2026/寒武纪深度价值投资分析报告_2026版.docx",),
            max_chunks=3,
        ),
        InvestmentKnowledgeCategory(
            key="company_research",
            title="个股深度投资报告",
            summary=(
                "兼容旧路由的个股报告聚合分类；只有问题中的公司名或股票代码"
                "精确命中材料时才读取对应报告。"
            ),
            keywords=(
                "个股",
                "公司研究",
                "公司价值",
                "价值投资",
                "股票投资报告",
                "深度报告",
            ),
            documents=("company-research/*.docx", "company-research/value-investing-2026/*.docx"),
            max_chunks=8,
        ),
        InvestmentKnowledgeCategory(
            key="macro_industry",
            title="宏观产业与地产金融推演",
            summary="日本经验、地产金融、人口、地方财政、资产负债表和中国未来产业推演。",
            keywords=(
                "日本",
                "地产",
                "房地产",
                "地方财政",
                "产业金融",
                "金融",
                "宏观",
                "人口",
                "债务",
                "资产负债表",
                "中国未来",
                "产业升级",
                "低利率",
            ),
            documents=("macro-industry/日本金融地产产业金融变化及中国未来推演.docx",),
            max_chunks=5,
        ),
        InvestmentKnowledgeCategory(
            key="risk_framework",
            title="组合风险与报告框架",
            summary="投资报告结构、仓位、组合配置、回撤、止损、税费、汇率和反证条件表达框架。",
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
            documents=("portfolio-risk/portfolio-risk-reporting.md",),
            max_chunks=3,
        ),
    )

    def __init__(self, doc_root: Path | None = None) -> None:
        self.doc_root = doc_root or (
            Path(__file__).resolve().parents[3] / "resources" / "doc" / "llm-knowledge"
        )

    def catalog(self) -> list[dict[str, str]]:
        """返回轻量知识库目录，供模型判断是否需要读取材料。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return [
            {"key": category.key, "title": category.title, "summary": category.summary}
            for category in self.categories
        ]

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
            chunks.extend(self._select_category_chunks(category, question))
            if len(chunks) >= max_total_chunks:
                break

        return InvestmentKnowledgeSelection(
            categories=[category.title for category in matched],
            chunks=chunks[:max_total_chunks],
        )

    def select_by_keys(
        self,
        category_keys: Iterable[str],
        max_total_chunks: int = 5,
        question: str | None = None,
        context: dict[str, object] | None = None,
    ) -> InvestmentKnowledgeSelection:
        """按模型选择的分类读取知识片段。

        创建日期：2026-05-05
        author: sunshengxian
        """

        requested_keys = list(dict.fromkeys(category_keys))
        category_map = {category.key: category for category in self.categories}
        matched = [category_map[key] for key in requested_keys if key in category_map]
        chunks: list[dict[str, str]] = []
        for category in matched:
            chunks.extend(self._select_category_chunks(category, question, context))
            if len(chunks) >= max_total_chunks:
                break
        return InvestmentKnowledgeSelection(
            categories=[category.title for category in matched],
            chunks=chunks[:max_total_chunks],
        )

    def _select_category_chunks(
        self,
        category: InvestmentKnowledgeCategory,
        question: str | None = None,
        context: dict[str, object] | None = None,
    ) -> list[dict[str, str]]:
        """跨文档轮询选取片段，避免单个长文占满上下文。

        创建日期：2026-05-04
        author: sunshengxian
        """

        document_chunks = [
            self._read_document_chunks(category, document)
            for document in self._filter_category_documents(
                category,
                self._resolve_category_documents(category),
                question,
                context,
            )
        ]
        selected: list[dict[str, str]] = []
        for chunk_index in range(category.max_chunks):
            for chunks in document_chunks:
                if len(selected) >= category.max_chunks:
                    return selected
                if chunk_index < len(chunks):
                    selected.append(chunks[chunk_index])
        return selected

    def _filter_category_documents(
        self,
        category: InvestmentKnowledgeCategory,
        documents: list[str],
        question: str | None,
        context: dict[str, object] | None,
    ) -> list[str]:
        """按公司名和股票代码过滤具体个股报告，避免无关报告污染上下文。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if category.key != "company_research":
            return documents
        signals = self._company_research_signals(question, context)
        if not signals:
            return []
        matched_documents = [
            document
            for document in documents
            if any(signal in self._normalize(document) for signal in signals)
        ]
        if matched_documents:
            return matched_documents
        # 文件名不总是覆盖完整股票名，兜底读取标题做一次精确匹配；未命中时返回空，不塞其他公司报告。
        result: list[str] = []
        for document in documents:
            path = self.doc_root / document
            content = self._cached_document_text(str(path)) if path.exists() else ""
            title_signal = self._normalize(f"{document}\n{content[:500]}")
            if any(signal in title_signal for signal in signals):
                result.append(document)
        return result

    def _company_research_signals(
        self,
        question: str | None,
        context: dict[str, object] | None,
    ) -> tuple[str, ...]:
        """提取具体公司研究可用的匹配信号。

        创建日期：2026-05-07
        author: sunshengxian
        """

        raw_values = [question or ""]
        if context:
            for key in (
                "ts_code",
                "a_ts_code",
                "stock_code",
                "symbol",
                "stock_name",
                "name",
                "company_name",
            ):
                value = context.get(key)
                if isinstance(value, str):
                    raw_values.append(value)
        signal_text = self._normalize("\n".join(raw_values))
        aliases = {
            "五粮液": ("五粮液", "000858"),
            "格力": ("格力", "格力电器", "000651"),
            "格力电器": ("格力", "格力电器", "000651"),
            "中国神华": ("中国神华", "601088", "01088"),
            "宁德时代": ("宁德时代", "300750"),
            "比亚迪": ("比亚迪", "002594"),
            "长江电力": ("长江电力", "600900"),
            "寒武纪": ("寒武纪", "688256"),
        }
        matched: list[str] = []
        for keys in aliases.values():
            normalized_keys = tuple(self._normalize(key) for key in keys)
            if any(key in signal_text for key in normalized_keys):
                matched.extend(normalized_keys)
        return tuple(dict.fromkeys(matched))

    def _resolve_category_documents(self, category: InvestmentKnowledgeCategory) -> list[str]:
        """展开分类中的文档路径和目录通配符。

        创建日期：2026-05-05
        author: sunshengxian
        """

        documents: list[str] = []
        for document in category.documents:
            if not any(marker in document for marker in ("*", "?", "[")):
                documents.append(document)
                continue
            matches = sorted(
                path
                for path in self.doc_root.glob(document)
                if path.is_file() and path.is_relative_to(self.doc_root)
            )
            documents.extend(path.relative_to(self.doc_root).as_posix() for path in matches)
        return documents

    def _read_document_chunks(
        self,
        category: InvestmentKnowledgeCategory,
        document: str,
    ) -> list[dict[str, str]]:
        path = self.doc_root / document
        if not path.exists():
            return []
        content = self._cached_document_text(str(path))
        chunks = self._split_document_chunks(path, content)
        document_title = self._document_title(path, content)
        return [
            {
                "category": category.title,
                "title": self._material_title(path, chunk, document_title, index),
                "content": chunk[:DOC_CHUNK_LIMIT],
            }
            for index, chunk in enumerate(chunks)
        ]

    def _read_document_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".md":
            return path.read_text(encoding="utf-8")
        if suffix == ".docx":
            return self._read_docx_text(path)
        return ""

    @staticmethod
    @lru_cache(maxsize=64)
    def _cached_document_text(path_value: str) -> str:
        """缓存投研材料文本，避免每轮问答重复解压 DOCX。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return InvestmentKnowledgeService._read_document_text_uncached(Path(path_value))

    @staticmethod
    def _read_document_text_uncached(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".md":
            return path.read_text(encoding="utf-8")
        if suffix == ".docx":
            return InvestmentKnowledgeService._read_docx_text_static(path)
        return ""

    def _read_docx_text(self, path: Path) -> str:
        return self._read_docx_text_static(path)

    @staticmethod
    def _read_docx_text_static(path: Path) -> str:
        """从 docx 主文档中抽取段落和表格文本。

        创建日期：2026-05-04
        author: sunshengxian
        """

        with zipfile.ZipFile(path) as docx_file:
            document_xml = docx_file.read("word/document.xml")
        root = ET.fromstring(document_xml)
        body = root.find("w:body", WORD_NS)
        if body is None:
            return ""
        lines: list[str] = []
        for child in body:
            tag = InvestmentKnowledgeService._xml_tag_name(child)
            if tag == "p":
                text = InvestmentKnowledgeService._word_text(child)
                if text:
                    lines.append(text)
            elif tag == "tbl":
                lines.extend(InvestmentKnowledgeService._word_table_rows(child))
        return "\n".join(lines)

    @staticmethod
    def _word_table_rows(table: ET.Element) -> list[str]:
        rows: list[str] = []
        for row in table.findall("w:tr", WORD_NS):
            cells = [
                " ".join(
                    paragraph_text
                    for paragraph in cell.findall(".//w:p", WORD_NS)
                    if (paragraph_text := InvestmentKnowledgeService._word_text(paragraph))
                )
                for cell in row.findall("w:tc", WORD_NS)
            ]
            row_text = " | ".join(cell for cell in cells if cell)
            if row_text:
                rows.append(row_text)
        return rows

    @staticmethod
    def _word_text(element: ET.Element) -> str:
        return "".join(text.text or "" for text in element.findall(".//w:t", WORD_NS)).strip()

    @staticmethod
    def _xml_tag_name(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    def _split_document_chunks(self, path: Path, content: str) -> list[str]:
        cleaned = content.strip()
        if not cleaned:
            return []
        if path.suffix.lower() == ".md":
            return [chunk.strip() for chunk in re.split(r"\n(?=##\s+)", cleaned) if chunk.strip()]
        return self._split_plain_text_chunks(cleaned)

    def _split_plain_text_chunks(self, content: str) -> list[str]:
        """按长度切分普通文本报告，保留段落边界。

        创建日期：2026-05-04
        author: sunshengxian
        """

        chunks: list[str] = []
        current: list[str] = []
        current_size = 0
        paragraphs = [line.strip() for line in content.splitlines() if line.strip()]
        for paragraph in paragraphs:
            paragraph_size = len(paragraph)
            if current and current_size + paragraph_size + 1 > DOC_CHUNK_LIMIT:
                chunks.append("\n".join(current))
                current = []
                current_size = 0
            current.append(paragraph)
            current_size += paragraph_size + 1
        if current:
            chunks.append("\n".join(current))
        return chunks

    def _chunk_title(self, chunk: str) -> str:
        first_line = chunk.splitlines()[0].strip()
        return first_line.lstrip("#").strip() or "投资分析材料"

    def _document_title(self, path: Path, content: str) -> str:
        if path.suffix.lower() == ".md":
            return ""
        for line in content.splitlines():
            if line.strip():
                return line.strip()
        return "投资分析材料"

    def _material_title(
        self,
        path: Path,
        chunk: str,
        document_title: str,
        index: int,
    ) -> str:
        if path.suffix.lower() == ".md":
            return self._chunk_title(chunk)
        return f"{document_title} 片段 {index + 1}"

    def _normalize(self, value: str) -> str:
        return value.lower().replace("／", "/").replace(" ", "")
