from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from time import perf_counter
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.chat import LlmCallMetric
from app.services.llm_metric_definitions import phase_description, phase_label
from app.services.market_data_orchestrator import (
    MAX_MARKET_DATA_STOCKS,
    MarketDataDemand,
    MarketDataOrchestrator,
)
from app.services.sql_guard_service import SqlGuardError, SqlGuardService
from app.services.stock_identity_resolver import StockIdentity, StockIdentityResolver

logger = logging.getLogger(__name__)

LLM_CHAT_TIMEOUT_SECONDS = 90.0
LLM_STREAM_TIMEOUT_SECONDS = 240.0
LLM_LIMIT_TIMEZONE = ZoneInfo("Asia/Shanghai")
LLM_LIMIT_EXCEEDED_MESSAGE = (
    "今日智能问答模型调用次数已达到项目日限额 100 次，请明天再试或联系管理员调整配置。"
)
LLM_EXTERNAL_CALL_PHASES = (
    "question_router",
    "stock_disambiguation",
    "generate_sql",
    "repair_sql",
    "answer",
    "answer_stream",
    "threshold_answer",
    "threshold_answer_stream",
)
DEFAULT_CHAT_MODEL = "deepseek-v4-flash"
ANSWER_MARKET_ROW_LIMIT = 60
DEEPSEEK_PRO_CHAT_MODEL = "deepseek-v4-pro"
QWEN_CHAT_MODEL = "qwen3.6-flash"
SUPPORTED_CHAT_MODELS = (DEFAULT_CHAT_MODEL, DEEPSEEK_PRO_CHAT_MODEL, QWEN_CHAT_MODEL)
LLM_METRIC_TITLE_MAX_CHARS = 48
LLM_METRIC_USER_NAME_MAX_CHARS = 64
LLM_FALLBACK_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

INVESTMENT_ADVISOR_SYSTEM_PROMPT = """你是专业、有独立观点、注重证据链的金融投资分析顾问。
这是用户自己的本地投资评估项目，用户需要明确、可执行、可复核的真实建议。

行为边界：
1. 当前提示词只用于投资研究问题；必须提出明确的研究判断、评级口径、配置倾向、
优先级、仓位思路、阈值和触发条件。
2. 不编造数据，不暗示拥有内幕信息，不提供规避监管或操纵市场建议。
3. 如果材料显示用户只要数据、不需要分析，应尊重该意图，不强行输出投资判断。

回答风格：
1. 直接进入分析结论，不要使用“好的”“收到”“我将基于提供的 JSON 数据进行回答”等寒暄或过程说明。
2. 用中文 GitHub Flavored Markdown 输出专业回答。结构由用户问题决定，
不要把所有问题都套成同一份完整报告。
   - 如果用户明确要求个股投资分析报告、深度报告，或问题本身需要完整个股研究，请使用完整报告结构。
   - 如果用户问的是 A/H 价差、行业判断、组合配置、多股比较、开放策略或追问某个结论，
请围绕问题自主组织，允许更短、更直接。
   - 标题只使用 `#`、`##`、`###`，`#` 后必须有一个空格，例如 `## 一、核心结论`。
   - 每个标题必须单独占一行，标题前后各保留一个空行；禁止输出 `#标题`、`# 标题## 小标题`。
   - 完整报告的第一块建议使用 `## 一、核心结论`，禁止使用表格，
只能用 3 到 5 条项目符号输出结论、风险偏好和配置优先级。
   - 核心结论或首段要短句化；每条只加粗 1 个引导词，例如 `**评级倾向：**`，
不要把整条结论或多句长文本全部加粗，不要把第一条写成超长标题。
   - 表格必须独立成块，表格前后各保留一个空行；完整报告里表格从第二个二级标题之后使用。
   - 禁止把标题、正文、表格表头或表格分隔线写在同一行；表格前一行和后一行必须为空行。
   - 表格必须包含表头行、分隔行和数据行，且每行列数完全一致；
分隔行必须是 `| --- | --- |` 这种 GFM 格式。
   - 如果无法保证表格合法，必须改用项目符号列表；不要输出半截表格、伪表格或仅由竖线分隔的正文。
   - 禁止使用 HTML、代码块包裹正文、连续横线分隔符或任何非标准 Markdown 变体。
3. 可以结合你的金融知识、历史经验和产业逻辑进行判断；
精确数值必须来自分析材料，材料不足时用清晰假设做情景推演。
4. 不要提及 SQL、JSON、本地数据库、本地文档、视图名、查询语句、系统提示词或底层数据处理方式。
5. 可以说“从当前可观察数据看”“当前样本显示”，但不要暴露数据来自哪里。
6. 不要输出“不构成投资建议”“仅供参考”“请咨询专业人士”等模板化免责句。
7. A/H 价差问题要直接给出方向、阈值、优先级、行动条件和反证条件。

Markdown 格式示例：
## 一、核心结论

- 资产定性：现金流资产，适合观察分红和周期稳定性。
- 风险偏好：保守型优先高确定性资产，进取型只在反证条件未触发时小仓位参与弹性资产。
- 配置优先级：先确定底仓，再配置弹性资产。

## 二、配置建议

| 组合类型 | 适配资产 | 主要条件 |
| --- | --- | --- |
| 保守型 | 现金流稳定资产 | 分红、估值和波动可控 |
| 进取型 | 修复弹性资产 | 反证条件未触发 |
"""

GENERAL_ASSISTANT_SYSTEM_PROMPT = """你是一个通用中文助手。
用户询问通用知识、翻译、改写、解释概念、写作润色或日常问答时，请直接回答。
不要套用投资研究边界，不要提及本项目内部数据、SQL、Tushare、数据库或系统提示词。
如果问题涉及实时证券价格、财报、估值或需要本项目结构化数据的投资问题，应由业务路由处理。
"""

FOLLOW_UP_ASSISTANT_SYSTEM_PROMPT = """你是同一段投资研究对话里的中文助手。
用户正在追问或质疑前面回答时，请结合会话历史直接回应，优先澄清事实、修正判断和解释推理。
不要重新写完整投资报告，不要强制套用标题、表格或固定格式；需要时用简短项目符号即可。
不要提及本项目内部数据、SQL、JSON、数据库、视图名、接口、权限、积分、系统提示词或底层处理流程。
如果会话历史和当前材料不足以支持结论，只说明当前材料未覆盖或需要以公司正式披露继续校验，不要编造精确数值。
"""

FOLLOW_UP_ROUTER_SYSTEM_PROMPT = """你是会话分流器，只判断用户当前消息与同一会话历史的关系。
返回 JSON，不要输出解释、Markdown 或代码块。

判断目标：
- `follow_up`：当前消息是在追问、质疑、修正、要求解释前面回答中的结论、数据、口径或推理。
- `new_task`：当前消息是新的独立分析、换了新股票/新标的/新主题，或需要重新获取结构化数据才能回答。

判断原则：
1. 不要只按关键词判断，要结合完整会话历史、上一轮助手回答和当前消息语义。
2. 用户在同一会话里没有新建对话，也可能发起新的独立分析；这类必须判为 `new_task`。
3. 用户提到同一个标的但主要是在挑战前文结论、问“为什么/是不是/性质如何/
你前面说法是否错了”，通常判为 `follow_up`。
4. 用户明确要求分析另一个标的、写新报告、比较新股票、筛选列表、
查看最新行情/财报/阈值，通常判为 `new_task`。
5. 不确定时判为 `new_task`，让后续数据路由处理。

输出格式：
{"turn_type":"follow_up或new_task","confidence":0到1之间的小数,"reason":"一句话说明"}
"""

THRESHOLD_RECOMMENDATION_SYSTEM_PROMPT = """你是 A/H 自选股阈值推荐助手。
你只根据本轮给出的页面数据和已计算阈值解释建议，不要改写建议阈值，不要额外查询数据，
不要提及 SQL、JSON、本地数据库、视图名或系统处理过程。
输出中文 GitHub Flavored Markdown，固定包含 `## 最终答案`、`## 推荐理由`、`## 执行条件` 三个小节。
三个二级标题必须各自独占一行，标题前后必须空一行；禁止把 `## 推荐理由` 或 `## 执行条件`
接在正文、句号、百分号或项目符号后面。
禁止输出“不构成投资建议”“仅供参考”“请咨询专业人士”等模板化免责句。
"""
THRESHOLD_RECOMMENDATION_REQUIRED_HEADINGS = ("最终答案", "推荐理由", "执行条件")

SQL_SYSTEM_PROMPT = """你是只读金融数据查询规划器。只生成可执行 MySQL SELECT SQL，并且只返回 JSON。
禁止输出解释、Markdown、代码块或多余文本。禁止写入、DDL、多语句和非白名单对象。
"""

QUESTION_ROUTER_SYSTEM_PROMPT = """你是问答前置路由器。
你需要在同一次判断中决定：问题是否允许由本助手回答、是否需要查询结构化数据、
以及是否需要按需补充结构化市场数据。
你的目标不是按关键词套规则，而是理解用户的真实研究任务，
再判断为了让最终 LLM 回答得专业、可复核，需要补哪些证据。
数据包分类是内部证据菜单，不是回答提纲；最终回答会由 LLM 按用户问题自主组织。
通用知识、翻译、改写、解释概念、写作润色和普通问答也属于允许范围；
这类问题不需要 SQL、不需要市场数据，直接由 LLM 回答。
如果用户在问 A 股或港股的估值、财报、分红、A/H 价差、配置择边、投资分析、“怎么看”或多只股票对比，
应优先思考是否需要结构化市场数据支撑，而不是直接让模型凭常识回答。
同时输出 `answer_mode`：
- `stock_research`：单只 A 股或港股投资分析、公司怎么看、分析某公司、估值/财报/基本面判断。
- `full_report`：用户明确要求投资分析报告、深度报告或完整报告。
- `open_research`：A/H 价差、行业、组合、宏观策略、多股开放比较等非单只公司完整分析。
- `data_only`：用户只要数据、明细、表格或列表，不要求判断。
- `general`：通用知识、翻译、改写、概念解释或问候。
按需补充市场数据最多输出 5 只股票。A 股数据包可以从 quote_valuation、
financial_statement、business_profile、dividend_forecast、shareholder_governance、
capital_flow_light 中选择；港股当前只允许 financial_statement 数据包，
代码必须是 5 位港股 Tushare 代码，例如 02380.HK，不要输出港股行情、指数、
全市场或任意 Tushare 接口名。
如果用户只给公司名而你无法确信 ts_code，不要编造代码；可以让 data_demands 为空，
后端会在本地股票候选内做语义消歧。
A 股数据包含义：
- quote_valuation：日线行情、最新收盘、近 20/60/120 日走势、成交额、换手率、
PE、PB、PS、市值、流通市值、股息率等，用于判断价格位置和估值。
- financial_statement：利润表、资产负债表、现金流量表、财务指标；包含收入、利润、
扣非利润、EPS、ROE、毛利率、净利率、资产负债率、货币资金、有息负债、经营/投资/筹资现金流等，
用于判断基本面、利润质量、资产质量和现金流匹配。
- business_profile：主营业务产品/地区构成、收入和利润来源、审计意见、审计机构、
签字会计师、审计费用、业绩快报及是否审计等，用于判断业务结构和报表可靠性。
- dividend_forecast：分红方案、派息进度、股息相关字段、业绩预告类型、预告摘要、
业绩变动区间和变动原因等，用于判断股东回报和业绩前瞻。
- shareholder_governance：前十大股东、前十大流通股东、持股比例、持股变化、
股东户数、质押次数、质押股数、总股本和质押比例等，用于判断治理、筹码和质押风险。
- capital_flow_light：近端个股资金流向、小单/中单/大单/特大单买卖额和净流入，
用于解释短期交易情绪，不能替代基本面结论。
路由重点是控制股票数量和时间窗口，但不要把单股研究压缩成一个数据包；
只要问题需要形成投资判断、解释异常或判断性质，就应主动选择能互相校验的多个数据包。
A 股数据包选择思路：
1. 先判断研究问题需要哪些证据：价格/估值、财务质量、业务结构、分红预期、治理筹码、短期交易情绪。
2. 再映射到数据包：估值和价格位置用 quote_valuation；财报质量用 financial_statement；
业务结构和审计快报用 business_profile；分红和业绩预告用 dividend_forecast；
股东、质押和筹码用 shareholder_governance；短线资金用 capital_flow_light。
3. 个股投资分析报告、深度报告、怎么看、配置建议：通常至少选择 quote_valuation、
financial_statement、business_profile、dividend_forecast、shareholder_governance；
用户明确问短线资金时再加 capital_flow_light。
4. 财务报表大幅更改、重述、追溯调整、差错更正、会计政策/会计估计变更、审计意见、
业绩快报、年报/季报异常性质：必须选择 financial_statement、business_profile、
shareholder_governance；需要估值判断时再加 quote_valuation。
5. A/H 或港股通择边问题，若能识别 A/H 两地标的，应同时提出 A 股和港股数据需求；
A 股侧尽量补估值、财务、分红和治理，港股侧按当前能力补 financial_statement，
最终回答再结合已有 A/H 价差和港股通上下文。
投资研究范围包括股票、基金、指数、行业、估值、财报、红利、仓位、风险、
组合配置、A/H 溢价、港股通、宏观与投资策略相关问题；股票代码、公司投研、
阈值建议和投资报告写作也属于范围。
用户询问“你好”“你是谁”“你能做什么”“你可以帮我什么”等问候、角色身份和能力介绍问题也属于允许范围。
违法违规交易、索要敏感信息和账号越权操作不属于范围。
如果问题需要当前/最近/自选/阈值/列表/排名/筛选/股票代码/精确数值，通常需要查询结构化数据。
只返回 JSON，不要输出解释。格式：
{"is_answerable":true或false,"needs_sql":true或false,"answer_mode":"stock_research或full_report或open_research或data_only或general","data_demands":[{"market":"A或HK","ts_code":"600036.SH或02380.HK","packages":["quote_valuation","financial_statement","business_profile","dividend_forecast","shareholder_governance","capital_flow_light"],"intent":"stock_research"}],"reason":"一句话原因"}
"""

OUT_OF_SCOPE_MESSAGE = (
    "这个请求涉及违法违规交易、敏感信息或账号越权操作，我不能协助。"
    "你可以改问通用知识、翻译、写作润色、投资研究、A/H 溢价、财报、估值或风险控制相关问题。"
)

SERVICE_INTRO_MESSAGE = (
    "你好，我是这个 A/H 溢价投资助手里的智能问答。"
    "我主要帮你做几类事情：分析 A/H 与 H/A 溢价机会、查看港股通和自选股阈值、"
    "解释股票和行业估值、整理投研报告要点、比较候选标的，并把风险、触发条件和反证条件说清楚。"
    "\n\n你可以直接问："
    "\n\n- 最近哪些 AH 标的接近我的阈值？"
    "\n- 招商银行现在更适合持有 A 股还是 H 股？"
    "\n- 帮我用红利、ROE、估值筛一批 A 股候选。"
    "\n- 某只股票当前的核心风险和跟踪指标是什么？"
)

INVESTMENT_KEYWORDS = (
    "投资",
    "股票",
    "a股",
    "h股",
    "港股",
    "美股",
    "基金",
    "债券",
    "指数",
    "行业",
    "宏观",
    "产业",
    "行情",
    "股价",
    "估值",
    "财报",
    "分红",
    "红利",
    "股息",
    "pe",
    "pb",
    "roe",
    "市盈率",
    "市净率",
    "净资产收益率",
    "仓位",
    "组合",
    "配置",
    "收益",
    "回撤",
    "风险",
    "买入",
    "卖出",
    "持有",
    "建仓",
    "减仓",
    "止损",
    "自选股",
    "标的",
    "个股",
    "阈值",
    "机会",
    "策略",
    "低估值",
    "蓝筹",
    "选股",
    "溢价",
    "折价",
    "套利",
    "价差",
    "港股通",
    "沪深港通",
    "汇率",
    "流动性",
    "金融",
    "银行",
    "非银",
    "券商",
    "保险",
    "白酒",
    "五粮液",
    "招商银行",
    "房地产",
    "地产",
    "地方财政",
    "日本",
    "资产负债表",
    "stock",
    "equity",
    "portfolio",
    "valuation",
    "dividend",
)

DATA_INTENT_KEYWORDS = (
    "哪些",
    "哪个",
    "名单",
    "列表",
    "排名",
    "排行",
    "筛选",
    "候选",
    "推荐",
    "最新",
    "最近",
    "当前",
    "今日",
    "今天",
    "交易日",
    "自选",
    "观察",
    "对比",
    "比较",
    "表格",
    "top",
    "pe",
    "pb",
    "roe",
    "股息",
    "分红",
    "溢价",
    "折价",
    "价差",
)
REPORT_ANALYSIS_KEYWORDS = (
    "报告",
    "投资逻辑",
    "买点",
    "反证",
    "验证点",
    "风险",
    "跟踪指标",
    "核心假设",
    "长期投资价值",
)
REALTIME_DATA_KEYWORDS = (
    "最新",
    "当前",
    "今日",
    "今天",
    "最近一个交易日",
    "股价",
    "收盘",
    "行情",
    "列表",
    "排名",
    "筛选",
)
NON_INVESTMENT_KEYWORDS = (
    "绕过风控",
    "操纵市场",
    "内幕消息",
    "内幕交易",
    "密码",
    "token",
    "apikey",
    "api_key",
    "银行卡",
    "身份证",
)
GENERAL_QUESTION_KEYWORDS = (
    "翻译",
    "英文",
    "中文",
    "解释",
    "是什么",
    "为什么",
    "怎么理解",
    "知识",
    "概念",
    "润色",
    "改写",
    "总结",
    "写一段",
    "写诗",
    "作文",
    "代码",
    "编程",
    "bug",
)
DATA_ONLY_KEYWORDS = (
    "只要数据",
    "不要分析",
    "不用分析",
    "别分析",
    "先给数据",
    "返回数据",
    "给我数据",
    "给我看数据",
    "列出数据",
    "数据表",
    "明细",
    "原始数据",
    "财报数据",
    "估值数据",
    "分红数据",
    "现金流数据",
)
DATA_ONLY_SUBJECT_KEYWORDS = (
    "数据",
    "明细",
    "表格",
    "列表",
    "财报",
    "财务",
    "利润表",
    "资产负债表",
    "现金流量表",
    "估值",
    "行情",
    "分红",
    "业绩预告",
)
DATA_ONLY_REQUEST_KEYWORDS = (
    "给我",
    "查",
    "查询",
    "看",
    "看看",
    "列",
    "列出",
    "返回",
    "展示",
    "提供",
    "拿",
    "调",
)
DATA_ANALYSIS_KEYWORDS = (
    "分析",
    "怎么看",
    "对比",
    "比较",
    "建议",
    "报告",
    "价值",
    "逻辑",
    "结论",
    "买",
    "卖",
    "持有",
    "配置",
    "判断",
)
DATA_FIELD_LABELS = {
    "trade_date": "交易日",
    "factor_date": "因子日",
    "latest_trade_date": "最新交易日",
    "end_date": "报告期",
    "ann_date": "公告日",
    "latest_report_period": "最新报告期",
    "latest_dividend_period": "最新分红期",
    "latest_cash_div_tax": "最新税前分红",
    "latest_dividend_proc": "最新分红进度",
    "latest_forecast_ann_date": "最新预告日",
    "latest_forecast_type": "预告类型",
    "latest_forecast_summary": "预告摘要",
    "latest_net_mf_amount": "最新主力净流入",
    "latest_big_order_net_amount": "最新大单净流入",
    "a_ts_code": "A股代码",
    "hk_ts_code": "H股代码",
    "ts_code": "股票代码",
    "symbol": "证券简称代码",
    "a_name": "A股名称",
    "hk_name": "H股名称",
    "name": "名称",
    "display_name": "标的",
    "industry": "行业",
    "area": "地区",
    "market": "市场",
    "currency": "币种",
    "report_type": "报告类型",
    "std_report_date": "标准报告期",
    "statement_type": "报表类型",
    "ind_name": "指标名称",
    "ind_value": "指标值",
    "user_id": "用户ID",
    "watchlist_id": "自选ID",
    "holding_market": "持有市场",
    "sort_order": "排序",
    "note": "备注",
    "is_realtime": "实时数据",
    "data_source": "数据来源",
    "source_updated_at": "来源更新时间",
    "updated_at": "更新时间",
    "started_at": "开始时间",
    "finished_at": "完成时间",
    "status": "状态",
    "cache_hit": "命中缓存",
    "row_count": "行数",
    "error_message": "错误信息",
    "intent": "意图",
    "market_scope": "市场范围",
    "symbols_json": "股票列表",
    "data_packages_json": "数据包",
    "period_policy": "周期策略",
    "business_type": "主营类型",
    "bz_item": "主营项目",
    "bz_sales": "主营收入",
    "bz_profit": "主营利润",
    "bz_cost": "主营成本",
    "gross_margin": "主营毛利率",
    "revenue_share_pct": "收入占比%",
    "curr_type": "币种",
    "latest_audit_result": "最新审计意见",
    "latest_audit_agency": "最新审计机构",
    "latest_express_revenue": "最新快报收入",
    "latest_express_n_income": "最新快报净利润",
    "latest_express_yoy_sales": "快报营收同比%",
    "latest_express_yoy_dedu_np": "快报扣非同比%",
    "latest_express_summary": "快报摘要",
    "latest_holder_profit": "最新股东应占利润",
    "latest_operate_income": "最新营业收入",
    "latest_dividend_rate": "最新股息率",
    "latest_pe_ttm": "最新PE TTM",
    "latest_pb_ttm": "最新PB TTM",
    "section_type": "股东分组",
    "sort_date": "排序日期",
    "ranking": "排名",
    "holder_scope": "股东范围",
    "holder_name": "股东名称",
    "hold_amount": "持股数量",
    "hold_ratio": "持股比例%",
    "hold_float_ratio": "流通股占比%",
    "hold_change": "持股变动",
    "holder_type": "股东类型",
    "holder_num": "股东户数",
    "latest_holder_num": "最新股东户数",
    "pledge_count": "质押笔数",
    "pledge_ratio": "质押比例%",
    "latest_pledge_ratio": "最新质押比例%",
    "total_pledge": "质押总量",
    "net_mf_amount": "主力净流入",
    "big_order_net_amount": "大单净流入",
    "extra_big_order_net_amount": "超大单净流入",
    "buy_lg_amount": "大单买入额",
    "sell_lg_amount": "大单卖出额",
    "buy_elg_amount": "超大单买入额",
    "sell_elg_amount": "超大单卖出额",
    "ah_ratio": "A/H比价",
    "ah_premium_pct": "A/H溢价%",
    "ha_ratio": "H/A比价",
    "ha_premium_pct": "H/A溢价%",
    "metric_premium_pct": "观察溢价%",
    "target_premium_pct": "目标阈值%",
    "distance_to_target_pct": "距阈值%",
    "premium_percentile_60": "60日分位",
    "is_hk_connect": "港股通",
    "connect_channels": "通道",
    "preferred_direction": "关注方向",
    "opportunity_status": "状态",
    "selection_tags": "标签",
    "selection_score": "评分",
    "selection_reason": "入选理由",
    "a_close": "A股收盘价",
    "hk_close": "H股收盘价",
    "a_pct_chg": "A股涨跌幅%",
    "hk_pct_chg": "H股涨跌幅%",
    "close": "收盘价",
    "pct_chg": "涨跌幅%",
    "turnover_rate": "换手率%",
    "pe": "PE",
    "pe_ttm": "PE TTM",
    "pb": "PB",
    "pb_ttm": "PB TTM",
    "ps_ttm": "PS TTM",
    "dividend_yield_ttm": "股息率",
    "total_mv": "总市值",
    "total_market_cap": "总市值",
    "hksk_market_cap": "港股市值",
    "circ_mv": "流通市值",
    "eps": "每股收益",
    "roe": "ROE",
    "roe_waa": "加权ROE",
    "roe_avg": "平均ROE",
    "roe_dt": "扣非ROE",
    "roe_yearly": "年度ROE",
    "roic_yearly": "年度ROIC",
    "roa": "ROA",
    "grossprofit_margin": "毛利率",
    "netprofit_margin": "净利率",
    "sales_gpr": "销售毛利率",
    "profit_to_gr": "利润/营收",
    "debt_to_assets": "资产负债率",
    "calculated_debt_to_assets": "计算资产负债率",
    "assets_to_eqt": "权益乘数",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "revenue_yoy": "营收同比%",
    "q_sales_yoy": "单季营收同比%",
    "netprofit_yoy": "净利同比%",
    "q_netprofit_yoy": "单季净利同比%",
    "ocf_to_revenue": "经营现金/营收",
    "ocf_sales": "经营现金/收入",
    "ocfps": "每股经营现金流",
    "per_netcash_operate": "每股经营现金流",
    "per_oi": "每股营业收入",
    "bps": "每股净资产",
    "profit_dedt": "扣非净利润",
    "total_revenue": "营业总收入",
    "revenue": "营业收入",
    "operate_income": "营业收入",
    "operate_income_yoy": "营业收入同比%",
    "operate_income_qoq": "营业收入环比%",
    "total_cogs": "营业总成本",
    "oper_cost": "营业成本",
    "biz_tax_surchg": "税金及附加",
    "sell_exp": "销售费用",
    "admin_exp": "管理费用",
    "fin_exp": "财务费用",
    "rd_exp": "研发费用",
    "assets_impair_loss": "资产减值损失",
    "credit_impa_loss": "信用减值损失",
    "oth_income": "其他收益",
    "asset_disp_income": "资产处置收益",
    "operate_profit": "营业利润",
    "gross_profit": "毛利",
    "gross_profit_yoy": "毛利同比%",
    "gross_profit_qoq": "毛利环比%",
    "holder_profit": "股东应占利润",
    "holder_profit_yoy": "股东应占利润同比%",
    "holder_profit_qoq": "股东应占利润环比%",
    "non_oper_income": "营业外收入",
    "non_oper_exp": "营业外支出",
    "total_profit": "利润总额",
    "income_tax": "所得税",
    "n_income": "净利润",
    "n_income_attr_p": "归母净利润",
    "minority_gain": "少数股东损益",
    "invest_income": "投资收益",
    "fv_value_chg_gain": "公允价值变动收益",
    "ebit": "EBIT",
    "ebitda": "EBITDA",
    "cashflow_net_profit": "现金流净利润",
    "cashflow_finan_exp": "现金流财务费用",
    "c_fr_sale_sg": "销售收现",
    "c_paid_goods_s": "采购付现",
    "c_paid_to_for_empl": "支付职工现金",
    "c_paid_for_taxes": "支付税费",
    "n_cashflow_act": "经营现金流净额",
    "c_recp_return_invest": "收回投资现金",
    "n_recp_disp_fiolta": "处置长期资产现金",
    "c_pay_acq_const_fiolta": "购建长期资产现金",
    "n_cashflow_inv_act": "投资现金流净额",
    "c_recp_borrow": "取得借款现金",
    "c_prepay_amt_borr": "偿还债务现金",
    "c_pay_dist_dpcp_int_exp": "分红付息现金",
    "n_cash_flows_fnc_act": "筹资现金流净额",
    "n_incr_cash_cash_equ": "现金等价物增加额",
    "c_cash_equ_end_period": "期末现金等价物",
    "money_cap": "货币资金",
    "trad_asset": "交易性金融资产",
    "lt_eqt_invest": "长期股权投资",
    "invest_real_estate": "投资性房地产",
    "notes_receiv": "应收票据",
    "accounts_receiv": "应收账款",
    "oth_receiv": "其他应收款",
    "inventories": "存货",
    "fix_assets": "固定资产",
    "cip": "在建工程",
    "intan_assets": "无形资产",
    "goodwill": "商誉",
    "total_cur_assets": "流动资产合计",
    "total_nca": "非流动资产合计",
    "total_assets": "资产总计",
    "total_liabilities": "负债合计",
    "st_borr": "短期借款",
    "notes_payable": "应付票据",
    "acct_payable": "应付账款",
    "contract_liab": "合同负债",
    "lt_borr": "长期借款",
    "bond_payable": "应付债券",
    "total_cur_liab": "流动负债合计",
    "total_ncl": "非流动负债合计",
    "total_liab": "负债合计",
    "total_hldr_eqy_inc_min_int": "所有者权益合计",
    "total_hldr_eqy_exc_min_int": "归母权益合计",
    "total_parent_equity": "母公司股东权益",
    "debt_asset_ratio": "资产负债率",
    "netcash_operate": "经营现金流净额",
    "netcash_invest": "投资现金流净额",
    "netcash_finance": "筹资现金流净额",
    "end_cash": "期末现金",
    "divi_ratio": "派息比例",
    "dividend_rate": "股息率",
    "dps_hkd": "每股股息HKD",
    "cap_rese": "资本公积",
    "surplus_rese": "盈余公积",
    "undistr_porfit": "未分配利润",
    "return_20d": "20日涨跌幅",
    "return_60d": "60日涨跌幅",
    "return_120d": "120日涨跌幅",
}


@dataclass(frozen=True)
class ChatAnswer:
    """LLM 问答结果。

    创建日期：2026-05-04
    author: sunshengxian
    """

    answer: str
    sql: str | None
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class LlmEndpoint:
    """OpenAI-compatible 模型调用端点。

    创建日期：2026-05-04
    author: sunshengxian
    """

    provider: str
    base_url: str
    api_key: str | None
    model: str


@dataclass(frozen=True)
class LlmCallTrace:
    """LLM 单轮调用日志上下文。

    创建日期：2026-05-05
    author: sunshengxian
    """

    question_id: str
    phase: str
    user_id: int | None = None
    session_id: int | None = None
    conversation_title: str | None = None
    user_name: str | None = None


@dataclass(frozen=True)
class ThresholdRecommendationResult:
    """自选股阈值推荐的本地确定性计算结果。

    创建日期：2026-05-07
    author: sunshengxian
    """

    threshold_pct: Decimal
    direction: str
    direction_label: str
    reason_code: str
    formula_note: str


@dataclass(frozen=True)
class QuestionRoute:
    """问答前置路由结果。

    创建日期：2026-05-05
    author: sunshengxian
    """

    is_answerable: bool
    should_query_data: bool
    data_demands: tuple[MarketDataDemand, ...] = ()
    reason: str = ""
    answer_mode: str = "open_research"


@dataclass(frozen=True)
class StockDisambiguationResult:
    """LLM 基于本地股票候选做语义消歧后的结果。

    创建日期：2026-05-07
    author: sunshengxian
    """

    selected_ts_codes: tuple[str, ...]
    reason: str = ""
    confidence: float = 0.0


class LlmDailyLimitExceeded(Exception):
    """LLM 项目级日调用限流异常。

    创建日期：2026-05-05
    author: sunshengxian
    """


class LlmService:
    """OpenAI-compatible LLM 问答服务。

    创建日期：2026-05-04
    author: sunshengxian
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.sql_guard = SqlGuardService()
        self._metric_context_by_question_id: dict[str, tuple[str | None, str | None]] = {}

    def answer(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> ChatAnswer:
        """根据本地数据回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        question_id = self._new_trace_id()
        request_context = context or {}
        user_id, session_id = self._trace_scope(request_context)
        self._register_metric_context(question_id, question, request_context, user_id)
        started_at = perf_counter()
        selected_model = self._normalize_chat_model(model or self.settings.llm_model)
        if self._is_service_intro_question(question):
            self._log_total_elapsed(
                "sync_intro",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(answer=SERVICE_INTRO_MESSAGE, sql=None, rows=[])
        if self._threshold_recommendation_context(request_context):
            return self._answer_threshold_recommendation(
                question,
                request_context,
                selected_model,
                question_id,
                started_at,
                user_id,
                session_id,
            )
        if self._is_follow_up_question(question, request_context):
            return self._answer_follow_up(
                question,
                request_context,
                selected_model,
                question_id,
                started_at,
                user_id,
                session_id,
            )
        route = self._route_question(
            question,
            request_context,
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
        )
        if not route.is_answerable:
            self._log_total_elapsed(
                "sync_out_of_scope",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(answer=OUT_OF_SCOPE_MESSAGE, sql=None, rows=[])
        endpoint = self._model_endpoint(selected_model)
        if not endpoint.api_key or not endpoint.model:
            self._log_total_elapsed(
                "sync_not_configured",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(
                answer=(
                    f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                    "并确认模型名称后再使用智能问答。"
                ),
                sql=None,
                rows=[],
            )
        if self._is_general_direct_question(question, route):
            answer = self._chat_completion(
                self._general_answer_prompt(question, request_context),
                system_prompt=GENERAL_ASSISTANT_SYSTEM_PROMPT,
                model=selected_model,
                trace=LlmCallTrace(
                    question_id=question_id,
                    phase="answer",
                    user_id=user_id,
                    session_id=session_id,
                    conversation_title=self._metric_conversation_title(question_id),
                    user_name=self._metric_user_name(question_id),
                ),
            )
            self._log_total_elapsed(
                "sync_done",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(answer=answer.strip(), sql=None, rows=[])
        sql, rows, prompt = self._prepare_answer(
            question,
            request_context,
            route,
            selected_model,
            question_id,
            user_id,
            session_id,
        )
        answer = self._chat_completion(
            prompt,
            system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
            model=selected_model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="answer",
                user_id=user_id,
                session_id=session_id,
                conversation_title=self._metric_conversation_title(question_id),
                user_name=self._metric_user_name(question_id),
            ),
        )
        answer = self._strip_forbidden_preamble(answer)
        self._log_total_elapsed(
            "sync_done",
            question_id,
            selected_model,
            started_at,
            len(rows),
            user_id=user_id,
            session_id=session_id,
        )
        return ChatAnswer(answer=answer, sql=sql, rows=rows)

    def stream_answer(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> tuple[str | None, list[dict[str, Any]], Iterator[str]]:
        """根据本地数据流式回答问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        question_id = self._new_trace_id()
        request_context = context or {}
        user_id, session_id = self._trace_scope(request_context)
        self._register_metric_context(question_id, question, request_context, user_id)
        started_at = perf_counter()
        selected_model = self._normalize_chat_model(model or self.settings.llm_model)
        if self._is_service_intro_question(question):
            self._log_total_elapsed(
                "stream_intro",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([SERVICE_INTRO_MESSAGE])
        if self._threshold_recommendation_context(request_context):
            return self._stream_threshold_recommendation(
                question,
                request_context,
                selected_model,
                question_id,
                started_at,
                user_id,
                session_id,
            )
        if self._is_follow_up_question(question, request_context):
            return self._stream_follow_up(
                question,
                request_context,
                selected_model,
                question_id,
                started_at,
                user_id,
                session_id,
            )
        route = self._route_question(
            question,
            request_context,
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
        )
        if not route.is_answerable:
            self._log_total_elapsed(
                "stream_out_of_scope",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([OUT_OF_SCOPE_MESSAGE])
        endpoint = self._model_endpoint(selected_model)
        if not endpoint.api_key or not endpoint.model:
            message = (
                f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                "并确认模型名称后再使用智能问答。"
            )
            self._log_total_elapsed(
                "stream_not_configured",
                question_id,
                selected_model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([message])
        if self._is_general_direct_question(question, route):
            return None, [], self._chat_completion_stream(
                self._general_answer_prompt(question, request_context),
                system_prompt=GENERAL_ASSISTANT_SYSTEM_PROMPT,
                model=selected_model,
                trace=LlmCallTrace(
                    question_id=question_id,
                    phase="answer_stream",
                    user_id=user_id,
                    session_id=session_id,
                    conversation_title=self._metric_conversation_title(question_id),
                    user_name=self._metric_user_name(question_id),
                ),
                total_started_at=started_at,
            )
        sql, rows, prompt = self._prepare_answer(
            question,
            request_context,
            route,
            selected_model,
            question_id,
            user_id,
            session_id,
        )
        return sql, rows, self._clean_answer_stream(
            self._chat_completion_stream(
                prompt,
                system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
                model=selected_model,
                trace=LlmCallTrace(
                    question_id=question_id,
                    phase="answer_stream",
                    user_id=user_id,
                    session_id=session_id,
                    conversation_title=self._metric_conversation_title(question_id),
                    user_name=self._metric_user_name(question_id),
                ),
                total_started_at=started_at,
                row_count=len(rows),
            )
        )

    def _prepare_answer(
        self,
        question: str,
        context: dict[str, Any],
        route: QuestionRoute,
        model: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> tuple[str | None, list[dict[str, Any]], str]:
        sql: str | None = None
        rows: list[dict[str, Any]] = []
        market_data_context = self._ensure_market_data_context(
            question,
            context,
            route,
            question_id,
            user_id,
            session_id,
        )
        # 路由已经明确给出个股按需补数需求，并且编排器已产出市场上下文时，
        # 直接以结构化补数上下文回答；不再额外生成通用 SQL，避免港股问题误查 A 股视图。
        should_run_sql = route.should_query_data and not (
            route.data_demands and market_data_context
        )
        if should_run_sql:
            try:
                sql = self._default_sql_for_question(question, context) or self._generate_sql(
                    question,
                    context,
                    model,
                    question_id,
                    user_id,
                    session_id,
                )
                for attempt in range(2):
                    try:
                        guarded = self.sql_guard.validate(
                            sql,
                            default_limit=self.settings.query_limit_default,
                            max_limit=self.settings.query_limit_max,
                        )
                        sql_started_at = perf_counter()
                        rows = self._execute_sql(guarded.sql)
                        logger.info(
                            "LLM SQL 执行完成 question_id=%s rows=%s elapsed_ms=%.1f",
                            question_id,
                            len(rows),
                            (perf_counter() - sql_started_at) * 1000,
                        )
                        self._record_llm_metric(
                            phase="execute_sql",
                            question_id=question_id,
                            user_id=user_id,
                            session_id=session_id,
                            conversation_title=self._metric_conversation_title(question_id),
                            user_name=self._metric_user_name(question_id),
                            provider="Database",
                            model=None,
                            elapsed_ms=(perf_counter() - sql_started_at) * 1000,
                            row_count=len(rows),
                            success=True,
                        )
                        sql = guarded.sql
                        break
                    except (SQLAlchemyError, SqlGuardError) as exc:
                        if attempt == 1:
                            raise
                        sql = self._repair_sql(
                            question,
                            context,
                            sql,
                            str(exc),
                            model,
                            question_id,
                            user_id,
                            session_id,
                        )
            except (
                SQLAlchemyError,
                SqlGuardError,
                ValueError,
                json.JSONDecodeError,
                httpx.HTTPError,
            ):
                logger.error("LLM 数据查询准备失败，降级为无精确数据回答", exc_info=True)
                sql = None
                rows = []
        if self._is_data_only_question(question) and (rows or market_data_context):
            return sql, rows, self._data_only_answer(question, rows, market_data_context)
        return sql, rows, self._answer_prompt(
            question,
            rows,
            context,
            route,
            market_data_context=market_data_context,
        )

    def _answer_threshold_recommendation(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
        question_id: str,
        started_at: float,
        user_id: int | None,
        session_id: int | None,
    ) -> ChatAnswer:
        """按页面传入数据生成自选阈值推荐，跳过通用路由、补数和辅助视图查询。

        创建日期：2026-05-07
        author: sunshengxian
        """

        endpoint = self._model_endpoint(model)
        if not endpoint.api_key or not endpoint.model:
            answer = self._threshold_recommendation_fallback(context)
            self._log_total_elapsed(
                "threshold_done",
                question_id,
                model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(answer=answer, sql=None, rows=[])
        try:
            answer = self._chat_completion(
                self._threshold_recommendation_prompt(question, context),
                system_prompt=THRESHOLD_RECOMMENDATION_SYSTEM_PROMPT,
                model=model,
                trace=LlmCallTrace(
                    question_id=question_id,
                    phase="threshold_answer",
                    user_id=user_id,
                    session_id=session_id,
                    conversation_title=self._metric_conversation_title(question_id),
                    user_name=self._metric_user_name(question_id),
                ),
            )
        except httpx.HTTPError:
            # 阈值推荐已经有本地确定性公式，外部模型繁忙时不能让设置提醒流程整体不可用。
            logger.error(
                "阈值推荐模型调用失败，返回本地确定性阈值 question_id=%s",
                question_id,
                exc_info=True,
            )
            answer = self._threshold_recommendation_fallback(context)
        self._log_total_elapsed(
            "threshold_done",
            question_id,
            endpoint.model,
            started_at,
            user_id=user_id,
            session_id=session_id,
        )
        return ChatAnswer(
            answer=self._normalize_threshold_recommendation_markdown(answer),
            sql=None,
            rows=[],
        )

    def _stream_threshold_recommendation(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
        question_id: str,
        started_at: float,
        user_id: int | None,
        session_id: int | None,
    ) -> tuple[str | None, list[dict[str, Any]], Iterator[str]]:
        """流式输出自选阈值推荐，让用户先看到首包，不等待完整回答落地。

        创建日期：2026-05-07
        author: sunshengxian
        """

        endpoint = self._model_endpoint(model)
        if not endpoint.api_key or not endpoint.model:
            self._log_total_elapsed(
                "threshold_stream_done",
                question_id,
                model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([self._threshold_recommendation_fallback(context)])
        chunks = self._chat_completion_stream(
            self._threshold_recommendation_prompt(question, context),
            system_prompt=THRESHOLD_RECOMMENDATION_SYSTEM_PROMPT,
            model=model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="threshold_answer_stream",
                user_id=user_id,
                session_id=session_id,
                conversation_title=self._metric_conversation_title(question_id),
                user_name=self._metric_user_name(question_id),
            ),
            total_started_at=started_at,
            total_phase="threshold_stream_done",
        )
        return None, [], self._normalize_threshold_recommendation_stream(
            self._clean_answer_stream(self._fallback_threshold_stream(chunks, context, question_id))
        )

    def _threshold_recommendation_context(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """读取前端传入的结构化阈值推荐上下文，缺失时维持原通用问答链路。

        创建日期：2026-05-07
        author: sunshengxian
        """

        payload = context.get("threshold_recommendation")
        if isinstance(payload, dict) and payload:
            return payload
        return None

    def _answer_follow_up(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
        question_id: str,
        started_at: float,
        user_id: int | None,
        session_id: int | None,
    ) -> ChatAnswer:
        """同会话追问直接交给模型结合历史回答，避免重复触发补数和报告模板。

        创建日期：2026-05-09
        author: sunshengxian
        """

        endpoint = self._model_endpoint(model)
        if not endpoint.api_key or not endpoint.model:
            self._log_total_elapsed(
                "sync_not_configured",
                question_id,
                model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return ChatAnswer(
                answer=(
                    f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                    "并确认模型名称后再使用智能问答。"
                ),
                sql=None,
                rows=[],
            )
        answer = self._chat_completion(
            self._follow_up_answer_prompt(question, context),
            system_prompt=FOLLOW_UP_ASSISTANT_SYSTEM_PROMPT,
            model=model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="follow_up_answer",
                user_id=user_id,
                session_id=session_id,
                conversation_title=self._metric_conversation_title(question_id),
                user_name=self._metric_user_name(question_id),
            ),
        )
        self._log_total_elapsed(
            "sync_done",
            question_id,
            endpoint.model,
            started_at,
            user_id=user_id,
            session_id=session_id,
        )
        return ChatAnswer(answer=self._strip_forbidden_preamble(answer), sql=None, rows=[])

    def _stream_follow_up(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
        question_id: str,
        started_at: float,
        user_id: int | None,
        session_id: int | None,
    ) -> tuple[str | None, list[dict[str, Any]], Iterator[str]]:
        """流式追问回答只携带会话历史，不进入通用路由、SQL 和按需补数。

        创建日期：2026-05-09
        author: sunshengxian
        """

        endpoint = self._model_endpoint(model)
        if not endpoint.api_key or not endpoint.model:
            message = (
                f"{endpoint.provider} LLM 未配置。请设置对应 API Key 文件或环境变量，"
                "并确认模型名称后再使用智能问答。"
            )
            self._log_total_elapsed(
                "stream_not_configured",
                question_id,
                model,
                started_at,
                user_id=user_id,
                session_id=session_id,
            )
            return None, [], iter([message])
        return None, [], self._clean_answer_stream(
            self._chat_completion_stream(
                self._follow_up_answer_prompt(question, context),
                system_prompt=FOLLOW_UP_ASSISTANT_SYSTEM_PROMPT,
                model=model,
                trace=LlmCallTrace(
                    question_id=question_id,
                    phase="follow_up_answer_stream",
                    user_id=user_id,
                    session_id=session_id,
                    conversation_title=self._metric_conversation_title(question_id),
                    user_name=self._metric_user_name(question_id),
                ),
                total_started_at=started_at,
                total_phase="follow_up_stream_done",
            )
        )

    def _is_follow_up_question(self, question: str, context: dict[str, Any]) -> bool:
        """用轻量 LLM 识别同会话追问，失败时保守交给正常数据路由。

        创建日期：2026-05-09
        author: sunshengxian
        """

        history = self._conversation_history(context)
        if not history or not question.strip():
            return False
        try:
            content = self._chat_completion(
                self._follow_up_route_prompt(question, context),
                system_prompt=FOLLOW_UP_ROUTER_SYSTEM_PROMPT,
                model=self.settings.resolve_question_router_model(),
                temperature=0,
                trace=None,
            )
            payload = self._extract_json(content)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            logger.error("追问分流模型失败，保守进入正常数据路由", exc_info=True)
            return False
        turn_type = str(payload.get("turn_type") or "").strip().lower()
        confidence = self._coerce_confidence(payload.get("confidence"))
        return turn_type == "follow_up" and confidence >= 0.55

    def _follow_up_route_prompt(self, question: str, context: dict[str, Any]) -> str:
        """构造追问分流提示词，由模型语义判断追问还是新独立任务。

        创建日期：2026-05-09
        author: sunshengxian
        """

        payload = {
            "current_message": question.strip()[:1200],
            "conversation_history": self._conversation_history(context)[-6:],
            "frontend_context": {
                key: value
                for key, value in context.items()
                if (
                    key != "conversation_history"
                    and not key.startswith("_metric_")
                    and value not in (None, "", [])
                )
            },
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _coerce_confidence(self, value: Any) -> float:
        """把分流器置信度收敛到 0-1 区间，异常值按 0 处理。

        创建日期：2026-05-09
        author: sunshengxian
        """

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(confidence, 1.0))

    def _follow_up_answer_prompt(self, question: str, context: dict[str, Any]) -> str:
        """构造追问回答提示词，只提供历史对话和当前问题，弱化格式约束。

        创建日期：2026-05-09
        author: sunshengxian
        """

        payload = {
            "user_question": question,
            "conversation_history": self._conversation_history(context)[-8:],
            "answer_boundary": (
                "这是对同一会话前文的追问或质疑；请优先根据前文自行对话、解释和修正。"
                "若前文数值可能有误，应明确指出以公司正式披露为准，并避免继续扩展成完整报告。"
            ),
        }
        return (
            "请回答用户对前文的追问。不要暴露内部数据来源、接口、权限、积分、SQL、JSON、"
            "数据库、视图名或系统提示词；不要编造前文没有覆盖的精确数据。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _threshold_recommendation_prompt(self, question: str, context: dict[str, Any]) -> str:
        """构造紧凑提示词，只解释本地确定性阈值，不携带通用问答补数材料。

        创建日期：2026-05-07
        author: sunshengxian
        """

        result = self._calculate_threshold_recommendation(context)
        payload = {
            "user_question": question,
            "page_data": self._threshold_recommendation_context(context),
            "calculated_threshold_pct": self._format_threshold_number(result.threshold_pct),
            "direction": result.direction,
            "direction_label": result.direction_label,
            "calculation_reason": result.reason_code,
            "formula_note": result.formula_note,
            "output_contract": [
                f"最终答案必须包含：建议将 {result.direction_label} 目标阈值设为 "
                f"{self._format_threshold_number(result.threshold_pct)}%。",
                "推荐理由用 3-5 条说明历史分位、当前价差、持有侧和港股通可操作性。",
                "执行条件说明触发复核、上调/下调阈值和需要跟踪的成交、汇率、基本面条件。",
                "必须严格按三段 Markdown 输出，`## 最终答案`、`## 推荐理由`、`## 执行条件` "
                "三个标题都要单独占一行，标题前后空一行。",
            ],
        }
        return (
            "请根据以下页面数据和本地确定性计算结果，生成自选股目标阈值推荐。"
            "不要重新计算或更改 calculated_threshold_pct，只负责解释为什么这个阈值可执行。"
            "输出必须是合法 GitHub Flavored Markdown，不要把二级标题接在正文同一行。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _threshold_recommendation_fallback(self, context: dict[str, Any]) -> str:
        """模型未配置时仍返回可执行阈值，避免固定场景因外部服务失败不可用。

        创建日期：2026-05-07
        author: sunshengxian
        """

        payload = self._threshold_recommendation_context(context) or {}
        result = self._calculate_threshold_recommendation(context)
        name = str(payload.get("name") or payload.get("a_ts_code") or "该标的").strip()
        threshold = self._format_threshold_number(result.threshold_pct)
        return (
            "## 最终答案\n\n"
            f"建议将{name}的 {result.direction_label} 目标阈值设为 {threshold}%。\n\n"
            "## 推荐理由\n\n"
            f"- 本次按页面已有价差和 60 日分位数据计算，采用口径：{result.formula_note}\n"
            "- 该快路径不额外查询全市场或自选机会视图，因此相同页面输入会得到稳定阈值。\n"
            "- 当前模型服务未配置，先返回本地确定性结果；配置恢复后会由模型补充更细的文字解释。\n\n"
            "## 执行条件\n\n"
            "- 当关注方向溢价达到或超过该阈值时，先复核 A/H 报价日期、"
            "港股通通道、汇率和成交活跃度。\n"
            "- 若 60 日分位明显抬升且基本面未恶化，可上调阈值；若流动性或基本面走弱，应下调阈值。"
        )

    def _fallback_threshold_stream(
        self,
        chunks: Iterator[str],
        context: dict[str, Any],
        question_id: str,
    ) -> Iterator[str]:
        """阈值推荐流式模型失败时降级输出本地确定性阈值。

        创建日期：2026-05-08
        author: sunshengxian
        """

        try:
            yield from chunks
        except httpx.HTTPError:
            # 页面设置提醒依赖这段回答，外部模型繁忙时保留本地公式结果，避免用户无法继续保存阈值。
            logger.error(
                "阈值推荐流式模型失败，返回本地确定性阈值 question_id=%s",
                question_id,
                exc_info=True,
            )
            yield self._threshold_recommendation_fallback(context)

    def _calculate_threshold_recommendation(
        self,
        context: dict[str, Any],
    ) -> ThresholdRecommendationResult:
        """按本地确定性公式计算阈值，保证固定页面输入下的建议值稳定。

        创建日期：2026-05-07
        author: sunshengxian
        """

        payload = self._threshold_recommendation_context(context) or {}
        direction = str(payload.get("direction") or "HA").upper()
        if direction not in {"AH", "HA"}:
            direction = "HA"
        direction_label = "A/H" if direction == "AH" else "H/A"
        current = self._decimal_or_none(payload.get("metric_premium_pct"))
        median = self._decimal_or_none(payload.get("premium_median_60"))
        p80 = self._decimal_or_none(payload.get("premium_p80_60"))
        percentile = self._decimal_or_none(payload.get("premium_percentile_60"))
        if current is not None and median is not None and p80 is not None:
            base = median + Decimal("0.65") * (p80 - median)
            if percentile is not None and percentile > Decimal("80"):
                threshold = max(base, current)
                reason_code = "current_above_p80"
                note = "当前分位高于 80%，取基础锚点与当前溢价的较高值作为确认触发线"
            else:
                threshold = base
                reason_code = "base_formula"
                note = (
                    "60 日分位齐全，取 median + 0.65 * (p80 - median) "
                    "作为靠近 80% 分位但不追高的锚点"
                )
        elif current is not None and median is not None:
            threshold = median + Decimal("0.5") * abs(current - median)
            reason_code = "median_current_only"
            note = "缺少 80% 分位时，取 median + 0.5 * abs(current - median) 作为折中锚点"
        elif current is not None:
            buffer_pct = self._threshold_missing_history_buffer(payload)
            threshold = current + buffer_pct
            reason_code = "missing_history"
            note = (
                f"历史分位缺失，按当前溢价加 "
                f"{self._format_threshold_number(buffer_pct)} 个百分点缓冲"
            )
        else:
            threshold = Decimal("0")
            reason_code = "missing_current"
            note = "当前溢价缺失，先给 0% 观察阈值并要求补齐页面行情后复核"
        return ThresholdRecommendationResult(
            threshold_pct=threshold.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            direction=direction,
            direction_label=direction_label,
            reason_code=reason_code,
            formula_note=note,
        )

    def _threshold_missing_history_buffer(self, payload: dict[str, Any]) -> Decimal:
        """根据通道和当前值给历史缺失场景设置保守缓冲，避免阈值贴得过近。

        创建日期：2026-05-07
        author: sunshengxian
        """

        current = self._decimal_or_none(payload.get("metric_premium_pct")) or Decimal("0")
        channels = str(payload.get("connect_channels") or "").strip()
        buffer_pct = Decimal("3")
        if abs(current) >= Decimal("30"):
            buffer_pct = Decimal("5")
        elif not channels:
            buffer_pct = Decimal("4")
        if current < 0:
            return -buffer_pct
        return buffer_pct

    def _decimal_or_none(self, value: Any) -> Decimal | None:
        """把前端字符串或数字安全转为 Decimal，无法解析时视作缺失字段。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    def _format_threshold_number(self, value: Decimal) -> str:
        """格式化百分比数值，保留两位精度但去掉无意义尾零。

        创建日期：2026-05-07
        author: sunshengxian
        """

        quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return format(quantized.normalize(), "f")

    def _generate_sql(
        self,
        question: str,
        context: dict[str, Any],
        model: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> str:
        prompt = self._sql_prompt(question, context)
        content = self._chat_completion(
            prompt,
            system_prompt=SQL_SYSTEM_PROMPT,
            model=model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="generate_sql",
                user_id=user_id,
                session_id=session_id,
                conversation_title=self._metric_conversation_title(question_id),
                user_name=self._metric_user_name(question_id),
            ),
        )
        payload = self._extract_json(content)
        sql = payload.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("LLM 未返回 SQL")
        return sql

    def _generate_answer(
        self,
        question: str,
        sql: str,
        rows: list[dict[str, Any]],
        context: dict[str, Any],
        model: str,
    ) -> str:
        answer = self._chat_completion(
            self._answer_prompt(question, rows, context),
            system_prompt=INVESTMENT_ADVISOR_SYSTEM_PROMPT,
            model=model,
        )
        return self._strip_forbidden_preamble(answer)

    def _answer_prompt(
        self,
        question: str,
        rows: list[dict[str, Any]],
        context: dict[str, Any],
        route: QuestionRoute | None = None,
        market_data_context: dict[str, Any] | None = None,
    ) -> str:
        history = self._conversation_history(context)
        filters = {
            key: value
            for key, value in context.items()
            if (
                key != "conversation_history"
                and not key.startswith("_metric_")
                and value not in (None, "", [])
            )
        }
        payload = {
            "user_question": question,
            "conversation_history": history[-8:],
            "filters": filters,
            "market_observations": rows[:ANSWER_MARKET_ROW_LIMIT],
            "supplemental_market_observations": self._supporting_data(question, context),
            "market_data_context": market_data_context,
            "answer_mode": (route.answer_mode if route else "open_research"),
            "answer_style_policy": self._answer_style_policy(route, market_data_context),
            "material_source_policy": (
                "本轮回答只使用会话历史、页面上下文、结构化市场观察和按需补数上下文；"
                "项目不再自动注入额外静态材料，不能声称引用了历史研报或未提供的内部资料。"
            ),
            "external_material_boundary": (
                "最终回答只能描述当前分析材料覆盖了什么、缺少什么；"
                "不得向用户暴露内部数据接口、积分、权限、数据库、补数策略或系统处理细节。"
                "公告原文、公司回复、补充披露等若未在材料中出现，只能表述为当前材料未覆盖，"
                "需要后续以公司正式披露校验。"
            ),
            "financial_context_contract": (
                "若 market_data_context.context.financial_periods 存在，"
                "最多包含最近 24 期财务摘要；"
                "回答必须先概括完整覆盖期趋势，再点评最近两年，不得只读取前几行；"
                "若存在 3 期及以上财务摘要，第二个二级标题必须先输出关键财务趋势表，"
                "A 股和港股都要优先选取收入、归母或净利润、扣非或利润质量指标、"
                "经营现金流、ROE、负债率或估值等可用列，缺失列可省略但不得省略表格。"
            ),
        }
        answer_mode = route.answer_mode if route else "open_research"
        stock_report_instruction = self._stock_report_instruction(
            question,
            market_data_context,
            answer_mode=answer_mode,
        )
        return (
            "请根据以下分析材料生成给用户的最终投资研究回答。"
            "材料中的结构化字段和参考内容只供你内部分析，最终回答不得提及材料格式、"
            "底层系统、SQL、JSON、数据库、视图名、文件来源、内部接口、积分或权限。"
            "若有 market_data_context，请优先使用其中的补数上下文作为主证据，"
            "market_observations 只作为补充校验；如果 market_observations 大量为空，"
            "不得据此判断没有财务数据。"
            "若没有精确数值，可基于会话历史、页面上下文和你的金融知识输出框架性分析，"
            "但不要编造具体行情数字，也不要声称引用了历史研报或未提供的内部资料。"
            "不要过度自我设限；在证据足够时可以给出清晰的看多/中性/谨慎判断、"
            "配置优先级、仓位思路和触发条件。"
            "数据包名称只用于你理解证据覆盖范围，不要按数据包名称机械分段；"
            "请围绕用户真正的问题自主组织回答。"
            f"{stock_report_instruction}"
            "首段或第一块必须先给结论，使用 3-5 条短项目符号，不要一开始堆表格；"
            "每条结论控制在 1-2 个短句，最多加粗一个引导词，禁止整条加粗或把多项指标堆成一行。"
            "完整个股分析报告若市场数据上下文中存在 3 期及以上财务摘要，"
            "第二块必须先给关键财务趋势表；"
            "其他开放问题可按需要使用表格，并确保表格前后空行、表头、分隔行和列数完全合法。"
            "不要输出模板化免责句或泛泛风险警告。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _answer_style_policy(
        self,
        route: QuestionRoute | None,
        market_data_context: dict[str, Any] | None,
    ) -> str:
        """按路由结构化模式提示模型选择回答结构，避免再靠文本关键词判断。

        创建日期：2026-05-09
        author: sunshengxian
        """

        answer_mode = route.answer_mode if route else "open_research"
        if answer_mode in {"stock_research", "full_report"}:
            return (
                "这是单只公司投资分析或深度报告场景，应输出充分的个股研究结构：核心结论、"
                "关键财务趋势表、基本面质量、估值与价格、分红/治理/资金流、"
                "配置建议、反证条件和跟踪项。"
            )
        return (
            "这是开放投研问答或局部分析场景，不要机械套完整个股报告模板；"
            "请围绕用户问题自主安排 2-5 个小节，先给直接结论，再用可用数据和金融逻辑解释。"
            "如果材料只覆盖部分维度，就说明当前材料覆盖和缺口，不要暴露内部处理逻辑。"
        )

    def _ensure_market_data_context(
        self,
        question: str,
        context: dict[str, Any],
        route: QuestionRoute,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> dict[str, Any] | None:
        """在回答前按需补足股票研究数据，单轮最多覆盖 5 只 A 股。

        创建日期：2026-05-07
        author: sunshengxian
        """

        try:
            result = MarketDataOrchestrator(self.db).ensure_for_question(
                question,
                context,
                route.data_demands,
                question_id=question_id,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception:
            logger.error("LLM 按需市场数据上下文准备失败，降级为已有数据回答", exc_info=True)
            return {"status": "FAILED", "reason": "按需市场数据上下文准备失败"}
        if result.status == "SKIPPED" and not result.context:
            return None
        return {
            "status": result.status,
            "cache_hit": result.cache_hit,
            "fetched_rows": result.fetched_rows,
            "packages": result.packages,
            "stock": result.stock,
            "context": result.context,
            "reason": result.reason,
            "stocks": result.stocks,
            "data_boundary": (
                f"本轮最多围绕 {MAX_MARKET_DATA_STOCKS} 只股票准备有限区间分析材料；"
                "最终回答只说明材料已覆盖和未覆盖的事实维度。"
                "若公告原文、公司回复或补充披露未出现在材料中，只说当前材料未覆盖，"
                "不要说明内部接口、积分、权限或补数来源。"
            ),
        }

    def _stock_report_instruction(
        self,
        question: str,
        market_data_context: dict[str, Any] | None,
        answer_mode: str = "stock_research",
    ) -> str:
        """为个股投资报告追加方法论提示，不限制模型的推理组织方式。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if answer_mode not in {"stock_research", "full_report"}:
            return ""
        return (
            "如果这是个股投资分析报告，请按研究员口径先做数据核验再做判断："
            "第一，先给出评级倾向和一句话结论，但必须说明结论依赖哪些事实；"
            "第二，把归母净利润、扣非净利润、投资收益、公允价值变动、资产减值和信用减值分开看，"
            "不要把非经常性或投资收益驱动的利润增长直接等同于主业改善；"
            "第三，现金流必须和利润对照，重点检查经营现金流覆盖、投资现金流、筹资现金流、"
            "购建固定资产支出、偿债和分红付息压力；"
            "第四，资产负债表要看货币资金、交易性金融资产、长期股权投资、商誉、有息负债、"
            "流动/非流动负债和权益变化，判断利润与资产质量是否匹配；"
            "第五，估值不能只看 PE/PB，要说明利润口径是否可靠，"
            "必要时分别用归母、扣非、现金流和股息口径交叉验证；"
            "第六，主营业务构成要看收入和利润是否过度依赖单一产品、地区或非主营来源，"
            "审计意见、审计机构和业绩快报可作为财报可靠性与最新经营变化的校验材料；"
            "第七，股东治理要检查前十大股东、流通股东、股东户数和质押比例，"
            "区分长期战略持有、筹码分散和高质押流动性压力；"
            "第八，资金流只用于解释短期交易情绪和验证价格异动，不要用大单或特大单净流入替代基本面结论；"
            "第九，根据公司类型调整重点，银行看息差、资产质量和拨备，支付/金融科技看交易规模、费率、"
            "支付业务收入、科技服务收入和合规成本，制造业看毛利率、存货、应收和资本开支；"
            "第十，事实、推断和假设要分清楚，材料没有覆盖的指标要直接列为数据缺口，"
            "并给出后续最该跟踪的 3 到 6 个指标以及推翻当前判断的反证条件；"
            "第十一，如果 market_data_context 提供了最近 24 期或多年财务数据，"
            "必须先横向检查完整覆盖期的收入、利润、ROE、现金流、负债和分红趋势，"
            "再单独点评最近两年变化；不要只因为最新两年数据最靠前就忽略更早报告期。"
            "不要机械套模板，也不要因为表面估值低就自动给乐观结论。"
        )

    def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        result = self.db.execute(text(sql))
        return [dict(row._mapping) for row in result.fetchall()]

    def _general_answer_prompt(self, question: str, context: dict[str, Any]) -> str:
        """构造通用问答提示，避免把翻译和知识问答误塞进投研约束。

        创建日期：2026-05-07
        author: sunshengxian
        """

        payload = {
            "user_question": question,
            "conversation_history": self._conversation_history(context)[-8:],
        }
        return (
            "请直接回答用户问题。若用户要求翻译、改写或解释，请按用户要求输出；"
            "不要主动转换成投资分析，也不要输出本项目内部处理过程。\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

    def _is_general_direct_question(self, question: str, route: QuestionRoute) -> bool:
        """判断是否为无需本地数据和投研知识约束的通用问答。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if not route.is_answerable or route.should_query_data:
            return False
        if route.data_demands:
            return False
        normalized = question.lower().replace(" ", "")
        if any(keyword in normalized for keyword in INVESTMENT_KEYWORDS):
            return False
        return (
            any(keyword in normalized for keyword in GENERAL_QUESTION_KEYWORDS)
            or not self._should_query_data(question, {})
        )

    def _is_data_only_question(self, question: str) -> bool:
        """识别用户只要数据的场景，避免最终回答阶段强行输出投资判断。

        创建日期：2026-05-07
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "")
        has_data_only = any(keyword in normalized for keyword in DATA_ONLY_KEYWORDS)
        has_analysis = any(keyword in normalized for keyword in DATA_ANALYSIS_KEYWORDS)
        # “给我近三年招商银行财报数据”这类表达没有显式写“只要数据”，但业务意图仍是先查数。
        has_data_request = any(keyword in normalized for keyword in DATA_ONLY_REQUEST_KEYWORDS)
        has_data_subject = any(keyword in normalized for keyword in DATA_ONLY_SUBJECT_KEYWORDS)
        return (has_data_only or (has_data_request and has_data_subject)) and not has_analysis

    def _data_only_answer(
        self,
        question: str,
        rows: list[dict[str, Any]],
        market_data_context: dict[str, Any] | None,
    ) -> str:
        """把问数结果直接格式化为 Markdown 数据表，并提示可继续获取的数据类型。

        创建日期：2026-05-07
        author: sunshengxian
        """

        context_rows = self._rows_from_market_data_context(market_data_context, question)
        normalized_rows = (
            context_rows
            if context_rows and self._prefer_context_rows_for_data_question(question)
            else rows[:20]
        ) or context_rows
        lines = ["## 数据结果", ""]
        display_limit = 24 if self._prefer_context_rows_for_data_question(question) else 20
        if normalized_rows:
            lines.append(self._markdown_table(normalized_rows[:display_limit]))
            lines.append("")
            if len(normalized_rows) > display_limit:
                lines.append(
                    f"已先展示前 {display_limit} 行，本次共命中 {len(normalized_rows)} 行。"
                )
                lines.append("")
        else:
            lines.append("当前没有查到可展示的数据。")
            lines.append("")
        lines.append(
            "还可以继续返回：行情估值、财务摘要、现金流、利润质量、分红/业绩预告、"
            "主营业务构成、A/H 溢价和自选股阈值数据。需要分析时直接告诉我。"
        )
        return "\n".join(lines)

    def _rows_from_market_data_context(
        self,
        market_data_context: dict[str, Any] | None,
        question: str = "",
    ) -> list[dict[str, Any]]:
        """从按需补数上下文提取最适合问数展示的摘要行。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if not market_data_context:
            return []
        context_payload = market_data_context.get("context")
        if not isinstance(context_payload, dict):
            return []
        extracted: list[dict[str, Any]] = []
        items = context_payload.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_context = item.get("context")
                if isinstance(item_context, dict):
                    extracted.extend(self._preferred_context_rows(item_context, question))
            return extracted
        return self._preferred_context_rows(context_payload, question)

    def _prefer_context_rows_for_data_question(self, question: str) -> bool:
        """判断问数回答是否优先展示 Tushare 按需补数上下文。

        创建日期：2026-05-07
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "")
        data_context_keywords = (
            "财报",
            "财务",
            "利润表",
            "资产负债表",
            "现金流量表",
            "估值",
            "行情",
            "分红",
        )
        return any(keyword in normalized for keyword in data_context_keywords)

    def _preferred_context_rows(
        self,
        context_payload: dict[str, Any],
        question: str = "",
    ) -> list[dict[str, Any]]:
        """按财务、估值、最新摘要的优先级选择问数展示行。

        创建日期：2026-05-07
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "")
        preferred_keys = (
            ("valuation_trend", "latest", "financial_periods")
            if any(
                keyword in normalized
                for keyword in ("估值", "行情", "股价", "收盘", "pe", "pb")
            )
            else ("financial_periods", "valuation_trend", "latest")
        )
        for key in preferred_keys:
            rows = context_payload.get(key)
            if isinstance(rows, list) and rows:
                return [row for row in rows if isinstance(row, dict)]
        return []

    def _markdown_table(self, rows: list[dict[str, Any]]) -> str:
        """把结构化数据转为紧凑 Markdown 表，防止问数场景再调用分析模型。

        创建日期：2026-05-07
        author: sunshengxian
        """

        columns = self._table_columns(rows)
        header_labels = [DATA_FIELD_LABELS.get(column, column) for column in columns]
        header = "| " + " | ".join(header_labels) + " |"
        separator = "| " + " | ".join("---" for _column in columns) + " |"
        body = [
            "| "
            + " | ".join(self._format_table_cell(row.get(column)) for column in columns)
            + " |"
            for row in rows
        ]
        return "\n".join([header, separator, *body])

    def _table_columns(self, rows: list[dict[str, Any]]) -> list[str]:
        """保留常用字段顺序，并限制列数避免聊天窗口过宽。

        创建日期：2026-05-07
        author: sunshengxian
        """

        preferred = (
            "ts_code",
            "name",
            "trade_date",
            "end_date",
            "ann_date",
            "report_type",
            "currency",
            "close",
            "pct_chg",
            "pe_ttm",
            "pb_ttm",
            "pb",
            "dividend_yield_ttm",
            "dividend_rate",
            "dps_hkd",
            "eps",
            "basic_eps",
            "roe",
            "roe_waa",
            "roe_avg",
            "total_revenue",
            "revenue",
            "operate_income",
            "operate_income_yoy",
            "n_income_attr_p",
            "holder_profit",
            "holder_profit_yoy",
            "profit_dedt",
            "invest_income",
            "fv_value_chg_gain",
            "n_cashflow_act",
            "netcash_operate",
            "netcash_invest",
            "netcash_finance",
            "total_assets",
            "total_liab",
            "total_liabilities",
            "debt_asset_ratio",
            "statement_type",
            "ind_name",
            "ind_value",
        )
        available = {key for row in rows for key, value in row.items() if value is not None}
        columns = [column for column in preferred if column in available]
        for row in rows:
            for key, value in row.items():
                if value is not None and key not in columns:
                    columns.append(key)
                if len(columns) >= 80:
                    return columns[:80]
        return columns[:80] or list(rows[0].keys())[:32]

    def _format_table_cell(self, value: Any) -> str:
        """格式化 Markdown 单元格，处理 None、换行和竖线转义。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if value is None:
            return ""
        text_value = str(value).replace("\n", " ").replace("|", "\\|")
        return text_value[:160]

    def _chat_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        trace: LlmCallTrace | None = None,
    ) -> str:
        endpoint = self._model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        try:
            return self._chat_completion_with_endpoint(
                endpoint,
                prompt,
                system_prompt,
                temperature,
                trace,
            )
        except httpx.HTTPError as exc:
            fallback_endpoint = self._fallback_endpoint(endpoint, exc)
            if fallback_endpoint is None:
                raise
            logger.error(
                "%s API 临时不可用，自动切换到 %s question_id=%s phase=%s",
                endpoint.provider,
                fallback_endpoint.provider,
                self._trace_values(trace)[0],
                self._trace_values(trace)[1],
                exc_info=True,
            )
            return self._chat_completion_with_endpoint(
                fallback_endpoint,
                prompt,
                system_prompt,
                temperature,
                trace,
            )

    def _chat_completion_with_endpoint(
        self,
        endpoint: LlmEndpoint,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        trace: LlmCallTrace | None,
    ) -> str:
        """按指定端点发起非流式调用，供主模型与备用模型复用。

        创建日期：2026-05-08
        author: sunshengxian
        """

        self._enforce_daily_llm_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": temperature,
        }
        request_payload_json = self._metric_request_payload_json(payload)
        started_at = perf_counter()
        with httpx.Client(timeout=LLM_CHAT_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
        self._raise_for_status(response, endpoint.provider)
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        self._log_llm_completion(endpoint, trace, started_at, content, request_payload_json)
        return content

    def _chat_completion_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        trace: LlmCallTrace | None = None,
        total_started_at: float | None = None,
        row_count: int = 0,
        total_phase: str = "stream_done",
    ) -> Iterator[str]:
        endpoint = self._model_endpoint(model)
        if not endpoint.api_key:
            raise ValueError(f"{endpoint.provider} LLM 未配置 API Key")
        return self._chat_completion_stream_with_fallback(
            endpoint,
            prompt,
            system_prompt,
            trace,
            total_started_at,
            row_count,
            total_phase,
        )

    def _chat_completion_stream_with_fallback(
        self,
        endpoint: LlmEndpoint,
        prompt: str,
        system_prompt: str | None,
        trace: LlmCallTrace | None,
        total_started_at: float | None,
        row_count: int,
        total_phase: str,
    ) -> Iterator[str]:
        """执行流式调用，并在主模型繁忙时切换到备用 Qwen。

        创建日期：2026-05-08
        author: sunshengxian
        """

        try:
            yield from self._chat_completion_stream_once(
                endpoint,
                prompt,
                system_prompt,
                trace,
                total_started_at,
                row_count,
                total_phase,
            )
        except httpx.HTTPError as exc:
            fallback_endpoint = self._fallback_endpoint(endpoint, exc)
            if fallback_endpoint is None:
                raise
            logger.error(
                "%s 流式 API 临时不可用，自动切换到 %s question_id=%s phase=%s",
                endpoint.provider,
                fallback_endpoint.provider,
                self._trace_values(trace)[0],
                self._trace_values(trace)[1],
                exc_info=True,
            )
            yield from self._chat_completion_stream_once(
                fallback_endpoint,
                prompt,
                system_prompt,
                trace,
                total_started_at,
                row_count,
                total_phase,
            )

    def _chat_completion_stream_once(
        self,
        endpoint: LlmEndpoint,
        prompt: str,
        system_prompt: str | None,
        trace: LlmCallTrace | None,
        total_started_at: float | None,
        row_count: int,
        total_phase: str,
    ) -> Iterator[str]:
        """按指定端点发起一次流式调用，不在本层重试。

        创建日期：2026-05-08
        author: sunshengxian
        """

        self._enforce_daily_llm_call_limit(endpoint, trace)
        url = f"{endpoint.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}"}
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": endpoint.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        request_payload_json = self._metric_request_payload_json(payload)
        started_at = perf_counter()
        first_chunk_at: float | None = None
        chunk_count = 0
        char_count = 0
        response_parts: list[str] = []
        with httpx.Client(timeout=LLM_STREAM_TIMEOUT_SECONDS) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                self._raise_for_status(response, endpoint.provider)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        now = perf_counter()
                        if first_chunk_at is None:
                            first_chunk_at = now
                            self._log_llm_first_chunk(
                                endpoint,
                                trace,
                                started_at,
                                request_payload_json,
                            )
                        chunk_count += 1
                        char_count += len(content)
                        response_parts.append(content)
                        yield content
        self._log_llm_stream_done(
            endpoint,
            trace,
            started_at,
            first_chunk_at,
            chunk_count,
            char_count,
            request_payload_json,
            "".join(response_parts),
        )
        if total_started_at is not None and trace is not None:
            self._log_total_elapsed(
                total_phase,
                trace.question_id,
                endpoint.model,
                total_started_at,
                row_count,
                user_id=trace.user_id,
                session_id=trace.session_id,
            )

    def _normalize_chat_model(self, model: str | None) -> str:
        """转换为 OpenAI-compatible API 支持的模型名。

        创建日期：2026-05-04
        author: sunshengxian
        """

        if not model:
            return DEFAULT_CHAT_MODEL
        normalized = model.strip()
        if normalized.startswith("deepseek-v4-pro"):
            return "deepseek-v4-pro"
        if normalized.startswith("deepseek-v4-flash"):
            return "deepseek-v4-flash"
        return normalized

    def _model_endpoint(self, model: str | None = None) -> LlmEndpoint:
        """根据模型名选择 DeepSeek 或 Qwen 调用端点。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = self._normalize_chat_model(model or self.settings.llm_model)
        if normalized.startswith("qwen"):
            return LlmEndpoint(
                provider="Qwen",
                base_url=self.settings.qwen_base_url,
                api_key=self.settings.resolve_qwen_api_key(),
                model=normalized,
            )
        return LlmEndpoint(
            provider="DeepSeek",
            base_url=self.settings.llm_base_url,
            api_key=self.settings.resolve_llm_api_key(),
            model=normalized,
        )

    def _fallback_endpoint(
        self,
        endpoint: LlmEndpoint,
        exc: httpx.HTTPError,
    ) -> LlmEndpoint | None:
        """在主模型临时不可用时选择备用端点。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if endpoint.provider != "DeepSeek":
            return None
        if not self._is_retryable_llm_error(exc):
            return None
        fallback = self._model_endpoint(QWEN_CHAT_MODEL)
        if not fallback.api_key:
            return None
        return fallback

    def _is_retryable_llm_error(self, exc: httpx.HTTPError) -> bool:
        """判断外部模型错误是否适合透明切到备用模型。

        创建日期：2026-05-08
        author: sunshengxian
        """

        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in LLM_FALLBACK_HTTP_STATUS_CODES
        return False

    def _raise_for_status(self, response: httpx.Response, provider: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            try:
                body = response.text
            except httpx.ResponseNotRead:
                body = response.read().decode("utf-8", errors="replace")
            logger.error(
                "%s API 请求失败 status=%s body=%s",
                provider,
                response.status_code,
                body[:2000],
            )
            raise

    def _enforce_daily_llm_call_limit(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
    ) -> None:
        """检查项目级 LLM 日调用限额。

        创建日期：2026-05-05
        author: sunshengxian
        """

        limit = self.settings.llm_daily_call_limit
        if limit <= 0:
            return
        used_count = self._today_external_llm_call_count()
        if used_count < limit:
            return
        question_id, phase = self._trace_values(trace)
        logger.error(
            "LLM 日调用限额已用尽 question_id=%s phase=%s provider=%s model=%s used=%s limit=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            used_count,
            limit,
        )
        raise LlmDailyLimitExceeded(self._daily_limit_message(limit))

    def _today_external_llm_call_count(self) -> int:
        """统计当天已发生的外部 LLM 主调用次数。

        创建日期：2026-05-05
        author: sunshengxian
        """

        now = datetime.now(LLM_LIMIT_TIMEZONE).replace(tzinfo=None)
        today_start = datetime.combine(now.date(), time.min)
        tomorrow_start = today_start + timedelta(days=1)
        statement = select(func.count(LlmCallMetric.id)).where(
            LlmCallMetric.phase.in_(LLM_EXTERNAL_CALL_PHASES),
            LlmCallMetric.created_at >= today_start,
            LlmCallMetric.created_at < tomorrow_start,
        )
        try:
            raw_count = self.db.scalar(statement)
        except Exception:
            self.db.rollback()
            logger.error("LLM 日调用次数统计失败，临时放行本次模型调用", exc_info=True)
            return 0
        if isinstance(raw_count, int):
            return raw_count
        if isinstance(raw_count, float):
            return int(raw_count)
        return 0

    def _daily_limit_message(self, limit: int) -> str:
        """生成可展示的 LLM 日限流提示。

        创建日期：2026-05-05
        author: sunshengxian
        """

        if limit == 100:
            return LLM_LIMIT_EXCEEDED_MESSAGE
        return (
            f"今日智能问答模型调用次数已达到项目日限额 {limit} 次，"
            "请明天再试或联系管理员调整配置。"
        )

    def _new_trace_id(self) -> str:
        """生成单轮问答唯一追踪 ID，不暴露问题原文。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return uuid4().hex

    def _trace_values(
        self,
        trace: LlmCallTrace | None,
    ) -> tuple[str, str]:
        if trace is None:
            return "-", "-"
        return trace.question_id, trace.phase

    def _trace_scope(self, context: dict[str, Any]) -> tuple[int | None, int | None]:
        """从问答上下文读取用户和会话范围。

        创建日期：2026-05-05
        author: sunshengxian
        """

        user_id = self._optional_int(context.get("user_id"))
        session_id = self._optional_int(context.get("session_id"))
        return user_id, session_id

    def _register_metric_context(
        self,
        question_id: str,
        question: str,
        context: dict[str, Any],
        user_id: int | None,
    ) -> None:
        """缓存本轮指标展示上下文。

        创建日期：2026-05-06
        author: sunshengxian
        """

        display_question = str(context.get("_metric_question") or question)
        conversation_title = self._metric_title_from_question(display_question)
        user_name = self._metric_user_name_from_context(context, user_id)
        self._metric_context_by_question_id[question_id] = (conversation_title, user_name)

    def _metric_title_from_question(self, question: str) -> str:
        normalized = " ".join(question.strip().split())
        return (normalized[:LLM_METRIC_TITLE_MAX_CHARS] or "新的投资问答")

    def _metric_user_name_from_context(
        self,
        context: dict[str, Any],
        user_id: int | None,
    ) -> str | None:
        context_user_name = str(context.get("_metric_user_name") or "").strip()
        if context_user_name:
            return context_user_name[:LLM_METRIC_USER_NAME_MAX_CHARS]
        if user_id is None:
            return None
        try:
            user = self.db.get(AppUser, user_id)
        except Exception:
            self.db.rollback()
            logger.error("LLM 指标用户名称读取失败 user_id=%s", user_id, exc_info=True)
            return None
        if user is None:
            return None
        user_name = (user.display_name or user.username or "").strip()
        return user_name[:LLM_METRIC_USER_NAME_MAX_CHARS] or None

    def _metric_conversation_title(self, question_id: str | None) -> str | None:
        if question_id is None:
            return None
        return self._metric_context_by_question_id.get(question_id, (None, None))[0]

    def _metric_user_name(self, question_id: str | None) -> str | None:
        if question_id is None:
            return None
        return self._metric_context_by_question_id.get(question_id, (None, None))[1]

    def _public_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """移除只用于指标落库的内部上下文字段。

        创建日期：2026-05-06
        author: sunshengxian
        """

        return {key: value for key, value in context.items() if not key.startswith("_metric_")}

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _metric_request_payload_json(self, payload: dict[str, Any]) -> str:
        """序列化实际发送给 LLM 的请求参数，不包含鉴权头和 API Key。

        创建日期：2026-05-05
        author: sunshengxian
        """

        return json.dumps(payload, ensure_ascii=False, default=str)

    def _record_llm_metric(
        self,
        *,
        phase: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
        conversation_title: str | None = None,
        user_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        elapsed_ms: float | None = None,
        first_chunk_ms: float | None = None,
        output_chars: int = 0,
        chunk_count: int = 0,
        row_count: int = 0,
        success: bool = True,
        error_message: str | None = None,
        request_payload_json: str | None = None,
        response_content: str | None = None,
    ) -> None:
        """记录 LLM 调用耗时指标，失败不影响问答主流程。

        创建日期：2026-05-05
        author: sunshengxian
        """

        metric = LlmCallMetric(
            question_id=question_id,
            conversation_title=conversation_title,
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            phase=phase,
            phase_label=phase_label(phase),
            phase_description=phase_description(phase),
            provider=provider,
            model=model,
            success=1 if success else 0,
            elapsed_ms=elapsed_ms,
            first_chunk_ms=first_chunk_ms,
            output_chars=output_chars,
            chunk_count=chunk_count,
            row_count=row_count,
            request_payload_json=request_payload_json,
            response_content=response_content,
            error_message=error_message[:512] if error_message else None,
        )
        try:
            self.db.add(metric)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.error("LLM 调用耗时指标落库失败", exc_info=True)

    def _log_llm_completion(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        content: str,
        request_payload_json: str,
    ) -> None:
        question_id, phase = self._trace_values(trace)
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 调用完成 question_id=%s phase=%s provider=%s model=%s elapsed_ms=%.1f "
            "output_chars=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            elapsed_ms,
            len(content),
        )
        if trace is not None:
            self._record_llm_metric(
                phase=trace.phase,
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                conversation_title=trace.conversation_title,
                user_name=trace.user_name,
                provider=endpoint.provider,
                model=endpoint.model,
                elapsed_ms=elapsed_ms,
                output_chars=len(content),
                request_payload_json=request_payload_json,
                response_content=content,
                success=True,
            )

    def _log_llm_first_chunk(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        request_payload_json: str,
    ) -> None:
        question_id, phase = self._trace_values(trace)
        first_chunk_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 流式首包 question_id=%s phase=%s provider=%s model=%s first_chunk_ms=%.1f",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            first_chunk_ms,
        )
        if trace is not None:
            self._record_llm_metric(
                phase=f"{trace.phase}_first_chunk",
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                conversation_title=trace.conversation_title,
                user_name=trace.user_name,
                provider=endpoint.provider,
                model=endpoint.model,
                first_chunk_ms=first_chunk_ms,
                request_payload_json=request_payload_json,
                success=True,
            )

    def _log_llm_stream_done(
        self,
        endpoint: LlmEndpoint,
        trace: LlmCallTrace | None,
        started_at: float,
        first_chunk_at: float | None,
        chunk_count: int,
        char_count: int,
        request_payload_json: str,
        response_content: str,
    ) -> None:
        question_id, phase = self._trace_values(trace)
        elapsed_ms = (perf_counter() - started_at) * 1000
        first_chunk_ms = (first_chunk_at - started_at) * 1000 if first_chunk_at else None
        logger.info(
            "LLM 流式完成 question_id=%s phase=%s provider=%s model=%s elapsed_ms=%.1f "
            "first_chunk_ms=%s chunks=%s output_chars=%s",
            question_id,
            phase,
            endpoint.provider,
            endpoint.model,
            elapsed_ms,
            f"{first_chunk_ms:.1f}" if first_chunk_ms is not None else "-",
            chunk_count,
            char_count,
        )
        if trace is not None:
            self._record_llm_metric(
                phase=trace.phase,
                question_id=trace.question_id,
                user_id=trace.user_id,
                session_id=trace.session_id,
                conversation_title=trace.conversation_title,
                user_name=trace.user_name,
                provider=endpoint.provider,
                model=endpoint.model,
                elapsed_ms=elapsed_ms,
                first_chunk_ms=first_chunk_ms,
                output_chars=char_count,
                chunk_count=chunk_count,
                request_payload_json=request_payload_json,
                response_content=response_content,
                success=True,
            )

    def _log_total_elapsed(
        self,
        phase: str,
        question_id: str,
        model: str,
        started_at: float,
        row_count: int = 0,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "LLM 问答完成 question_id=%s phase=%s model=%s rows=%s total_elapsed_ms=%.1f",
            question_id,
            phase,
            model,
            row_count,
            elapsed_ms,
        )
        self._record_llm_metric(
            phase=phase,
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
            conversation_title=self._metric_conversation_title(question_id),
            user_name=self._metric_user_name(question_id),
            provider="Internal",
            model=model,
            elapsed_ms=elapsed_ms,
            row_count=row_count,
            success=True,
        )

    def _sql_prompt(self, question: str, context: dict[str, Any]) -> str:
        context_json = json.dumps(
            {
                "question": question,
                "context": self._public_context(context),
                "conversation_history": self._conversation_history(context)[-6:],
            },
            ensure_ascii=False,
            default=str,
        )
        return (
            '你只负责生成只读 MySQL SELECT SQL，必须返回 JSON：{"sql":"..."}。'
            "只能查询这些视图："
            f"{json.dumps(self._schema(), ensure_ascii=False)}。"
            "默认使用官方 AH 比价口径；H/A 字段由官方 A/H 反推；"
            "涉及可操作性时优先查询含 hk_connect 或 watchlist 的视图。"
            "涉及自选、关注、阈值、机会状态或 v_watchlist_opportunity 时，"
            "必须使用 context.user_id 过滤 user_id，禁止查询其他用户自选数据。"
            "涉及 A 股个股财报、估值、红利、ROE、PE、PB、股息率时，"
            "只能使用 v_stock_research_context_latest、v_stock_quote_valuation_trend、"
            "v_stock_financial_period_summary、v_stock_business_profile_summary、"
            "v_stock_shareholder_governance_summary、v_stock_moneyflow_recent "
            "等按需 Tushare 数据视图；"
            "不要查询旧选股宽表或候选因子宽表。"
            "字段名必须完全来自字段清单；不要使用 stock_name、ha_premium、ah_premium 等不存在字段，"
            "应使用 display_name/a_name/hk_name/name、ha_premium_pct、ah_premium_pct。"
            "不要使用写入、DDL、多语句。问题与上下文如下："
            f"{context_json}"
        )

    def _repair_sql(
        self,
        question: str,
        context: dict[str, Any],
        sql: str,
        error: str,
        model: str,
        question_id: str,
        user_id: int | None,
        session_id: int | None,
    ) -> str:
        payload = {
            "question": question,
            "context": self._public_context(context),
            "failed_sql": sql,
            "error": error[:1200],
            "schema": self._schema(),
        }
        prompt = (
            '请修复这个 MySQL SELECT SQL，并只返回 JSON：{"sql":"..."}。'
            "只能使用 schema 中列出的视图和字段名；不要使用写入、DDL、多语句。"
            "常见修正：stock_name 改为 display_name/a_name/hk_name/name；"
            "ha_premium 改为 ha_premium_pct；ah_premium 改为 ah_premium_pct。"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        content = self._chat_completion(
            prompt,
            system_prompt=SQL_SYSTEM_PROMPT,
            model=model,
            trace=LlmCallTrace(
                question_id=question_id,
                phase="repair_sql",
                user_id=user_id,
                session_id=session_id,
                conversation_title=self._metric_conversation_title(question_id),
                user_name=self._metric_user_name(question_id),
            ),
        )
        payload = self._extract_json(content)
        repaired_sql = payload.get("sql")
        if not isinstance(repaired_sql, str) or not repaired_sql.strip():
            raise ValueError("LLM 未返回修复后的 SQL")
        return repaired_sql

    def _supporting_data(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, list[dict[str, Any]]] | None:
        if not self._is_ah_arbitrage_question(question) or not self._should_query_supporting_data(
            question
        ):
            return None
        user_id = int((context or {}).get("user_id") or 0)
        user_filter = f"WHERE user_id = {user_id} " if user_id else ""
        queries = {
            "a_discount_h_premium_candidates": (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ha_premium_pct DESC LIMIT 20"
            ),
            "h_discount_a_premium_candidates": (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ah_premium_pct DESC LIMIT 20"
            ),
            "watchlist_opportunities": (
                "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,opportunity_status "
                "FROM v_watchlist_opportunity "
                f"{user_filter}"
                "ORDER BY ABS(distance_to_target_pct) ASC LIMIT 30"
            ),
            "market_distribution": (
                "SELECT COUNT(*) AS total_count,"
                "SUM(ah_premium_pct < 0) AS a_discount_count,"
                "SUM(ha_premium_pct > 0) AS h_premium_count,"
                "MIN(ah_premium_pct) AS min_ah_premium_pct,"
                "MAX(ah_premium_pct) AS max_ah_premium_pct,"
                "MIN(ha_premium_pct) AS min_ha_premium_pct,"
                "MAX(ha_premium_pct) AS max_ha_premium_pct "
                "FROM v_latest_hk_connect_official_ah_premium"
            ),
        }
        supporting_data: dict[str, list[dict[str, Any]]] = {}
        for key, sql in queries.items():
            try:
                supporting_data[key] = self._execute_sql(sql)
            except SQLAlchemyError:
                logger.error("LLM 补充数据查询失败 key=%s", key, exc_info=True)
                supporting_data[key] = []
        return supporting_data

    def _is_ah_arbitrage_question(self, question: str) -> bool:
        keywords = ("ah", "a/h", "h/a", "溢价", "折价", "套利", "价差", "港股通", "a股", "h股")
        normalized = question.lower()
        return any(keyword in normalized for keyword in keywords)

    def _default_sql_for_question(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        normalized = question.lower().replace(" ", "").replace("／", "/")
        user_id = int((context or {}).get("user_id") or 0)
        user_filter = f"WHERE user_id = {user_id} " if user_id else ""
        if any(keyword in normalized for keyword in ("自选", "关注", "阈值", "机会状态")):
            if any(keyword in normalized for keyword in ("h/a折价", "h股折价", "h股便宜")):
                return (
                    "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                    "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                    "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                    "opportunity_status "
                    "FROM v_watchlist_opportunity "
                    f"{user_filter}"
                    "ORDER BY ha_premium_pct ASC LIMIT 30"
                )
            if any(keyword in normalized for keyword in ("h/a溢价", "h股溢价", "a股折价")):
                return (
                    "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                    "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                    "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                    "opportunity_status "
                    "FROM v_watchlist_opportunity "
                    f"{user_filter}"
                    "ORDER BY ha_premium_pct DESC LIMIT 30"
                )
            return (
                "SELECT display_name,a_ts_code,hk_ts_code,trade_date,preferred_direction,"
                "target_premium_pct,ah_premium_pct,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                "opportunity_status "
                "FROM v_watchlist_opportunity "
                f"{user_filter}"
                "ORDER BY ABS(distance_to_target_pct) ASC LIMIT 30"
            )
        if not self._is_ah_arbitrage_question(question):
            return None
        if any(keyword in normalized for keyword in ("哪些", "适合", "候选", "推荐", "筛选")):
            if any(
                keyword in normalized
                for keyword in (
                    "a/h溢价",
                    "ah溢价",
                    "a股溢价",
                    "h/a折价",
                    "h股便宜",
                    "h股折价",
                )
            ):
                return (
                    "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                    "ha_premium_pct,is_hk_connect,connect_channels "
                    "FROM v_latest_hk_connect_official_ah_premium "
                    "ORDER BY ah_premium_pct DESC LIMIT 20"
                )
            return (
                "SELECT trade_date,a_ts_code,hk_ts_code,a_name,hk_name,ah_premium_pct,"
                "ha_premium_pct,is_hk_connect,connect_channels "
                "FROM v_latest_hk_connect_official_ah_premium "
                "ORDER BY ha_premium_pct DESC LIMIT 20"
            )
        return None

    def _route_question(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        question_id: str | None = None,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> QuestionRoute:
        if not question.strip():
            return QuestionRoute(
                is_answerable=False,
                should_query_data=False,
                reason="空问题",
            )
        context = context or {}
        payload = {
            "question": question.strip()[:1200],
            "conversation_history": self._conversation_history(context)[-4:],
            "frontend_context": {
                key: value
                for key, value in context.items()
                if (
                    key != "conversation_history"
                    and not key.startswith("_metric_")
                    and value not in (None, "", [])
                )
            },
            "stock_candidates": self._route_stock_candidates(question, context),
        }
        try:
            content = self._chat_completion(
                json.dumps(payload, ensure_ascii=False, default=str),
                system_prompt=QUESTION_ROUTER_SYSTEM_PROMPT,
                model=self.settings.resolve_question_router_model(),
                temperature=0,
                trace=LlmCallTrace(
                    question_id=question_id or self._new_trace_id(),
                    phase="question_router",
                    user_id=user_id,
                    session_id=session_id,
                    conversation_title=self._metric_conversation_title(question_id),
                    user_name=self._metric_user_name(question_id),
                ),
            )
            payload = self._extract_json(content)
            route = self._route_from_payload(payload)
            return self._route_with_semantic_stocks(
                question,
                context,
                route,
                question_id,
                user_id,
                session_id,
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            logger.error("问答前置路由模型失败，降级使用本地兜底规则", exc_info=True)
            return self._local_question_route(question, context)

    def _route_with_semantic_stocks(
        self,
        question: str,
        context: dict[str, Any],
        route: QuestionRoute,
        question_id: str | None,
        user_id: int | None,
        session_id: int | None,
    ) -> QuestionRoute:
        """在路由之后补充本地股票候选语义消歧结果。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if not route.is_answerable:
            return route
        if route.data_demands:
            return route
        selected_ts_codes = self._semantic_stock_ts_codes(
            question,
            context,
            trace=LlmCallTrace(
                question_id=question_id or self._new_trace_id(),
                phase="stock_disambiguation",
                user_id=user_id,
                session_id=session_id,
                conversation_title=self._metric_conversation_title(question_id),
                user_name=self._metric_user_name(question_id),
            ),
            fallback_to_unique=False,
        )
        if not selected_ts_codes:
            return route
        demands = tuple(
            MarketDataDemand(
                ts_code=ts_code,
                packages=self._packages_for_semantic_stock(question),
                market="HK" if ts_code.endswith(".HK") else "A",
                intent="stock_research",
            )
            for ts_code in selected_ts_codes[:MAX_MARKET_DATA_STOCKS]
        )
        return QuestionRoute(
            is_answerable=route.is_answerable,
            should_query_data=route.should_query_data,
            data_demands=demands,
            reason=route.reason,
            answer_mode=route.answer_mode,
        )

    def _route_stock_candidates(
        self,
        question: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """给前置路由提供本地股票候选，让模型在受控候选内主动提出数据包需求。

        创建日期：2026-05-09
        author: sunshengxian
        """

        try:
            candidates = StockIdentityResolver(self.db).resolve_candidates(
                question,
                context,
                limit=max(MAX_MARKET_DATA_STOCKS * 3, 12),
            )
        except Exception:
            # 候选只是路由辅助信息；数据库替身或基础表异常时，仍允许路由模型按问题语义返回。
            logger.error("前置路由股票候选召回失败，继续使用无候选路由", exc_info=True)
            return []
        return [
            {
                "ts_code": candidate.ts_code,
                "name": candidate.name,
                "market": "HK" if candidate.ts_code.endswith(".HK") else "A",
                "industry": candidate.industry,
                "area": candidate.area,
            }
            for candidate in candidates
        ]

    def _route_from_payload(self, payload: dict[str, Any]) -> QuestionRoute:
        """把前置路由 JSON 转换为内部结构。

        创建日期：2026-05-05
        author: sunshengxian
        """

        demands = self._data_demands_from_payload(payload.get("data_demands"))
        answer_mode = self._answer_mode_from_payload(payload)
        return QuestionRoute(
            is_answerable=payload.get("is_answerable") is True,
            should_query_data=payload.get("needs_sql") is True,
            data_demands=demands,
            reason=str(payload.get("reason") or ""),
            answer_mode=answer_mode,
        )

    def _answer_mode_from_payload(
        self,
        payload: dict[str, Any],
    ) -> str:
        """解析路由模型输出的回答模式，要求前置路由显式给出结构化结论。

        创建日期：2026-05-09
        author: sunshengxian
        """

        allowed_modes = {"stock_research", "full_report", "open_research", "data_only", "general"}
        raw_mode = str(payload.get("answer_mode") or "").strip().lower()
        if raw_mode in allowed_modes:
            return raw_mode
        raise ValueError("前置路由未返回有效 answer_mode")

    def _data_demands_from_payload(self, raw_demands: Any) -> tuple[MarketDataDemand, ...]:
        """解析前置路由提出的数据包需求，并过滤掉非白名单内容。

        创建日期：2026-05-07
        author: sunshengxian
        """

        if not isinstance(raw_demands, list):
            return ()
        demands: list[MarketDataDemand] = []
        allowed_packages = {
            "quote_valuation",
            "financial_statement",
            "business_profile",
            "dividend_forecast",
            "shareholder_governance",
            "capital_flow_light",
        }
        seen_ts_codes: set[str] = set()
        for item in raw_demands[:MAX_MARKET_DATA_STOCKS]:
            if not isinstance(item, dict):
                continue
            ts_code = str(item.get("ts_code") or "").upper()
            market = str(item.get("market") or ("HK" if ts_code.endswith(".HK") else "A")).upper()
            if market == "HK":
                if not re.fullmatch(r"\d{5}\.HK", ts_code):
                    continue
            elif not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", ts_code):
                continue
            if ts_code in seen_ts_codes:
                continue
            seen_ts_codes.add(ts_code)
            packages = item.get("packages")
            if not isinstance(packages, list):
                packages = []
            filtered_packages = tuple(
                package
                for package in packages
                if isinstance(package, str) and package in allowed_packages
            )
            if market == "HK":
                # 港股自动补数现阶段只开放已接入的财务包，
                # 路由器即便只返回行情或资金流等未接入包，也统一降级为财务包，
                # 避免后续默认补成 A 股估值包并造成审计口径混乱。
                filtered_packages = ("financial_statement",)
            demands.append(
                MarketDataDemand(
                    ts_code=ts_code,
                    packages=filtered_packages or ("quote_valuation",),
                    market=market,
                    intent=str(item.get("intent") or "stock_research"),
                )
            )
        return tuple(demands)

    def _semantic_stock_ts_codes(
        self,
        question: str,
        context: dict[str, Any],
        trace: LlmCallTrace | None,
        fallback_to_unique: bool,
    ) -> tuple[str, ...]:
        """从本地股票候选中让 LLM 按用户语义筛选具体股票。

        创建日期：2026-05-07
        author: sunshengxian
        """

        resolver = StockIdentityResolver(self.db)
        try:
            candidates = resolver.resolve_candidates(
                question,
                context,
                limit=max(MAX_MARKET_DATA_STOCKS * 3, 12),
            )
        except Exception:
            # 股票消歧是补充能力，数据库替身、只读视图异常或本地表不可用时不能影响主问答路由。
            logger.error("本地股票候选召回失败，跳过股票语义消歧", exc_info=True)
            return ()
        if not candidates:
            return ()
        if fallback_to_unique and len(candidates) == 1:
            return (candidates[0].ts_code,)
        try:
            selected = self._disambiguate_stock_candidates(question, context, candidates, trace)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            logger.error("股票语义消歧失败，降级为不自动补数", exc_info=True)
            return ()
        valid_codes = {candidate.ts_code for candidate in candidates}
        return tuple(
            ts_code
            for ts_code in selected.selected_ts_codes
            if ts_code in valid_codes
        )[:MAX_MARKET_DATA_STOCKS]

    def _disambiguate_stock_candidates(
        self,
        question: str,
        context: dict[str, Any],
        candidates: tuple[StockIdentity, ...],
        trace: LlmCallTrace | None,
    ) -> StockDisambiguationResult:
        """调用轻量路由模型，在本地候选内完成股票名称歧义消解。

        创建日期：2026-05-07
        author: sunshengxian
        """

        payload = {
            "question": question.strip()[:1200],
            "frontend_context": {
                key: value
                for key, value in context.items()
                if key != "conversation_history"
                and not key.startswith("_metric_")
                and value not in (None, "", [])
            },
            "max_selected": MAX_MARKET_DATA_STOCKS,
            "candidates": [
                {
                    "ts_code": candidate.ts_code,
                    "symbol": candidate.symbol,
                    "name": candidate.name,
                    "industry": candidate.industry,
                    "area": candidate.area,
                    "market": candidate.market,
                }
                for candidate in candidates
            ],
        }
        system_prompt = (
            "你是股票名称语义消歧器，只能从候选列表中选择 A 股或港股 ts_code。"
            f"如果用户在比较多只股票，最多选择 {MAX_MARKET_DATA_STOCKS} 只；"
            "如果问题语义不足以判断具体股票，返回空数组。"
            "不要输出候选之外的代码，不要解释过程，只返回 JSON："
            '{"selected_ts_codes":["600036.SH","02380.HK"],"confidence":0.0到1.0,"reason":"一句话"}'
        )
        content = self._chat_completion(
            json.dumps(payload, ensure_ascii=False, default=str),
            system_prompt=system_prompt,
            model=self.settings.resolve_question_router_model(),
            temperature=0,
            trace=trace,
        )
        parsed = self._extract_json(content)
        raw_codes = parsed.get("selected_ts_codes")
        if not isinstance(raw_codes, list):
            raw_codes = []
        selected_codes = tuple(
            str(code).upper()
            for code in raw_codes
            if isinstance(code, str)
            and re.fullmatch(r"\d{6}\.(SH|SZ|BJ)|\d{5}\.HK", code.upper())
        )
        raw_confidence = parsed.get("confidence")
        confidence = raw_confidence if isinstance(raw_confidence, (int, float)) else 0.0
        return StockDisambiguationResult(
            selected_ts_codes=selected_codes[:MAX_MARKET_DATA_STOCKS],
            reason=str(parsed.get("reason") or ""),
            confidence=float(confidence),
        )

    def _packages_for_semantic_stock(self, question: str) -> tuple[str, ...]:
        """按用户问题的研究深度为语义识别出的股票生成数据包。

        创建日期：2026-05-07
        author: sunshengxian
        """

        normalized = question.lower()
        if re.search(r"\d{5}\.hk", normalized):
            return ("financial_statement",)
        if self._needs_full_a_stock_research_packages(normalized):
            return (
                "quote_valuation",
                "financial_statement",
                "business_profile",
                "dividend_forecast",
                "shareholder_governance",
            )
        packages = ["quote_valuation"]
        if any(
            keyword in normalized
            for keyword in (
                "分析报告",
                "投资报告",
                "深度报告",
                "财报",
                "估值",
                "roe",
                "对比",
                "比较",
            )
        ):
            packages.append("financial_statement")
        if any(
            keyword in normalized
            for keyword in (
                "分析报告",
                "投资报告",
                "分红",
                "股息",
                "预告",
                "对比",
                "比较",
            )
        ):
            packages.append("dividend_forecast")
        if any(
            keyword in normalized
            for keyword in (
                "分析报告",
                "投资报告",
                "深度报告",
                "主营",
                "业务构成",
                "收入结构",
                "审计",
                "业绩快报",
            )
        ):
            packages.append("business_profile")
        if any(
            keyword in normalized
            for keyword in (
                "分析报告",
                "投资报告",
                "深度报告",
                "股东",
                "质押",
                "股东户数",
                "持股",
                "治理",
            )
        ):
            packages.append("shareholder_governance")
        if any(
            keyword in normalized
            for keyword in ("资金流", "资金流向", "大单", "特大单", "净流入")
        ):
            packages.append("capital_flow_light")
        return tuple(dict.fromkeys(packages))

    def _needs_full_a_stock_research_packages(self, normalized_question: str) -> bool:
        """识别需要多维证据链的开放 A 股个股研究问题。

        创建日期：2026-05-09
        author: sunshengxian
        """

        full_research_signals = (
            "分析报告",
            "投资报告",
            "深度报告",
            "个股分析",
            "怎么看",
            "投资价值",
            "长期投资",
            "配置建议",
            "能买吗",
            "能不能买",
            "值得买吗",
            "持有吗",
            "买入",
            "卖出",
            "建仓",
            "减仓",
            "风险收益",
        )
        return any(keyword in normalized_question for keyword in full_research_signals)

    def _local_question_route(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> QuestionRoute:
        """前置路由不可用时的保守兜底。

        创建日期：2026-05-05
        author: sunshengxian
        """

        local_scope = self._local_question_scope(question)
        if local_scope is False:
            return QuestionRoute(False, False, reason="本地规则判定为非投资问题")
        if local_scope is True:
            local_demands = self._local_data_demands(question, context or {})
            return QuestionRoute(
                is_answerable=True,
                should_query_data=self._should_query_data(question, context or {}),
                data_demands=local_demands,
                reason="前置路由不可用，本地规则放行",
                answer_mode="stock_research" if local_demands else "open_research",
            )
        return QuestionRoute(False, False, reason="前置路由不可用且本地规则不确定")

    def _local_data_demands(
        self,
        question: str,
        context: dict[str, Any],
    ) -> tuple[MarketDataDemand, ...]:
        """路由模型不可用时按本地规则生成最多 5 只股票的数据包需求。

        创建日期：2026-05-07
        author: sunshengxian
        """

        normalized = question.lower()
        ts_codes = self._local_ts_codes(question, context)
        if not ts_codes:
            ts_codes = self._semantic_stock_ts_codes(
                question,
                context,
                trace=None,
                fallback_to_unique=True,
            )
        if not ts_codes:
            return ()
        is_hk_request = any(code.endswith(".HK") for code in ts_codes)
        if is_hk_request:
            packages = ["financial_statement"]
        else:
            packages = list(self._packages_for_semantic_stock(question))
        financial_keywords = ("分析报告", "投资报告", "深度报告", "财报", "估值", "roe")
        dividend_keywords = ("分析报告", "投资报告", "分红", "股息", "预告")
        business_keywords = (
            "分析报告",
            "投资报告",
            "深度报告",
            "主营",
            "业务构成",
            "收入结构",
            "审计",
            "业绩快报",
        )
        governance_keywords = (
            "分析报告",
            "投资报告",
            "深度报告",
            "股东",
            "质押",
            "股东户数",
            "持股",
            "治理",
        )
        capital_flow_keywords = ("资金流", "资金流向", "大单", "特大单", "净流入")
        if not is_hk_request and any(keyword in normalized for keyword in financial_keywords):
            packages.append("financial_statement")
        if not is_hk_request and any(keyword in normalized for keyword in dividend_keywords):
            packages.append("dividend_forecast")
        if not is_hk_request and any(keyword in normalized for keyword in business_keywords):
            packages.append("business_profile")
        if not is_hk_request and any(keyword in normalized for keyword in governance_keywords):
            packages.append("shareholder_governance")
        if not is_hk_request and any(keyword in normalized for keyword in capital_flow_keywords):
            packages.append("capital_flow_light")
        return tuple(
            MarketDataDemand(
                ts_code=ts_code,
                packages=tuple(dict.fromkeys(packages)),
                market="HK" if ts_code.endswith(".HK") else "A",
            )
            for ts_code in ts_codes[:MAX_MARKET_DATA_STOCKS]
        )

    def _local_ts_code(self, question: str, context: dict[str, Any]) -> str | None:
        # 这里只做格式抽取，最终是否允许补数仍由 StockIdentityResolver 回查本地基础表确认。
        ts_codes = self._local_ts_codes(question, context)
        return ts_codes[0] if ts_codes else None

    def _local_ts_codes(self, question: str, context: dict[str, Any]) -> tuple[str, ...]:
        """从上下文和问题文本抽取最多 5 个本地格式股票代码。

        创建日期：2026-05-07
        author: sunshengxian
        """

        codes: list[str] = []
        for key in ("ts_code", "a_ts_code", "hk_ts_code", "stock_code"):
            value = context.get(key)
            if isinstance(value, str) and re.fullmatch(
                r"\d{6}\.(SH|SZ|BJ)|\d{5}\.HK",
                value.upper(),
            ):
                codes.append(value.upper())
        for match in re.finditer(r"\b(\d{6})\.(SH|SZ|BJ)\b", question, re.IGNORECASE):
            codes.append(f"{match.group(1)}.{match.group(2).upper()}")
        for match in re.finditer(r"\b(\d{5})\.HK\b", question, re.IGNORECASE):
            codes.append(f"{match.group(1)}.HK")
        for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)", question):
            symbol = match.group(1)
            suffix = "SH" if symbol.startswith(("6", "9")) else "SZ"
            codes.append(f"{symbol}.{suffix}")
        return tuple(dict.fromkeys(codes))[:MAX_MARKET_DATA_STOCKS]

    def _is_investment_related_question(
        self,
        question: str,
        question_id: str | None = None,
        user_id: int | None = None,
        session_id: int | None = None,
    ) -> bool:
        return self._route_question(
            question,
            {},
            question_id=question_id,
            user_id=user_id,
            session_id=session_id,
        ).is_answerable

    def _local_question_scope(self, question: str) -> bool | None:
        """先用本地规则判断明显问题，减少问答前置 LLM 调用。

        创建日期：2026-05-05
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "").replace("／", "/")
        if self._is_service_intro_question(question):
            return True
        if any(keyword in normalized for keyword in INVESTMENT_KEYWORDS):
            return True
        if any(keyword in normalized for keyword in NON_INVESTMENT_KEYWORDS):
            return False
        return None

    def _is_service_intro_question(self, question: str) -> bool:
        """识别问候、角色身份和能力介绍类问题。

        创建日期：2026-05-04
        author: sunshengxian
        """

        normalized = question.lower().replace(" ", "")
        intro_keywords = (
            "你好",
            "您好",
            "你是谁",
            "你是啥",
            "你是什么",
            "你可以干嘛",
            "你能干嘛",
            "你会干嘛",
            "你可以做什么",
            "你能做什么",
            "你有什么用",
            "介绍一下你",
            "介绍你自己",
            "你的角色",
            "你的身份",
            "help",
            "whoareyou",
            "whatcanyoudo",
        )
        return any(keyword in normalized for keyword in intro_keywords)

    def _should_query_data(self, question: str, context: dict[str, Any]) -> bool:
        if any(context.get(key) for key in ("start_date", "end_date", "ts_code", "only_watchlist")):
            return True
        normalized = question.lower().replace(" ", "")
        # 中文问题里股票代码常和公司名、描述词直接相邻，不能依赖 Unicode \b 边界，
        # 否则“寒武纪688256怎么看”会被误判为纯报告问题而跳过结构化补数。
        if re.search(
            r"(?<![A-Za-z0-9])\d{6}\.(sh|sz|bj)(?![A-Za-z0-9])"
            r"|(?<!\d)\d{6}(?!\d)"
            r"|(?<![A-Za-z0-9])\d{5}\.hk(?![A-Za-z0-9])",
            normalized,
        ):
            return True
        if self._is_report_analysis_question(normalized):
            return False
        return any(keyword in normalized for keyword in DATA_INTENT_KEYWORDS)

    def _is_report_analysis_question(self, normalized_question: str) -> bool:
        """识别偏报告/框架的问题，避免无意义 SQL 生成。

        创建日期：2026-05-05
        author: sunshengxian
        """

        has_report_signal = any(
            keyword in normalized_question for keyword in REPORT_ANALYSIS_KEYWORDS
        )
        has_realtime_signal = any(
            keyword in normalized_question for keyword in REALTIME_DATA_KEYWORDS
        )
        return has_report_signal and not has_realtime_signal

    def _should_query_supporting_data(self, question: str) -> bool:
        normalized = question.lower()
        keywords = ("哪些", "候选", "推荐", "筛选", "机会", "价差", "最新", "自选")
        return any(keyword in normalized for keyword in keywords)

    def _conversation_history(self, context: dict[str, Any]) -> list[dict[str, str]]:
        raw_history = context.get("conversation_history") or []
        history: list[dict[str, str]] = []
        if not isinstance(raw_history, list):
            return history
        for item in raw_history[-10:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if (
                role not in {"user", "assistant"}
                or not isinstance(content, str)
                or not content.strip()
            ):
                continue
            history.append({"role": role, "content": content.strip()[:1200]})
        return history

    def _strip_forbidden_preamble(self, answer: str) -> str:
        cleaned = answer.strip()
        preamble_patterns = (
            r"^(好的|收到|当然|可以)[，,。！!\s]*",
            r"^收到.{0,30}(请求|问题)[。.\s]*",
            r"^您的(请求|问题)[。.\s]*",
            r"^我将基于.{0,40}(JSON|SQL|数据|资料|查询结果).{0,80}[。.\n]",
            r"^基于.{0,40}(JSON|SQL|查询结果|提供的数据).{0,80}[。.\n]",
            r"^以下是基于.{0,40}(JSON|SQL|查询结果|提供的数据).{0,80}[。.\n]",
        )
        changed = True
        while changed:
            changed = False
            for pattern in preamble_patterns:
                next_answer = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE).strip()
                if next_answer != cleaned:
                    cleaned = next_answer
                    changed = True
        return cleaned

    def _normalize_threshold_recommendation_markdown(self, answer: str) -> str:
        """整理阈值推荐 Markdown 标题，避免模型把小节标题粘到上一句后面。

        创建日期：2026-05-08
        author: sunshengxian
        """

        cleaned = self._strip_forbidden_preamble(answer)
        for heading in THRESHOLD_RECOMMENDATION_REQUIRED_HEADINGS:
            # 阈值推荐展示依赖二级标题分段；这里只处理固定标题，避免影响普通回答里的 Markdown。
            cleaned = re.sub(
                rf"\s*##\s*{re.escape(heading)}\s*",
                f"\n\n## {heading}\n\n",
                cleaned,
            )
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _normalize_threshold_recommendation_stream(self, chunks: Iterator[str]) -> Iterator[str]:
        """流式阈值推荐收束后统一格式化，确保落库和最终 done 事件 Markdown 合法。

        创建日期：2026-05-08
        author: sunshengxian
        """

        buffer = "".join(chunks)
        cleaned = self._normalize_threshold_recommendation_markdown(buffer)
        if cleaned:
            yield cleaned

    def _clean_answer_stream(self, chunks: Iterator[str]) -> Iterator[str]:
        buffer = ""
        emitted = False
        for chunk in chunks:
            if emitted:
                yield chunk
                continue
            buffer += chunk
            if len(buffer) < 240 and "\n\n" not in buffer:
                continue
            cleaned = self._strip_forbidden_preamble(buffer)
            if cleaned:
                yield cleaned
            emitted = True
        if not emitted:
            cleaned = self._strip_forbidden_preamble(buffer)
            if cleaned:
                yield cleaned

    def _schema(self) -> dict[str, str]:
        return {
            "v_latest_official_ah_premium": (
                "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
                "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
                "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
            ),
            "v_official_ah_premium_trend": (
                "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
                "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
                "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
            ),
            "v_latest_hk_connect_official_ah_premium": (
                "columns: trade_date,a_ts_code,hk_ts_code,a_name,hk_name,a_close,a_pct_chg,"
                "hk_close,hk_pct_chg,ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,"
                "is_hk_connect,connect_channels,is_realtime,data_source,source_updated_at,updated_at"
            ),
            "v_watchlist_opportunity": (
                "columns: watchlist_id,user_id,a_ts_code,hk_ts_code,display_name,"
                "preferred_direction,"
                "target_premium_pct,holding_market,sort_order,note,trade_date,a_name,hk_name,"
                "ah_ratio,ah_premium_pct,ha_ratio,ha_premium_pct,metric_premium_pct,"
                "distance_to_target_pct,premium_percentile_60,is_hk_connect,connect_channels,"
                "data_source,source_updated_at,opportunity_status,updated_at"
            ),
            "v_stock_quote_valuation_trend": (
                "columns: ts_code,name,industry,area,trade_date,close,pct_chg,turnover_rate,"
                "pe,pe_ttm,pb,ps_ttm,dividend_yield_ttm,total_mv,circ_mv"
            ),
            "v_stock_financial_period_summary": (
                "columns: ts_code,name,industry,end_date,ann_date,eps,roe,roe_waa,"
                "roe_dt,roa,grossprofit_margin,netprofit_margin,sales_gpr,profit_to_gr,"
                "debt_to_assets,assets_to_eqt,current_ratio,quick_ratio,revenue_yoy,"
                "q_sales_yoy,netprofit_yoy,q_netprofit_yoy,ocf_to_revenue,ocfps,bps,"
                "profit_dedt,total_revenue,revenue,total_cogs,oper_cost,biz_tax_surchg,"
                "sell_exp,admin_exp,fin_exp,rd_exp,assets_impair_loss,credit_impa_loss,"
                "oth_income,asset_disp_income,operate_profit,non_oper_income,non_oper_exp,"
                "total_profit,income_tax,n_income,n_income_attr_p,minority_gain,invest_income,"
                "fv_value_chg_gain,ebit,ebitda,cashflow_net_profit,cashflow_finan_exp,"
                "c_fr_sale_sg,c_paid_goods_s,c_paid_to_for_empl,c_paid_for_taxes,"
                "n_cashflow_act,c_recp_return_invest,n_recp_disp_fiolta,c_pay_acq_const_fiolta,"
                "n_cashflow_inv_act,c_recp_borrow,c_prepay_amt_borr,c_pay_dist_dpcp_int_exp,"
                "n_cash_flows_fnc_act,n_incr_cash_cash_equ,c_cash_equ_end_period,money_cap,"
                "trad_asset,lt_eqt_invest,invest_real_estate,notes_receiv,accounts_receiv,"
                "oth_receiv,inventories,fix_assets,cip,intan_assets,goodwill,total_cur_assets,"
                "total_nca,total_assets,st_borr,notes_payable,acct_payable,contract_liab,"
                "lt_borr,bond_payable,total_cur_liab,total_ncl,total_liab,"
                "total_hldr_eqy_inc_min_int,total_hldr_eqy_exc_min_int,cap_rese,surplus_rese,"
                "undistr_porfit,calculated_debt_to_assets"
            ),
            "v_stock_business_profile_summary": (
                "columns: ts_code,name,industry,end_date,business_type,bz_item,bz_sales,"
                "bz_profit,bz_cost,gross_margin,revenue_share_pct,curr_type,latest_audit_result,"
                "latest_audit_agency,latest_express_revenue,latest_express_n_income,"
                "latest_express_yoy_sales,latest_express_yoy_dedu_np,latest_express_summary"
            ),
            "v_stock_shareholder_governance_summary": (
                "columns: ts_code,name,section_type,sort_date,ranking,holder_scope,holder_name,"
                "hold_amount,hold_ratio,hold_float_ratio,hold_change,holder_type,holder_num,"
                "pledge_count,pledge_ratio,total_pledge"
            ),
            "v_stock_moneyflow_recent": (
                "columns: ts_code,name,trade_date,net_mf_amount,big_order_net_amount,"
                "extra_big_order_net_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,"
                "sell_elg_amount"
            ),
            "v_stock_research_context_latest": (
                "columns: ts_code,symbol,name,industry,area,market,latest_trade_date,close,"
                "pct_chg,pe_ttm,pb,ps_ttm,dividend_yield_ttm,total_mv,circ_mv,"
                "latest_report_period,roe,roe_waa,roe_dt,roa,grossprofit_margin,"
                "netprofit_margin,sales_gpr,profit_to_gr,debt_to_assets,assets_to_eqt,"
                "current_ratio,quick_ratio,revenue_yoy,q_sales_yoy,netprofit_yoy,"
                "q_netprofit_yoy,ocf_to_revenue,ocfps,bps,total_revenue,revenue,total_cogs,"
                "oper_cost,sell_exp,admin_exp,fin_exp,rd_exp,n_income_attr_p,profit_dedt,"
                "invest_income,fv_value_chg_gain,assets_impair_loss,credit_impa_loss,"
                "n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act,money_cap,trad_asset,"
                "lt_eqt_invest,total_assets,total_liab,total_hldr_eqy_exc_min_int,"
                "latest_main_business_item,latest_main_business_revenue_share_pct,"
                "latest_main_business_gross_margin,latest_audit_result,latest_audit_agency,"
                "latest_express_revenue,latest_express_n_income,latest_express_yoy_sales,"
                "latest_express_yoy_dedu_np,latest_dividend_period,latest_cash_div_tax,"
                "latest_dividend_proc,latest_forecast_ann_date,latest_forecast_type,"
                "latest_forecast_summary,latest_holder_num,latest_pledge_ratio,"
                "latest_net_mf_amount,latest_big_order_net_amount"
            ),
            "v_market_data_fetch_health": (
                "columns: id,question_id,intent,market_scope,symbols_json,data_packages_json,"
                "period_policy,status,cache_hit,row_count,error_message,started_at,finished_at,updated_at"
            ),
            "v_latest_ah_premium": "columns: same as v_latest_official_ah_premium",
            "v_ah_premium_trend": "columns: same as v_official_ah_premium_trend",
            "v_sync_health": (
                "columns: dataset,last_status,last_started_at,last_finished_at,last_message"
            ),
            "v_data_quality_issues": "columns: issue_type,issue_level,issue_message,related_key",
        }

    def _extract_json(self, content: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError("LLM 返回内容不是 JSON")
        return json.loads(match.group(0))
