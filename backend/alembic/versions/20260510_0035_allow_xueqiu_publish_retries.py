from __future__ import annotations

from alembic import op

revision = "20260510_0035"
down_revision = "20260510_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 雪球网页端删除草稿后，管理员需要重新创建一篇草稿，同时保留旧流水供审计；
    # 因此取消 analysis_id + publish_mode 唯一键，改用普通索引支持查询最近一次尝试。
    op.drop_constraint(
        "uk_xueqiu_publish_analysis_mode",
        "xueqiu_publish_record",
        type_="unique",
    )
    op.create_index(
        "idx_xueqiu_publish_record_mode_latest",
        "xueqiu_publish_record",
        ["analysis_id", "publish_mode", "created_at"],
    )


def downgrade() -> None:
    # 回滚前必须确认不存在同一报告同一模式的多条流水；否则唯一键无法恢复。
    op.drop_index(
        "idx_xueqiu_publish_record_mode_latest",
        table_name="xueqiu_publish_record",
    )
    op.create_unique_constraint(
        "uk_xueqiu_publish_analysis_mode",
        "xueqiu_publish_record",
        ["analysis_id", "publish_mode"],
    )
