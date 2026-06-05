from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260605_0046"
down_revision = "20260602_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 错误日志表只面向管理员排查后台任务和供应商异常；普通用户仍只读取
    # ai_image_generation.error_message 中的友好摘要，避免把外部服务细节直接展示到前端。
    op.create_table(
        "ai_image_generation_error_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键 ID"),
        sa.Column("generation_id", sa.Integer(), nullable=False, comment="图片生成记录 ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="图片所属用户 ID"),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            server_default="86gamestore",
            comment="供应商标识",
        ),
        sa.Column("model", sa.String(length=64), nullable=False, comment="实际调用模型"),
        sa.Column("phase", sa.String(length=64), nullable=False, comment="失败阶段"),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="本次供应商调用已重试次数",
        ),
        sa.Column("status_code", sa.Integer(), nullable=True, comment="供应商 HTTP 状态码"),
        sa.Column("error_type", sa.String(length=128), nullable=False, comment="异常类型"),
        sa.Column("user_message", sa.String(length=512), nullable=False, comment="用户侧失败摘要"),
        sa.Column(
            "detail_message",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=False,
            comment="管理员排查用详细错误，已截断不含鉴权头",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["generation_id"], ["ai_image_generation.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ai_image_generation_error_log_generation",
        "ai_image_generation_error_log",
        ["generation_id", "created_at"],
    )
    op.create_index(
        "idx_ai_image_generation_error_log_user",
        "ai_image_generation_error_log",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_ai_image_generation_error_log_user",
        table_name="ai_image_generation_error_log",
    )
    op.drop_index(
        "idx_ai_image_generation_error_log_generation",
        table_name="ai_image_generation_error_log",
    )
    op.drop_table("ai_image_generation_error_log")
