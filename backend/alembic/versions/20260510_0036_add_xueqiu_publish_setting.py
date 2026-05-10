from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260510_0036"
down_revision = "20260510_0035"
branch_labels = None
depends_on = None

DEFAULT_COVER_PIC = "https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png"


def upgrade() -> None:
    # 自动发布配置单独落库，管理员可在页面调整是否定时、草稿/正式发布和默认封面；
    # 运行时调度仍保留环境总开关，避免未部署好 Cookie 时误触发第三方写入。
    op.create_table(
        "xueqiu_publish_setting",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scheduler_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("poll_hours", sa.String(length=32), nullable=False, server_default="8"),
        sa.Column("poll_minutes", sa.String(length=64), nullable=False, server_default="30"),
        sa.Column("default_cover_pic", sa.String(length=512), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO xueqiu_publish_setting
              (scheduler_enabled, auto_publish, poll_hours, poll_minutes, default_cover_pic)
            VALUES
              (0, 0, '8', '30', :default_cover_pic)
            """
        ).bindparams(default_cover_pic=DEFAULT_COVER_PIC)
    )


def downgrade() -> None:
    # 回滚只删除雪球页面配置，不触碰已生成的草稿/发布流水。
    op.drop_table("xueqiu_publish_setting")
