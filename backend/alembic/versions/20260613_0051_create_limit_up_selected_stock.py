from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260613_0051"
down_revision = "20260613_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建打板信号计划落表 limit_up_selected_stock（一股一行）。

    业务意图：把多阶段选股 pipeline 与投资建议分层的结论结构化成"一只票一买入日一行"，
        供 QMT 闭环归因与只读导出消费。
    口径：trade_date=T 信号日、target_trade_date=T+1 买入日；
        唯一键 (trade_date, ts_code, prompt_version)；
        id 与 source_analysis_id 用 Integer，与主表 limit_up_analysis_cache.id 对齐，
        避免外键类型不匹配。
    幂等：写入收口整组 delete-then-insert，与报告 READY 同事务原子提交。

    创建日期：2026-06-13
    author: claude
    """

    op.create_table(
        "limit_up_selected_stock",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键"),
        # ① 主键与关联键（QMT 闭环归因 join：ts_code + target_trade_date）
        sa.Column(
            "trade_date",
            sa.Date(),
            nullable=False,
            comment="信号日 T（东八区交易日，对应报告复盘日）",
        ),
        sa.Column(
            "target_trade_date",
            sa.Date(),
            nullable=False,
            comment="计划买入日 T+1（a_trade_calendar 映射，禁手工+1天）",
        ),
        sa.Column(
            "ts_code",
            sa.String(length=16),
            nullable=False,
            comment="标准代码 600000.SH 形态，供 norm_code 关联",
        ),
        sa.Column("name", sa.String(length=64), nullable=True, comment="股票名称快照"),
        # ② 板块 / 连板维度
        sa.Column(
            "board",
            sa.String(length=16),
            nullable=True,
            comment="所属市场板：MAIN 主板 / GEM 创业板",
        ),
        sa.Column(
            "tier",
            sa.String(length=16),
            nullable=False,
            comment="入选分层来源：FIRST_BOARD/CHAIN/HIGH_BOARD",
        ),
        sa.Column(
            "board_level",
            sa.Integer(),
            nullable=True,
            comment="连板高度（首板=1，N连板=N；无法识别为 NULL）",
        ),
        sa.Column(
            "limit_type",
            sa.String(length=16),
            nullable=True,
            comment="涨停形态：一字/T字/换手/秒板/烂板等",
        ),
        # ③ 龙头强度分及各维度分
        sa.Column(
            "leader_strength_score",
            sa.DECIMAL(precision=8, scale=2),
            nullable=True,
            comment="龙头强度综合分（0-100）",
        ),
        sa.Column(
            "strength_dim_json",
            sa.JSON(),
            nullable=True,
            comment="各维度分：题材卡位/封板质量/资金/辨识度等子分",
        ),
        # ④ 角色 / 战法 / 形态 / 动作
        sa.Column(
            "role_tags",
            sa.JSON(),
            nullable=True,
            comment="角色标签数组：龙头/板块前排/跟风/空间板/中军等",
        ),
        sa.Column(
            "strategy_family",
            sa.String(length=32),
            nullable=True,
            comment="战法族：首板打板/低吸/连板接力等",
        ),
        sa.Column(
            "setup",
            sa.String(length=64),
            nullable=True,
            comment="技术/资金形态：题材发酵/缩量回踩/放量突破等",
        ),
        sa.Column(
            "action",
            sa.String(length=32),
            nullable=True,
            comment="建议动作分层：重点观察/谨慎观察/放弃观察",
        ),
        # ⑤ 情绪周期与可成交性
        sa.Column(
            "sentiment_cycle",
            sa.String(length=16),
            nullable=True,
            comment="个股/梯队情绪阶段（与市场级 market_state 区分）",
        ),
        sa.Column(
            "market_state",
            sa.String(length=16),
            nullable=True,
            comment="市场情绪周期：启动/高潮/震荡/退潮/冰点/空仓",
        ),
        sa.Column(
            "tradable_flag",
            sa.String(length=16),
            nullable=False,
            server_default="TRADABLE",
            comment="可成交性：TRADABLE可参与/WATCH仅观察/BLOCKED闸门关闭",
        ),
        # ⑥ 先验概率
        sa.Column(
            "continuation_prob",
            sa.DECIMAL(precision=5, scale=4),
            nullable=True,
            comment="次日续板概率先验（0-1）",
        ),
        sa.Column(
            "next_day_premium_prob",
            sa.DECIMAL(precision=5, scale=4),
            nullable=True,
            comment="隔日溢价为正概率先验（0-1）",
        ),
        # ⑦ 晋级 / 失败条件与持有逻辑
        sa.Column(
            "boost_conditions",
            sa.JSON(),
            nullable=True,
            comment="晋级/触发条件列表（竞价区间、量能、题材延续等）",
        ),
        sa.Column(
            "fail_conditions",
            sa.JSON(),
            nullable=True,
            comment="失败/止损/反证条件列表",
        ),
        sa.Column(
            "suggested_hold_thesis",
            sa.Text(),
            nullable=True,
            comment="建议持有逻辑/参与方式（结论性文本）",
        ),
        # ⑧ 热字段
        sa.Column(
            "seal_ratio_pct",
            sa.DECIMAL(precision=10, scale=4),
            nullable=True,
            comment="封流比/封单占比%（封板质量代理）",
        ),
        sa.Column(
            "limit_order",
            sa.DECIMAL(precision=20, scale=4),
            nullable=True,
            comment="封单金额/封单量快照",
        ),
        sa.Column(
            "turnover_rate",
            sa.DECIMAL(precision=10, scale=4),
            nullable=True,
            comment="T 日换手率%",
        ),
        sa.Column(
            "close",
            sa.DECIMAL(precision=20, scale=6),
            nullable=True,
            comment="T 日收盘价（信号决策价快照，不复权）",
        ),
        sa.Column(
            "winner_rate",
            sa.DECIMAL(precision=10, scale=4),
            nullable=True,
            comment="筹码获利盘比例%（来自 cyq 补数，可空）",
        ),
        # ⑨ 优先级 / 原始结构 / 入选理由
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=True,
            comment="同分层内优先级（越小越靠前）",
        ),
        sa.Column(
            "item_json",
            sa.JSON(),
            nullable=True,
            comment="该股完整结构化快照（选股映射行+建议结论原文，审计/回放）",
        ),
        sa.Column(
            "selection_reason",
            sa.Text(),
            nullable=True,
            comment="入选理由（LLM 文本）",
        ),
        # ⑩ 审计与版本
        sa.Column(
            "source_analysis_id",
            sa.Integer(),
            nullable=False,
            comment="来源报告 id -> limit_up_analysis_cache.id",
        ),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            nullable=False,
            comment="JSON 契约/字段结构版本，对齐 schemas/limit_up_watchlist.py",
        ),
        sa.Column("model", sa.String(length=64), nullable=False, comment="生成模型名"),
        sa.Column(
            "prompt_version",
            sa.String(length=64),
            nullable=False,
            comment="提示词版本（唯一键组成，换版不互相覆盖）",
        ),
        sa.Column(
            "advice_degraded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="建议是否降级：1=建议未就绪/降级整报，维度字段可能部分缺失",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间（UTC-naive）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="更新时间（UTC-naive）",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trade_date",
            "ts_code",
            "prompt_version",
            name="uk_limit_up_selected_once",
        ),
        sa.ForeignKeyConstraint(
            ["source_analysis_id"],
            ["limit_up_analysis_cache.id"],
            name="fk_limit_up_selected_analysis",
        ),
        comment="打板信号计划落表：一股一行，T信号/T+1买入，供QMT闭环归因与只读导出",
    )
    op.create_index(
        "idx_limit_up_selected_target", "limit_up_selected_stock", ["target_trade_date"]
    )
    op.create_index(
        "idx_limit_up_selected_analysis", "limit_up_selected_stock", ["source_analysis_id"]
    )
    op.create_index("idx_limit_up_selected_tier", "limit_up_selected_stock", ["tier"])


def downgrade() -> None:
    """回滚：删除 limit_up_selected_stock 表。

    创建日期：2026-06-13
    author: claude
    """

    # 直接删表：MySQL drop_table 会级联删除其索引与外键约束；
    # 不可先 drop_index 再 drop_table——FK source_analysis_id 依赖 idx_limit_up_selected_analysis，
    # 先删该索引会触发 MySQL errno 1553（外键所需索引不可删）。
    op.drop_table("limit_up_selected_stock")
