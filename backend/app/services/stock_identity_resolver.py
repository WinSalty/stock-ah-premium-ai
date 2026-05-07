from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models.market import AHStockPair, AStockBasic

TS_CODE_PATTERN = re.compile(r"\b(?P<symbol>\d{6})\.(?P<exchange>SH|SZ|BJ)\b", re.IGNORECASE)
SIX_DIGIT_PATTERN = re.compile(r"(?<!\d)(?P<symbol>\d{6})(?!\d)")


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
    """从用户问题和前端上下文中保守解析单只 A 股股票。

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

    def _context_ts_code(self, context: dict[str, object]) -> str | None:
        # 前端若已经选中个股，优先信任显式代码；仍要回查本地基础表，避免用户传入任意接口参数。
        for key in ("ts_code", "a_ts_code", "stock_code", "symbol"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return self._normalize_code(value.strip())
        return None

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
        if not matched:
            matched = self._resolve_ah_pair_name(question)
        return self._result_from_stocks(matched, "名称匹配到多只股票，已停止自动补数")

    def _name_matches(self, stock_name: str, question: str) -> bool:
        # 中文简称经常和“怎么看/投资报告”等问法混在一起；先剥离问法词再做片段匹配。
        if stock_name in question:
            return True
        cleaned = question
        for suffix in ("怎么看", "投资报告", "分析报告", "深度报告", "估值", "财报", "分红"):
            cleaned = cleaned.replace(suffix, "")
        cleaned = cleaned.strip()
        return len(cleaned) >= 2 and cleaned in stock_name

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
