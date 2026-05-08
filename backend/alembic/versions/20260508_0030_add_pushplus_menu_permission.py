from __future__ import annotations

from alembic import op

revision = "20260508_0030"
down_revision = "20260508_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PushPlus 从用户管理拆成独立菜单后，给已有管理员补齐权限；
    # 只追加缺失权限，重复执行或已手动授权的账号不会产生重复项。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json =
          JSON_ARRAY_APPEND(menu_permissions_json, '$', 'pushplus')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('pushplus')) = 0
        """
    )
    # 极少数历史管理员可能没有单独权限 JSON，这里按当前管理员默认菜单写入，
    # 保证迁移后能立即看到新拆分的 PushPlus 菜单。
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
          'profile'
        )
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚菜单拆分时移除管理员 JSON 中的 pushplus 权限；
    # 只处理存在该权限的记录，避免 JSON_SEARCH 为空导致 JSON_REMOVE 报错。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'pushplus'))
        )
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'pushplus') IS NOT NULL
        """
    )
