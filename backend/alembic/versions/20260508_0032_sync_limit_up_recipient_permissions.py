from __future__ import annotations

from alembic import op

revision = "20260508_0032"
down_revision = "20260508_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 历史已启用的打板接收人需要补齐菜单权限，否则只能收到推送却看不到报告入口；
    # 仅追加缺失的 limit_up_push，不改变用户已有其它菜单授权。
    op.execute(
        """
        UPDATE app_user u
        JOIN limit_up_push_recipient r ON r.user_id = u.id AND r.enabled = 1
        SET u.menu_permissions_json = JSON_ARRAY_APPEND(u.menu_permissions_json, '$', 'limit_up_push')
        WHERE u.menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(u.menu_permissions_json, JSON_QUOTE('limit_up_push')) = 0
        """
    )
    op.execute(
        """
        UPDATE app_user u
        JOIN limit_up_push_recipient r ON r.user_id = u.id AND r.enabled = 1
        SET u.menu_permissions_json = JSON_ARRAY('limit_up_push')
        WHERE u.menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚只撤销普通用户因接收人身份获得的打板入口；管理员保留管理菜单，避免回滚误删管理权限。
    op.execute(
        """
        UPDATE app_user u
        JOIN limit_up_push_recipient r ON r.user_id = u.id AND r.enabled = 1
        SET u.menu_permissions_json = JSON_REMOVE(
          u.menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(u.menu_permissions_json, 'one', 'limit_up_push'))
        )
        WHERE u.role <> 'ADMIN'
          AND u.menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(u.menu_permissions_json, 'one', 'limit_up_push') IS NOT NULL
        """
    )
