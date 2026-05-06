from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260505_0018"
down_revision = "20260505_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_call_metric",
        sa.Column(
            "response_content",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_call_metric", "response_content")
