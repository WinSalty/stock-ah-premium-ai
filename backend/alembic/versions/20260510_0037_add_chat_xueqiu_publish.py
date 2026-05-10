from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260510_0037"
down_revision = "20260510_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 雪球发布流水从“打板报告专用”扩展为多来源，问答回答会记录 assistant 消息 ID；
    # 打板报告历史流水统一标记为 LIMIT_UP_REPORT，保持原有审计数据可查。
    op.add_column(
        "xueqiu_publish_record",
        sa.Column("chat_message_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "xueqiu_publish_record",
        sa.Column(
            "source_type",
            sa.String(length=32),
            nullable=False,
            server_default="LIMIT_UP_REPORT",
        ),
    )
    op.create_foreign_key(
        "fk_xueqiu_publish_record_chat_message",
        "xueqiu_publish_record",
        "llm_chat_message",
        ["chat_message_id"],
        ["id"],
    )
    op.alter_column(
        "xueqiu_publish_record",
        "analysis_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_index(
        "idx_xueqiu_publish_record_chat",
        "xueqiu_publish_record",
        ["chat_message_id", "publish_mode", "created_at"],
    )
    # 问答页发布雪球是独立动作权限，不作为侧边栏页面展示；默认只追加给管理员。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json =
          JSON_ARRAY_APPEND(menu_permissions_json, '$', 'chat_xueqiu_publish')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('chat_xueqiu_publish')) = 0
        """
    )
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_ARRAY('chat_xueqiu_publish')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚只移除问答发布相关字段和权限；已有打板报告流水仍保留。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'chat_xueqiu_publish'))
        )
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'chat_xueqiu_publish') IS NOT NULL
        """
    )
    op.drop_index("idx_xueqiu_publish_record_chat", table_name="xueqiu_publish_record")
    op.drop_constraint(
        "fk_xueqiu_publish_record_chat_message",
        "xueqiu_publish_record",
        type_="foreignkey",
    )
    op.alter_column(
        "xueqiu_publish_record",
        "analysis_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("xueqiu_publish_record", "source_type")
    op.drop_column("xueqiu_publish_record", "chat_message_id")
