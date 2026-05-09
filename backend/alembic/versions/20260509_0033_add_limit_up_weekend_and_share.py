from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260509_0033"
down_revision = "20260508_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 接收人周末复推开关默认开启，保持历史“周六/周日晚上全部启用接收人复推”的既有口径；
    # 管理员后续可按人关闭，常规数据就绪推送和手动推送不受该字段影响。
    op.add_column(
        "limit_up_push_recipient",
        sa.Column("weekend_replay_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # 分享链接单独落表，不改写报告缓存正文；expires_at 为空表示永久链接，
    # 公开访问时只凭 token 读取 READY 报告，避免暴露后台完整管理接口。
    op.create_table(
        "limit_up_report_share",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("limit_up_analysis_cache.id"), nullable=False),
        sa.Column("share_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("share_token", name="uk_limit_up_report_share_token"),
    )
    op.create_index(
        "idx_limit_up_report_share_analysis",
        "limit_up_report_share",
        ["analysis_id", "created_at"],
    )
    op.create_index(
        "idx_limit_up_report_share_expires",
        "limit_up_report_share",
        ["expires_at"],
    )


def downgrade() -> None:
    # 回滚时先删分享表再删接收人新增列，避免外键和新增配置残留影响旧版本服务。
    op.drop_index("idx_limit_up_report_share_expires", table_name="limit_up_report_share")
    op.drop_index("idx_limit_up_report_share_analysis", table_name="limit_up_report_share")
    op.drop_table("limit_up_report_share")
    op.drop_column("limit_up_push_recipient", "weekend_replay_enabled")
