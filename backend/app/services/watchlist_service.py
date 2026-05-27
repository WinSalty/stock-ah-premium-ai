from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.market import AHStockPair, AStockBasic, HKStockBasic, WatchlistStock
from app.db.models.notification import PushplusBinding
from app.schemas.market import RealtimeQuoteItem
from app.schemas.watchlist import (
    WatchlistCandidateResponse,
    WatchlistCreate,
    WatchlistOpportunityResponse,
    WatchlistUpdate,
)
from app.services.premium_query_service import PremiumQueryService
from app.services.realtime_market_service import (
    DEFAULT_QUOTE_QUALITY,
    REALTIME_MARKET_A,
    REALTIME_MARKET_HK,
    RealtimeMarketDataService,
    RealtimeQuote,
)

WATCHLIST_TARGET_PAIR = "PAIR"
WATCHLIST_TARGET_A_ONLY = "A_ONLY"
WATCHLIST_TARGET_H_ONLY = "H_ONLY"
WATCHLIST_TARGET_TYPES = {
    WATCHLIST_TARGET_PAIR,
    WATCHLIST_TARGET_A_ONLY,
    WATCHLIST_TARGET_H_ONLY,
}
WATCHLIST_CANDIDATE_LIMIT = 20


class WatchlistError(ValueError):
    """自选股业务错误。

    创建日期：2026-05-05
    author: sunshengxian
    """


class WatchlistService:
    """用户自选股服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.premium_query_service = PremiumQueryService(db)
        self.realtime_market_data_service = RealtimeMarketDataService.from_db(db)

    def list_opportunities(
        self,
        active_only: bool = True,
        user_id: int | None = None,
    ) -> list[WatchlistOpportunityResponse]:
        """查询自选股机会状态。

        创建日期：2026-05-04
        author: sunshengxian
        """

        statement = select(WatchlistStock)
        if user_id is not None:
            statement = statement.where(WatchlistStock.user_id == user_id)
        if active_only:
            statement = statement.where(WatchlistStock.is_active.is_(True))
        statement = statement.order_by(WatchlistStock.sort_order, WatchlistStock.id)
        rows = list(self.db.scalars(statement).all())
        result: list[WatchlistOpportunityResponse] = []
        for item in rows:
            premium_row = (
                self.premium_query_service.latest_pair_row(
                    item.a_ts_code,
                    item.hk_ts_code,
                )
                if item.target_type == WATCHLIST_TARGET_PAIR
                and item.a_ts_code
                and item.hk_ts_code
                else None
            )
            premium = (
                self.premium_query_service.to_response(
                    premium_row,
                    item.preferred_direction,
                    item,
                )
                if premium_row is not None
                else None
            )
            result.append(
                WatchlistOpportunityResponse(
                    watchlist=item,
                    premium=premium,
                    single_quote=self._single_quote(item),
                )
            )
        return result

    def create(self, payload: WatchlistCreate, user_id: int = 1) -> WatchlistStock:
        """新增或恢复自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        target_type = self._normalize_target_type(
            payload.target_type,
            payload.a_ts_code,
            payload.hk_ts_code,
        )
        a_ts_code, hk_ts_code = self._normalize_target_codes(
            target_type,
            payload.a_ts_code,
            payload.hk_ts_code,
        )
        target_key = self._target_key(target_type, a_ts_code, hk_ts_code)
        existing = self._get_by_target(target_type, target_key, user_id)
        if existing is not None:
            self._apply_update(existing, payload.model_dump(exclude_none=False))
            self._apply_target(existing, target_type, a_ts_code, hk_ts_code, target_key)
            self._normalize_alert_scope(existing)
            self._ensure_push_binding_for_alert(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        item = WatchlistStock(
            target_type=target_type,
            target_key=target_key,
            a_ts_code=a_ts_code,
            hk_ts_code=hk_ts_code,
            user_id=user_id,
            display_name=payload.display_name,
            preferred_direction=self._normalize_direction(payload.preferred_direction),
            target_premium_pct=payload.target_premium_pct,
            push_enabled=payload.push_enabled,
            a_price_alert_enabled=payload.a_price_alert_enabled,
            a_price_alert_operator=self._normalize_price_alert_operator(payload.a_price_alert_operator),
            a_price_alert_target_price=payload.a_price_alert_target_price,
            h_price_alert_enabled=payload.h_price_alert_enabled,
            h_price_alert_operator=self._normalize_price_alert_operator(payload.h_price_alert_operator),
            h_price_alert_target_price=payload.h_price_alert_target_price,
            holding_market=self._normalize_holding_market(payload.holding_market),
            sort_order=payload.sort_order,
            note=payload.note,
            is_active=payload.is_active,
        )
        self._normalize_alert_scope(item)
        self._ensure_push_binding_for_alert(item)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def search_candidates(
        self,
        target_type: str,
        keyword: str | None,
        limit: int = WATCHLIST_CANDIDATE_LIMIT,
    ) -> list[WatchlistCandidateResponse]:
        """按关注类型查询可加入自选的本地标的候选。

        创建日期：2026-05-19
        author: sunshengxian
        """

        normalized_type = self._normalize_target_type(target_type, None, None)
        normalized_keyword = (keyword or "").strip()
        # 候选查询只读取本地基础表和 AH 配对表，不触发外部行情补数，避免用户搜索时产生隐式成本。
        if normalized_type == WATCHLIST_TARGET_A_ONLY:
            return self._search_a_candidates(normalized_keyword, limit)
        if normalized_type == WATCHLIST_TARGET_H_ONLY:
            return self._search_h_candidates(normalized_keyword, limit)
        return self._search_pair_candidates(normalized_keyword, limit)

    def update(
        self,
        item_id: int,
        payload: WatchlistUpdate,
        user_id: int | None = None,
    ) -> WatchlistStock | None:
        """更新自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        item = self.db.get(WatchlistStock, item_id)
        if item is None or (user_id is not None and item.user_id != user_id):
            return None
        self._apply_update(item, payload.model_dump(exclude_unset=True))
        self._normalize_alert_scope(item)
        self._ensure_push_binding_for_alert(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def deactivate(self, item_id: int, user_id: int | None = None) -> bool:
        """停用自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        item = self.db.get(WatchlistStock, item_id)
        if item is None or (user_id is not None and item.user_id != user_id):
            return False
        item.is_active = False
        self.db.commit()
        return True

    def _get_by_target(
        self,
        target_type: str,
        target_key: str,
        user_id: int,
    ) -> WatchlistStock | None:
        return self.db.scalar(
            select(WatchlistStock).where(
                WatchlistStock.user_id == user_id,
                WatchlistStock.target_type == target_type,
                WatchlistStock.target_key == target_key,
            )
        )

    def _apply_target(
        self,
        item: WatchlistStock,
        target_type: str,
        a_ts_code: str | None,
        hk_ts_code: str | None,
        target_key: str,
    ) -> None:
        """统一写入关注身份，确保恢复停用记录和新增记录使用同一唯一键口径。"""

        item.target_type = target_type
        item.target_key = target_key
        item.a_ts_code = a_ts_code
        item.hk_ts_code = hk_ts_code

    def _apply_update(self, item: WatchlistStock, values: dict[str, object]) -> None:
        for key, value in values.items():
            if key in {"a_ts_code", "hk_ts_code", "target_type", "target_key"}:
                # 关注身份只允许创建或恢复自选时变更，普通编辑避免误把历史提醒改挂到其他股票。
                continue
            elif key == "preferred_direction" and value is not None:
                item.preferred_direction = self._normalize_direction(str(value))
            elif key == "holding_market" and value is not None:
                item.holding_market = self._normalize_holding_market(str(value))
            elif key in {"a_price_alert_operator", "h_price_alert_operator"} and value is not None:
                setattr(item, key, self._normalize_price_alert_operator(str(value)))
            else:
                setattr(item, key, value)

    def _normalize_direction(self, value: str) -> str:
        return "AH" if value.upper() == "AH" else "HA"

    def _normalize_holding_market(self, value: str) -> str:
        normalized = value.upper()
        return normalized if normalized in {"A", "H"} else "UNKNOWN"

    def _normalize_price_alert_operator(self, value: str) -> str:
        normalized = value.upper()
        return normalized if normalized in {"GTE", "LTE"} else "GTE"

    def _normalize_target_type(
        self,
        value: str | None,
        a_ts_code: str | None,
        hk_ts_code: str | None,
    ) -> str:
        normalized = (value or "").upper()
        if normalized in WATCHLIST_TARGET_TYPES:
            return normalized
        if a_ts_code and hk_ts_code:
            return WATCHLIST_TARGET_PAIR
        if a_ts_code:
            return WATCHLIST_TARGET_A_ONLY
        if hk_ts_code:
            return WATCHLIST_TARGET_H_ONLY
        raise WatchlistError("请选择关注标的")

    def _normalize_target_codes(
        self,
        target_type: str,
        a_ts_code: str | None,
        hk_ts_code: str | None,
    ) -> tuple[str | None, str | None]:
        normalized_a = a_ts_code.upper() if a_ts_code else None
        normalized_h = hk_ts_code.upper() if hk_ts_code else None
        if target_type == WATCHLIST_TARGET_PAIR:
            if not normalized_a or not normalized_h:
                raise WatchlistError("A/H 配对关注必须同时选择 A 股和 H 股")
            return normalized_a, normalized_h
        if target_type == WATCHLIST_TARGET_A_ONLY:
            if not normalized_a:
                raise WatchlistError("仅 A 股关注必须选择 A 股代码")
            return normalized_a, None
        if target_type == WATCHLIST_TARGET_H_ONLY:
            if not normalized_h:
                raise WatchlistError("仅 H 股关注必须选择 H 股代码")
            return None, normalized_h
        raise WatchlistError("不支持的关注类型")

    def _target_key(
        self,
        target_type: str,
        a_ts_code: str | None,
        hk_ts_code: str | None,
    ) -> str:
        if target_type == WATCHLIST_TARGET_PAIR:
            return f"{a_ts_code}|{hk_ts_code}"
        if target_type == WATCHLIST_TARGET_A_ONLY and a_ts_code:
            return a_ts_code
        if target_type == WATCHLIST_TARGET_H_ONLY and hk_ts_code:
            return hk_ts_code
        raise WatchlistError("关注标的代码不完整")

    def _normalize_alert_scope(self, item: WatchlistStock) -> None:
        """按关注类型清理不可用提醒，避免单股关注残留另一侧或溢价阈值配置。"""

        if item.target_type == WATCHLIST_TARGET_A_ONLY:
            item.target_premium_pct = None
            item.h_price_alert_enabled = False
            item.h_price_alert_target_price = None
            item.h_price_alert_operator = "GTE"
            item.holding_market = "A"
        elif item.target_type == WATCHLIST_TARGET_H_ONLY:
            item.target_premium_pct = None
            item.a_price_alert_enabled = False
            item.a_price_alert_target_price = None
            item.a_price_alert_operator = "GTE"
            item.holding_market = "H"

    def _single_quote(self, item: WatchlistStock) -> RealtimeQuoteItem | None:
        """为单市场关注读取实时行情快照，供首页卡片展示股价。

        创建日期：2026-05-27
        author: sunshengxian
        """

        # A/H 配对仍走官方 AH 主表和实时溢价回写链路；单 A/单 H 没有 premium，
        # 需要直接读取 water-stock 写入的 realtime_quote_snapshot。
        if item.target_type == WATCHLIST_TARGET_A_ONLY and item.a_ts_code:
            quote = self.realtime_market_data_service.provider.get_a_quote(item.a_ts_code)
            return self._quote_response(
                quote or self._unavailable_single_quote(REALTIME_MARKET_A, item.a_ts_code, "CNY")
            )
        if item.target_type == WATCHLIST_TARGET_H_ONLY and item.hk_ts_code:
            quote = self.realtime_market_data_service.provider.get_hk_quote(item.hk_ts_code)
            return self._quote_response(
                quote or self._unavailable_single_quote(REALTIME_MARKET_HK, item.hk_ts_code, "HKD")
            )
        return None

    def _unavailable_single_quote(self, market: str, symbol: str, currency: str) -> RealtimeQuote:
        """构造无快照占位，前端可明确显示暂无报价而不是误判接口缺字段。"""

        return RealtimeQuote(
            market=market,
            symbol=symbol,
            last_price=None,
            currency=currency,
            quote_time=None,
            source=None,
            quality=DEFAULT_QUOTE_QUALITY,
        )

    def _quote_response(self, quote: RealtimeQuote) -> RealtimeQuoteItem:
        """把实时快照 dataclass 转成 API 响应模型。"""

        return RealtimeQuoteItem(
            market=quote.market,
            symbol=quote.symbol,
            last_price=quote.last_price,
            currency=quote.currency,
            quote_time=quote.quote_time,
            source=quote.source,
            quality=quote.quality,
        )

    def _search_a_candidates(self, keyword: str, limit: int) -> list[WatchlistCandidateResponse]:
        statement = select(AStockBasic).where(
            or_(AStockBasic.list_status.is_(None), AStockBasic.list_status == "L")
        )
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                or_(
                    AStockBasic.ts_code.like(like),
                    AStockBasic.symbol.like(like),
                    AStockBasic.name.like(like),
                )
            )
        rows = list(self.db.scalars(statement.order_by(AStockBasic.ts_code).limit(limit)).all())
        return [
            WatchlistCandidateResponse(
                target_type=WATCHLIST_TARGET_A_ONLY,
                a_ts_code=item.ts_code,
                name=item.name,
                display_label=f"{item.name} {item.ts_code}",
            )
            for item in rows
        ]

    def _search_h_candidates(self, keyword: str, limit: int) -> list[WatchlistCandidateResponse]:
        statement = select(HKStockBasic).where(
            or_(HKStockBasic.list_status.is_(None), HKStockBasic.list_status == "L")
        )
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                or_(
                    HKStockBasic.ts_code.like(like),
                    HKStockBasic.name.like(like),
                    HKStockBasic.fullname.like(like),
                    HKStockBasic.cn_spell.like(like),
                )
            )
        rows = list(self.db.scalars(statement.order_by(HKStockBasic.ts_code).limit(limit)).all())
        return [
            WatchlistCandidateResponse(
                target_type=WATCHLIST_TARGET_H_ONLY,
                hk_ts_code=item.ts_code,
                name=item.name,
                display_label=f"{item.name} {item.ts_code}",
            )
            for item in rows
        ]

    def _search_pair_candidates(
        self,
        keyword: str,
        limit: int,
    ) -> list[WatchlistCandidateResponse]:
        statement = select(AHStockPair).where(AHStockPair.is_active.is_(True))
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                or_(
                    AHStockPair.a_ts_code.like(like),
                    AHStockPair.hk_ts_code.like(like),
                    AHStockPair.a_name.like(like),
                    AHStockPair.hk_name.like(like),
                )
            )
        rows = list(self.db.scalars(statement.order_by(AHStockPair.a_ts_code).limit(limit)).all())
        return [
            WatchlistCandidateResponse(
                target_type=WATCHLIST_TARGET_PAIR,
                a_ts_code=item.a_ts_code,
                hk_ts_code=item.hk_ts_code,
                name=item.a_name or item.hk_name or item.a_ts_code,
                display_label=(
                    f"{item.a_name or item.hk_name or item.a_ts_code} "
                    f"{item.a_ts_code} / {item.hk_ts_code}"
                ),
            )
            for item in rows
        ]

    def _ensure_push_binding_for_alert(self, item: WatchlistStock) -> None:
        if not item.push_enabled or not self._has_alert_config(item):
            return
        has_binding = self.db.scalar(
            select(PushplusBinding.id).where(
                PushplusBinding.user_id == item.user_id,
                PushplusBinding.is_active.is_(True),
            )
        )
        if has_binding is None:
            user = self.db.get(AppUser, item.user_id)
            if (
                user is not None
                and user.is_active
                and user.username == self.settings.default_admin_username
            ):
                return
            raise WatchlistError("设置提醒前请先完成 PushPlus 扫码绑定")

    def _has_alert_config(self, item: WatchlistStock) -> bool:
        return (
            (item.target_type == WATCHLIST_TARGET_PAIR and item.target_premium_pct is not None)
            or (item.a_price_alert_enabled and item.a_price_alert_target_price is not None)
            or (item.h_price_alert_enabled and item.h_price_alert_target_price is not None)
        )
