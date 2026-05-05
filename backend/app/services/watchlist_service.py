from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import WatchlistStock
from app.db.models.notification import PushplusBinding
from app.schemas.watchlist import WatchlistCreate, WatchlistOpportunityResponse, WatchlistUpdate
from app.services.premium_query_service import PremiumQueryService


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

    def __init__(self, db: Session) -> None:
        self.db = db
        self.premium_query_service = PremiumQueryService(db)

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
            premium_row = self.premium_query_service.latest_pair_row(
                item.a_ts_code,
                item.hk_ts_code,
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
            result.append(WatchlistOpportunityResponse(watchlist=item, premium=premium))
        return result

    def create(self, payload: WatchlistCreate, user_id: int = 1) -> WatchlistStock:
        """新增或恢复自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        existing = self._get_by_pair(payload.a_ts_code, payload.hk_ts_code, user_id)
        if existing is not None:
            self._apply_update(existing, payload.model_dump(exclude_none=False))
            self._ensure_push_binding_for_alert(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        item = WatchlistStock(
            a_ts_code=payload.a_ts_code.upper(),
            hk_ts_code=payload.hk_ts_code.upper(),
            user_id=user_id,
            display_name=payload.display_name,
            preferred_direction=self._normalize_direction(payload.preferred_direction),
            target_premium_pct=payload.target_premium_pct,
            price_alert_enabled=payload.price_alert_enabled,
            price_alert_market=self._normalize_price_alert_market(payload.price_alert_market),
            price_alert_operator=self._normalize_price_alert_operator(payload.price_alert_operator),
            price_alert_target_price=payload.price_alert_target_price,
            holding_market=self._normalize_holding_market(payload.holding_market),
            sort_order=payload.sort_order,
            note=payload.note,
            is_active=payload.is_active,
        )
        self._ensure_push_binding_for_alert(item)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

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

    def _get_by_pair(
        self,
        a_ts_code: str,
        hk_ts_code: str,
        user_id: int,
    ) -> WatchlistStock | None:
        return self.db.scalar(
            select(WatchlistStock).where(
                WatchlistStock.user_id == user_id,
                WatchlistStock.a_ts_code == a_ts_code.upper(),
                WatchlistStock.hk_ts_code == hk_ts_code.upper(),
            )
        )

    def _apply_update(self, item: WatchlistStock, values: dict[str, object]) -> None:
        for key, value in values.items():
            if key in {"a_ts_code", "hk_ts_code"}:
                setattr(item, key, str(value).upper())
            elif key == "preferred_direction" and value is not None:
                item.preferred_direction = self._normalize_direction(str(value))
            elif key == "holding_market" and value is not None:
                item.holding_market = self._normalize_holding_market(str(value))
            elif key == "price_alert_market" and value is not None:
                item.price_alert_market = self._normalize_price_alert_market(str(value))
            elif key == "price_alert_operator" and value is not None:
                item.price_alert_operator = self._normalize_price_alert_operator(str(value))
            else:
                setattr(item, key, value)

    def _normalize_direction(self, value: str) -> str:
        return "AH" if value.upper() == "AH" else "HA"

    def _normalize_holding_market(self, value: str) -> str:
        normalized = value.upper()
        return normalized if normalized in {"A", "H"} else "UNKNOWN"

    def _normalize_price_alert_market(self, value: str) -> str:
        normalized = value.upper()
        return normalized if normalized in {"A", "H"} else "UNKNOWN"

    def _normalize_price_alert_operator(self, value: str) -> str:
        normalized = value.upper()
        return normalized if normalized in {"GTE", "LTE"} else "GTE"

    def _ensure_push_binding_for_alert(self, item: WatchlistStock) -> None:
        if not self._has_alert_config(item):
            return
        has_binding = self.db.scalar(
            select(PushplusBinding.id).where(
                PushplusBinding.user_id == item.user_id,
                PushplusBinding.is_active.is_(True),
            )
        )
        if has_binding is None:
            raise WatchlistError("设置提醒前请先完成 PushPlus 扫码绑定")

    def _has_alert_config(self, item: WatchlistStock) -> bool:
        return item.target_premium_pct is not None or (
            item.price_alert_enabled
            and item.price_alert_market in {"A", "H"}
            and item.price_alert_target_price is not None
        )
