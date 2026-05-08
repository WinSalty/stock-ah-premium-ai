from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260508_0031"
down_revision = "20260508_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 打板报告缓存表按交易日、模型、提示词版本和数据快照去重；
    # 定时任务重跑时优先复用 READY 报告，避免同一份 KPL 数据重复消耗 LLM 调用。
    op.create_table(
        "limit_up_analysis_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
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
            "model",
            "prompt_version",
            "data_snapshot_hash",
            name="uk_limit_up_analysis_snapshot",
        ),
    )
    op.create_index(
        "idx_limit_up_analysis_trade_status",
        "limit_up_analysis_cache",
        ["trade_date", "status"],
    )
    op.create_index(
        "idx_limit_up_analysis_generated",
        "limit_up_analysis_cache",
        ["generated_at"],
    )

    # 接收人表只引用系统用户，不直接保存 PushPlus 好友 token；
    # 推送时再通过既有绑定表解析通道，保证用户换绑后配置无需迁移。
    op.create_table(
        "limit_up_push_recipient",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uk_limit_up_push_recipient_user"),
    )
    op.create_index(
        "idx_limit_up_push_recipient_enabled",
        "limit_up_push_recipient",
        ["enabled"],
    )

    # 业务推送流水与 PushPlus 原始流水分离：这里负责幂等计划和重试状态，
    # pushplus_message_log 继续记录真实提交给 PushPlus 的消息体和响应结果。
    op.create_table(
        "limit_up_push_delivery",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("limit_up_analysis_cache.id"), nullable=False),
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
            name="uk_limit_up_push_delivery_once",
        ),
    )
    op.create_index(
        "idx_limit_up_push_delivery_status",
        "limit_up_push_delivery",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "idx_limit_up_push_delivery_user",
        "limit_up_push_delivery",
        ["user_id", "scheduled_at"],
    )

    # 新增打板推送管理员菜单权限；只追加缺失权限，保护用户已手动维护的菜单顺序和其它权限。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json =
          JSON_ARRAY_APPEND(menu_permissions_json, '$', 'limit_up_push')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('limit_up_push')) = 0
        """
    )
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_ARRAY(
          'overview',
          'sync',
          'query',
          'premium',
          'chat',
          'llm_metrics',
          'users',
          'pushplus',
          'limit_up_push',
          'profile'
        )
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚时先清理权限，再按外键依赖顺序删除业务表，避免残留不可达菜单入口。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'limit_up_push'))
        )
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'limit_up_push') IS NOT NULL
        """
    )
    op.drop_index("idx_limit_up_push_delivery_user", table_name="limit_up_push_delivery")
    op.drop_index("idx_limit_up_push_delivery_status", table_name="limit_up_push_delivery")
    op.drop_table("limit_up_push_delivery")
    op.drop_index("idx_limit_up_push_recipient_enabled", table_name="limit_up_push_recipient")
    op.drop_table("limit_up_push_recipient")
    op.drop_index("idx_limit_up_analysis_generated", table_name="limit_up_analysis_cache")
    op.drop_index("idx_limit_up_analysis_trade_status", table_name="limit_up_analysis_cache")
    op.drop_table("limit_up_analysis_cache")
