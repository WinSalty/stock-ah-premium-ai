from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.market import AHStockPair, AStockBasic, HKStockBasic

TS_CODE_PATTERN = re.compile(r"\b(?P<symbol>\d{6})\.(?P<exchange>SH|SZ|BJ)\b", re.IGNORECASE)
HK_TS_CODE_PATTERN = re.compile(r"\b(?P<symbol>\d{5})\.HK\b", re.IGNORECASE)
HK_FIVE_DIGIT_PATTERN = re.compile(r"(?<!\d)(?P<symbol>\d{5})(?!\d)")
SIX_DIGIT_PATTERN = re.compile(r"(?<!\d)(?P<symbol>\d{6})(?!\d)")
DEFAULT_CANDIDATE_LIMIT = 12
AH_CROSS_MARKET_KEYWORDS = frozenset(
    {
        "AH",
        "A/H",
        "H/A",
        "A股H股",
        "港股通",
        "沪港通",
        "深港通",
        "H股",
        "港股",
        "两地",
        "双上市",
        "溢价",
        "折价",
        "择边",
    }
)
GENERIC_NAME_FRAGMENTS = frozenset(
    {
        "股份",
        "有限",
        "集团",
        "控股",
        "银行",
        "证券",
        "中国",
        "上海",
        "深圳",
        "科技",
    }
)
MULTI_STOCK_QUESTION_KEYWORDS = frozenset(
    {
        "对比",
        "比较",
        "和",
        "与",
        "以及",
        "哪个",
        "谁更",
        "两只",
        "多只",
    }
)


@dataclass(frozen=True)
class StockIdentity:
    """LLM 问答中解析到的单只股票身份。

    创建日期：2026-05-07
    author: sunshengxian
    """

    ts_code: str
    symbol: str | None
    name: str
    industry: str | None = None
    area: str | None = None
    market: str | None = None
    source: str = "A_STOCK_BASIC"


@dataclass(frozen=True)
class StockResolveResult:
    """股票解析结果，显式区分成功、歧义和未命中。

    创建日期：2026-05-07
    author: sunshengxian
    """

    identity: StockIdentity | None
    ambiguous_candidates: tuple[StockIdentity, ...] = ()
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.identity is not None and not self.ambiguous_candidates


class StockIdentityResolver:
    """从用户问题和前端上下文中解析本地股票候选。

    创建日期：2026-05-07
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(
        self,
        question: str,
        context: dict[str, object] | None = None,
    ) -> StockResolveResult:
        """按“显式代码优先、名称严格匹配其次”的顺序解析股票。

        创建日期：2026-05-07
        author: sunshengxian
        """

        context = context or {}
        context_code = self._context_ts_code(context)
        if context_code:
            result = self._resolve_ts_code(context_code)
            if result.resolved:
                return result
        explicit_code = self._explicit_ts_code(question)
        if explicit_code:
            result = self._resolve_ts_code(explicit_code)
            if result.resolved:
                return result
        explicit_hk_code = self._explicit_hk_ts_code(question)
        if explicit_hk_code:
            result = self._resolve_ts_code(explicit_hk_code)
            if result.resolved:
                return result
        five_digit_code = self._five_digit_hk_code(question)
        if five_digit_code:
            result = self._resolve_ts_code(f"{five_digit_code}.HK")
            if result.resolved:
                return result
        six_digit_code = self._six_digit_code(question)
        if six_digit_code:
            result = self._resolve_symbol(six_digit_code)
            if result.resolved or result.ambiguous_candidates:
                return result
        return self._resolve_name(question)

    def resolve_code(self, ts_code: str) -> StockResolveResult:
        """按本地基础表校验单个股票代码，供 LLM 语义消歧结果二次验真。

        创建日期：2026-05-07
        author: sunshengxian
        """

        return self._resolve_ts_code(ts_code)

    def resolve_candidates(
        self,
        question: str,
        context: dict[str, object] | None = None,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> tuple[StockIdentity, ...]:
        """返回可交给 LLM 做语义筛选的本地股票候选集合。

        创建日期：2026-05-07
        author: sunshengxian
        """

        context = context or {}
        stocks: list[AStockBasic] = []
        for code in self._candidate_codes(question, context):
            # 显式代码来自前端或用户原文，但仍必须落在本地股票表中，避免 LLM 借机扩展接口参数。
            stock = self.db.get(AStockBasic, self._normalize_code(code))
            if stock is not None:
                stocks.append(stock)
        hk_stocks: list[HKStockBasic] = []
        for code in self._candidate_hk_codes(question, context):
            stock = self.db.get(HKStockBasic, self._normalize_code(code))
            if stock is not None:
                hk_stocks.append(stock)
        stocks.extend(self._name_matched_stocks(question))
        ah_pair_stocks, ah_pair_hk_stocks = self._resolve_ah_pair_name(question)
        stocks.extend(ah_pair_stocks)
        hk_stocks.extend(ah_pair_hk_stocks)
        hk_stocks.extend(self._hk_name_matched_stocks(question))
        deduped_a = {stock.ts_code: stock for stock in stocks}
        deduped_hk = {stock.ts_code: stock for stock in hk_stocks}
        identities = [
            self._identity_from_stock(stock) for stock in list(deduped_a.values())
        ] + [
            self._identity_from_hk_stock(stock) for stock in list(deduped_hk.values())
        ]
        return tuple(identities[:limit])

    def _context_ts_code(self, context: dict[str, object]) -> str | None:
        # 前端若已经选中个股，优先信任显式代码；仍要回查本地基础表，避免用户传入任意接口参数。
        for key in ("ts_code", "a_ts_code", "hk_ts_code", "stock_code", "symbol"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return self._normalize_code(value.strip())
        return None

    def _candidate_codes(self, question: str, context: dict[str, object]) -> tuple[str, ...]:
        # 候选抽取要覆盖前端选中、完整 Tushare 代码和用户常写的六位代码；后续统一回查本地表。
        codes: list[str] = []
        context_code = self._context_ts_code(context)
        if context_code:
            codes.append(context_code)
        codes.extend(
            f"{match.group('symbol')}.{match.group('exchange').upper()}"
            for match in TS_CODE_PATTERN.finditer(question)
        )
        codes.extend(
            f"{match.group('symbol')}.HK" for match in HK_TS_CODE_PATTERN.finditer(question)
        )
        for match in SIX_DIGIT_PATTERN.finditer(question):
            codes.append(self._normalize_code(match.group("symbol")))
        return tuple(dict.fromkeys(codes))

    def _candidate_hk_codes(self, question: str, context: dict[str, object]) -> tuple[str, ...]:
        # 港股用户常写完整 Tushare 代码或五位数字；五位数字只按 HK 处理，
        # 不与 A 股六位代码共用推断规则，避免跨市场误补数。
        codes: list[str] = []
        context_code = self._context_ts_code(context)
        if context_code and context_code.endswith(".HK"):
            codes.append(context_code)
        codes.extend(
            f"{match.group('symbol')}.HK" for match in HK_TS_CODE_PATTERN.finditer(question)
        )
        for match in HK_FIVE_DIGIT_PATTERN.finditer(question):
            codes.append(f"{match.group('symbol')}.HK")
        return tuple(dict.fromkeys(codes))

    def _explicit_ts_code(self, question: str) -> str | None:
        match = TS_CODE_PATTERN.search(question)
        if not match:
            return None
        return f"{match.group('symbol')}.{match.group('exchange').upper()}"

    def _explicit_hk_ts_code(self, question: str) -> str | None:
        match = HK_TS_CODE_PATTERN.search(question)
        if not match:
            return None
        return f"{match.group('symbol')}.HK"

    def _six_digit_code(self, question: str) -> str | None:
        match = SIX_DIGIT_PATTERN.search(question)
        return match.group("symbol") if match else None

    def _five_digit_hk_code(self, question: str) -> str | None:
        match = HK_FIVE_DIGIT_PATTERN.search(question)
        return match.group("symbol") if match else None

    def _normalize_code(self, value: str) -> str:
        value = value.upper()
        if TS_CODE_PATTERN.fullmatch(value):
            return value
        if HK_TS_CODE_PATTERN.fullmatch(value):
            return value
        if HK_FIVE_DIGIT_PATTERN.fullmatch(value):
            return f"{value}.HK"
        if SIX_DIGIT_PATTERN.fullmatch(value):
            suffix = "SH" if value.startswith(("6", "9")) else "SZ"
            return f"{value}.{suffix}"
        return value

    def _resolve_ts_code(self, ts_code: str) -> StockResolveResult:
        normalized = self._normalize_code(ts_code)
        if normalized.endswith(".HK"):
            hk_stock = self.db.get(HKStockBasic, normalized)
            if hk_stock is None:
                return StockResolveResult(None, reason="本地港股基础表未找到该代码")
            return StockResolveResult(self._identity_from_hk_stock(hk_stock))
        stock = self.db.get(AStockBasic, normalized)
        if stock is None:
            return StockResolveResult(None, reason="本地 A 股基础表未找到该代码")
        return StockResolveResult(self._identity_from_stock(stock))

    def _resolve_symbol(self, symbol: str) -> StockResolveResult:
        stocks = list(
            self.db.scalars(select(AStockBasic).where(AStockBasic.symbol == symbol)).all()
        )
        return self._result_from_stocks(stocks, "六位代码匹配到多只股票，已停止自动补数")

    def _resolve_name(self, question: str) -> StockResolveResult:
        # 先做股票简称的包含匹配，只有唯一命中才触发补数；“平安”“银行”等模糊词会进入歧义分支。
        matched = self._name_matched_stocks(question)
        exact_matched = [
            stock
            for stock in matched
            if stock.name and self._is_exact_name_mention(stock.name, question)
        ]
        if exact_matched and not self._looks_like_multi_stock_question(question):
            # 单股问法里完整出现股票简称时，优先按精确简称解析；否则“昊华能源”会被
            # “能源”片段召回的几十只同后缀股票淹没，导致本可补取的数据被误判为歧义。
            result = self._result_from_stocks(
                exact_matched,
                "精确名称匹配到多只股票，已停止自动补数",
            )
            if result.resolved or result.ambiguous_candidates:
                return result
        if not matched:
            matched, _hk_matched = self._resolve_ah_pair_name(question)
        result = self._result_from_stocks(matched, "名称匹配到多只股票，已停止自动补数")
        if result.resolved or result.ambiguous_candidates:
            return result
        return self._result_from_hk_stocks(
            self._hk_name_matched_stocks(question),
            "名称匹配到多只港股，已停止自动补数",
        )

    def _name_matched_stocks(self, question: str) -> list[AStockBasic]:
        # 本地股票名称表是歧义处理的候选来源；这里只做召回，不在此处替 LLM 做语义取舍。
        stocks = list(
            self.db.scalars(
                select(AStockBasic)
                .where(
                    AStockBasic.name.is_not(None),
                    AStockBasic.name != "",
                    or_(
                        AStockBasic.list_status.is_(None),
                        AStockBasic.list_status == "L",
                    ),
                )
                .limit(5000)
            ).all()
        )
        matched = [
            stock
            for stock in stocks
            if stock.name and self._name_matches(stock.name, question)
        ]
        return sorted(
            matched,
            key=lambda stock: self._name_match_rank(stock.name or "", question),
        )

    def _is_exact_name_mention(self, stock_name: str, question: str) -> bool:
        # 完整简称出现在原文中，才视为精确命中；不把“能源”等片段误升格为单股解析依据。
        return stock_name in question

    def _name_match_rank(self, stock_name: str, question: str) -> int:
        # 候选列表会被截断给路由/消歧模型，精确简称必须排在片段召回前面，
        # 这样同后缀股票很多时仍能把用户真正点名的股票交给模型选择。
        if self._is_exact_name_mention(stock_name, question):
            return 0
        cleaned = self._clean_question_for_name_match(question)
        if len(cleaned) >= 2 and cleaned in stock_name:
            return 1
        return 2

    def _clean_question_for_name_match(self, question: str) -> str:
        # 清理常见问法尾词，保留用户可能输入的股票简称主体，供简称片段匹配复用。
        cleaned = question
        for suffix in ("怎么看", "投资报告", "分析报告", "深度报告", "估值", "财报", "分红"):
            cleaned = cleaned.replace(suffix, "")
        return cleaned.strip()

    def _name_matches(self, stock_name: str, question: str) -> bool:
        # 中文简称经常和“怎么看/投资报告”等问法混在一起；先剥离问法词再做片段匹配。
        if stock_name in question:
            return True
        cleaned = self._clean_question_for_name_match(question)
        if len(cleaned) >= 2 and cleaned in stock_name:
            return True
        return self._meaningful_name_fragment_matches(stock_name, question)

    def _looks_like_multi_stock_question(self, question: str) -> bool:
        # 多股比较题需要保留候选歧义交给语义消歧，不能因为其中一只股票完整出现就提前收敛。
        return any(keyword in question for keyword in MULTI_STOCK_QUESTION_KEYWORDS)

    def _meaningful_name_fragment_matches(self, stock_name: str, question: str) -> bool:
        # 对比问题常把股票名简称化为“平安、招商、宁德”等片段；过滤行业泛词后再召回候选。
        for start in range(len(stock_name)):
            for end in range(start + 2, min(len(stock_name), start + 4) + 1):
                fragment = stock_name[start:end]
                if fragment in GENERIC_NAME_FRAGMENTS:
                    continue
                if fragment in question:
                    return True
        return False

    def _resolve_ah_pair_name(self, question: str) -> tuple[list[AStockBasic], list[HKStockBasic]]:
        # AH 场景下用户可能说港股简称；A/H 专项问题仍优先映射回 A 股配对，
        # 明确港股通、溢价、择边等跨市场问题时，同时召回 H 股，避免只看单边。
        pairs = list(
            self.db.scalars(
                select(AHStockPair).where(
                    AHStockPair.is_active.is_(True),
                    or_(AHStockPair.a_name.is_not(None), AHStockPair.hk_name.is_not(None)),
                )
            ).all()
        )
        wants_cross_market = self._wants_ah_cross_market(question)
        a_codes = {
            pair.a_ts_code
            for pair in pairs
            if (pair.a_name and pair.a_name in question)
            or (pair.hk_name and pair.hk_name in question)
        }
        hk_codes = {
            pair.hk_ts_code
            for pair in pairs
            if wants_cross_market
            and (
                (pair.a_name and pair.a_name in question)
                or (pair.hk_name and pair.hk_name in question)
            )
        }
        if not a_codes:
            return [], []
        a_stocks = list(
            self.db.scalars(select(AStockBasic).where(AStockBasic.ts_code.in_(a_codes))).all()
        )
        hk_stocks = (
            list(
                self.db.scalars(select(HKStockBasic).where(HKStockBasic.ts_code.in_(hk_codes))).all()
            )
            if hk_codes
            else []
        )
        return a_stocks, hk_stocks

    def _wants_ah_cross_market(self, question: str) -> bool:
        """识别是否需要同时查看 A 股、H 股和港股通价差信息。

        创建日期：2026-05-08
        author: sunshengxian
        """

        normalized = question.upper().replace(" ", "")
        return any(
            keyword.upper().replace(" ", "") in normalized
            for keyword in AH_CROSS_MARKET_KEYWORDS
        )

    def _hk_name_matched_stocks(self, question: str) -> list[HKStockBasic]:
        # 港股基础表用于港股投研自动补数的名称召回；这里只召回候选，
        # 多命中时交给统一歧义处理，避免“中国”等泛词误触补数。
        stocks = list(
            self.db.scalars(
                select(HKStockBasic)
                .where(
                    HKStockBasic.name.is_not(None),
                    HKStockBasic.name != "",
                    or_(
                        HKStockBasic.list_status.is_(None),
                        HKStockBasic.list_status == "L",
                    ),
                )
                .limit(5000)
            ).all()
        )
        return [
            stock
            for stock in stocks
            if stock.name and self._name_matches(stock.name, question)
        ]

    def _result_from_stocks(
        self,
        stocks: list[AStockBasic],
        ambiguous_reason: str,
    ) -> StockResolveResult:
        if not stocks:
            return StockResolveResult(None, reason="未解析到唯一 A 股股票")
        deduped = {stock.ts_code: stock for stock in stocks}
        identities = tuple(self._identity_from_stock(stock) for stock in deduped.values())
        if len(identities) == 1:
            return StockResolveResult(identities[0])
        return StockResolveResult(
            None,
            ambiguous_candidates=identities[:8],
            reason=ambiguous_reason,
        )

    def _result_from_hk_stocks(
        self,
        stocks: list[HKStockBasic],
        ambiguous_reason: str,
    ) -> StockResolveResult:
        if not stocks:
            return StockResolveResult(None, reason="未解析到唯一港股股票")
        deduped = {stock.ts_code: stock for stock in stocks}
        identities = tuple(self._identity_from_hk_stock(stock) for stock in deduped.values())
        if len(identities) == 1:
            return StockResolveResult(identities[0])
        return StockResolveResult(
            None,
            ambiguous_candidates=identities[:8],
            reason=ambiguous_reason,
        )

    def _identity_from_stock(self, stock: AStockBasic) -> StockIdentity:
        return StockIdentity(
            ts_code=stock.ts_code,
            symbol=stock.symbol,
            name=stock.name,
            industry=stock.industry,
            area=stock.area,
            market=stock.market,
        )

    def _identity_from_hk_stock(self, stock: HKStockBasic) -> StockIdentity:
        return StockIdentity(
            ts_code=stock.ts_code,
            symbol=stock.ts_code.split(".", 1)[0],
            name=stock.name,
            industry=None,
            area="HK",
            market=stock.market or "HK",
            source="HK_STOCK_BASIC",
        )
