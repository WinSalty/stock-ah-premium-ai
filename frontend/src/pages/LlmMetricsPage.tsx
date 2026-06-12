import {
  Button,
  DatePicker,
  Empty,
  Input,
  Modal,
  Select,
  Skeleton,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message
} from 'antd';
import type { TableColumnsType } from 'antd';
import { CircleHelp, Copy, RotateCw, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useIsFetching, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import { fetchLlmMetricDetail, fetchLlmMetricRounds, fetchLlmMetricSummary, fetchLlmMetrics } from '../api/llmMetrics';
import type { LlmMetricItem, LlmRoundItem } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

type DateRange = [dayjs.Dayjs, dayjs.Dayjs] | null;
type MetricViewerState = {
  title: string;
  type: 'payload' | 'response';
  metricId: number;
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
  question_router: '前置路由阶段，判断问题是否属于投资研究、是否需要查结构化数据、是否需要按需补数。',
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

/**
 * "按对话轮"视图字段口径说明：与后端 /api/llm-metrics/rounds 聚合口径保持一致，
 * 用于列头帮助图标，避免使用者误读聚合数值（尤其是总耗时为求和参考值而非墙钟时间）。
 */
const roundFieldDescriptions: Record<string, string> = {
  started_at: '本轮最早阶段的开始时间，页面按东八区展示；列表按轮开始时间倒序排列。',
  question_id: '单轮问答唯一追踪 ID，仅展示前 8 位，点击复制按钮可复制完整 ID 用于精确检索。',
  phase_count: '轮内全部阶段记录数，包含路由、SQL、回答、工具执行与汇总等所有阶段。',
  llm_call_count: '外部 LLM 调用数（Agent 迭代 + 流式收尾），不含首包派生记录与工具执行。',
  tool_call_count: '轮内工具执行次数。',
  total_elapsed_ms: '轮内各阶段耗时求和（按秒展示），属于相对参考值，不等于用户真实等待的墙钟时间。',
  has_failure: '轮内任一阶段失败即标记为“含失败”，可展开该行定位具体失败阶段。'
};

interface MetricFilters {
  question_id?: string;
  provider?: string;
  model?: string;
  phase?: string;
  session_id?: string;
  user_id?: string;
  date_range?: DateRange;
}

/** 按对话轮视图的筛选条件：只保留轮级维度（追踪 ID / 会话 / 用户 / 日期范围），阶段级筛选留在阶段明细 Tab。 */
interface RoundFilters {
  question_id?: string;
  session_id?: string;
  user_id?: string;
  date_range?: DateRange;
}

/**
 * LLM 调用耗时查询页面。
 * Agent 化后一轮问答会产生多条阶段记录，页面拆成双 Tab 视图：
 * - 按对话轮（默认）：一个 question_id 聚合为一行，行内展开懒加载该轮全部阶段明细，便于按轮排查链路。
 * - 阶段明细：保留原有统计卡片、阶段级筛选与平铺明细表，作为兜底排查入口。
 * 创建日期：2026-05-05
 * author: sunshengxian
 */
function LlmMetricsPage() {
  // 当前激活视图：rounds=按对话轮聚合主视图（默认），phases=阶段明细兜底视图。
  const [activeTab, setActiveTab] = useState<'rounds' | 'phases'>('rounds');
  // payload/响应全文查看器状态：两个 Tab 共用同一个 Modal，并复用按 metric id 懒加载详情的查询。
  const [viewer, setViewer] = useState<MetricViewerState>(null);
  const queryClient = useQueryClient();
  // 分别统计两个视图的在途请求数，让头部刷新按钮的 loading 状态只跟随当前 Tab。
  const roundsFetching = useIsFetching({ queryKey: ['llm-metric-rounds'] });
  const metricsFetching = useIsFetching({ queryKey: ['llm-metrics'] });
  const summaryFetching = useIsFetching({ queryKey: ['llm-metrics-summary'] });
  // 详情按 metric id 懒加载：只有点击“查看”后才请求 payload/响应全文，列表接口不传输大字段。
  const metricDetail = useQuery({
    queryKey: ['llm-metric-detail', viewer?.metricId],
    queryFn: () => fetchLlmMetricDetail(viewer?.metricId || 0),
    enabled: Boolean(viewer?.metricId)
  });

  const refreshActiveTab = () => {
    // 刷新只作用于当前 Tab 的数据源，避免无意义地重复拉取另一个视图的接口。
    if (activeTab === 'rounds') {
      queryClient.invalidateQueries({ queryKey: ['llm-metric-rounds'] });
      return;
    }
    // 列表和摘要拆成两个请求：刷新时同时触发，但摘要慢也不阻塞表格首屏。
    queryClient.invalidateQueries({ queryKey: ['llm-metrics'] });
    queryClient.invalidateQueries({ queryKey: ['llm-metrics-summary'] });
  };

  return (
    <main className="page">
      <PageHeader
        title="LLM 耗时"
        extra={
          <Button
            title="刷新"
            icon={<RotateCw size={16} />}
            onClick={refreshActiveTab}
            loading={activeTab === 'rounds' ? roundsFetching > 0 : metricsFetching + summaryFetching > 0}
          />
        }
      />
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as 'rounds' | 'phases')}
        items={[
          { key: 'rounds', label: '按对话轮', children: <RoundMetricsTab onOpenViewer={setViewer} /> },
          { key: 'phases', label: '阶段明细', children: <PhaseMetricsTab onOpenViewer={setViewer} /> }
        ]}
      />
      <Modal
        title={viewer?.title || '指标内容'}
        open={Boolean(viewer)}
        footer={null}
        width={920}
        onCancel={() => setViewer(null)}
      >
        <MetricDetailViewer
          loading={metricDetail.isLoading}
          error={metricDetail.error}
          type={viewer?.type}
          value={
            viewer?.type === 'payload'
              ? metricDetail.data?.request_payload_json
              : metricDetail.data?.response_content
          }
        />
      </Modal>
    </main>
  );
}

/**
 * Tab1 按对话轮聚合视图（默认主视图）。
 * 聚合口径：一轮 = 一个 question_id，后端把该轮全部阶段汇总成一行并按轮起始时间倒序分页返回；
 * 行展开时复用既有 /api/llm-metrics 接口按 question_id 懒加载阶段明细，并缓存到 state，重复展开不重复请求。
 */
function RoundMetricsTab({ onOpenViewer }: { onOpenViewer: (viewer: MetricViewerState) => void }) {
  const [draftFilters, setDraftFilters] = useState<RoundFilters>({});
  const [filters, setFilters] = useState<RoundFilters>({});
  const [queryVersion, setQueryVersion] = useState(0);
  const [page, setPage] = useState(1);
  // 后端 page_size 限制为 10-100，默认 20，分页器选项与之对齐。
  const [pageSize, setPageSize] = useState(20);
  // 阶段明细缓存：key=question_id。一轮的阶段集合落库后不可变，翻页或重复展开时直接命中缓存渲染，不再请求后端。
  const [roundDetailCache, setRoundDetailCache] = useState<Record<string, LlmMetricItem[]>>({});
  // 正在懒加载阶段明细的轮次集合（question_id -> true）：用于展开区域 Spin 展示，并防止同一轮并发重复请求。
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>({});
  // 当前展开的轮次 question_id 列表：受控展开，便于在加载失败时收起该行实现“重新展开即重试”。
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([]);

  const roundParams = useMemo(
    () => ({
      question_id: filters.question_id?.trim() || undefined,
      session_id: toNumber(filters.session_id),
      user_id: toNumber(filters.user_id),
      start_date: filters.date_range?.[0]?.format('YYYY-MM-DD'),
      end_date: filters.date_range?.[1]?.format('YYYY-MM-DD')
    }),
    [filters]
  );
  const roundList = useQuery({
    queryKey: ['llm-metric-rounds', roundParams, page, pageSize, queryVersion],
    queryFn: () => fetchLlmMetricRounds({ ...roundParams, page, page_size: pageSize })
  });

  /**
   * 懒加载某一轮的阶段明细：复用既有 /api/llm-metrics 接口按 question_id 精确过滤，
   * 不取全文内容/统计摘要/精确总数（单轮阶段数有限，page_size=50 足够覆盖一轮）。
   * 失败时弹出 message.error 并收起该行；缓存未写入，重新展开会再次发起请求实现重试。
   */
  const loadRoundDetail = (questionId: string) => {
    if (roundDetailCache[questionId] || detailLoading[questionId]) {
      // 缓存命中或请求在途时直接跳过，保证“重复展开不重复请求”。
      return;
    }
    setDetailLoading((items) => ({ ...items, [questionId]: true }));
    fetchLlmMetrics({
      page: 1,
      page_size: 50,
      question_id: questionId,
      include_content: false,
      include_summary: false,
      include_total: false
    })
      .then((data) => {
        // 按落库时间正序整理阶段：展开后从上到下即一轮链路的执行顺序，便于定位耗时瓶颈与失败阶段。
        const rows = [...data.rows].sort((a, b) =>
          a.created_at === b.created_at ? a.id - b.id : a.created_at < b.created_at ? -1 : 1
        );
        setRoundDetailCache((items) => ({ ...items, [questionId]: rows }));
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : '阶段明细加载失败，请重新展开重试');
        // 失败时主动收起该行：用户重新展开即可重试，避免停留在空白展开区。
        setExpandedRowKeys((keys) => keys.filter((key) => key !== questionId));
      })
      .finally(() => {
        setDetailLoading((items) => {
          const next = { ...items };
          delete next[questionId];
          return next;
        });
      });
  };

  const handleExpand = (expanded: boolean, record: LlmRoundItem) => {
    if (!expanded) {
      setExpandedRowKeys((keys) => keys.filter((key) => key !== record.question_id));
      return;
    }
    setExpandedRowKeys((keys) => [...keys, record.question_id]);
    loadRoundDetail(record.question_id);
  };

  // 展开行内的嵌套阶段明细列：复用阶段明细视图的核心列子集与“查看”详情交互。
  const phaseColumns = useMemo(() => buildRoundPhaseColumns(onOpenViewer), [onOpenViewer]);

  const columns = useMemo<TableColumnsType<LlmRoundItem>>(
    () => [
      {
        title: <HelpTitle label="开始时间" help={roundFieldDescriptions.started_at} />,
        dataIndex: 'started_at',
        width: 188,
        render: (value: string) => (
          <Typography.Text className="llm-metric-time">
            {formatEast8DateTime(value, { naiveAsEast8: true })}
          </Typography.Text>
        )
      },
      {
        title: <HelpTitle label="用户" help={fieldDescriptions.user_name} />,
        dataIndex: 'user_name',
        width: 120,
        render: renderText
      },
      {
        title: <HelpTitle label="对话标题" help={fieldDescriptions.conversation_title} />,
        dataIndex: 'conversation_title',
        width: 260,
        // 单元格内截断展示，悬浮 Tooltip 查看完整标题；showTitle 关闭原生 title 避免双重提示。
        ellipsis: { showTitle: false },
        render: (value: string | null) =>
          value ? (
            <Tooltip title={value} placement="topLeft">
              {value}
            </Tooltip>
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          )
      },
      {
        title: <HelpTitle label="追踪 ID" help={roundFieldDescriptions.question_id} />,
        dataIndex: 'question_id',
        width: 140,
        render: (value: string) => (
          <Space size={4}>
            <Tooltip title={value}>
              <Typography.Text>{value.slice(0, 8)}</Typography.Text>
            </Tooltip>
            <Tooltip title="复制完整追踪 ID">
              <Button type="text" size="small" icon={<Copy size={13} />} onClick={() => copyQuestionId(value)} />
            </Tooltip>
          </Space>
        )
      },
      {
        title: <HelpTitle label="阶段数" help={roundFieldDescriptions.phase_count} />,
        dataIndex: 'phase_count',
        width: 92,
        align: 'right',
        render: renderCount
      },
      {
        title: <HelpTitle label="LLM 调用" help={roundFieldDescriptions.llm_call_count} />,
        dataIndex: 'llm_call_count',
        width: 104,
        align: 'right',
        render: renderCount
      },
      {
        title: <HelpTitle label="工具执行" help={roundFieldDescriptions.tool_call_count} />,
        dataIndex: 'tool_call_count',
        width: 104,
        align: 'right',
        render: renderCount
      },
      {
        title: <HelpTitle label="总耗时(s)" help={roundFieldDescriptions.total_elapsed_ms} />,
        dataIndex: 'total_elapsed_ms',
        width: 110,
        align: 'right',
        render: (value: number | null) => <Typography.Text>{formatSeconds(value)}</Typography.Text>
      },
      {
        title: <HelpTitle label="状态" help={roundFieldDescriptions.has_failure} />,
        dataIndex: 'has_failure',
        width: 96,
        render: (value: boolean) => <Tag color={value ? 'red' : 'green'}>{value ? '含失败' : '正常'}</Tag>
      }
    ],
    []
  );

  const applyFilters = () => {
    // 查询按钮代表一次显式提交：即使条件未变化也强制刷新；同时收起展开行，避免旧展开状态跨筛选残留。
    setFilters({ ...draftFilters });
    setPage(1);
    setExpandedRowKeys([]);
    setQueryVersion((version) => version + 1);
  };

  const resetFilters = () => {
    setDraftFilters({});
    setFilters({});
    setPage(1);
    setExpandedRowKeys([]);
    setQueryVersion((version) => version + 1);
  };

  return (
    <>
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
            <div className="panel-title">对话轮列表</div>
            <Typography.Text type="secondary">
              一轮问答（一个追踪 ID）聚合为一行，按轮开始时间倒序；点击行首箭头展开查看该轮全部阶段明细。
            </Typography.Text>
          </div>
          <Tag color="blue">{roundList.data?.total ?? 0} 轮</Tag>
        </div>
        <Table<LlmRoundItem>
          className="llm-metric-table"
          rowKey="question_id"
          loading={roundList.isLoading || roundList.isFetching}
          dataSource={roundList.data?.rows || []}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 1260 }}
          expandable={{
            expandedRowKeys,
            onExpand: handleExpand,
            expandedRowRender: (record) =>
              detailLoading[record.question_id] ? (
                // 阶段明细懒加载中：展开区域先展示 Spin，加载完成后替换为嵌套阶段表格。
                <div style={{ padding: '16px 0', textAlign: 'center' }}>
                  <Spin />
                </div>
              ) : (
                <Table<LlmMetricItem>
                  rowKey="id"
                  size="small"
                  columns={phaseColumns}
                  dataSource={roundDetailCache[record.question_id] || []}
                  pagination={false}
                  locale={{
                    emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该轮暂无阶段明细" />
                  }}
                  scroll={{ x: 1190 }}
                />
              )
          }}
          pagination={{
            current: page,
            pageSize,
            total: roundList.data?.total ?? 0,
            showSizeChanger: true,
            // 分页大小选项与后端 page_size 限制（10-100）对齐。
            pageSizeOptions: [10, 20, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
              // 翻页后收起展开行；已加载的明细缓存保留，翻回原页重复展开仍命中缓存。
              setExpandedRowKeys([]);
            }
          }}
        />
      </section>
    </>
  );
}

/**
 * Tab2 阶段明细视图：保留原有统计卡片、全部阶段级筛选（provider/model/phase 等）与平铺明细表，
 * 作为兜底排查入口；payload/响应全文查看通过 onOpenViewer 复用页面级共享 Modal。
 */
function PhaseMetricsTab({ onOpenViewer }: { onOpenViewer: (viewer: MetricViewerState) => void }) {
  const [draftFilters, setDraftFilters] = useState<MetricFilters>({});
  const [filters, setFilters] = useState<MetricFilters>({});
  const [queryVersion, setQueryVersion] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);
  const metricParams = useMemo(
    () => ({
      question_id: filters.question_id?.trim() || undefined,
      provider: filters.provider,
      model: filters.model,
      phase: filters.phase,
      session_id: toNumber(filters.session_id),
      user_id: toNumber(filters.user_id),
      start_date: filters.date_range?.[0]?.format('YYYY-MM-DD'),
      end_date: filters.date_range?.[1]?.format('YYYY-MM-DD')
    }),
    [filters]
  );
  const metricList = useQuery({
    queryKey: ['llm-metrics', metricParams, page, pageSize, queryVersion],
    queryFn: () =>
      fetchLlmMetrics({
        ...metricParams,
        page,
        page_size: pageSize,
        include_summary: false,
        include_total: false,
        include_content: false
      })
  });
  const metricSummary = useQuery({
    queryKey: ['llm-metrics-summary', metricParams, queryVersion],
    queryFn: () => fetchLlmMetricSummary(metricParams)
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
          record.request_payload_size > 0 ? (
            <Button
              size="small"
              onClick={() =>
                onOpenViewer({
                  title: `${record.phase_label || record.phase} 请求参数`,
                  type: 'payload',
                  metricId: record.id
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
          record.response_content_size > 0 ? (
            <Button
              size="small"
              onClick={() =>
                onOpenViewer({
                  title: `${record.phase_label || record.phase} 响应内容`,
                  type: 'response',
                  metricId: record.id
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
    // 列定义依赖外部传入的查看器回调：回调变化时同步重建“查看”按钮的点击行为。
    [onOpenViewer]
  );

  const applyFilters = () => {
    // 查询按钮代表一次显式提交：即使筛选条件和页码未变化，也要刷新指标排查最新链路。
    setFilters({ ...draftFilters });
    setPage(1);
    setQueryVersion((version) => version + 1);
  };

  const resetFilters = () => {
    setDraftFilters({});
    setFilters({});
    setPage(1);
    setQueryVersion((version) => version + 1);
  };

  return (
    <>
      <section className="metrics-summary-grid">
        <MetricCard
          label="调用阶段"
          value={metricSummary.data?.total ?? 0}
          help={summaryDescriptions.total}
          loading={metricSummary.isLoading}
        />
        <MetricCard
          label="成功阶段"
          value={metricSummary.data?.success_count ?? 0}
          help={summaryDescriptions.success_count}
          loading={metricSummary.isLoading}
        />
        <MetricCard
          label="平均耗时"
          value={formatMs(metricSummary.data?.avg_elapsed_ms)}
          help={summaryDescriptions.avg_elapsed_ms}
          loading={metricSummary.isLoading}
        />
        <MetricCard
          label="最大耗时"
          value={formatMs(metricSummary.data?.max_elapsed_ms)}
          help={summaryDescriptions.max_elapsed_ms}
          loading={metricSummary.isLoading}
        />
        <MetricCard
          label="平均首包"
          value={formatMs(metricSummary.data?.avg_first_chunk_ms)}
          help={summaryDescriptions.avg_first_chunk_ms}
          loading={metricSummary.isLoading}
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
          <Tag color="blue">{formatTotalTag(metricSummary.data?.total, metricList.data?.total_exact, metricList.data?.total)}</Tag>
        </div>
        <Table<LlmMetricItem>
          className="llm-metric-table"
          rowKey="id"
          loading={metricList.isLoading || metricList.isFetching}
          dataSource={metricList.data?.rows || []}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 2210 }}
          pagination={{
            current: page,
            pageSize,
            total: metricSummary.data?.total ?? metricList.data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [20, 30, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            }
          }}
        />
      </section>
    </>
  );
}

function MetricDetailViewer({
  loading,
  error,
  type,
  value
}: {
  loading: boolean;
  error: unknown;
  type?: 'payload' | 'response';
  value?: string | null;
}) {
  if (loading) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }
  if (error) {
    return <Typography.Text type="danger">内容加载失败，请稍后重试。</Typography.Text>;
  }
  return type === 'payload' ? <PayloadViewer value={value} /> : <ResponseViewer value={value} />;
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

function MetricCard({
  label,
  value,
  help,
  loading
}: {
  label: string;
  value: string | number;
  help: string;
  loading?: boolean;
}) {
  return (
    <div className="metric-card">
      <Typography.Text type="secondary">
        <HelpTitle label={label} help={help} />
      </Typography.Text>
      {loading ? <Skeleton.Input active size="small" className="metric-card-skeleton" /> : <strong>{value}</strong>}
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

/**
 * 把毫秒耗时换算成秒展示（保留两位小数）：用于轮级"总耗时(s)"列统一量纲；空值显示 -。
 * 注意该值是轮内阶段耗时求和的相对参考值，不代表用户真实等待的墙钟时间。
 */
function formatSeconds(value?: number | null) {
  if (value === null || value === undefined) {
    return '-';
  }
  return `${(value / 1000).toFixed(2)}s`;
}

/**
 * 一键复制完整追踪 ID：列表内只截断展示前 8 位，复制时写入完整值，便于粘贴到筛选框或日志检索。
 * 剪贴板写入失败（如非安全上下文）时给出错误提示，不中断页面操作。
 */
function copyQuestionId(value: string) {
  navigator.clipboard
    .writeText(value)
    .then(() => message.success('已复制追踪 ID'))
    .catch(() => message.error('复制失败'));
}

/**
 * 构建"按对话轮"展开行内的嵌套阶段明细列：复用阶段明细视图的核心列子集
 * （阶段/来源/模型/状态/耗时/首包/输出字符/时间/查看），渲染函数与字段口径说明全部复用既有实现；
 * "查看"按钮通过 onOpenViewer 打开页面级共享 Modal，复用按 metric id 懒加载 payload/响应全文的交互。
 */
function buildRoundPhaseColumns(
  onOpenViewer: (viewer: MetricViewerState) => void
): TableColumnsType<LlmMetricItem> {
  return [
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
      width: 104,
      align: 'right',
      render: renderMs
    },
    {
      title: <HelpTitle label="首包" help={fieldDescriptions.first_chunk_ms} />,
      dataIndex: 'first_chunk_ms',
      width: 104,
      align: 'right',
      render: renderMs
    },
    {
      title: <HelpTitle label="输出字符" help={fieldDescriptions.output_chars} />,
      dataIndex: 'output_chars',
      width: 100,
      align: 'right',
      render: renderCount
    },
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
      title: '查看',
      key: 'detail-actions',
      width: 134,
      render: (_value: unknown, record) => {
        // 只有后端标记存在 payload/响应内容时才渲染按钮；两者皆无时显示占位符。
        const hasPayload = record.request_payload_size > 0;
        const hasResponse = record.response_content_size > 0;
        if (!hasPayload && !hasResponse) {
          return <Typography.Text type="secondary">-</Typography.Text>;
        }
        return (
          <Space size={4}>
            {hasPayload ? (
              <Button
                size="small"
                onClick={() =>
                  onOpenViewer({
                    title: `${record.phase_label || record.phase} 请求参数`,
                    type: 'payload',
                    metricId: record.id
                  })
                }
              >
                参数
              </Button>
            ) : null}
            {hasResponse ? (
              <Button
                size="small"
                onClick={() =>
                  onOpenViewer({
                    title: `${record.phase_label || record.phase} 响应内容`,
                    type: 'response',
                    metricId: record.id
                  })
                }
              >
                响应
              </Button>
            ) : null}
          </Space>
        );
      }
    }
  ];
}

function formatTotalTag(exactTotal?: number, listTotalExact?: boolean, listTotal?: number) {
  if (exactTotal !== undefined) {
    return `${exactTotal} 条`;
  }
  if (listTotalExact === false && listTotal !== undefined) {
    return `${listTotal}+ 条`;
  }
  return `${listTotal ?? 0} 条`;
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
