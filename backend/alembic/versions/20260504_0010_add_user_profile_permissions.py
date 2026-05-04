from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260504_0010"
down_revision = "20260504_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("display_name", sa.String(length=64), nullable=True))
    op.add_column("app_user", sa.Column("email", sa.String(length=128), nullable=True))
    op.add_column("app_user", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("app_user", sa.Column("bio", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("menu_permissions_json", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = CASE
          WHEN role = 'ADMIN' THEN '["overview","sync","query","premium","chat","users","profile"]'
          ELSE '["overview","premium","chat","profile"]'
        END
        WHERE menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("app_user", "menu_permissions_json")
    op.drop_column("app_user", "bio")
    op.drop_column("app_user", "phone")
    op.drop_column("app_user", "email")
    op.drop_column("app_user", "display_name")
