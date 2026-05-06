import { Button, DatePicker, Empty, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { CircleHelp, RotateCw, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import { fetchLlmMetrics } from '../api/llmMetrics';
import type { LlmMetricItem } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

type DateRange = [dayjs.Dayjs, dayjs.Dayjs] | null;
type MetricViewerState = {
  title: string;
  type: 'payload' | 'response';
  value?: string | null;
} | null;

interface LlmPayloadMessage {
  role?: string;
  content?: unknown;
  [key: string]: unknown;
}

interface LlmRequestPayload {
  model?: string;
  temperature?: number;
  stream?: boolean;
  messages?: LlmPayloadMessage[];
  [key: string]: unknown;
}

const providerOptions = ['Qwen', 'DeepSeek', 'Database', 'Internal'].map((item) => ({
  label: item,
  value: item
}));

const phaseDescriptions: Record<string, string> = {
  question_router: '前置路由阶段，判断问题是否属于投资研究、是否需要查结构化数据、是否需要读取知识库。',
  generate_sql: 'SQL 生成阶段，仅在问题需要精确结构化数据时调用外部模型生成只读查询。',
  repair_sql: 'SQL 修复阶段，仅在生成的 SQL 字段或语法执行失败时触发一次修复。',
  execute_sql: '数据库执行阶段，不调用 LLM；row_count 表示实际返回给回答链路的数据行数。',
  answer: '非流式回答阶段，用于 AI 阈值推荐等一次性返回场景；output_chars 表示模型回答字符数。',
  answer_stream_first_chunk: '流式回答首包记录，只记录 first_chunk_ms；其它计数字段通常为 0。',
  answer_stream: '流式回答主体完成记录；chunk_count 是流式片段数，output_chars 是累计输出字符数。',
  stream_done: '整轮流式问答总耗时汇总；row_count 是本轮用于回答的数据行数。',
  sync_done: '整轮非流式问答总耗时汇总；常见于阈值推荐等非流式调用。',
  sync_intro: '非流式问候或能力介绍快路径，本地直接返回，不调用外部模型。',
  stream_intro: '流式问候或能力介绍快路径，本地直接返回，不调用外部模型。',
  stream_out_of_scope: '流式越界问题快路径，本地直接返回范围提示，不调用外部模型。',
  sync_out_of_scope: '非流式越界问题快路径，本地直接返回范围提示，不调用外部模型。',
  stream_not_configured: '流式模型未配置时的本地返回记录。',
  sync_not_configured: '非流式模型未配置时的本地返回记录。'
};

const phaseOptions = [
  'question_router',
  'generate_sql',
  'repair_sql',
  'execute_sql',
  'answer',
  'answer_stream_first_chunk',
  'answer_stream',
  'stream_done',
  'sync_done',
  'sync_intro',
  'stream_intro',
  'stream_out_of_scope',
  'sync_out_of_scope',
  'stream_not_configured',
  'sync_not_configured'
].map((item) => ({ label: `${item} - ${phaseDescriptions[item] || '阶段记录'}`, value: item }));

const fieldDescriptions: Record<string, string> = {
  created_at: '该阶段指标落库时间，页面按东八区展示。',
  conversation_title: '本轮对话标题，由用户提问清洗并截取前 48 个字符生成，便于快速识别问题主题。',
  question_id: '单轮问答唯一追踪 ID；一轮问答会产生多条不同阶段记录，重复提问也会生成新的 ID。',
  phase: '阶段流水名称。不同阶段采集口径不同，因此某些计数字段在该阶段为 0 是正常现象。',
  provider: '调用来源：Qwen/DeepSeek 是外部模型，Database 是数据库执行，Internal 是本地快路径或整轮汇总。',
  model: '本阶段使用的模型。数据库执行和本地阶段可能没有具体模型。',
  success: '该阶段是否成功落地指标；失败时可查看错误字段。',
  elapsed_ms: '该阶段耗时。外部模型阶段表示模型调用耗时，Database 表示 SQL 执行耗时，Internal 表示整轮或快路径耗时。',
  first_chunk_ms: '流式回答从请求发出到收到首个内容片段的时间；非流式、SQL、汇总阶段通常为空。',
  row_count: '该阶段关联的数据行数。主要在 execute_sql、stream_done、sync_done 有意义，其它阶段常为 0。',
  chunk_count: '流式回答片段数量。只有 answer_stream 完成记录通常有值，其它阶段为 0。',
  output_chars: '模型输出字符数。回答类阶段有意义；SQL 执行、首包、整轮汇总等阶段通常为 0。',
  request_payload_json: '实际发送给 OpenAI-compatible 接口的请求 JSON，包括模型、messages、temperature 和 stream，不包含 Authorization 或 API Key。',
  response_content: '大模型返回的原始响应内容。流式回答只在 answer_stream 完成记录保存拼接后的完整内容。',
  user_name: '系统用户展示名称；优先使用展示名称，没有展示名称时使用登录名。',
  session_id: '聊天会话 ID；后台任务或无会话上下文时为空。',
  user_id: '系统用户 ID；无用户上下文时为空。',
  error_message: '阶段失败时记录的错误摘要，最多保留后端截断后的内容。'
};

const summaryDescriptions: Record<string, string> = {
  total: '当前筛选条件下的阶段记录总数，不等于问题总数；一轮问答可能包含多条阶段记录。',
  success_count: '当前筛选条件下 success=true 的阶段数。',
  avg_elapsed_ms: '对非空 elapsed_ms 求平均；没有耗时采集的阶段不会参与平均。',
  max_elapsed_ms: '当前筛选条件下最大的阶段耗时。',
  avg_first_chunk_ms: '只对有首包时间的流式阶段求平均；非流式调用不参与，所以无流式数据时会显示 -。'
};

const modelOptions = [
  'qwen3.6-flash',
  'deepseek-v4-flash',
  'deepseek-v4-pro'
].map((item) => ({ label: item, value: item }));

interface MetricFilters {
  question_id?: string;
  provider?: string;
  model?: string;
  phase?: string;
  session_id?: string;
  user_id?: string;
  date_range?: DateRange;
}

/**
 * LLM 调用耗时查询页面。
 * 创建日期：2026-05-05
 * author: sunshengxian
 */
function LlmMetricsPage() {
  const [draftFilters, setDraftFilters] = useState<MetricFilters>({});
  const [filters, setFilters] = useState<MetricFilters>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);
  const [viewer, setViewer] = useState<MetricViewerState>(null);
  const metrics = useQuery({
    queryKey: ['llm-metrics', filters, page, pageSize],
    queryFn: () =>
      fetchLlmMetrics({
        page,
        page_size: pageSize,
        question_id: filters.question_id?.trim() || undefined,
        provider: filters.provider,
        model: filters.model,
        phase: filters.phase,
        session_id: toNumber(filters.session_id),
        user_id: toNumber(filters.user_id),
        start_date: filters.date_range?.[0]?.format('YYYY-MM-DD'),
        end_date: filters.date_range?.[1]?.format('YYYY-MM-DD')
      })
  });

  const columns = useMemo<TableColumnsType<LlmMetricItem>>(
    () => [
      {
        title: <HelpTitle label="时间" help={fieldDescriptions.created_at} />,
        dataIndex: 'created_at',
        width: 188,
        render: (value: string) => (
          <Typography.Text className="llm-metric-time">
            {formatEast8DateTime(value, { naiveAsEast8: true })}
          </Typography.Text>
        )
      },
      {
        title: <HelpTitle label="对话标题" help={fieldDescriptions.conversation_title} />,
        dataIndex: 'conversation_title',
        width: 220,
        ellipsis: true,
        render: renderText
      },
      { title: <HelpTitle label="追踪 ID" help={fieldDescriptions.question_id} />, dataIndex: 'question_id', width: 112 },
      {
        title: <HelpTitle label="阶段" help={fieldDescriptions.phase} />,
        dataIndex: 'phase',
        width: 210,
        render: (_value: string, record) => renderPhase(record)
      },
      { title: <HelpTitle label="来源" help={fieldDescriptions.provider} />, dataIndex: 'provider', width: 96, render: renderTag },
      { title: <HelpTitle label="模型" help={fieldDescriptions.model} />, dataIndex: 'model', width: 170, render: renderText },
      {
        title: <HelpTitle label="状态" help={fieldDescriptions.success} />,
        dataIndex: 'success',
        width: 84,
        render: (value: boolean) => <Tag color={value ? 'blue' : 'red'}>{value ? '成功' : '失败'}</Tag>
      },
      {
        title: <HelpTitle label="耗时" help={fieldDescriptions.elapsed_ms} />,
        dataIndex: 'elapsed_ms',
        width: 108,
        align: 'right',
        render: renderMs
      },
      {
        title: <HelpTitle label="参数" help={fieldDescriptions.request_payload_json} />,
        dataIndex: 'request_payload_json',
        width: 92,
        render: (_value: string | null, record) =>
          record.request_payload_json ? (
            <Button
              size="small"
              onClick={() =>
                setViewer({
                  title: `${record.phase_label || record.phase} 请求参数`,
                  type: 'payload',
                  value: record.request_payload_json
                })
              }
            >
              查看
            </Button>
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          )
      },
      {
        title: <HelpTitle label="响应" help={fieldDescriptions.response_content} />,
        dataIndex: 'response_content',
        width: 92,
        render: (_value: string | null, record) =>
          record.response_content ? (
            <Button
              size="small"
              onClick={() =>
                setViewer({
                  title: `${record.phase_label || record.phase} 响应内容`,
                  type: 'response',
                  value: record.response_content
                })
              }
            >
              查看
            </Button>
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          )
      },
      {
        title: <HelpTitle label="用户名称" help={fieldDescriptions.user_name} />,
        dataIndex: 'user_name',
        width: 130,
        render: renderText
      },
      {
        title: <HelpTitle label="首包" help={fieldDescriptions.first_chunk_ms} />,
        dataIndex: 'first_chunk_ms',
        width: 108,
        align: 'right',
        render: renderMs
      },
      {
        title: <HelpTitle label="行数" help={fieldDescriptions.row_count} />,
        dataIndex: 'row_count',
        width: 86,
        align: 'right',
        render: renderCount
      },
      {
        title: <HelpTitle label="Chunk" help={fieldDescriptions.chunk_count} />,
        dataIndex: 'chunk_count',
        width: 92,
        align: 'right',
        render: renderCount
      },
      {
        title: <HelpTitle label="字符" help={fieldDescriptions.output_chars} />,
        dataIndex: 'output_chars',
        width: 86,
        align: 'right',
        render: renderCount
      },
      { title: <HelpTitle label="会话" help={fieldDescriptions.session_id} />, dataIndex: 'session_id', width: 86, render: renderText },
      { title: <HelpTitle label="用户" help={fieldDescriptions.user_id} />, dataIndex: 'user_id', width: 86, render: renderText },
      { title: <HelpTitle label="错误" help={fieldDescriptions.error_message} />, dataIndex: 'error_message', width: 220, ellipsis: true, render: renderText }
    ],
    []
  );

  const applyFilters = () => {
    setFilters(draftFilters);
    setPage(1);
  };

  const resetFilters = () => {
    setDraftFilters({});
    setFilters({});
    setPage(1);
  };

  return (
    <main className="page">
      <PageHeader
        title="LLM 耗时"
        extra={
          <Button
            title="刷新"
            icon={<RotateCw size={16} />}
            onClick={() => metrics.refetch()}
            loading={metrics.isFetching}
          />
        }
      />

      <section className="metrics-summary-grid">
        <MetricCard label="调用阶段" value={metrics.data?.summary.total ?? 0} help={summaryDescriptions.total} />
        <MetricCard
          label="成功阶段"
          value={metrics.data?.summary.success_count ?? 0}
          help={summaryDescriptions.success_count}
        />
        <MetricCard
          label="平均耗时"
          value={formatMs(metrics.data?.summary.avg_elapsed_ms)}
          help={summaryDescriptions.avg_elapsed_ms}
        />
        <MetricCard
          label="最大耗时"
          value={formatMs(metrics.data?.summary.max_elapsed_ms)}
          help={summaryDescriptions.max_elapsed_ms}
        />
        <MetricCard
          label="平均首包"
          value={formatMs(metrics.data?.summary.avg_first_chunk_ms)}
          help={summaryDescriptions.avg_first_chunk_ms}
        />
      </section>

      <section className="panel">
        <div className="llm-metric-filter-grid">
          <FilterInput
            label="追踪 ID"
            value={draftFilters.question_id}
            placeholder="question_id"
            onChange={(value) => setDraftFilters((items) => ({ ...items, question_id: value }))}
            onPressEnter={applyFilters}
          />
          <FilterInput
            label="会话 ID"
            value={draftFilters.session_id}
            placeholder="session_id"
            onChange={(value) => setDraftFilters((items) => ({ ...items, session_id: value }))}
            onPressEnter={applyFilters}
          />
          <FilterInput
            label="用户 ID"
            value={draftFilters.user_id}
            placeholder="user_id"
            onChange={(value) => setDraftFilters((items) => ({ ...items, user_id: value }))}
            onPressEnter={applyFilters}
          />
          <div>
            <Typography.Text className="field-label">来源</Typography.Text>
            <Select
              allowClear
              className="full-width"
              value={draftFilters.provider}
              options={providerOptions}
              onChange={(value) => setDraftFilters((items) => ({ ...items, provider: value }))}
            />
          </div>
          <div>
            <Typography.Text className="field-label">模型</Typography.Text>
            <Select
              allowClear
              className="full-width"
              value={draftFilters.model}
              options={modelOptions}
              onChange={(value) => setDraftFilters((items) => ({ ...items, model: value }))}
            />
          </div>
          <div>
            <Typography.Text className="field-label">阶段</Typography.Text>
            <Select
              allowClear
              showSearch
              className="full-width"
              value={draftFilters.phase}
              options={phaseOptions}
              onChange={(value) => setDraftFilters((items) => ({ ...items, phase: value }))}
            />
          </div>
          <div>
            <Typography.Text className="field-label">日期范围</Typography.Text>
            <DatePicker.RangePicker
              className="full-width"
              value={draftFilters.date_range || null}
              onChange={(value) =>
                setDraftFilters((items) => ({ ...items, date_range: value as DateRange }))
              }
            />
          </div>
          <Space className="query-actions">
            <Button type="primary" icon={<Search size={16} />} onClick={applyFilters}>
              查询
            </Button>
            <Button icon={<X size={16} />} onClick={resetFilters}>
              清空
            </Button>
          </Space>
        </div>
      </section>

      <section className="panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">调用明细</div>
            <Typography.Text type="secondary">
              按阶段记录路由、SQL、回答、流式首包和整轮耗时；计数字段只在对应阶段有意义。
            </Typography.Text>
          </div>
          <Tag color="blue">{metrics.data?.total ?? 0} 条</Tag>
        </div>
        <Table<LlmMetricItem>
          className="llm-metric-table"
          rowKey="id"
          loading={metrics.isLoading || metrics.isFetching}
          dataSource={metrics.data?.rows || []}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 2210 }}
          pagination={{
            current: page,
            pageSize,
            total: metrics.data?.total || 0,
            showSizeChanger: true,
            pageSizeOptions: [20, 30, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            }
          }}
        />
      </section>
      <Modal
        title={viewer?.title || '指标内容'}
        open={Boolean(viewer)}
        footer={null}
        width={920}
        onCancel={() => setViewer(null)}
      >
        {viewer?.type === 'payload' ? <PayloadViewer value={viewer.value} /> : <ResponseViewer value={viewer?.value} />}
      </Modal>
    </main>
  );
}

function HelpTitle({ label, help }: { label: string; help: string }) {
  return (
    <span className="help-title">
      <span>{label}</span>
      <Tooltip title={help}>
        <CircleHelp size={13} className="help-title-icon" />
      </Tooltip>
    </span>
  );
}

function MetricCard({ label, value, help }: { label: string; value: string | number; help: string }) {
  return (
    <div className="metric-card">
      <Typography.Text type="secondary">
        <HelpTitle label={label} help={help} />
      </Typography.Text>
      <strong>{value}</strong>
    </div>
  );
}

function PayloadViewer({ value }: { value?: string | null }) {
  const payload = parsePayload(value);
  if (!value) {
    return <Typography.Text type="secondary">无请求参数</Typography.Text>;
  }
  if (!payload) {
    return <pre className="llm-payload-viewer">{value}</pre>;
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const extraPayload = Object.fromEntries(
    Object.entries(payload).filter(([key]) => !['model', 'messages', 'temperature', 'stream'].includes(key))
  );
  return (
    <div className="llm-payload-viewer">
      <div className="llm-payload-summary">
        <PayloadMeta label="模型" value={payload.model || '-'} />
        <PayloadMeta label="温度" value={payload.temperature ?? '-'} />
        <PayloadMeta label="流式" value={payload.stream === undefined ? '否' : payload.stream ? '是' : '否'} />
        <PayloadMeta label="消息数" value={messages.length} />
      </div>
      {messages.length ? (
        <div className="llm-payload-jumpbar">
          {messages.map((messageItem, index) => (
            <Button
              key={`${messageItem.role || 'message'}-jump-${index}`}
              size="small"
              onClick={() => scrollPayloadMessage(index)}
            >
              #{index + 1} {formatRoleName(messageItem.role)}
            </Button>
          ))}
        </div>
      ) : null}
      {messages.map((messageItem, index) => (
        <div
          className="llm-payload-message"
          id={payloadMessageId(index)}
          key={`${messageItem.role || 'message'}-${index}`}
        >
          <div className="llm-payload-message-head">
            <Tag>{formatRoleName(messageItem.role)}</Tag>
            <Typography.Text type="secondary">#{index + 1}</Typography.Text>
          </div>
          <pre>{formatPayloadValue(messageItem.content)}</pre>
          {renderMessageExtra(messageItem)}
        </div>
      ))}
      {Object.keys(extraPayload).length ? (
        <div className="llm-payload-message">
          <div className="llm-payload-message-head">
            <Tag>其他参数</Tag>
          </div>
          <pre>{JSON.stringify(extraPayload, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}

function ResponseViewer({ value }: { value?: string | null }) {
  if (!value) {
    return <Typography.Text type="secondary">无响应内容</Typography.Text>;
  }
  return <pre className="llm-content-viewer">{tryFormatJsonText(value)}</pre>;
}

function PayloadMeta({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="llm-payload-meta">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <strong>{value}</strong>
    </span>
  );
}

function renderMessageExtra(messageItem: LlmPayloadMessage) {
  const extra = Object.fromEntries(Object.entries(messageItem).filter(([key]) => !['role', 'content'].includes(key)));
  if (!Object.keys(extra).length) {
    return null;
  }
  return (
    <div className="llm-payload-extra">
      <Typography.Text type="secondary">消息附加参数</Typography.Text>
      <pre>{JSON.stringify(extra, null, 2)}</pre>
    </div>
  );
}

function payloadMessageId(index: number) {
  return `llm-payload-message-${index}`;
}

function scrollPayloadMessage(index: number) {
  document.getElementById(payloadMessageId(index))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function formatRoleName(role?: string) {
  const roleNames: Record<string, string> = {
    system: 'system 系统',
    user: 'user 用户',
    assistant: 'assistant 助手',
    tool: 'tool 工具'
  };
  if (!role) {
    return 'message';
  }
  return roleNames[role] || role;
}

function FilterInput({
  label,
  value,
  placeholder,
  onChange,
  onPressEnter
}: {
  label: string;
  value?: string;
  placeholder: string;
  onChange: (value: string) => void;
  onPressEnter: () => void;
}) {
  return (
    <div>
      <Typography.Text className="field-label">{label}</Typography.Text>
      <Input
        allowClear
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onPressEnter={onPressEnter}
      />
    </div>
  );
}

function toNumber(value?: string) {
  const normalized = value?.trim();
  if (!normalized) {
    return undefined;
  }
  const numberValue = Number(normalized);
  return Number.isFinite(numberValue) ? numberValue : undefined;
}

function renderMs(value: number | null | undefined) {
  return <Typography.Text>{formatMs(value)}</Typography.Text>;
}

function renderCount(value: number | null | undefined) {
  return <Typography.Text>{value ?? 0}</Typography.Text>;
}

function renderPhase(record: LlmMetricItem) {
  if (!record.phase) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  const description = record.phase_description || phaseDescriptions[record.phase] || '阶段记录';
  return (
    <Tooltip title={description}>
      <span className="phase-cell">
        <Typography.Text>{record.phase_label || record.phase}</Typography.Text>
        <Typography.Text type="secondary">{record.phase}</Typography.Text>
      </span>
    </Tooltip>
  );
}

function renderText(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  return <Typography.Text>{value}</Typography.Text>;
}

function renderTag(value: string | null | undefined) {
  if (!value) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  return <Tag>{value}</Tag>;
}

function formatMs(value?: number | null) {
  if (value === null || value === undefined) {
    return '-';
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}s`;
  }
  return `${value.toFixed(1)}ms`;
}

function parsePayload(value?: string | null): LlmRequestPayload | null {
  if (!value) {
    return null;
  }
  try {
    const payload = JSON.parse(value);
    return payload && typeof payload === 'object' ? (payload as LlmRequestPayload) : null;
  } catch {
    return null;
  }
}

function formatPayloadValue(value: unknown) {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return tryFormatJsonText(value);
  }
  return JSON.stringify(value, null, 2);
}

function tryFormatJsonText(value: string) {
  const normalized = value.trim();
  if (!normalized || !['{', '['].includes(normalized[0])) {
    return value;
  }
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export default LlmMetricsPage;
