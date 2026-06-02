import { Button, Checkbox, Drawer, Form, Input, Popconfirm, Segmented, Skeleton, Table, message } from 'antd';
import { Download, FileText, MessageCircleMore, Plus, Send, SendHorizontal, Trash2 } from 'lucide-react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEffect, useRef, useState } from 'react';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import LlmProgressNote from '../components/LlmProgressNote';
import {
  batchDeleteChatSessions,
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessageStream
} from '../api/chat';
import type {
  ChatMessageResponse,
  ChatModel,
  ChatSession,
  ChatStoredMessage,
  UserInfo
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';
import { exportChatAnswersToWord } from '../utils/chatWordExport';
import { CHAT_PROGRESS_STEPS } from '../constants/llmProgress';
import { publishXueqiuChatAnswer } from '../api/xueqiuPublish';

interface ChatFormValues {
  question: string;
}

interface ChatTurn {
  id: string;
  messageId?: number | null;
  question: string;
  response?: ChatMessageResponse;
  streaming?: boolean;
  progressText?: string;
}

interface ChatPageProps {
  currentUser: UserInfo;
}

const LAST_SESSION_KEY = 'stock-ah-premium-ai:last-chat-session';

const CHAT_TABLE_LABELS: Record<string, string> = {
  trade_date: '交易日',
  factor_date: '因子日',
  latest_trade_date: '最新交易日',
  end_date: '报告期',
  ann_date: '公告日',
  latest_report_period: '最新报告期',
  latest_dividend_period: '最新分红期',
  latest_cash_div_tax: '最新税前分红',
  latest_dividend_proc: '最新分红进度',
  latest_forecast_ann_date: '最新预告日',
  latest_forecast_type: '预告类型',
  latest_forecast_summary: '预告摘要',
  latest_net_mf_amount: '最新主力净流入',
  latest_big_order_net_amount: '最新大单净流入',
  a_ts_code: 'A 股代码',
  hk_ts_code: 'H 股代码',
  ts_code: '股票代码',
  symbol: '证券简称代码',
  a_name: 'A 股名称',
  hk_name: 'H 股名称',
  name: '名称',
  display_name: '标的',
  industry: '行业',
  area: '地区',
  market: '市场',
  user_id: '用户 ID',
  watchlist_id: '自选 ID',
  holding_market: '持有市场',
  sort_order: '排序',
  note: '备注',
  is_realtime: '实时数据',
  data_source: '数据来源',
  source_updated_at: '来源更新时间',
  updated_at: '更新时间',
  started_at: '开始时间',
  finished_at: '完成时间',
  status: '状态',
  cache_hit: '命中缓存',
  row_count: '行数',
  error_message: '错误信息',
  intent: '意图',
  market_scope: '市场范围',
  symbols_json: '股票列表',
  data_packages_json: '数据包',
  period_policy: '周期策略',
  business_type: '主营类型',
  bz_item: '主营项目',
  bz_sales: '主营收入',
  bz_profit: '主营利润',
  bz_cost: '主营成本',
  gross_margin: '主营毛利率',
  revenue_share_pct: '收入占比%',
  curr_type: '币种',
  latest_audit_result: '最新审计意见',
  latest_audit_agency: '最新审计机构',
  latest_express_revenue: '最新快报收入',
  latest_express_n_income: '最新快报净利润',
  latest_express_yoy_sales: '快报营收同比%',
  latest_express_yoy_dedu_np: '快报扣非同比%',
  latest_express_summary: '快报摘要',
  section_type: '股东分组',
  sort_date: '排序日期',
  ranking: '排名',
  holder_scope: '股东范围',
  holder_name: '股东名称',
  hold_amount: '持股数量',
  hold_ratio: '持股比例%',
  hold_float_ratio: '流通股占比%',
  hold_change: '持股变动',
  holder_type: '股东类型',
  holder_num: '股东户数',
  latest_holder_num: '最新股东户数',
  pledge_count: '质押笔数',
  pledge_ratio: '质押比例%',
  latest_pledge_ratio: '最新质押比例%',
  total_pledge: '质押总量',
  net_mf_amount: '主力净流入',
  big_order_net_amount: '大单净流入',
  extra_big_order_net_amount: '超大单净流入',
  buy_lg_amount: '大单买入额',
  sell_lg_amount: '大单卖出额',
  buy_elg_amount: '超大单买入额',
  sell_elg_amount: '超大单卖出额',
  ah_premium_pct: 'A/H 溢价%',
  ha_premium_pct: 'H/A 溢价%',
  ah_ratio: 'A/H 比价',
  ha_ratio: 'H/A 比价',
  metric_premium_pct: '观察溢价%',
  target_premium_pct: '目标阈值%',
  distance_to_target_pct: '距阈值%',
  premium_percentile_60: '60 日分位',
  is_hk_connect: '港股通',
  connect_channels: '通道',
  preferred_direction: '关注方向',
  opportunity_status: '状态',
  selection_tags: '标签',
  selection_score: '评分',
  selection_reason: '入选理由',
  a_close: 'A 股收盘价',
  hk_close: 'H 股收盘价',
  a_pct_chg: 'A 股涨跌幅%',
  hk_pct_chg: 'H 股涨跌幅%',
  close: '收盘价',
  pct_chg: '涨跌幅%',
  turnover_rate: '换手率%',
  pe: 'PE',
  pe_ttm: 'PE TTM',
  pb: 'PB',
  ps_ttm: 'PS TTM',
  dividend_yield_ttm: '股息率',
  total_mv: '总市值',
  circ_mv: '流通市值',
  eps: '每股收益',
  roe: 'ROE',
  roe_waa: '加权 ROE',
  roe_dt: '扣非 ROE',
  roa: 'ROA',
  grossprofit_margin: '毛利率',
  netprofit_margin: '净利率',
  sales_gpr: '销售毛利率',
  profit_to_gr: '利润/营收',
  debt_to_assets: '资产负债率',
  calculated_debt_to_assets: '计算资产负债率',
  assets_to_eqt: '权益乘数',
  current_ratio: '流动比率',
  quick_ratio: '速动比率',
  revenue_yoy: '营收同比%',
  q_sales_yoy: '单季营收同比%',
  netprofit_yoy: '净利同比%',
  q_netprofit_yoy: '单季净利同比%',
  ocf_to_revenue: '经营现金/营收',
  ocfps: '每股经营现金流',
  bps: '每股净资产',
  profit_dedt: '扣非净利润',
  total_revenue: '营业总收入',
  revenue: '营业收入',
  total_cogs: '营业总成本',
  oper_cost: '营业成本',
  biz_tax_surchg: '税金及附加',
  sell_exp: '销售费用',
  admin_exp: '管理费用',
  fin_exp: '财务费用',
  rd_exp: '研发费用',
  assets_impair_loss: '资产减值损失',
  credit_impa_loss: '信用减值损失',
  oth_income: '其他收益',
  asset_disp_income: '资产处置收益',
  operate_profit: '营业利润',
  non_oper_income: '营业外收入',
  non_oper_exp: '营业外支出',
  total_profit: '利润总额',
  income_tax: '所得税',
  n_income: '净利润',
  n_income_attr_p: '归母净利润',
  minority_gain: '少数股东损益',
  invest_income: '投资收益',
  fv_value_chg_gain: '公允价值变动收益',
  ebit: 'EBIT',
  ebitda: 'EBITDA',
  cashflow_net_profit: '现金流净利润',
  cashflow_finan_exp: '现金流财务费用',
  c_fr_sale_sg: '销售收现',
  c_paid_goods_s: '采购付现',
  c_paid_to_for_empl: '支付职工现金',
  c_paid_for_taxes: '支付税费',
  n_cashflow_act: '经营现金流净额',
  c_recp_return_invest: '收回投资现金',
  n_recp_disp_fiolta: '处置长期资产现金',
  c_pay_acq_const_fiolta: '购建长期资产现金',
  n_cashflow_inv_act: '投资现金流净额',
  c_recp_borrow: '取得借款现金',
  c_prepay_amt_borr: '偿还债务现金',
  c_pay_dist_dpcp_int_exp: '分红付息现金',
  n_cash_flows_fnc_act: '筹资现金流净额',
  n_incr_cash_cash_equ: '现金等价物增加额',
  c_cash_equ_end_period: '期末现金等价物',
  money_cap: '货币资金',
  trad_asset: '交易性金融资产',
  lt_eqt_invest: '长期股权投资',
  invest_real_estate: '投资性房地产',
  notes_receiv: '应收票据',
  accounts_receiv: '应收账款',
  oth_receiv: '其他应收款',
  inventories: '存货',
  fix_assets: '固定资产',
  cip: '在建工程',
  intan_assets: '无形资产',
  goodwill: '商誉',
  total_cur_assets: '流动资产合计',
  total_nca: '非流动资产合计',
  total_assets: '资产总计',
  st_borr: '短期借款',
  notes_payable: '应付票据',
  acct_payable: '应付账款',
  contract_liab: '合同负债',
  lt_borr: '长期借款',
  bond_payable: '应付债券',
  total_cur_liab: '流动负债合计',
  total_ncl: '非流动负债合计',
  total_liab: '负债合计',
  total_hldr_eqy_inc_min_int: '所有者权益合计',
  total_hldr_eqy_exc_min_int: '归母权益合计',
  cap_rese: '资本公积',
  surplus_rese: '盈余公积',
  undistr_porfit: '未分配利润',
  return_20d: '20 日涨跌幅',
  return_60d: '60 日涨跌幅',
  return_120d: '120 日涨跌幅'
};

const CHAT_SUMMARY_COLUMN_PRIORITY = [
  'display_name',
  'name',
  'a_name',
  'hk_name',
  'ts_code',
  'a_ts_code',
  'hk_ts_code',
  'trade_date',
  'factor_date',
  'latest_trade_date',
  'end_date',
  'ann_date',
  'latest_report_period',
  'industry',
  'a_close',
  'hk_close',
  'a_pct_chg',
  'hk_pct_chg',
  'business_type',
  'bz_item',
  'holder_name',
  'net_mf_amount',
  'big_order_net_amount',
  'latest_net_mf_amount',
  'selection_tags',
  'selection_score',
  'close',
  'pct_chg',
  'pe_ttm',
  'pb',
  'dividend_yield_ttm',
  'eps',
  'roe',
  'roe_waa',
  'total_revenue',
  'revenue',
  'n_income_attr_p',
  'profit_dedt',
  'n_cashflow_act',
  'return_60d',
  'ah_premium_pct',
  'ha_premium_pct',
  'metric_premium_pct',
  'distance_to_target_pct',
  'premium_percentile_60',
  'opportunity_status',
  'connect_channels',
  'selection_reason'
];

const CHAT_SUMMARY_COLUMN_WIDTHS: Record<string, number> = {
  display_name: 140,
  name: 120,
  a_name: 120,
  hk_name: 120,
  ts_code: 116,
  a_ts_code: 116,
  hk_ts_code: 116,
  trade_date: 112,
  factor_date: 112,
  latest_trade_date: 112,
  end_date: 112,
  ann_date: 112,
  latest_report_period: 112,
  industry: 116,
  a_close: 104,
  hk_close: 104,
  a_pct_chg: 104,
  hk_pct_chg: 104,
  business_type: 112,
  bz_item: 160,
  holder_name: 180,
  net_mf_amount: 120,
  big_order_net_amount: 120,
  latest_net_mf_amount: 132,
  selection_tags: 180,
  selection_score: 88,
  close: 92,
  pct_chg: 92,
  pe_ttm: 88,
  pb: 80,
  dividend_yield_ttm: 100,
  eps: 88,
  roe: 88,
  roe_waa: 96,
  total_revenue: 128,
  revenue: 128,
  n_income_attr_p: 128,
  profit_dedt: 128,
  n_cashflow_act: 132,
  return_60d: 104,
  ah_premium_pct: 104,
  ha_premium_pct: 104,
  metric_premium_pct: 104,
  distance_to_target_pct: 96,
  premium_percentile_60: 96,
  opportunity_status: 96,
  connect_channels: 120,
  data_source: 120,
  source_updated_at: 160,
  updated_at: 160,
  selection_reason: 260
};

const markdownComponents: Components = {
  table({ children }) {
    return (
      <div className="markdown-table-wrap">
        <table>{children}</table>
      </div>
    );
  }
};

const PRESET_QUESTION_COUNT = 4;
const CHAT_AUTO_SCROLL_THRESHOLD = 96;
const DEFAULT_CHAT_MODEL: ChatModel = 'deepseek-v4-flash';
const CHAT_MODEL_OPTIONS: { label: string; value: ChatModel }[] = [
  { label: 'DeepSeek Flash', value: 'deepseek-v4-flash' },
  { label: 'DeepSeek Pro', value: 'deepseek-v4-pro' },
  { label: 'Qwen 3.6 Flash', value: 'qwen3.6-flash' }
];

const STRUCTURED_ANALYSIS_PRESET_QUESTIONS = [
  '帮我分析一下招商银行，重点看估值、财务质量、分红和 A/H 价差',
  '帮我分析一下金螳螂，重点看主营业务、现金流和股东质押风险',
  '帮我分析一下中国神华，重点看红利稳定性、现金流和估值安全边际',
  '帮我分析一下格力电器，重点看主营结构、分红能力和长期竞争力',
  '帮我分析一下宁德时代，重点看增长质量、毛利率和资金流是否配合',
  '帮我分析一下比亚迪，重点看利润质量、竞争压力和估值反证条件',
  '帮我分析一下长江电力，重点看现金流、防御属性和分红可持续性',
  '帮我分析一下寒武纪，重点看收入兑现、股东结构和估值风险',
  '招商银行和平安银行谁的财务质量更稳？请给出关键指标和反证条件',
  '我关注的股票里，哪些 A/H 价差更像择边机会而不是套利机会？',
  '当前适合用高股息策略还是成长股策略？请结合估值和现金流给框架',
  '请找出一只股票做完整个股分析报告，覆盖财务、主营、股东和资金流',
  '近几年财务数据里，哪些指标最能说明一家公司的利润质量？',
  '如果一家公司短期资金流入但扣非和现金流不好，应该怎么判断？',
  '股东户数下降、质押比例上升同时出现时，对个股分析意味着什么？',
  '主营业务收入集中度过高时，估值应该打折还是看行业壁垒？',
  'A/H 溢价达到目标阈值后，执行换仓前最应该复核哪些条件？',
  '请给我一个保守型股票组合的筛选框架，重点控制回撤和现金流风险',
  '财报问数模式下，给我展示招商银行最近 24 期财务摘要数据',
  '帮我生成一份股票复盘清单，用于每周跟踪持仓的估值、资金流和反证条件'
];

function randomPresetQuestions(previous: string[] = []) {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const nextQuestions = [...STRUCTURED_ANALYSIS_PRESET_QUESTIONS]
      .sort(() => Math.random() - 0.5)
      .slice(0, PRESET_QUESTION_COUNT);
    if (nextQuestions.some((item, index) => item !== previous[index])) {
      return nextQuestions;
    }
  }
  return [...STRUCTURED_ANALYSIS_PRESET_QUESTIONS].slice(0, PRESET_QUESTION_COUNT);
}

/**
 * 智能问答页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function ChatPage({ currentUser }: ChatPageProps) {
  const [form] = Form.useForm<ChatFormValues>();
  const historyRef = useRef<HTMLElement | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const autoScrollFrameRef = useRef<number | null>(null);
  const isProgrammaticScrollRef = useRef(false);
  const lastTurnCountRef = useRef(0);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [presetQuestions, setPresetQuestions] = useState(randomPresetQuestions);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ChatModel>(DEFAULT_CHAT_MODEL);
  const [selectedSessionIds, setSelectedSessionIds] = useState<number[]>([]);
  const [publishingTurnId, setPublishingTurnId] = useState<string | null>(null);
  const [isMobileSessionOpen, setIsMobileSessionOpen] = useState(false);
  const canPublishChatAnswerToXueqiu = currentUser.permissions.includes('chat_xueqiu_publish');

  useEffect(() => {
    void loadInitialSessions();
  }, []);

  useEffect(() => {
    const history = historyRef.current;
    if (!history) {
      return;
    }
    const hasNewTurn = turns.length > lastTurnCountRef.current;
    lastTurnCountRef.current = turns.length;
    if (!hasNewTurn && !isLoadingHistory && !shouldAutoScrollRef.current) {
      return;
    }
    scheduleHistoryAutoScroll(history);
  }, [turns, isLoadingHistory]);

  useEffect(() => {
    return () => {
      if (autoScrollFrameRef.current !== null) {
        window.cancelAnimationFrame(autoScrollFrameRef.current);
      }
    };
  }, []);

  /**
   * 合并流式分片触发的滚动请求，避免程序滚动被 onScroll 误判为用户手动滚动。
   * 创建日期：2026-05-07
   * author: sunshengxian
   */
  const scheduleHistoryAutoScroll = (history: HTMLElement) => {
    if (autoScrollFrameRef.current !== null) {
      return;
    }
    autoScrollFrameRef.current = window.requestAnimationFrame(() => {
      autoScrollFrameRef.current = null;
      isProgrammaticScrollRef.current = true;
      history.scrollTop = history.scrollHeight;
      shouldAutoScrollRef.current = true;
      window.setTimeout(() => {
        isProgrammaticScrollRef.current = false;
      }, 80);
    });
  };

  const onHistoryScroll = () => {
    if (isProgrammaticScrollRef.current) {
      return;
    }
    const history = historyRef.current;
    if (!history) {
      return;
    }
    const distanceToBottom = history.scrollHeight - history.scrollTop - history.clientHeight;
    shouldAutoScrollRef.current = distanceToBottom <= CHAT_AUTO_SCROLL_THRESHOLD;
  };

  const loadInitialSessions = async () => {
    setIsLoadingSessions(true);
    try {
      const items = await listChatSessions();
      setSessions(items);
      // 进入问答页默认停留在新会话草稿，只加载历史列表，不自动恢复旧会话；
      // 用户主动点开历史会话时才读取消息，避免页面一进来就把上次问题接着聊。
      setSession(null);
      setTurns([]);
      setSelectedSessionIds([]);
      setPresetQuestions((questions) => randomPresetQuestions(questions));
      form.resetFields();
      window.localStorage.removeItem(LAST_SESSION_KEY);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '会话加载失败');
    } finally {
      setIsLoadingSessions(false);
    }
  };

  const refreshSessions = async (activeSessionId?: number) => {
    const items = await listChatSessions();
    setSessions(items);
    setSelectedSessionIds((ids) => ids.filter((id) => items.some((item) => item.id === id)));
    if (activeSessionId) {
      const activeSession = items.find((item) => item.id === activeSessionId);
      if (activeSession) {
        setSession(activeSession);
      }
    }
  };

  const openSession = async (sessionId: number, showLoading = true) => {
    if (isSending) {
      return;
    }
    if (showLoading) {
      setIsLoadingHistory(true);
    }
    try {
      const detail = await getChatSession(sessionId);
      shouldAutoScrollRef.current = true;
      setSession(detail);
      setTurns(buildTurns(detail.messages));
      window.localStorage.setItem(LAST_SESSION_KEY, String(detail.id));
      setIsMobileSessionOpen(false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '会话加载失败');
    } finally {
      if (showLoading) {
        setIsLoadingHistory(false);
      }
    }
  };

  const handleNewSession = async () => {
    if (isSending) {
      return;
    }
    try {
      const created = await createChatSession();
      shouldAutoScrollRef.current = true;
      setSession(created);
      setTurns([]);
      setSessions((items) => [created, ...items]);
      setSelectedSessionIds([]);
      window.localStorage.setItem(LAST_SESSION_KEY, String(created.id));
      setPresetQuestions((items) => randomPresetQuestions(items));
      form.resetFields();
      setIsMobileSessionOpen(false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '新建会话失败');
    }
  };

  const handleDeleteSession = async (sessionId: number) => {
    if (isSending) {
      return;
    }
    try {
      await deleteChatSession(sessionId);
      message.success('会话已删除');
      const items = await listChatSessions();
      setSessions(items);
      setSelectedSessionIds((ids) => ids.filter((id) => id !== sessionId));
      if (session?.id === sessionId) {
        const nextSession = items[0];
        if (nextSession) {
          await openSession(nextSession.id, false);
        } else {
          setSession(null);
          setTurns([]);
          setPresetQuestions((items) => randomPresetQuestions(items));
          window.localStorage.removeItem(LAST_SESSION_KEY);
        }
      } else if (Number(window.localStorage.getItem(LAST_SESSION_KEY)) === sessionId) {
        window.localStorage.removeItem(LAST_SESSION_KEY);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除会话失败');
    }
  };

  const toggleSessionSelection = (sessionId: number, checked: boolean) => {
    setSelectedSessionIds((ids) =>
      checked ? Array.from(new Set([...ids, sessionId])) : ids.filter((id) => id !== sessionId)
    );
  };

  const handleSelectAllSessions = () => {
    setSelectedSessionIds(sessions.map((item) => item.id));
  };

  const handleClearSessionSelection = () => {
    setSelectedSessionIds([]);
  };

  const handleBatchDeleteSessions = async () => {
    if (isSending || selectedSessionIds.length === 0) {
      return;
    }
    try {
      const ids = [...selectedSessionIds];
      const response = await batchDeleteChatSessions(ids);
      message.success(`已删除 ${response.deleted_count} 个会话`);
      const items = await listChatSessions();
      setSessions(items);
      setSelectedSessionIds([]);
      if (session && ids.includes(session.id)) {
        const nextSession = items[0];
        if (nextSession) {
          await openSession(nextSession.id, false);
        } else {
          setSession(null);
          setTurns([]);
          setPresetQuestions((items) => randomPresetQuestions(items));
          window.localStorage.removeItem(LAST_SESSION_KEY);
        }
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量删除会话失败');
    }
  };

  const updateTurn = (id: string, patch: Partial<ChatTurn>) => {
    setTurns((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const updateTurnResponse = (id: string, patch: Partial<ChatMessageResponse>) => {
    setTurns((items) =>
      items.map((item) =>
        item.id === id
          ? {
              ...item,
              response: {
                answer: item.response?.answer || '',
                rows: item.response?.rows || [],
                ...patch
              }
            }
          : item
      )
    );
  };

  const submitQuestion = async (rawQuestion: string) => {
    if (isSending) {
      return;
    }
    const question = rawQuestion.trim();
    if (!question) {
      return;
    }
    const turnId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    let progressIndex = 0;
    let progressTimer: number | null = null;
    shouldAutoScrollRef.current = true;
    setIsSending(true);
    form.setFieldValue('question', '');
    setTurns((items) => [
      ...items,
      {
        id: turnId,
        question,
        response: { answer: '', rows: [] },
        streaming: true,
        progressText: CHAT_PROGRESS_STEPS[0]
      }
    ]);
    try {
      progressTimer = window.setInterval(() => {
        progressIndex = Math.min(progressIndex + 1, CHAT_PROGRESS_STEPS.length - 1);
        updateTurn(turnId, { progressText: CHAT_PROGRESS_STEPS[progressIndex] });
      }, 2600);
      const currentSession = session || (await createChatSession());
      if (!session) {
        setSession(currentSession);
        window.localStorage.setItem(LAST_SESSION_KEY, String(currentSession.id));
      }
      await sendChatMessageStream(
        currentSession.id,
        { question, llm_model: selectedModel },
        {
          onMeta: (event) => {
            updateTurn(turnId, { progressText: '正在生成分析...' });
            updateTurnResponse(turnId, { rows: event.rows || [] });
          },
          onDelta: (content) =>
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId && item.response
                  ? {
                      ...item,
                      progressText: '',
                      response: { ...item.response, answer: `${item.response.answer}${content}` }
                    }
                  : item
              )
            ),
          onDone: (event) => {
            updateTurn(turnId, { streaming: false, progressText: '', messageId: event.message_id });
            updateTurnResponse(turnId, {
              message_id: event.message_id,
              answer: event.answer || '',
              rows: event.rows || []
            });
            void refreshSessions(currentSession.id);
          },
          onError: (event) => {
            updateTurn(turnId, { streaming: false, progressText: '', messageId: event.message_id });
            updateTurnResponse(turnId, {
              message_id: event.message_id,
              answer: event.answer || '问答失败，请稍后再试。',
              rows: event.rows || []
            });
            void refreshSessions(currentSession.id);
            message.error(event.answer || '问答失败');
          }
        }
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '问答失败';
      updateTurn(turnId, { streaming: false, progressText: '' });
      updateTurnResponse(turnId, { answer: errorMessage });
      message.error(errorMessage);
    } finally {
      if (progressTimer !== null) {
        window.clearInterval(progressTimer);
      }
      setIsSending(false);
    }
  };

  const handleSubmit = async (values: ChatFormValues) => {
    await submitQuestion(values.question);
  };

  const exportTurns = async (targetTurns: ChatTurn[], title: string) => {
    const answeredTurns = targetTurns.filter((turn) => turn.response?.answer?.trim());
    if (!answeredTurns.length) {
      message.warning('当前没有可导出的回答内容');
      return;
    }
    await exportChatAnswersToWord(
      title,
      answeredTurns.map((turn) => ({
        question: turn.question,
        answer: turn.response?.answer || ''
      }))
    );
    message.success('Word 文档已下载');
  };

  const publishTurnToXueqiu = async (turn: ChatTurn) => {
    const messageId = turn.messageId || turn.response?.message_id;
    if (!messageId) {
      message.warning('这条回答还没有落库，请等生成完成后再发布');
      return;
    }
    setPublishingTurnId(turn.id);
    try {
      const response = await publishXueqiuChatAnswer({
        message_id: messageId,
        publish: false,
        force: false
      });
      message.success(response.draft_id ? '雪球草稿已保存' : response.message);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存雪球草稿失败');
    } finally {
      setPublishingTurnId(null);
    }
  };

  /**
   * 复用会话管理面板，桌面端渲染为左侧栏，移动端渲染到抽屉中，避免两套删除和批量选择逻辑分叉。
   * 创建日期：2026-05-18
   * author: sunshengxian
   */
  const renderSessionPanel = () => (
    <>
      <div className="chat-sidebar-head">
        <span>会话</span>
        <Button
          type="text"
          size="small"
          aria-label="新建会话"
          title="新建会话"
          icon={<Plus size={16} />}
          onClick={handleNewSession}
          disabled={isSending}
        />
      </div>
      {sessions.length ? (
        <div className="chat-session-bulkbar">
          <span>{selectedSessionIds.length ? `已选 ${selectedSessionIds.length}` : '批量管理'}</span>
          <div>
            <Button type="link" size="small" onClick={handleSelectAllSessions} disabled={isSending}>
              全选
            </Button>
            <Button
              type="link"
              size="small"
              onClick={handleClearSessionSelection}
              disabled={isSending || selectedSessionIds.length === 0}
            >
              清空
            </Button>
            <Popconfirm
              title="批量删除会话"
              description={`确认删除选中的 ${selectedSessionIds.length} 个会话？`}
              okText="删除"
              cancelText="取消"
              onConfirm={() => void handleBatchDeleteSessions()}
              disabled={isSending || selectedSessionIds.length === 0}
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<Trash2 size={14} />}
                disabled={isSending || selectedSessionIds.length === 0}
              />
            </Popconfirm>
          </div>
        </div>
      ) : null}
      <div className="chat-session-list">
        {isLoadingSessions ? <Skeleton active paragraph={{ rows: 5 }} /> : null}
        {!isLoadingSessions && sessions.length === 0 ? (
          <div className="chat-session-empty">暂无会话</div>
        ) : null}
        {sessions.map((item) => (
          <div
            key={item.id}
            className={`chat-session-item${session?.id === item.id ? ' active' : ''}`}
          >
            <Checkbox
              checked={selectedSessionIds.includes(item.id)}
              onChange={(event) => toggleSessionSelection(item.id, event.target.checked)}
              disabled={isSending}
              aria-label={`选择会话 ${item.title}`}
            />
            <button
              type="button"
              className="chat-session-open"
              onClick={() => void openSession(item.id)}
              disabled={isSending}
            >
              <strong>{item.title}</strong>
              <span>{formatEast8DateTime(item.updated_at, { naiveAsEast8: true })}</span>
            </button>
            <Popconfirm
              title="删除会话"
              description="删除后将不再显示该会话"
              okText="删除"
              cancelText="取消"
              onConfirm={() => void handleDeleteSession(item.id)}
              disabled={isSending}
            >
              <Button
                type="text"
                size="small"
                danger
                aria-label="删除会话"
                title="删除会话"
                icon={<Trash2 size={15} />}
                disabled={isSending}
              />
            </Popconfirm>
          </div>
        ))}
      </div>
    </>
  );

  return (
    <main className="page chat-page">
      <PageHeader title="智能问答" />
      <div className="chat-workspace">
        <div className="chat-mobile-topbar">
          <Button
            icon={<MessageCircleMore size={16} />}
            onClick={() => setIsMobileSessionOpen(true)}
            disabled={isSending && isLoadingSessions}
          >
            会话
          </Button>
          <span>{session ? session.title : '新会话'}</span>
          <Button
            type="primary"
            aria-label="新建会话"
            title="新建会话"
            icon={<Plus size={16} />}
            onClick={handleNewSession}
            disabled={isSending}
          />
        </div>
        <aside className="chat-sidebar">{renderSessionPanel()}</aside>
        <Drawer
          title={null}
          placement="left"
          width="88vw"
          open={isMobileSessionOpen}
          onClose={() => setIsMobileSessionOpen(false)}
          className="chat-mobile-session-drawer"
        >
          <div className="chat-mobile-session-panel">{renderSessionPanel()}</div>
        </Drawer>

        <div className="chat-main">
          <div className="chat-main-toolbar">
            <span>{session ? session.title : '未选择会话'}</span>
            <Button
              size="small"
              icon={<FileText size={15} />}
              onClick={() => void exportTurns(turns, session?.title || '智能问答回答')}
              disabled={!turns.some((turn) => turn.response?.answer?.trim())}
            >
              导出当前会话
            </Button>
          </div>
          <section className="chat-history" ref={historyRef} onScroll={onHistoryScroll}>
            {isLoadingHistory ? <Skeleton active paragraph={{ rows: 6 }} /> : null}
            {!isLoadingHistory && turns.length === 0 && !isSending ? (
              <div className="chat-empty-state">
                <div className="question-bank">
                  {presetQuestions.map((item) => (
                    <Button key={item} onClick={() => void submitQuestion(item)} disabled={isSending}>
                      {item}
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}
            {!isLoadingHistory
              ? turns.map((turn) => (
                  <div className="chat-turn" key={turn.id}>
                    <div className="chat-question">{turn.question}</div>
                    <div className="chat-answer">
                      <div className="chat-answer-actions">
                        {canPublishChatAnswerToXueqiu ? (
                          <Popconfirm
                            title="保存雪球草稿"
                            description="将这条回答转换为 HTML 长文并保存到雪球草稿？"
                            okText="保存"
                            cancelText="取消"
                            onConfirm={() => void publishTurnToXueqiu(turn)}
                            disabled={
                              Boolean(turn.streaming) ||
                              !turn.response?.answer?.trim() ||
                              !(turn.messageId || turn.response?.message_id)
                            }
                          >
                            <Button
                              type="text"
                              size="small"
                              icon={<Send size={14} />}
                              loading={publishingTurnId === turn.id}
                              disabled={
                                Boolean(turn.streaming) ||
                                !turn.response?.answer?.trim() ||
                                !(turn.messageId || turn.response?.message_id)
                              }
                            >
                              发布雪球
                            </Button>
                          </Popconfirm>
                        ) : null}
                        <Button
                          type="text"
                          size="small"
                          icon={<Download size={14} />}
                          onClick={() =>
                            void exportTurns([turn], `${session?.title || '智能问答'}-${turn.question}`)
                          }
                          disabled={!turn.response?.answer?.trim()}
                        >
                          导出
                        </Button>
                      </div>
                      <div className="markdown-answer">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={markdownComponents}
                        >
                          {turn.response?.answer || ''}
                        </ReactMarkdown>
                        {turn.streaming && !turn.response?.answer ? (
                          <LlmProgressNote text={turn.progressText} />
                        ) : null}
                        {turn.streaming && turn.response?.answer ? <span className="stream-caret" /> : null}
                      </div>
                      <ChatDataSummary rows={turn.response?.rows || []} />
                    </div>
                  </div>
                ))
              : null}
            {isSending && turns.length === 0 ? <Skeleton active paragraph={{ rows: 4 }} /> : null}
            <div className="chat-history-end" />
          </section>

          <section className="chat-composer">
            <Form form={form} layout="vertical" onFinish={handleSubmit}>
              <Form.Item name="question" rules={[{ required: true, message: '请输入问题' }]}>
                <Input.TextArea
                  rows={3}
                  placeholder="输入投资相关问题"
                  onPressEnter={(event) => {
                    if (!event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      form.submit();
                    }
                  }}
                />
              </Form.Item>
              <div className="composer-actions">
                <Segmented
                  size="small"
                  options={CHAT_MODEL_OPTIONS}
                  value={selectedModel}
                  onChange={(value) => setSelectedModel(value as ChatModel)}
                  disabled={isSending}
                  aria-label="选择问答模型"
                />
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<SendHorizontal size={16} />}
                  loading={isSending}
                  disabled={isSending}
                >
                  发送
                </Button>
              </div>
            </Form>
          </section>
        </div>
      </div>
    </main>
  );
}

function buildTurns(messages: ChatStoredMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  messages.forEach((item) => {
    if (item.role === 'user') {
      turns.push({
        id: `message-${item.id}`,
        question: item.content,
        response: { answer: '', rows: [] }
      });
      return;
    }
    if (item.role === 'assistant') {
      const target = [...turns].reverse().find((turn) => !turn.response?.answer);
      if (target) {
        target.messageId = item.id;
        target.response = { message_id: item.id, answer: item.content, rows: item.rows || [] };
      }
    }
  });
  return turns.filter((turn) => turn.question || turn.response?.answer);
}

function ChatDataSummary({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) {
    return null;
  }
  const keys = getSummaryKeys(rows);
  const visibleRows = rows.slice(0, 8);
  const tableWidth = keys.reduce((total, key) => total + (CHAT_SUMMARY_COLUMN_WIDTHS[key] || 128), 0);

  return (
    <details className="chat-data-summary">
      <summary>
        <span>数据摘要</span>
        <b>{rows.length} 条样本</b>
      </summary>
      <div className="chat-data-body">
        <Table
          rowKey={(_, rowIndex) => String(rowIndex)}
          size="small"
          pagination={false}
          tableLayout="fixed"
          dataSource={visibleRows}
          columns={keys.map((key) => ({
            title: CHAT_TABLE_LABELS[key] || key,
            dataIndex: key,
            width: CHAT_SUMMARY_COLUMN_WIDTHS[key] || 128,
            ellipsis: true,
            render: (value) => <OverflowCell value={value} fieldKey={key} threshold={18} />
          }))}
          scroll={{ x: tableWidth }}
        />
      </div>
    </details>
  );
}

function getSummaryKeys(rows: Record<string, unknown>[]) {
  const allKeys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const prioritized = CHAT_SUMMARY_COLUMN_PRIORITY.filter((key) => allKeys.includes(key));
  const fallback = allKeys.filter((key) => !prioritized.includes(key));
  // 数据摘要用于核验原始事实，保留横向滚动承接更多字段，不再人为截断列数。
  return [...prioritized, ...fallback];
}

export default ChatPage;
