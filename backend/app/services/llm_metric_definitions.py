from __future__ import annotations

PHASE_LABELS: dict[str, str] = {
    "question_router": "问题路由",
    "stock_disambiguation": "股票消歧",
    "generate_sql": "生成 SQL",
    "repair_sql": "修复 SQL",
    "execute_sql": "执行 SQL",
    "answer": "非流式回答",
    "answer_stream_first_chunk": "流式首包",
    "answer_stream": "流式回答",
    "threshold_answer": "阈值推荐回答",
    "threshold_answer_stream_first_chunk": "阈值推荐首包",
    "threshold_answer_stream": "阈值推荐流式回答",
    "limit_up_analysis": "打板报告分析",
    "threshold_done": "阈值推荐总耗时",
    "threshold_stream_done": "阈值推荐流式总耗时",
    "stream_done": "流式总耗时",
    "sync_done": "非流式总耗时",
    "sync_intro": "非流式介绍",
    "stream_intro": "流式介绍",
    "stream_out_of_scope": "流式越界提示",
    "sync_out_of_scope": "非流式越界提示",
    "stream_not_configured": "流式未配置",
    "sync_not_configured": "非流式未配置",
}

PHASE_DESCRIPTIONS: dict[str, str] = {
    "question_router": (
        "前置路由阶段，判断问题是否属于投资研究、是否需要查结构化数据、是否需要读取知识库。"
    ),
    "stock_disambiguation": (
        "股票名称语义消歧阶段，只在本地股票候选内选择具体 A 股代码，不调用外部行情接口。"
    ),
    "generate_sql": "SQL 生成阶段，仅在问题需要精确结构化数据时调用外部模型生成只读查询。",
    "repair_sql": "SQL 修复阶段，仅在生成的 SQL 字段或语法执行失败时触发一次修复。",
    "execute_sql": "数据库执行阶段，不调用 LLM；行数表示实际返回给回答链路的数据行数。",
    "answer": "非流式回答阶段，用于 AI 阈值推荐等一次性返回场景；字符表示模型回答字符数。",
    "answer_stream_first_chunk": "流式回答首包记录，只记录首包耗时；其它计数字段通常为 0。",
    "answer_stream": "流式回答主体完成记录；Chunk 是流式片段数，字符是累计输出字符数。",
    "threshold_answer": "AI 阈值推荐快路径的非流式回答阶段，只解释页面数据和本地确定性阈值。",
    "threshold_answer_stream_first_chunk": "AI 阈值推荐快路径的流式首包记录，只记录首包耗时。",
    "threshold_answer_stream": (
        "AI 阈值推荐快路径的流式回答主体完成记录，不经过通用路由、补数和辅助视图查询。"
    ),
    "limit_up_analysis": "打板报告生成阶段，使用 KPL 与涨停专题数据生成完整 HTML 推送报告。",
    "threshold_done": "AI 阈值推荐快路径非流式总耗时；来源 Internal 表示系统内部汇总。",
    "threshold_stream_done": "AI 阈值推荐快路径流式总耗时；来源 Internal 表示系统内部汇总。",
    "stream_done": "整轮流式问答总耗时汇总；来源 Internal 表示系统内部汇总，不是外部 LLM 调用。",
    "sync_done": "整轮非流式问答总耗时汇总；来源 Internal 表示系统内部汇总，不是外部 LLM 调用。",
    "sync_intro": "非流式问候或能力介绍快路径，系统本地直接返回，不调用外部模型。",
    "stream_intro": "流式问候或能力介绍快路径，系统本地直接返回，不调用外部模型。",
    "stream_out_of_scope": "流式越界问题快路径，系统本地直接返回范围提示，不调用外部模型。",
    "sync_out_of_scope": "非流式越界问题快路径，系统本地直接返回范围提示，不调用外部模型。",
    "stream_not_configured": "流式模型未配置时的系统本地返回记录。",
    "sync_not_configured": "非流式模型未配置时的系统本地返回记录。",
}


def phase_label(phase: str) -> str:
    return PHASE_LABELS.get(phase, phase)


def phase_description(phase: str) -> str:
    return PHASE_DESCRIPTIONS.get(phase, "阶段记录。")
