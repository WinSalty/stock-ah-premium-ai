import { Button, DatePicker, Form, Input, Skeleton, Table, Typography, message } from 'antd';
import { SendHorizontal } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import { createChatSession, sendChatMessage } from '../api/chat';
import type { ChatMessageResponse, ChatSession } from '../types/domain';

interface ChatFormValues {
  question: string;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  ts_code?: string;
}

interface ChatTurn {
  question: string;
  response?: ChatMessageResponse;
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
  const mutation = useMutation({
    mutationFn: async (values: ChatFormValues) => {
      const currentSession = session || (await createChatSession());
      if (!session) {
        setSession(currentSession);
      }
      return sendChatMessage(currentSession.id, {
        question: values.question,
        start_date: values.range?.[0]?.format('YYYY-MM-DD'),
        end_date: values.range?.[1]?.format('YYYY-MM-DD'),
        ts_code: values.ts_code?.trim() || undefined
      });
    },
    onSuccess: (response, values) => {
      setTurns((items) => [...items, { question: values.question, response }]);
      form.resetFields(['question']);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '问答失败')
  });

  return (
    <main className="page chat-page">
      <PageHeader title="智能问答" />
      <section className="panel chat-history">
        {turns.length === 0 && !mutation.isPending ? (
          <div className="question-bank">
            {[
              '最近一个交易日 A/H 溢价最高的 10 只是什么？',
              '哪些股票今天无法计算溢价？',
              '近 60 个交易日溢价率趋势如何？'
            ].map((item) => (
              <Button key={item} onClick={() => form.setFieldValue('question', item)}>
                {item}
              </Button>
            ))}
          </div>
        ) : null}
        {turns.map((turn, index) => (
          <div className="chat-turn" key={`${turn.question}-${index}`}>
            <div className="chat-question">{turn.question}</div>
            <div className="chat-answer">
              <Typography.Paragraph>{turn.response?.answer}</Typography.Paragraph>
              {turn.response?.sql ? <pre className="sql-preview">{turn.response.sql}</pre> : null}
              {turn.response?.rows.length ? (
                <Table
                  rowKey={(_, rowIndex) => String(rowIndex)}
                  size="small"
                  pagination={false}
                  dataSource={turn.response.rows.slice(0, 8)}
                  columns={Object.keys(turn.response.rows[0]).map((key) => ({ title: key, dataIndex: key }))}
                  scroll={{ x: true }}
                />
              ) : null}
            </div>
          </div>
        ))}
        {mutation.isPending ? <Skeleton active paragraph={{ rows: 4 }} /> : null}
      </section>

      <section className="panel chat-composer">
        <Form form={form} layout="vertical" onFinish={(values) => mutation.mutate(values)}>
          <div className="chat-form-grid">
            <Form.Item label="范围" name="range">
              <DatePicker.RangePicker className="full-width" />
            </Form.Item>
            <Form.Item label="股票" name="ts_code">
              <Input placeholder="可选代码" />
            </Form.Item>
          </div>
          <Form.Item name="question" rules={[{ required: true, message: '请输入问题' }]}>
            <Input.TextArea rows={3} placeholder="输入问题" />
          </Form.Item>
          <div className="composer-actions">
            <Button type="primary" htmlType="submit" icon={<SendHorizontal size={16} />} loading={mutation.isPending}>
              发送
            </Button>
          </div>
        </Form>
      </section>
    </main>
  );
}

export default ChatPage;
