import { Button, DatePicker, Empty, Input, Select, Space, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { RotateCw, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import { fetchLlmMetrics } from '../api/llmMetrics';
import type { LlmMetricItem } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

type DateRange = [dayjs.Dayjs, dayjs.Dayjs] | null;

const providerOptions = ['Qwen', 'DeepSeek', 'Database', 'Internal'].map((item) => ({
  label: item,
  value: item
}));

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
  'stream_out_of_scope'
].map((item) => ({ label: item, value: item }));

const modelOptions = [
  'qwen3.6-flash',
  'qwen3.6-max-preview',
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
        title: '时间',
        dataIndex: 'created_at',
        width: 168,
        render: (value: string) => formatEast8DateTime(value, { naiveAsEast8: true })
      },
      { title: '追踪 ID', dataIndex: 'question_id', width: 112 },
      { title: '阶段', dataIndex: 'phase', width: 172 },
      { title: '来源', dataIndex: 'provider', width: 96, render: renderTag },
      { title: '模型', dataIndex: 'model', width: 170, render: renderText },
      {
        title: '状态',
        dataIndex: 'success',
        width: 84,
        render: (value: boolean) => <Tag color={value ? 'blue' : 'red'}>{value ? '成功' : '失败'}</Tag>
      },
      {
        title: '耗时',
        dataIndex: 'elapsed_ms',
        width: 108,
        align: 'right',
        render: renderMs
      },
      {
        title: '首包',
        dataIndex: 'first_chunk_ms',
        width: 108,
        align: 'right',
        render: renderMs
      },
      { title: '行数', dataIndex: 'row_count', width: 86, align: 'right' },
      { title: 'Chunk', dataIndex: 'chunk_count', width: 86, align: 'right' },
      { title: '字符', dataIndex: 'output_chars', width: 86, align: 'right' },
      { title: '会话', dataIndex: 'session_id', width: 86, render: renderText },
      { title: '用户', dataIndex: 'user_id', width: 86, render: renderText },
      { title: '错误', dataIndex: 'error_message', width: 220, ellipsis: true, render: renderText }
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
        <MetricCard label="调用阶段" value={metrics.data?.summary.total ?? 0} />
        <MetricCard label="成功阶段" value={metrics.data?.summary.success_count ?? 0} />
        <MetricCard label="平均耗时" value={formatMs(metrics.data?.summary.avg_elapsed_ms)} />
        <MetricCard label="最大耗时" value={formatMs(metrics.data?.summary.max_elapsed_ms)} />
        <MetricCard label="平均首包" value={formatMs(metrics.data?.summary.avg_first_chunk_ms)} />
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
            <Typography.Text type="secondary">按阶段记录分类、SQL、回答和流式首包耗时</Typography.Text>
          </div>
          <Tag color="blue">{metrics.data?.total ?? 0} 条</Tag>
        </div>
        <Table<LlmMetricItem>
          rowKey="id"
          loading={metrics.isLoading || metrics.isFetching}
          dataSource={metrics.data?.rows || []}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 1540 }}
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
    </main>
  );
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric-card">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <strong>{value}</strong>
    </div>
  );
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

export default LlmMetricsPage;
