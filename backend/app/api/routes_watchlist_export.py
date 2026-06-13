"""watchlist 只读导出接口（机器对机器）。

业务意图：把 limit_up_selected_stock 解析为结构化契约 LimitUpWatchlistResponse，供外部回测/
    对账/QMT 执行侧只读消费，避免外部耦合表结构。与"对方直读 MySQL"二选一，默认走本接口。
鉴权：内网 token（X-Internal-Token 头，机器对机器，不走登录 JWT）；token 未配置即 503 关闭，
    缺失/不符一律 401（常量时间比较防时序侧信道）。
口径：date=信号日 T；prompt_version 缺省取该 trade_date 最新 READY 报告版本；无数据返回 200 空集；
    JSON 列坏行记日志后跳过、不整请求 500；接口全程只读。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import hmac
import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.notification import LimitUpAnalysisCache, LimitUpSelectedStock
from app.db.session import get_db
from app.schemas.limit_up_watchlist import LimitUpWatchlistItem, LimitUpWatchlistResponse

logger = logging.getLogger(__name__)
router = APIRouter()

DbSession = Annotated[Session, Depends(get_db)]

# 报告 READY 状态常量（与 limit_up_push_service.ANALYSIS_STATUS_READY 同值，
# 本地内联以避免循环导入）。
_ANALYSIS_STATUS_READY = "READY"


def require_internal_token(
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    """内网 token 鉴权：token 未配置→503（默认关闭）；缺失/不符→401（常量时间比较）。

    创建日期：2026-06-13
    author: claude
    """

    expected = get_settings().resolve_watchlist_export_internal_token()
    if not expected:
        raise HTTPException(status_code=503, detail="watchlist 只读导出未开启")
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="内网鉴权失败")


@router.get(
    "/internal/watchlist",
    response_model=LimitUpWatchlistResponse,
    dependencies=[Depends(require_internal_token)],
)
def export_watchlist(
    db: DbSession,
    date_: Annotated[
        date, Query(alias="date", description="信号日 T，东八区交易日 YYYY-MM-DD")
    ],
    prompt_version: Annotated[
        str | None, Query(description="缺省取该交易日最新 READY 报告版本")
    ] = None,
) -> LimitUpWatchlistResponse:
    """按信号日 T 导出当日入选股全集（只读）。

    创建日期：2026-06-13
    author: claude
    """

    pv = prompt_version
    if pv is None:
        # 缺省版本：取该 trade_date 最新 READY 报告的 prompt_version，保证导出与当前生效报告一致。
        pv = db.execute(
            select(LimitUpAnalysisCache.prompt_version)
            .where(
                LimitUpAnalysisCache.trade_date == date_,
                LimitUpAnalysisCache.status == _ANALYSIS_STATUS_READY,
            )
            .order_by(desc(LimitUpAnalysisCache.generated_at))
            .limit(1)
        ).scalar_one_or_none()
    if pv is None:
        # 当日无 READY 报告：返回空集（200，外部轮询友好），不 404。
        return LimitUpWatchlistResponse(trade_date=date_, count=0, items=[])

    rows = (
        db.execute(
            select(LimitUpSelectedStock)
            .where(
                LimitUpSelectedStock.trade_date == date_,
                LimitUpSelectedStock.prompt_version == pv,
            )
            .order_by(LimitUpSelectedStock.tier, LimitUpSelectedStock.priority)
        )
        .scalars()
        .all()
    )
    items: list[LimitUpWatchlistItem] = []
    for row in rows:
        try:
            items.append(LimitUpWatchlistItem.model_validate(row))
        except Exception:
            # JSON 列坏行：记日志跳过该行，不让整请求 500。
            logger.warning(
                "watchlist 导出跳过坏行 trade_date=%s ts_code=%s",
                date_,
                getattr(row, "ts_code", "?"),
                exc_info=True,
            )
    return LimitUpWatchlistResponse(
        trade_date=date_,
        target_trade_date=items[0].target_trade_date if items else None,
        market_state=items[0].market_state if items else None,
        count=len(items),
        items=items,
    )
