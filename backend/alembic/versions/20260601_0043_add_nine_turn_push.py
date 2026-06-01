from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260601_0043"
down_revision = "20260530_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 神奇九转报告按交易日、频率、模型、提示词版本和数据快照幂等缓存；
    # 定时任务重跑或接口延迟恢复时只为真实变化的数据重新生成 LLM 报告。
    op.create_table(
        "nine_turn_analysis_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("freq", sa.String(length=16), nullable=False, server_default="daily"),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("data_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("content_html", mysql.LONGTEXT(), nullable=True),
        sa.Column("content_markdown", mysql.LONGTEXT(), nullable=True),
        sa.Column("context_json", mysql.LONGTEXT(), nullable=True),
        sa.Column("data_quality_json", mysql.LONGTEXT(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "trade_date",
            "freq",
            "model",
            "prompt_version",
            "data_snapshot_hash",
            name="uk_nine_turn_analysis_snapshot",
        ),
    )
    op.create_index(
        "idx_nine_turn_analysis_trade_status",
        "nine_turn_analysis_cache",
        ["trade_date", "status"],
    )
    op.create_index(
        "idx_nine_turn_analysis_generated",
        "nine_turn_analysis_cache",
        ["generated_at"],
    )

    # 九转推送流水复用打板接收人名单，但单独记录业务计划；
    # 这样同一报告对同一用户、同一调度计划只会提交一次 PushPlus。
    op.create_table(
        "nine_turn_push_delivery",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("nine_turn_analysis_cache.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("scheduled_kind", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("pushplus_message_log_id", sa.Integer(), sa.ForeignKey("pushplus_message_log.id"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "analysis_id",
            "scheduled_kind",
            "scheduled_at",
            "user_id",
            name="uk_nine_turn_push_delivery_once",
        ),
    )
    op.create_index(
        "idx_nine_turn_push_delivery_status",
        "nine_turn_push_delivery",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "idx_nine_turn_push_delivery_user",
        "nine_turn_push_delivery",
        ["user_id", "scheduled_at"],
    )

    # 雪球流水增加九转报告外键，source_type 区分来源；
    # 旧打板流水继续使用 analysis_id，九转发文不复用打板报告 ID，避免列表和幂等记录串源。
    op.add_column(
        "xueqiu_publish_record",
        sa.Column("nine_turn_analysis_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_xueqiu_publish_record_nine_turn_analysis",
        "xueqiu_publish_record",
        "nine_turn_analysis_cache",
        ["nine_turn_analysis_id"],
        ["id"],
    )
    op.create_index(
        "idx_xueqiu_publish_record_nine_turn",
        "xueqiu_publish_record",
        ["nine_turn_analysis_id", "publish_mode", "created_at"],
    )


def downgrade() -> None:
    # 回滚时先移除雪球外键和索引，再按依赖顺序删除九转推送流水与报告缓存。
    op.drop_index("idx_xueqiu_publish_record_nine_turn", table_name="xueqiu_publish_record")
    op.drop_constraint(
        "fk_xueqiu_publish_record_nine_turn_analysis",
        "xueqiu_publish_record",
        type_="foreignkey",
    )
    op.drop_column("xueqiu_publish_record", "nine_turn_analysis_id")
    op.drop_index("idx_nine_turn_push_delivery_user", table_name="nine_turn_push_delivery")
    op.drop_index("idx_nine_turn_push_delivery_status", table_name="nine_turn_push_delivery")
    op.drop_table("nine_turn_push_delivery")
    op.drop_index("idx_nine_turn_analysis_generated", table_name="nine_turn_analysis_cache")
    op.drop_index("idx_nine_turn_analysis_trade_status", table_name="nine_turn_analysis_cache")
    op.drop_table("nine_turn_analysis_cache")
