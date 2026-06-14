"""QMT 实盘复盘看板只读接口。

业务意图：为前端「实盘复盘」菜单提供账户清单 / 当日汇总 / 成交明细 / 持仓 / 历史净值五类只读数据。
全部接口挂 require_permission("qmt_review")（默认仅 admin 有该权限）；当前 admin 可见全部账户，
非 admin 多账户隔离待 qmt_account 绑定表落地（见 routes 内注释）。

入参缺省口径：account_id 缺省取最新有数据账户；trade_date 缺省取该账户已回流的最新交易日；
无任何数据时返回空壳响应（has_data=false / 空列表），前端据此展示空态而非报错。

创建日期：2026-06-14
author: claude
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import require_permission
from app.db.session import get_db
from app.schemas.qmt_review import (
    QmtAccountInfo,
    QmtDailySummary,
    QmtHistoryStats,
    QmtPositionItem,
    QmtSelectionResp,
    QmtTradesPage,
)
from app.services.qmt_review_service import QmtReviewService

# 整组接口要求 qmt_review 权限（默认仅 admin 角色具备）。
router = APIRouter(dependencies=[Depends(require_permission("qmt_review"))])
DbSession = Annotated[Session, Depends(get_db)]


def _resolve_account(svc: QmtReviewService, account_id: str | None) -> str | None:
    """账户缺省解析：未指定则取最新有数据账户。"""
    return account_id or svc.default_account()


def _resolve_date(svc: QmtReviewService, account_id: str, trade_date: date | None) -> date | None:
    """交易日缺省解析：未指定则取该账户最新交易日。"""
    return trade_date or svc.latest_trade_date(account_id)


@router.get("/review/accounts", response_model=list[QmtAccountInfo])
def list_accounts(db: DbSession) -> list[QmtAccountInfo]:
    """已回流账户清单（供顶部账户切换）。"""
    return QmtReviewService(db).list_accounts()


@router.get("/review/daily", response_model=QmtDailySummary)
def daily_summary(
    db: DbSession,
    account_id: Annotated[str | None, Query(description="资金账号，缺省取最新账户")] = None,
    trade_date: Annotated[date | None, Query(description="交易日，缺省取最新交易日")] = None,
) -> QmtDailySummary:
    """当日复盘汇总卡片。"""
    svc = QmtReviewService(db)
    acct = _resolve_account(svc, account_id)
    if acct is None:
        # 全库无任何账户数据：返回空壳，前端显示「暂无回流数据」。
        return QmtDailySummary(trade_date=trade_date or date.today(), has_data=False)
    eff_date = _resolve_date(svc, acct, trade_date)
    if eff_date is None:
        return QmtDailySummary(trade_date=trade_date or date.today(), has_data=False)
    return svc.daily_summary(acct, eff_date)


@router.get("/review/trades", response_model=QmtTradesPage)
def list_trades(
    db: DbSession,
    account_id: Annotated[str | None, Query(description="资金账号，缺省取最新账户")] = None,
    trade_date: Annotated[date | None, Query(description="交易日，缺省取最新交易日；传则只看当日")] = None,
    side: Annotated[str | None, Query(description="方向过滤 BUY/SELL")] = None,
    page: Annotated[int, Query(ge=1, description="页码(从1起)")] = 1,
    page_size: Annotated[int, Query(ge=1, le=200, description="每页条数")] = 50,
) -> QmtTradesPage:
    """成交明细分页（含回挂信号侧策略/角色）。"""
    svc = QmtReviewService(db)
    acct = _resolve_account(svc, account_id)
    if acct is None:
        return QmtTradesPage(items=[], total=0, page=page, page_size=page_size)
    eff_date = _resolve_date(svc, acct, trade_date)
    return svc.trades(acct, eff_date, side, page, page_size)


@router.get("/review/positions", response_model=list[QmtPositionItem])
def list_positions(
    db: DbSession,
    account_id: Annotated[str | None, Query(description="资金账号，缺省取最新账户")] = None,
    trade_date: Annotated[date | None, Query(description="交易日，缺省取最新交易日")] = None,
) -> list[QmtPositionItem]:
    """指定日收盘持仓（无该日取 ≤该日 最近 CLOSE 日）。"""
    svc = QmtReviewService(db)
    acct = _resolve_account(svc, account_id)
    if acct is None:
        return []
    eff_date = _resolve_date(svc, acct, trade_date)
    if eff_date is None:
        return []
    return svc.positions(acct, eff_date)


@router.get("/review/selection", response_model=QmtSelectionResp)
def selection(
    db: DbSession,
    signal_date: Annotated[
        date | None, Query(alias="date", description="信号日 T，缺省取最新有选股的交易日")
    ] = None,
) -> QmtSelectionResp:
    """信号选股决策明细（什么信号达标 / 为什么入选）。"""
    return QmtReviewService(db).selection(signal_date)


@router.get("/review/history", response_model=QmtHistoryStats)
def history(
    db: DbSession,
    account_id: Annotated[str | None, Query(description="资金账号，缺省取最新账户")] = None,
    start: Annotated[date | None, Query(description="起始交易日(含)")] = None,
    end: Annotated[date | None, Query(description="截止交易日(含)")] = None,
) -> QmtHistoryStats:
    """历史净值曲线 + 绩效指标。"""
    svc = QmtReviewService(db)
    acct = _resolve_account(svc, account_id)
    if acct is None:
        return QmtHistoryStats(points=[], trading_days=0)
    return svc.history(acct, start, end)
