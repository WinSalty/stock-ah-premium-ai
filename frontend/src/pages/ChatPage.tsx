import { Button, Checkbox, DatePicker, Form, Input, Skeleton, Table, message } from 'antd';
import { Plus, SendHorizontal } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEffect, useState } from 'react';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import {
  createChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessageStream
} from '../api/chat';
import type {
  ChatMessageResponse,
  ChatSession,
  ChatStoredMessage
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

interface ChatFormValues {
  question: string;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  ts_code?: string;
  only_watchlist?: boolean;
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
  const [isSending, setIsSending] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

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
      form.resetFields();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '新建会话失败');
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
        {
          question,
          start_date: values.range?.[0]?.format('YYYY-MM-DD'),
          end_date: values.range?.[1]?.format('YYYY-MM-DD'),
          ts_code: values.ts_code?.trim() || undefined,
          only_watchlist: values.only_watchlist
        },
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
      form.resetFields(['question']);
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
        <aside className="panel chat-sidebar">
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
              <button
                key={item.id}
                type="button"
                className={`chat-session-item${session?.id === item.id ? ' active' : ''}`}
                onClick={() => void openSession(item.id)}
                disabled={isSending}
              >
                <strong>{item.title}</strong>
                <span>{formatEast8DateTime(item.updated_at)}</span>
              </button>
            ))}
          </div>
        </aside>

        <div className="chat-main">
          <section className="panel chat-history">
            {isLoadingHistory ? <Skeleton active paragraph={{ rows: 6 }} /> : null}
            {!isLoadingHistory && turns.length === 0 && !isSending ? (
              <div className="question-bank">
                {[
                  '我关注的股票里，最近一个交易日哪些 H/A 折价最明显？',
                  '哪些自选股已经达到我设置的阈值？',
                  '请筛选低估值、高股息且 ROE 稳定的 A 股候选'
                ].map((item) => (
                  <Button key={item} onClick={() => form.setFieldValue('question', item)}>
                    {item}
                  </Button>
                ))}
              </div>
            ) : null}
            {!isLoadingHistory
              ? turns.map((turn) => (
                  <div className="chat-turn" key={turn.id}>
                    <div className="chat-question">{turn.question}</div>
                    <div className="chat-answer">
                      <div className="markdown-answer">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {turn.response?.answer || (turn.streaming ? '正在分析...' : '')}
                        </ReactMarkdown>
                        {turn.streaming ? <span className="stream-caret" /> : null}
                      </div>
                      {turn.response?.rows.length ? (
                        <div className="chat-data-table">
                          <div className="chat-data-title">数据摘要</div>
                          <Table
                            rowKey={(_, rowIndex) => String(rowIndex)}
                            size="small"
                            pagination={false}
                            dataSource={turn.response.rows.slice(0, 8)}
                            columns={Object.keys(turn.response.rows[0]).map((key) => ({
                              title: CHAT_TABLE_LABELS[key] || key,
                              dataIndex: key,
                              width: key.endsWith('_at') || key.includes('time') ? 190 : 140,
                              ellipsis: true,
                              render: (value) => <OverflowCell value={value} fieldKey={key} threshold={22} />
                            }))}
                            scroll={{ x: true }}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))
              : null}
            {isSending && turns.length === 0 ? <Skeleton active paragraph={{ rows: 4 }} /> : null}
          </section>

          <section className="panel chat-composer">
            <Form form={form} layout="vertical" onFinish={handleSubmit}>
              <div className="chat-form-grid">
                <Form.Item label="范围" name="range">
                  <DatePicker.RangePicker className="full-width" />
                </Form.Item>
                <Form.Item label="股票" name="ts_code">
                  <Input placeholder="可选代码" />
                </Form.Item>
                <Form.Item label="自选范围" name="only_watchlist" valuePropName="checked">
                  <Checkbox>只看自选股</Checkbox>
                </Form.Item>
              </div>
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

export default ChatPage;
