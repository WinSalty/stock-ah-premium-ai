from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260505_0016"
down_revision = "20260505_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "realtime_quote_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("last_price", sa.DECIMAL(20, 8), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("quote_time", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False, server_default="UNAVAILABLE"),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_realtime_quote_symbol_time",
        "realtime_quote_snapshot",
        ["market", "symbol", "quote_time"],
    )
    op.create_index(
        "idx_realtime_quote_source_time",
        "realtime_quote_snapshot",
        ["source", "quote_time"],
    )


def downgrade() -> None:
    op.drop_index("idx_realtime_quote_source_time", table_name="realtime_quote_snapshot")
    op.drop_index("idx_realtime_quote_symbol_time", table_name="realtime_quote_snapshot")
    op.drop_table("realtime_quote_snapshot")
