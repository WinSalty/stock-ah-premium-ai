from __future__ import annotations

from alembic import op

revision = "20260601_0044"
down_revision = "20260601_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为 LLM 耗时排查页补充查询索引。

    创建日期：2026-06-01
    author: sunshengxian
    """

    # 指标表是追加写为主、管理员读取排查为辅；索引围绕页面常用筛选项和日期范围建立，
    # 让列表、计数和懒加载摘要尽量走范围扫描，避免数据增长后每次统计都扫完整表。
    op.create_index("idx_llm_metric_created_id", "llm_call_metric", ["created_at", "id"])
    op.create_index(
        "idx_llm_metric_provider_created",
        "llm_call_metric",
        ["provider", "created_at", "id"],
    )
    op.create_index(
        "idx_llm_metric_phase_created",
        "llm_call_metric",
        ["phase", "created_at", "id"],
    )
    op.create_index(
        "idx_llm_metric_model_created",
        "llm_call_metric",
        ["model", "created_at", "id"],
    )


def downgrade() -> None:
    """回滚 LLM 耗时排查页查询索引。

    创建日期：2026-06-01
    author: sunshengxian
    """

    # 回滚只移除本迁移新增索引，不触碰指标数据，避免排查历史丢失。
    op.drop_index("idx_llm_metric_model_created", table_name="llm_call_metric")
    op.drop_index("idx_llm_metric_phase_created", table_name="llm_call_metric")
    op.drop_index("idx_llm_metric_provider_created", table_name="llm_call_metric")
    op.drop_index("idx_llm_metric_created_id", table_name="llm_call_metric")
