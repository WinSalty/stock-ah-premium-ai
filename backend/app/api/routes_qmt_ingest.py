"""QMT 回流 ingest 接口（机器对机器）。

业务意图：接收执行侧（QMT/Windows）盘后 POST 来的 qmt_* 当日数据，幂等落库到信号侧 MySQL，
    供复盘看板 / 闭环归因 / 只读对账消费。与 watchlist 只读导出接口（GET /internal/watchlist）配对，
    共同构成「信号侧托管双接口、执行侧纯客户端」的 HTTP 数据交互（详见 doc/07）。

鉴权：内网 token（X-Internal-Token 头，机器对机器，不走登录 JWT）；token 未配置即 503 关闭，
    缺失/不符一律 401（常量时间比较防时序侧信道）。默认复用 watchlist 导出 token（可单独配置）。

幂等/事务：service 逐条 ON DUPLICATE KEY UPDATE，全部成功才 commit 返回 200；任一记录失败则整批
    rollback + 非 2xx，执行侧据此保 synced=0 下轮重试（幂等安全）。校验失败 422、落库异常 500。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.qmt_ingest import QmtIngestRequest, QmtIngestResponse
from app.services.qmt_ingest_service import QmtIngestService, QmtIngestValidationError

logger = logging.getLogger(__name__)
router = APIRouter()

DbSession = Annotated[Session, Depends(get_db)]


def require_qmt_ingest_token(
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    """内网 token 鉴权：token 未配置→503（默认关闭）；缺失/不符→401（常量时间比较）。"""

    expected = get_settings().resolve_qmt_ingest_internal_token()
    if not expected:
        raise HTTPException(status_code=503, detail="qmt 回流接口未开启")
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="内网鉴权失败")


@router.post(
    "/internal/qmt/ingest",
    response_model=QmtIngestResponse,
    dependencies=[Depends(require_qmt_ingest_token)],
)
def ingest_qmt(payload: QmtIngestRequest, db: DbSession) -> QmtIngestResponse:
    """幂等回流执行侧 qmt_* 当日数据。"""

    if not payload.records:
        # 空请求合法但无意义：直接返回 200 空结果，避免执行侧把空批当失败重试。
        return QmtIngestResponse(ok=True, total=0, by_table={})

    service = QmtIngestService(db)
    try:
        by_table = service.ingest(payload)
        db.commit()
    except QmtIngestValidationError as exc:
        # 来料校验失败：回滚并 422（数据由 mappers 生成，正常不应触发；触发记日志便于定位）。
        db.rollback()
        logger.warning("qmt 回流来料校验失败 account_id=%s err=%s", payload.account_id, exc)
        raise HTTPException(status_code=422, detail=f"回流数据非法：{exc}") from exc
    except Exception as exc:
        # 落库异常：回滚并 500，执行侧保 synced=0 下轮重试（幂等安全）。
        db.rollback()
        logger.exception("qmt 回流落库失败 account_id=%s", payload.account_id)
        raise HTTPException(status_code=500, detail="回流落库失败") from exc

    total = sum(by_table.values())
    logger.info(
        "qmt 回流成功 account_id=%s trade_date=%s total=%s by_table=%s",
        payload.account_id, payload.trade_date, total, by_table,
    )
    return QmtIngestResponse(ok=True, total=total, by_table=by_table)
