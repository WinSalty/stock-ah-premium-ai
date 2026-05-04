import { Button, Form, Input, Popconfirm, Segmented, Skeleton, Table, message } from 'antd';
import { Plus, SendHorizontal, Trash2 } from 'lucide-react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEffect, useState } from 'react';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import {
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
  ChatStoredMessage
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

interface ChatFormValues {
  question: string;
}

interface ChatTurn {
  id: string;
  question: string;
  response?: ChatMessageResponse;
  streaming?: boolean;
}

const LAST_SESSION_KEY = 'stock-ah-premium-ai:last-chat-session';

const CHAT_TABLE_LABELS: Record<string, string> = {
  trade_date: '交易日',
  factor_date: '因子日',
  a_ts_code: 'A 股代码',
  hk_ts_code: 'H 股代码',
  ts_code: '股票代码',
  a_name: 'A 股名称',
  hk_name: 'H 股名称',
  name: '名称',
  display_name: '标的',
  industry: '行业',
  ah_premium_pct: 'A/H 溢价%',
  ha_premium_pct: 'H/A 溢价%',
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
  pe_ttm: 'PE TTM',
  pb: 'PB',
  dividend_yield_ttm: '股息率',
  roe: 'ROE',
  debt_to_assets: '资产负债率',
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
  'industry',
  'selection_tags',
  'selection_score',
  'pe_ttm',
  'pb',
  'dividend_yield_ttm',
  'roe',
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
  industry: 116,
  selection_tags: 180,
  selection_score: 88,
  pe_ttm: 88,
  pb: 80,
  dividend_yield_ttm: 100,
  roe: 88,
  return_60d: 104,
  ah_premium_pct: 104,
  ha_premium_pct: 104,
  metric_premium_pct: 104,
  distance_to_target_pct: 96,
  premium_percentile_60: 96,
  opportunity_status: 96,
  connect_channels: 120,
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
const DEFAULT_CHAT_MODEL: ChatModel = 'deepseek-v4-flash';
const CHAT_MODEL_OPTIONS: { label: string; value: ChatModel }[] = [
  { label: 'DeepSeek Flash', value: 'deepseek-v4-flash' },
  { label: 'DeepSeek Pro', value: 'deepseek-v4-pro' },
  { label: 'Qwen 3.6 Max', value: 'qwen3.6-max-preview' }
];

const REPORT_BASED_PRESET_QUESTIONS = [
  '五粮液当前更应按修复股还是价值股定价？请给出评级口径、核心假设和跟踪指标',
  '五粮液 2026 年投资报告里最需要验证的三个风险是什么？',
  '招商银行现在还适合作为长期核心银行持仓吗？请和宁波银行、江苏银行做对比',
  '银行与非银长期投资中，哪些资产更适合防御底仓，哪些更适合弹性配置？',
  '日本地产金融调整对中国银行、地产链和高股息资产配置有什么启示？',
  '参考日本经验，中国房地产出清阶段哪些行业可能更受益，哪些行业需要回避？',
  '如果地产长期出清，A 股长期投资应优先关注哪些现金流资产？',
  'A/H 溢价候选里，哪些标的更像跨市场替代机会而不是套利机会？',
  '请给出 A/H 价差策略的保守、中性、进取三种配置框架',
  '低估值、高股息、ROE 稳定的 A 股候选，如何结合银行和红利资产筛选？',
  '五粮液、贵州茅台和高股息央企分别适合什么风险偏好的组合？',
  '在宏观低收益环境下，银行、白酒、公用事业和高端制造应如何分层配置？'
];

function randomPresetQuestions(previous: string[] = []) {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const nextQuestions = [...REPORT_BASED_PRESET_QUESTIONS]
      .sort(() => Math.random() - 0.5)
      .slice(0, PRESET_QUESTION_COUNT);
    if (nextQuestions.some((item, index) => item !== previous[index])) {
      return nextQuestions;
    }
  }
  return [...REPORT_BASED_PRESET_QUESTIONS].slice(0, PRESET_QUESTION_COUNT);
}

/**
 * 智能问答页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function ChatPage() {
  const [form] = Form.useForm<ChatFormValues>();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [presetQuestions, setPresetQuestions] = useState(randomPresetQuestions);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ChatModel>(DEFAULT_CHAT_MODEL);

  useEffect(() => {
    void loadInitialSessions();
  }, []);

  const loadInitialSessions = async () => {
    setIsLoadingSessions(true);
    try {
      const items = await listChatSessions();
      setSessions(items);
      const savedId = Number(window.localStorage.getItem(LAST_SESSION_KEY));
      const target = items.find((item) => item.id === savedId) || items[0];
      if (target) {
        await openSession(target.id, false);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '会话加载失败');
    } finally {
      setIsLoadingSessions(false);
    }
  };

  const refreshSessions = async (activeSessionId?: number) => {
    const items = await listChatSessions();
    setSessions(items);
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
      setSession(detail);
      setTurns(buildTurns(detail.messages));
      window.localStorage.setItem(LAST_SESSION_KEY, String(detail.id));
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
      setSession(created);
      setTurns([]);
      setSessions((items) => [created, ...items]);
      window.localStorage.setItem(LAST_SESSION_KEY, String(created.id));
      setPresetQuestions((items) => randomPresetQuestions(items));
      form.resetFields();
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

  const handleSubmit = async (values: ChatFormValues) => {
    if (isSending) {
      return;
    }
    const question = values.question.trim();
    if (!question) {
      return;
    }
    const turnId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setIsSending(true);
    form.setFieldValue('question', '');
    setTurns((items) => [
      ...items,
      {
        id: turnId,
        question,
        response: { answer: '', rows: [] },
        streaming: true
      }
    ]);
    try {
      const currentSession = session || (await createChatSession());
      if (!session) {
        setSession(currentSession);
        window.localStorage.setItem(LAST_SESSION_KEY, String(currentSession.id));
      }
      await sendChatMessageStream(
        currentSession.id,
        { question, llm_model: selectedModel },
        {
          onMeta: (event) => updateTurnResponse(turnId, { rows: event.rows || [] }),
          onDelta: (content) =>
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId && item.response
                  ? { ...item, response: { ...item.response, answer: `${item.response.answer}${content}` } }
                  : item
              )
            ),
          onDone: (event) => {
            updateTurn(turnId, { streaming: false });
            updateTurnResponse(turnId, {
              answer: event.answer || '',
              rows: event.rows || []
            });
            void refreshSessions(currentSession.id);
          },
          onError: (event) => {
            updateTurn(turnId, { streaming: false });
            updateTurnResponse(turnId, {
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
      updateTurn(turnId, { streaming: false });
      updateTurnResponse(turnId, { answer: errorMessage });
      message.error(errorMessage);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <main className="page chat-page">
      <PageHeader title="智能问答" />
      <div className="chat-workspace">
        <aside className="chat-sidebar">
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
        </aside>

        <div className="chat-main">
          <section className="chat-history">
            {isLoadingHistory ? <Skeleton active paragraph={{ rows: 6 }} /> : null}
            {!isLoadingHistory && turns.length === 0 && !isSending ? (
              <div className="chat-empty-state">
                <div className="question-bank">
                  {presetQuestions.map((item) => (
                    <Button key={item} onClick={() => form.setFieldValue('question', item)}>
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
                      <div className="markdown-answer">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={markdownComponents}
                        >
                          {turn.response?.answer || (turn.streaming ? '正在分析...' : '')}
                        </ReactMarkdown>
                        {turn.streaming ? <span className="stream-caret" /> : null}
                      </div>
                      <ChatDataSummary rows={turn.response?.rows || []} />
                    </div>
                  </div>
                ))
              : null}
            {isSending && turns.length === 0 ? <Skeleton active paragraph={{ rows: 4 }} /> : null}
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
        target.response = { answer: item.content, rows: item.rows || [] };
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
  return [...prioritized, ...fallback].slice(0, 9);
}

export default ChatPage;
