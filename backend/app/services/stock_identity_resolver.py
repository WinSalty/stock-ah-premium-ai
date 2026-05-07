from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.market import AHStockPair, AStockBasic

TS_CODE_PATTERN = re.compile(r"\b(?P<symbol>\d{6})\.(?P<exchange>SH|SZ|BJ)\b", re.IGNORECASE)
SIX_DIGIT_PATTERN = re.compile(r"(?<!\d)(?P<symbol>\d{6})(?!\d)")
DEFAULT_CANDIDATE_LIMIT = 12
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
    """从用户问题和前端上下文中解析本地 A 股股票候选。

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
        six_digit_code = self._six_digit_code(question)
        if six_digit_code:
            result = self._resolve_symbol(six_digit_code)
            if result.resolved or result.ambiguous_candidates:
                return result
        return self._resolve_name(question)

    def resolve_code(self, ts_code: str) -> StockResolveResult:
        """按本地基础表校验单个 A 股代码，供 LLM 语义消歧结果二次验真。

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
        stocks.extend(self._name_matched_stocks(question))
        stocks.extend(self._resolve_ah_pair_name(question))
        deduped = {stock.ts_code: stock for stock in stocks}
        return tuple(self._identity_from_stock(stock) for stock in list(deduped.values())[:limit])

    def _context_ts_code(self, context: dict[str, object]) -> str | None:
        # 前端若已经选中个股，优先信任显式代码；仍要回查本地基础表，避免用户传入任意接口参数。
        for key in ("ts_code", "a_ts_code", "stock_code", "symbol"):
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
        for match in SIX_DIGIT_PATTERN.finditer(question):
            codes.append(self._normalize_code(match.group("symbol")))
        return tuple(dict.fromkeys(codes))

    def _explicit_ts_code(self, question: str) -> str | None:
        match = TS_CODE_PATTERN.search(question)
        if not match:
            return None
        return f"{match.group('symbol')}.{match.group('exchange').upper()}"

    def _six_digit_code(self, question: str) -> str | None:
        match = SIX_DIGIT_PATTERN.search(question)
        return match.group("symbol") if match else None

    def _normalize_code(self, value: str) -> str:
        value = value.upper()
        if TS_CODE_PATTERN.fullmatch(value):
            return value
        if SIX_DIGIT_PATTERN.fullmatch(value):
            suffix = "SH" if value.startswith(("6", "9")) else "SZ"
            return f"{value}.{suffix}"
        return value

    def _resolve_ts_code(self, ts_code: str) -> StockResolveResult:
        stock = self.db.get(AStockBasic, self._normalize_code(ts_code))
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
        if not matched:
            matched = self._resolve_ah_pair_name(question)
        return self._result_from_stocks(matched, "名称匹配到多只股票，已停止自动补数")

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
        return [
            stock
            for stock in stocks
            if stock.name and self._name_matches(stock.name, question)
        ]

    def _name_matches(self, stock_name: str, question: str) -> bool:
        # 中文简称经常和“怎么看/投资报告”等问法混在一起；先剥离问法词再做片段匹配。
        if stock_name in question:
            return True
        cleaned = question
        for suffix in ("怎么看", "投资报告", "分析报告", "深度报告", "估值", "财报", "分红"):
            cleaned = cleaned.replace(suffix, "")
        cleaned = cleaned.strip()
        if len(cleaned) >= 2 and cleaned in stock_name:
            return True
        return self._meaningful_name_fragment_matches(stock_name, question)

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

    def _resolve_ah_pair_name(self, question: str) -> list[AStockBasic]:
        # AH 场景下用户可能说港股简称，这里只把 AH 配对表映射回 A 股代码，仍不触碰港股补数接口。
        pairs = list(
            self.db.scalars(
                select(AHStockPair).where(
                    AHStockPair.is_active.is_(True),
                    or_(AHStockPair.a_name.is_not(None), AHStockPair.hk_name.is_not(None)),
                )
            ).all()
        )
        a_codes = {
            pair.a_ts_code
            for pair in pairs
            if (pair.a_name and pair.a_name in question)
            or (pair.hk_name and pair.hk_name in question)
        }
        if not a_codes:
            return []
        return list(
            self.db.scalars(select(AStockBasic).where(AStockBasic.ts_code.in_(a_codes))).all()
        )

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

    def _identity_from_stock(self, stock: AStockBasic) -> StockIdentity:
        return StockIdentity(
            ts_code=stock.ts_code,
            symbol=stock.symbol,
            name=stock.name,
            industry=stock.industry,
            area=stock.area,
            market=stock.market,
        )
