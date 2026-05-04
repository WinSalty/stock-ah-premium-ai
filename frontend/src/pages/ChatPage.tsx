import { Button, Checkbox, DatePicker, Form, Input, Skeleton, Table, message } from 'antd';
import { SendHorizontal } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useState } from 'react';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import { createChatSession, sendChatMessageStream } from '../api/chat';
import type { ChatMessageResponse, ChatSession } from '../types/domain';

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

/**
 * 智能问答页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function ChatPage() {
  const [form] = Form.useForm<ChatFormValues>();
  const [session, setSession] = useState<ChatSession | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [isSending, setIsSending] = useState(false);

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
                sql: item.response?.sql ?? null,
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
        response: { answer: '', sql: null, rows: [] },
        streaming: true
      }
    ]);
    try {
      const currentSession = session || (await createChatSession());
      if (!session) {
        setSession(currentSession);
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
          onMeta: (event) => updateTurnResponse(turnId, { sql: event.sql ?? null, rows: event.rows || [] }),
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
              sql: event.sql ?? null,
              rows: event.rows || []
            });
          },
          onError: (event) => {
            updateTurn(turnId, { streaming: false });
            updateTurnResponse(turnId, {
              answer: event.answer || '问答失败，请稍后再试。',
              sql: event.sql ?? null,
              rows: event.rows || []
            });
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
      <section className="panel chat-history">
        {turns.length === 0 && !isSending ? (
          <div className="question-bank">
            {[
              '我关注的股票里，最近一个交易日哪些 H/A 折价最明显？',
              '哪些自选股已经达到我设置的阈值？',
              '最新交易日哪些官方 AH 比价数据不是港股通可操作标的？'
            ].map((item) => (
              <Button key={item} onClick={() => form.setFieldValue('question', item)}>
                {item}
              </Button>
            ))}
          </div>
        ) : null}
        {turns.map((turn) => (
          <div className="chat-turn" key={turn.id}>
            <div className="chat-question">{turn.question}</div>
            <div className="chat-answer">
              <div className="markdown-answer">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {turn.response?.answer || (turn.streaming ? '正在分析...' : '')}
                </ReactMarkdown>
                {turn.streaming ? <span className="stream-caret" /> : null}
              </div>
              {turn.response?.sql ? <pre className="sql-preview">{turn.response.sql}</pre> : null}
              {turn.response?.rows.length ? (
                <Table
                  rowKey={(_, rowIndex) => String(rowIndex)}
                  size="small"
                  pagination={false}
                  dataSource={turn.response.rows.slice(0, 8)}
                  columns={Object.keys(turn.response.rows[0]).map((key) => ({
                    title: key,
                    dataIndex: key,
                    width: key.endsWith('_at') || key.includes('time') ? 190 : 140,
                    ellipsis: true,
                    render: (value) => <OverflowCell value={value} fieldKey={key} threshold={22} />
                  }))}
                  scroll={{ x: true }}
                />
              ) : null}
            </div>
          </div>
        ))}
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
              placeholder="输入问题"
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
    </main>
  );
}

export default ChatPage;
