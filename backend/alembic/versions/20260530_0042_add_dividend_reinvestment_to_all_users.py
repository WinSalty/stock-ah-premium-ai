from __future__ import annotations

from alembic import op

revision = "20260530_0042"
down_revision = "20260530_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 分红再投筛选改为所有用户默认可见：已有用户在保留原菜单配置的基础上只追加缺失项。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json =
          JSON_ARRAY_APPEND(menu_permissions_json, '$', 'dividend_reinvestment')
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('dividend_reinvestment')) = 0
        """
    )
    # 极少数历史用户没有菜单 JSON 时，按普通用户默认入口补齐，避免迁移后仍看不到新菜单。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_ARRAY(
          'overview',
          'premium',
          'dividend_reinvestment',
          'chat',
          'image_generation',
          'profile'
        )
        WHERE menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚只撤销非管理员的默认分红再投入口；管理员入口由 0041 迁移负责，避免误删管理权限。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'dividend_reinvestment'))
        )
        WHERE role <> 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'dividend_reinvestment') IS NOT NULL
        """
    )
