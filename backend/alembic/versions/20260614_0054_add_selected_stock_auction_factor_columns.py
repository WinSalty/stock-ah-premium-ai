from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260614_0054"
down_revision = "20260613_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """评审 F3：limit_up_selected_stock 新增竞价两因子分母列。

    创建日期：2026-06-14
    author: claude

    业务意图：执行侧集合竞价四因子里的「量能比」「封流比」需要两个个股基准作分母——
    first_board_vol（首板/信号日全天成交量，量能比分母）与 float_mktcap（流通市值，封流比分母）。
    原 watchlist 契约不导出这两列，执行侧只能写死 None → 两因子在生产恒降级。
    这里在选股落表加这两列，随 watchlist 契约下发执行侧。两列均可空（缺数据时执行侧仍走降级，不报错），
    存量行为 NULL，不影响历史。
    """

    op.add_column(
        "limit_up_selected_stock",
        sa.Column(
            "float_mktcap",
            sa.DECIMAL(20, 4),
            nullable=True,
            comment="流通市值(元)，执行侧封流比分母（评审 F3）",
        ),
    )
    op.add_column(
        "limit_up_selected_stock",
        sa.Column(
            "first_board_vol",
            sa.BigInteger(),
            nullable=True,
            comment="信号日全天成交量(手)，执行侧竞价量能比分母（评审 F3）",
        ),
    )


def downgrade() -> None:
    op.drop_column("limit_up_selected_stock", "first_board_vol")
    op.drop_column("limit_up_selected_stock", "float_mktcap")
