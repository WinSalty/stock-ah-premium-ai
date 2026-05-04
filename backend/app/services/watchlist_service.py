from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.market import WatchlistStock
from app.schemas.watchlist import WatchlistCreate, WatchlistOpportunityResponse, WatchlistUpdate
from app.services.premium_query_service import PremiumQueryService


class WatchlistService:
    """用户自选股服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.premium_query_service = PremiumQueryService(db)

    def list_opportunities(self, active_only: bool = True) -> list[WatchlistOpportunityResponse]:
        """查询自选股机会状态。

        创建日期：2026-05-04
        author: sunshengxian
        """

        statement = select(WatchlistStock)
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

    def create(self, payload: WatchlistCreate) -> WatchlistStock:
        """新增或恢复自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        existing = self._get_by_pair(payload.a_ts_code, payload.hk_ts_code)
        if existing is not None:
            self._apply_update(existing, payload.model_dump(exclude_none=False))
            self.db.commit()
            self.db.refresh(existing)
            return existing
        item = WatchlistStock(
            a_ts_code=payload.a_ts_code.upper(),
            hk_ts_code=payload.hk_ts_code.upper(),
            display_name=payload.display_name,
            preferred_direction=self._normalize_direction(payload.preferred_direction),
            target_premium_pct=payload.target_premium_pct,
            holding_market=self._normalize_holding_market(payload.holding_market),
            sort_order=payload.sort_order,
            note=payload.note,
            is_active=payload.is_active,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def update(self, item_id: int, payload: WatchlistUpdate) -> WatchlistStock | None:
        """更新自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        item = self.db.get(WatchlistStock, item_id)
        if item is None:
            return None
        self._apply_update(item, payload.model_dump(exclude_unset=True))
        self.db.commit()
        self.db.refresh(item)
        return item

    def deactivate(self, item_id: int) -> bool:
        """停用自选股。

        创建日期：2026-05-04
        author: sunshengxian
        """

        item = self.db.get(WatchlistStock, item_id)
        if item is None:
            return False
        item.is_active = False
        self.db.commit()
        return True

    def _get_by_pair(self, a_ts_code: str, hk_ts_code: str) -> WatchlistStock | None:
        return self.db.scalar(
            select(WatchlistStock).where(
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
            else:
                setattr(item, key, value)

    def _normalize_direction(self, value: str) -> str:
        return "AH" if value.upper() == "AH" else "HA"

    def _normalize_holding_market(self, value: str) -> str:
        normalized = value.upper()
        return normalized if normalized in {"A", "H"} else "UNKNOWN"
