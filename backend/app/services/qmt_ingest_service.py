"""QMT 回流 ingest 服务（执行侧 → 信号侧 MySQL 幂等落库）。

业务意图：把执行侧盘后 POST 来的 qmt_* 行（mappers.*_to_row 的 JSON 友好字典）反序列化为
    数据库类型并 `INSERT ... ON DUPLICATE KEY UPDATE` 落库，供复盘/归因消费。

关键不变量：
1. **幂等**：按各表加固唯一键 upsert（含 trade_date），同一行重传只更新不新增；
   signal_trade_date / *_east8 走 COALESCE——已回填的非空值不被后到的空值覆盖（回填口径单一来源）。
2. **类型安全**：来料是字符串/ISO/0-1 的 JSON 友好值，按 ORM 列类型逐列反序列化
   （DECIMAL→Decimal、Date→date、DateTime→datetime、Boolean→bool、Int→int），杜绝把字符串
   直接写进数值/日期列导致的隐式转换坑。
3. **白名单**：只允许四张 qmt_* 表，未知表名抛 QmtIngestValidationError（接口转 422）。
4. **事务一致**：service 只执行 upsert 不 commit，事务由接口层统一 commit/rollback；任一记录失败
   则整批回滚 + 抛错，执行侧据非 2xx 保 synced=0 下轮重试（幂等使重试安全）。

创建日期：2026-06-13
author: claude
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models.qmt import QmtAccountDaily, QmtOrder, QmtPositionSnapshot, QmtTrade
from app.schemas.qmt_ingest import QMT_INGEST_TABLES, QmtIngestRecord, QmtIngestRequest

logger = logging.getLogger(__name__)


class QmtIngestValidationError(ValueError):
    """来料校验失败（未知表名 / 缺主键列等），接口层转 422。"""


# —— 各表落库口径：ORM 模型、加固唯一键列（不进 UPDATE）、COALESCE 列（不被空覆盖）——
# 单一来源，避免散落 if/elif；与 alembic 0053 / 执行侧 storage.schema.TABLE_META 对齐。
_TABLE_SPEC: dict[str, dict[str, Any]] = {
    "qmt_trade": {
        "model": QmtTrade,
        # unique 用有序元组（SQLite on_conflict 的 index_elements 需按唯一索引列序传入）。
        "unique": ("account_id", "trade_date", "traded_id"),
        "coalesce": {"signal_trade_date", "traded_time_east8"},
    },
    "qmt_order": {
        "model": QmtOrder,
        "unique": ("account_id", "trade_date", "order_id"),
        "coalesce": {"signal_trade_date", "order_time_east8"},
    },
    "qmt_position_snapshot": {
        "model": QmtPositionSnapshot,
        "unique": ("account_id", "trade_date", "ts_code", "snapshot_type"),
        "coalesce": set(),
    },
    "qmt_account_daily": {
        "model": QmtAccountDaily,
        "unique": ("account_id", "trade_date", "snapshot_type"),
        "coalesce": set(),
    },
}

# 落库时不接受来料覆盖的列（DB 自管）：主键与审计时间。
_DB_MANAGED = {"id", "created_at", "updated_at"}


def _coerce_value(coltype: Any, value: Any) -> Any:
    """按 ORM 列类型把 JSON 友好来料反序列化为 DB 期望的 Python 类型。

    口径（与执行侧 mappers 逆向一致）：
    - None / 空串 → None（不臆造默认，交由 DB 列默认或保持空）；
    - Date：取 ISO 前 10 位转 date；DateTime：fromisoformat 转 datetime（含 UTC naive）；
    - Numeric/DECIMAL：转 Decimal（非法 → 抛 QmtIngestValidationError，杜绝脏数值静默落库）；
    - Boolean：'0'/'1'/0/1/true/false 统一转 bool；
    - Integer：转 int（成交量/订单号等，BigInteger 也走 Integer 分支）。
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "" and not isinstance(coltype, (Date, DateTime)):
        return None
    try:
        if isinstance(coltype, Date) and not isinstance(coltype, DateTime):
            if isinstance(value, date) and not isinstance(value, datetime):
                return value
            return date.fromisoformat(str(value)[:10])
        if isinstance(coltype, DateTime):
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value))
        if isinstance(coltype, Numeric):
            if isinstance(value, Decimal):
                return value
            return Decimal(str(value))
        if isinstance(coltype, Boolean):
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on", "t", "y"}
        if isinstance(coltype, Integer):
            return int(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise QmtIngestValidationError(f"列值反序列化失败：{value!r} -> {coltype} ({exc})") from exc
    # 其余（String/Text）原样转字符串。
    return str(value)


def _coerce_row(model: Any, data: dict[str, Any]) -> dict[str, Any]:
    """把来料字典裁剪为「该表合法列」并逐列反序列化；过滤未知列与 DB 自管列。

    边界：只保留 data 中确为该表列、且非 DB 自管的键；未知列直接丢弃（向后兼容执行侧多送字段）。
    """
    columns = {c.name: c.type for c in model.__table__.columns}
    coerced: dict[str, Any] = {}
    for key, raw in data.items():
        if key in _DB_MANAGED or key not in columns:
            continue
        coerced[key] = _coerce_value(columns[key], raw)
    return coerced


class QmtIngestService:
    """执行侧 qmt_* 回流幂等落库服务。"""

    def __init__(self, db: Session):
        self._db = db

    def ingest(self, request: QmtIngestRequest) -> dict[str, int]:
        """逐条 upsert 全部 records，返回各表成功行数。只执行不 commit（事务由接口层控制）。

        任一记录抛错则整体上抛（接口层 rollback + 非 2xx），执行侧据此保 synced=0 重试。
        """
        by_table: dict[str, int] = {}
        for record in request.records:
            table = self._upsert_one(record)
            by_table[table] = by_table.get(table, 0) + 1
        return by_table

    def _upsert_one(self, record: QmtIngestRecord) -> str:
        """校验表名 → 反序列化 → 按方言构造幂等 upsert → 执行。返回表名。

        方言适配：生产 MySQL 用 ON DUPLICATE KEY UPDATE；测试/其它用 SQLite ON CONFLICT DO UPDATE。
        两者语义一致：唯一键命中则更新非键列，COALESCE 列已非空不被后到空值覆盖。
        """
        table = record.table
        if table not in QMT_INGEST_TABLES:
            raise QmtIngestValidationError(f"不支持的回流表：{table}")
        spec = _TABLE_SPEC[table]
        model = spec["model"]
        unique_cols: tuple[str, ...] = spec["unique"]
        unique_set = set(unique_cols)
        coalesce_cols: set[str] = spec["coalesce"]

        values = _coerce_row(model, record.data)
        # 唯一键列必须齐全，否则 upsert 无法定位/去重，按校验失败处理（杜绝串号）。
        missing = [c for c in unique_cols if values.get(c) is None]
        if missing:
            raise QmtIngestValidationError(f"{table} 缺少唯一键列：{missing}")

        sa_table = model.__table__
        # 待更新列：排除唯一键列、DB 自管列、本次未提供的列。
        updatable = [
            c.name
            for c in sa_table.columns
            if c.name not in unique_set and c.name not in _DB_MANAGED and c.name in values
        ]

        dialect = self._db.get_bind().dialect.name
        if dialect == "mysql":
            stmt = mysql_insert(sa_table).values(**values)
            ins = stmt.inserted  # 等价 MySQL VALUES(col)
            update_map = {
                name: (
                    func.coalesce(ins[name], sa_table.c[name])
                    if name in coalesce_cols else ins[name]
                )
                for name in updatable
            }
            stmt = stmt.on_duplicate_key_update(**update_map)
        else:
            # SQLite（单测）/ 兼容 ON CONFLICT 的方言：index_elements 按唯一索引列序传入。
            stmt = sqlite_insert(sa_table).values(**values)
            exc = stmt.excluded  # 等价 SQLite excluded.col
            update_map = {
                name: (
                    func.coalesce(exc[name], sa_table.c[name])
                    if name in coalesce_cols else exc[name]
                )
                for name in updatable
            }
            stmt = stmt.on_conflict_do_update(index_elements=list(unique_cols), set_=update_map)

        self._db.execute(stmt)
        return table
