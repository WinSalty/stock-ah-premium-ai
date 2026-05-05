from __future__ import annotations

from alembic import op

revision = "20260505_0012"
down_revision = "20260505_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json =
          JSON_ARRAY_APPEND(menu_permissions_json, '$', 'llm_metrics')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('llm_metrics')) = 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'llm_metrics'))
        )
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'llm_metrics') IS NOT NULL
        """
    )
