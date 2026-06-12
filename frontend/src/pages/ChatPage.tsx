import { Button, Checkbox, Collapse, Drawer, Form, Input, Popconfirm, Skeleton, Spin, message } from 'antd';
import {
  CircleCheck,
  CircleX,
  Download,
  FileText,
  MessageCircleMore,
  Plus,
  Send,
  SendHorizontal,
  Trash2
} from 'lucide-react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';
import PageHeader from '../components/PageHeader';
import ChatChart from '../components/ChatChart';
import {
  batchDeleteChatSessions,
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessageStream
} from '../api/chat';
import type {
  ChartSpec,
  ChatMessageResponse,
  ChatSession,
  ChatStoredMessage,
  ToolTraceItem,
  UserInfo
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';
import { exportChatAnswersToWord } from '../utils/chatWordExport';
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
  /** 已完成的工具执行轨迹（流式过程逐步累积，done 事件以全量汇总覆盖）。 */
  toolTrace: ToolTraceItem[];
  /** 正在执行中的工具步骤；Agent 主循环为串行执行，同一时刻最多一个进行中步骤。 */
  activeTool?: { tool: string; summary: string };
  /** 本轮登记的图表 spec（含后端写入的 chart_id）：正文按 {{chart:id}} 占位符配对渲染 ChatChart。 */
  charts?: ChartSpec[];
  /** 整轮墙钟耗时毫秒数（done 事件下发，含模型思考；历史回放无该值时不展示合计）。 */
  totalElapsedMs?: number | null;
}

interface ChatPageProps {
  currentUser: UserInfo;
}

const LAST_SESSION_KEY = 'stock-ah-premium-ai:last-chat-session';

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

const STRUCTURED_ANALYSIS_PRESET_QUESTIONS = [
  '我该买什么股票？',
  '我可以投资哪些股票？',
  '长期持有保守型，帮我推荐不超过 10 只适合价值投资的股票',
  '风险高收益型，帮我从最新打板报告里挑几只晋级观察标的',
  '近十年平均年化大于 10%、ROE 大于 2%、PE 小于 7 的股票有哪些？',
  '招商银行分红再投年度明细是什么样？',
  '分红再投筛选里，哪些股票更适合长期持有？',
  '按分红稳定性、ROE 和低估值帮我筛一批红利复利候选',
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
  '招商银行十年平均年化收益率是多少？',
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
 * 把毫秒耗时格式化为秒级展示（如 412.5 -> "0.4s"），用于工具步骤与整轮耗时。
 * 本地查询常在毫秒级，四舍五入为 "0.0s" 观感像统计错误，统一显示 "<0.1s"。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function formatElapsedSeconds(elapsedMs: number) {
  if (elapsedMs > 0 && elapsedMs < 100) {
    return '<0.1s';
  }
  return `${(elapsedMs / 1000).toFixed(1)}s`;
}

/**
 * 渲染工具执行步骤明细（轻量自定义列表）：
 * - 已完成步骤按成功/失败展示打勾/打叉图标，并附结果摘要与耗时；
 * - 进行中的步骤展示 Spin 小图标（Agent 主循环串行执行，同一时刻最多一个进行中步骤）。
 * 流式实时时间线与完成后的折叠明细复用同一份渲染，保证两种形态展示口径一致。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function renderToolSteps(
  toolTrace: ToolTraceItem[],
  activeTool?: { tool: string; summary: string },
  thinking?: boolean
) {
  return (
    <ul className="chat-tool-steps">
      {toolTrace.map((step, index) => (
        <li key={`${step.tool}-${index}`} className="chat-tool-step">
          {step.ok ? (
            <CircleCheck size={14} className="chat-tool-step-icon ok" />
          ) : (
            <CircleX size={14} className="chat-tool-step-icon fail" />
          )}
          <span className="chat-tool-step-summary">{step.summary || step.tool}</span>
          {step.result_summary ? (
            <span className="chat-tool-step-result">{step.result_summary}</span>
          ) : null}
          <span className="chat-tool-step-elapsed">{formatElapsedSeconds(step.elapsed_ms || 0)}</span>
        </li>
      ))}
      {activeTool ? (
        <li className="chat-tool-step running">
          <Spin size="small" />
          <span className="chat-tool-step-summary">{activeTool.summary || activeTool.tool}</span>
        </li>
      ) : null}
      {/* LLM 迭代思考期（工具步骤之间 / 回答生成前）的进行中行：
          没有该行时图表先渲染、回答未到的空窗会让页面看起来像已结束（试用反馈问题3）。 */}
      {!activeTool && thinking ? (
        <li className="chat-tool-step running">
          <Spin size="small" />
          <span className="chat-tool-step-summary">正在分析与组织回答...</span>
        </li>
      ) : null}
    </ul>
  );
}

/**
 * 渲染一轮回答的工具执行时间线：
 * - 流式进行中：在回答区顶部实时展示每一步执行状态；
 * - 回答完成（含历史回放）：折叠为"本轮执行 N 步（耗时合计 X s）"一行摘要，点击可展开明细。
 * 没有任何工具步骤时不渲染（纯对话轮次保持原有界面）。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function renderToolTimeline(turn: ChatTurn) {
  if (turn.streaming) {
    // 思考行口径：回答文本尚未开始且没有正在执行的工具时，始终保留一个进行中指示，
    // 覆盖「首个事件前」「工具步骤之间」「最终回答生成前」三段空窗。
    const thinking = !turn.activeTool && !turn.response?.answer;
    if (!turn.toolTrace.length && !turn.activeTool && !thinking) {
      return null;
    }
    return (
      <div className="chat-tool-timeline">
        {renderToolSteps(turn.toolTrace, turn.activeTool, thinking)}
      </div>
    );
  }
  if (!turn.toolTrace.length) {
    return null;
  }
  // 合计口径（试用反馈修正）：用 done 事件下发的整轮墙钟耗时（含模型思考），
  // 而非仅工具执行求和——后者会把一轮 60s 的对话显示成 1.1s，严重误导。
  // 历史回放没有墙钟值时不显示合计，只显示步数（每步耗时仍在明细中可见）。
  const totalLabel = turn.totalElapsedMs
    ? `（总耗时 ${formatElapsedSeconds(turn.totalElapsedMs)}，含模型分析）`
    : '';
  return (
    <Collapse
      ghost
      size="small"
      className="chat-tool-trace-collapse"
      items={[
        {
          key: 'trace',
          label: `本轮执行 ${turn.toolTrace.length} 步${totalLabel}`,
          children: renderToolSteps(turn.toolTrace)
        }
      ]}
    />
  );
}

// 匹配回答正文中的图表占位符 {{chart:cN}}，捕获组取出 chart_id。
// 全局 + 多次匹配，用于按占位符把正文切分为「文本段 / 图表段」交替序列。
const CHART_PLACEHOLDER_PATTERN = /\{\{chart:([a-zA-Z0-9_-]+)\}\}/g;

/**
 * 渲染一段回答正文 Markdown（复用自定义的 table 组件，保证分段后表格样式一致）。
 * 空文本不渲染，避免占位符相邻时产生多余空段落。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function renderMarkdownSegment(text: string, key: string) {
  if (!text.trim()) {
    return null;
  }
  return (
    <ReactMarkdown key={key} remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {text}
    </ReactMarkdown>
  );
}

/**
 * 按 {{chart:id}} 占位符把回答正文切分为 [文本段, 图表, 文本段, ...] 交替渲染：
 * - 文本段走 ReactMarkdown（复用 markdownComponents 的 table 渲染）；
 * - 图表段按 chart_id 从 charts 中查找对应 ChartSpec 渲染 <ChatChart>；
 * - 占位符引用了但 charts 里找不到对应 id 的，渲染为空（不显示残留的 {{chart:x}} 文本）；
 * - charts 中未被正文任何占位符引用的图表，追加渲染在回答末尾（兜底，设计 3.5）。
 * 流式与历史回放复用同一逻辑（均以 answer 文本 + turn.charts 为输入）。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function renderAnswerWithCharts(answer: string, charts: ChartSpec[] | undefined, turnId: string) {
  const chartList = charts || [];
  // 建立 chart_id -> spec 映射，便于占位符按 id 取图；无 chart_id 的 spec 不参与占位匹配。
  const chartMap = new Map<string, ChartSpec>();
  chartList.forEach((spec) => {
    if (spec.chart_id) {
      chartMap.set(spec.chart_id, spec);
    }
  });

  const nodes: ReactNode[] = [];
  // 记录正文已引用的 chart_id，用于末尾兜底渲染未引用图表。
  const referencedIds = new Set<string>();
  let lastIndex = 0;
  let matchSeq = 0;
  // 重置全局正则的 lastIndex，避免跨调用状态污染。
  CHART_PLACEHOLDER_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CHART_PLACEHOLDER_PATTERN.exec(answer)) !== null) {
    const chartId = match[1];
    // 占位符之前的文本段先作为 Markdown 渲染。
    const textBefore = answer.slice(lastIndex, match.index);
    const textNode = renderMarkdownSegment(textBefore, `${turnId}-text-${matchSeq}`);
    if (textNode) {
      nodes.push(textNode);
    }
    referencedIds.add(chartId);
    const spec = chartMap.get(chartId);
    if (spec) {
      // 命中已登记图表：渲染对应 ChatChart。
      nodes.push(<ChatChart key={`${turnId}-chart-${chartId}-${matchSeq}`} spec={spec} />);
    }
    // 未命中（占位符引用了不存在的 id）：不渲染任何内容，丢弃残留占位符文本。
    lastIndex = match.index + match[0].length;
    matchSeq += 1;
  }
  // 最后一个占位符之后的剩余文本段。
  const tailNode = renderMarkdownSegment(answer.slice(lastIndex), `${turnId}-text-tail`);
  if (tailNode) {
    nodes.push(tailNode);
  }
  // 兜底：charts 里存在但正文从未引用的图表，按登记顺序追加在回答末尾。
  chartList.forEach((spec, index) => {
    if (!spec.chart_id || !referencedIds.has(spec.chart_id)) {
      nodes.push(<ChatChart key={`${turnId}-extra-${spec.chart_id || index}`} spec={spec} />);
    }
  });
  return nodes;
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
              // 合并已有 response（保留先前写入的 message_id 等字段），answer 兜底为空串。
              response: {
                ...item.response,
                answer: item.response?.answer || '',
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
    shouldAutoScrollRef.current = true;
    setIsSending(true);
    form.setFieldValue('question', '');
    setTurns((items) => [
      ...items,
      {
        id: turnId,
        question,
        response: { answer: '' },
        streaming: true,
        toolTrace: []
      }
    ]);
    try {
      const currentSession = session || (await createChatSession());
      if (!session) {
        setSession(currentSession);
        window.localStorage.setItem(LAST_SESSION_KEY, String(currentSession.id));
      }
      // Agent 化后服务端统一使用 agent_model，请求体不再携带 llm_model；
      // 等待提示完全由真实的 tool_start/tool_result 事件驱动，不再做假进度轮播。
      await sendChatMessageStream(
        currentSession.id,
        { question },
        {
          onToolStart: (event) => {
            // 记录进行中的工具步骤；启动 summary 留待 tool_result 时合入轨迹明细。
            updateTurn(turnId, { activeTool: { tool: event.tool, summary: event.summary } });
          },
          onToolResult: (event) => {
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId
                  ? {
                      ...item,
                      activeTool: undefined,
                      toolTrace: [
                        ...item.toolTrace,
                        {
                          tool: event.tool,
                          // 步骤动作摘要取自配对的 tool_start 事件；若事件乱序导致无法配对，
                          // 降级用工具名兜底（renderToolSteps 中 summary 为空时回退 tool）。
                          summary:
                            item.activeTool && item.activeTool.tool === event.tool
                              ? item.activeTool.summary
                              : '',
                          result_summary: event.summary,
                          ok: event.ok,
                          elapsed_ms: event.elapsed_ms
                        }
                      ]
                    }
                  : item
              )
            );
          },
          onChart: (event) => {
            // 流式累积图表 spec（event.spec 含后端写入的 chart_id），供正文 {{chart:id}} 占位渲染；
            // done 事件以全量 charts 覆盖。ChatChart 已接入 ECharts，图表登记即可先于正文占位渲染。
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId ? { ...item, charts: [...(item.charts || []), event.spec] } : item
              )
            );
          },
          onDelta: (content) =>
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId && item.response
                  ? {
                      ...item,
                      response: { ...item.response, answer: `${item.response.answer}${content}` }
                    }
                  : item
              )
            ),
          onDone: (event) => {
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId
                  ? {
                      ...item,
                      streaming: false,
                      messageId: event.message_id,
                      activeTool: undefined,
                      // done 事件携带的 tool_trace/charts 为本轮全量汇总，以服务端口径覆盖
                      // 流式过程累积值；缺省时保留已累积的本地数据兜底。
                      toolTrace: event.tool_trace?.length ? event.tool_trace : item.toolTrace,
                      charts: event.charts?.length ? event.charts : item.charts,
                      // 整轮墙钟耗时（含模型思考）：折叠摘要展示真实等待时长。
                      totalElapsedMs: event.elapsed_ms ?? null,
                      response: {
                        message_id: event.message_id,
                        answer: event.answer || item.response?.answer || ''
                      }
                    }
                  : item
              )
            );
            void refreshSessions(currentSession.id);
          },
          onError: (event) => {
            // error 事件的 answer 为服务端已落库的失败文案，直接作为本轮回答展示；
            // toast 提示统一交给下方 catch（sendChatMessageStream 收到 error 后仍会抛出）。
            updateTurn(turnId, { streaming: false, activeTool: undefined, messageId: event.message_id });
            updateTurnResponse(turnId, {
              message_id: event.message_id,
              answer: event.answer || '问答失败，请稍后再试。'
            });
            void refreshSessions(currentSession.id);
          }
        }
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '问答失败';
      // 网络中断等未收到 error 事件的失败：此时回答仍为空，用异常文案兜底展示；
      // 若已由 onError 写入落库文案，这里覆盖为同一段文案（streamError 即 event.answer），无副作用。
      updateTurn(turnId, { streaming: false, activeTool: undefined });
      updateTurnResponse(turnId, { answer: errorMessage });
      message.error(errorMessage);
    } finally {
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
        answer: turn.response?.answer || '',
        // 携带本轮图表 spec，供 Word 导出对 {{chart:id}} 占位符降级为数据表格。
        charts: turn.charts
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
                    {/* 孤立 assistant 消息（历史回放中无配对提问）不渲染空的提问气泡 */}
                    {turn.question ? <div className="chat-question">{turn.question}</div> : null}
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
                      {renderToolTimeline(turn)}
                      <div className="markdown-answer">
                        {/* 按 {{chart:id}} 占位符分段渲染：文本段走 Markdown，图表段渲染 ChatChart；
                            未被正文引用的图表追加在末尾（流式与历史回放复用同一逻辑）。 */}
                        {renderAnswerWithCharts(turn.response?.answer || '', turn.charts, turn.id)}
                        {/* 等待提示统一收敛到时间线的"正在分析与组织回答"思考行
                            （renderToolTimeline），不再单独渲染 LlmProgressNote，避免双指示。 */}
                        {turn.streaming && turn.response?.answer ? <span className="stream-caret" /> : null}
                      </div>
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

/**
 * 历史会话回放：把按 id 升序返回的消息列表按"相邻配对"组装为问答轮次。
 * 配对口径：user 消息开启新一轮；紧随其后的第一条 assistant 消息即本轮回答
 * （依赖接口按消息 id 升序返回的相邻关系）。连续两条 user 消息时前一条单独成轮
 * （无回答），修复旧实现"倒查最近未回答轮"在该场景下的错配（旧评审 E6）。
 * 孤立的 assistant 消息（前面没有待配对的 user 消息）也单独成轮展示，避免内容丢失。
 * 创建日期：2026-05-04
 * 更新日期：2026-06-12（改为相邻配对；回放 tool_trace 与 charts）
 * author: sunshengxian
 */
function buildTurns(messages: ChatStoredMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  // 指向最近一条尚未配对回答的 user 轮次；配对成功或被更新的 user 消息顶替后清空/重置。
  let pendingTurn: ChatTurn | null = null;
  messages.forEach((item) => {
    if (item.role === 'user') {
      pendingTurn = {
        id: `message-${item.id}`,
        question: item.content,
        toolTrace: [],
        response: { answer: '' }
      };
      turns.push(pendingTurn);
      return;
    }
    if (item.role === 'assistant') {
      if (pendingTurn) {
        pendingTurn.messageId = item.id;
        pendingTurn.response = { message_id: item.id, answer: item.content };
        // 历史旧消息可能没有 tool_trace/charts 字段，按空数组兜底（向后兼容口径）。
        pendingTurn.toolTrace = item.tool_trace || [];
        pendingTurn.charts = item.charts || [];
        pendingTurn = null;
        return;
      }
      turns.push({
        id: `message-${item.id}`,
        messageId: item.id,
        question: '',
        toolTrace: item.tool_trace || [],
        charts: item.charts || [],
        response: { message_id: item.id, answer: item.content }
      });
    }
  });
  return turns.filter((turn) => turn.question || turn.response?.answer);
}

export default ChatPage;
