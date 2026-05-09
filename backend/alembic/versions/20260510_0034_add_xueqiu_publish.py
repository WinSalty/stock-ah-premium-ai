from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260510_0034"
down_revision = "20260509_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 雪球登录态只保存浏览器 Cookie 和请求基础配置，不保存账号密码；
    # 列表接口只返回掩码摘要和更新时间，避免敏感 Cookie 在前端和日志中扩散。
    op.create_table(
        "xueqiu_publish_credential",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cookie_text", mysql.LONGTEXT(), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=False),
        sa.Column(
            "mp_base_url",
            sa.String(length=128),
            nullable=False,
            server_default="https://mp.xueqiu.com",
        ),
        sa.Column(
            "referer_url",
            sa.String(length=255),
            nullable=False,
            server_default="https://mp.xueqiu.com/write/",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_xueqiu_publish_credential_enabled",
        "xueqiu_publish_credential",
        ["enabled"],
    )

    # 发布流水按 analysis_id + publish_mode 幂等，避免早盘任务重跑或管理员重复点击导致同一报告多次发文；
    # 草稿和正式发布分别记录请求摘要、雪球返回和文章地址，便于本地排查失败原因。
    op.create_table(
        "xueqiu_publish_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "analysis_id",
            sa.Integer(),
            sa.ForeignKey("limit_up_analysis_cache.id"),
            nullable=False,
        ),
        sa.Column("publish_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("content_html", mysql.LONGTEXT(), nullable=False),
        sa.Column("cover_pic", sa.String(length=512), nullable=True),
        sa.Column("draft_id", sa.String(length=128), nullable=True),
        sa.Column("status_id", sa.String(length=128), nullable=True),
        sa.Column("article_url", sa.String(length=512), nullable=True),
        sa.Column("request_payload_json", mysql.LONGTEXT(), nullable=True),
        sa.Column("response_json", mysql.LONGTEXT(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("analysis_id", "publish_mode", name="uk_xueqiu_publish_analysis_mode"),
    )
    op.create_index(
        "idx_xueqiu_publish_record_status",
        "xueqiu_publish_record",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_xueqiu_publish_record_analysis",
        "xueqiu_publish_record",
        ["analysis_id"],
    )

    # 雪球发布菜单默认只给管理员；普通用户不自动获得入口，后续也不会因接收打板报告而被授予发布权限。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_ARRAY_APPEND(menu_permissions_json, '$', 'xueqiu_publish')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_CONTAINS(menu_permissions_json, JSON_QUOTE('xueqiu_publish')) = 0
        """
    )
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_ARRAY('xueqiu_publish')
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NULL
        """
    )


def downgrade() -> None:
    # 回滚时移除管理员新增菜单并删除发布流水表；不会触碰打板报告缓存和 PushPlus 既有数据。
    op.execute(
        """
        UPDATE app_user
        SET menu_permissions_json = JSON_REMOVE(
          menu_permissions_json,
          JSON_UNQUOTE(JSON_SEARCH(menu_permissions_json, 'one', 'xueqiu_publish'))
        )
        WHERE role = 'ADMIN'
          AND menu_permissions_json IS NOT NULL
          AND JSON_SEARCH(menu_permissions_json, 'one', 'xueqiu_publish') IS NOT NULL
        """
    )
    op.drop_index("idx_xueqiu_publish_record_analysis", table_name="xueqiu_publish_record")
    op.drop_index("idx_xueqiu_publish_record_status", table_name="xueqiu_publish_record")
    op.drop_table("xueqiu_publish_record")
    op.drop_index("idx_xueqiu_publish_credential_enabled", table_name="xueqiu_publish_credential")
    op.drop_table("xueqiu_publish_credential")
