from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260527_0039"
down_revision = "20260519_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 图片生成记录按用户隔离，文件只保存相对路径；实际图片落在独立数据盘目录，
    # 避免数据库膨胀，也避免把本地绝对路径暴露给前端。
    op.create_table(
        "ai_image_generation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键 ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="创建图片的系统用户 ID"),
        sa.Column("prompt", sa.Text(), nullable=False, comment="用户提交的原始提示词"),
        sa.Column("model", sa.String(length=64), nullable=False, comment="实际调用的文生图模型"),
        sa.Column("size", sa.String(length=32), nullable=False, comment="实际请求的输出尺寸"),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDING",
            comment="生成状态",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            server_default="86gamestore",
            comment="供应商标识",
        ),
        sa.Column(
            "generation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="TEXT_TO_IMAGE",
            comment="生成模式",
        ),
        sa.Column("mime_type", sa.String(length=64), nullable=True, comment="输出图片 MIME 类型"),
        sa.Column(
            "file_relative_path",
            sa.String(length=512),
            nullable=True,
            comment="输出图片相对存储路径",
        ),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True, comment="输出图片字节数"),
        sa.Column("file_sha256", sa.String(length=64), nullable=True, comment="输出图片 SHA256"),
        sa.Column(
            "reference_file_relative_path",
            sa.String(length=512),
            nullable=True,
            comment="参考图相对存储路径",
        ),
        sa.Column(
            "reference_mime_type",
            sa.String(length=64),
            nullable=True,
            comment="参考图 MIME 类型",
        ),
        sa.Column("reference_file_size_bytes", sa.Integer(), nullable=True, comment="参考图字节数"),
        sa.Column(
            "reference_file_sha256",
            sa.String(length=64),
            nullable=True,
            comment="参考图 SHA256",
        ),
        sa.Column(
            "external_url_expires_unknown",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="外部 URL 是否可能过期",
        ),
        sa.Column(
            "request_payload_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="脱敏后的供应商请求摘要，不含鉴权头",
        ),
        sa.Column(
            "response_summary_json",
            sa.Text().with_variant(mysql.LONGTEXT(), "mysql"),
            nullable=True,
            comment="脱敏后的供应商响应摘要",
        ),
        sa.Column("elapsed_ms", sa.Float(), nullable=True, comment="生成与落盘总耗时毫秒"),
        sa.Column("error_message", sa.String(length=512), nullable=True, comment="失败摘要"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="逻辑删除时间"),
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
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ai_image_generation_user_created",
        "ai_image_generation",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_ai_image_generation_status_created",
        "ai_image_generation",
        ["status", "created_at"],
    )
    op.create_index("idx_ai_image_generation_file_sha", "ai_image_generation", ["file_sha256"])
    op.create_index(
        "idx_ai_image_generation_reference_sha",
        "ai_image_generation",
        ["reference_file_sha256"],
    )

    # quota 表只保存当前计数日期和已用次数；跨日由服务层按东八区懒重置，
    # 管理员重置也只影响次数，不改历史图片记录。
    op.create_table(
        "ai_image_user_quota",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键 ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="系统用户 ID"),
        sa.Column(
            "daily_limit",
            sa.Integer(),
            nullable=False,
            server_default="10",
            comment="每日可生成次数",
        ),
        sa.Column("quota_date", sa.Date(), nullable=True, comment="当前计数日期，按东八区"),
        sa.Column(
            "used_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="当日已使用次数",
        ),
        sa.Column("last_reset_at", sa.DateTime(), nullable=True, comment="管理员最近重置时间"),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True, comment="最近维护管理员 ID"),
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
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uk_ai_image_user_quota_user"),
    )
    op.create_index("idx_ai_image_user_quota_user", "ai_image_user_quota", ["user_id"])

    # 图片生成默认向已有用户开放；只追加菜单权限，不改动用户其它自定义权限。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = CASE
          WHEN menu_permissions_json IS NULL OR menu_permissions_json = ''
            THEN JSON_ARRAY('image_generation')
          WHEN JSON_VALID(menu_permissions_json)
               AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('image_generation')) = 0
            THEN JSON_ARRAY_APPEND(menu_permissions_json, '$', 'image_generation')
          ELSE menu_permissions_json
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'image_generation'))
        )
        WHERE menu_permissions_json IS NOT NULL
          AND JSON_VALID(menu_permissions_json)
          AND JSON_SEARCH(menu_permissions_json, 'one', 'image_generation') IS NOT NULL
        """
    )
    op.drop_index("idx_ai_image_user_quota_user", table_name="ai_image_user_quota")
    op.drop_table("ai_image_user_quota")
    op.drop_index("idx_ai_image_generation_reference_sha", table_name="ai_image_generation")
    op.drop_index("idx_ai_image_generation_file_sha", table_name="ai_image_generation")
    op.drop_index("idx_ai_image_generation_status_created", table_name="ai_image_generation")
    op.drop_index("idx_ai_image_generation_user_created", table_name="ai_image_generation")
    op.drop_table("ai_image_generation")
