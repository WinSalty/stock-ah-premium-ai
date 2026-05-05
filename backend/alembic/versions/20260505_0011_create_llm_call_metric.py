from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260505_0011"
down_revision = "20260504_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call_metric",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("first_chunk_ms", sa.Float(), nullable=True),
        sa.Column("output_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_llm_call_metric_question", "llm_call_metric", ["question_id"])
    op.create_index("idx_llm_call_metric_user_created", "llm_call_metric", ["user_id", "created_at"])
    op.create_index(
        "idx_llm_call_metric_session_created",
        "llm_call_metric",
        ["session_id", "created_at"],
    )
    op.create_index("idx_llm_call_metric_phase_model", "llm_call_metric", ["phase", "model"])


def downgrade() -> None:
    op.drop_index("idx_llm_call_metric_phase_model", table_name="llm_call_metric")
    op.drop_index("idx_llm_call_metric_session_created", table_name="llm_call_metric")
    op.drop_index("idx_llm_call_metric_user_created", table_name="llm_call_metric")
    op.drop_index("idx_llm_call_metric_question", table_name="llm_call_metric")
    op.drop_table("llm_call_metric")
