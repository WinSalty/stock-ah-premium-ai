from __future__ import annotations

from alembic import op

revision = "20260530_0041"
down_revision = "20260529_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 分红再投筛选是独立菜单，给既有管理员补齐权限；普通用户后续可由用户管理手动授权。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json =
          JSON_ARRAY_APPEND(menu_permissions_json, '$', 'dividend_reinvestment')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('dividend_reinvestment')) = 0
        """
    )
    # 极少数历史管理员没有菜单 JSON 时，写入包含新菜单的管理员默认权限，保证迁移后可见。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_ARRAY(
          'overview',
          'sync',
          'query',
          'premium',
          'dividend_reinvestment',
          'chat',
          'image_generation',
          'llm_metrics',
          'users',
          'pushplus',
          'limit_up_push',
          'xueqiu_publish',
          'chat_xueqiu_publish',
          'profile'
        )
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚时只移除分红再投筛选权限，不触碰用户手动配置的其他菜单权限。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'dividend_reinvestment'))
        )
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'dividend_reinvestment') IS NOT NULL
        """
    )
