from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260505_0017"
down_revision = "20260505_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_call_metric", sa.Column("phase_label", sa.String(length=64), nullable=True))
    op.add_column("llm_call_metric", sa.Column("phase_description", sa.Text(), nullable=True))
    op.add_column(
        "llm_call_metric",
        sa.Column(
            "request_payload_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_call_metric", "request_payload_json")
    op.drop_column("llm_call_metric", "phase_description")
    op.drop_column("llm_call_metric", "phase_label")
