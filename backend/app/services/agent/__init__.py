"""问答 Agent 引擎包：LLM 通过 function calling 自主编排工具的新问答链路。

包结构见 resources/doc/chat-agent-refactor-design-and-plan.md 2.2 节。
注意：本 __init__ 保持空导出，避免 llm_client -> agent.budget 与
agent.engine -> llm_client 之间出现包级循环导入。

创建日期：2026-06-12
author: claude
"""
