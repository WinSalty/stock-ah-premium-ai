import {
  Alert,
  Button,
  Checkbox,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popover,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message
} from 'antd';
import { FileUp, Play, RotateCw } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { useMemo, useState } from 'react';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import {
  createAhPremiumSyncBatch,
  createDividendReinvestmentSyncBatch,
  createSyncRun,
  fetchDatasets,
  fetchSyncRuns
} from '../api/sync';
import type {
  DatasetInfo,
  DividendReinvestmentSyncBatchCreate,
  DividendReinvestmentSyncMode,
  SyncBatchCreate,
  SyncRun,
  SyncRunCreate,
  SyncRunFilters
} from '../types/domain';
import { importCsv, type ImportKind } from '../api/imports';

interface SyncFormValues {
  dataset: string;
  mode?: 'manual' | 'incremental' | 'full';
  trade_date?: dayjs.Dayjs;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  ts_code?: string;
  type?: string;
}

interface ImportFormValues {
  kind: ImportKind;
  content: string;
}

interface BatchFormValues {
  mode: 'incremental' | 'full';
  range?: [dayjs.Dayjs, dayjs.Dayjs];
}

interface DividendReinvestmentBatchFormValues {
  mode: DividendReinvestmentSyncMode;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  initial_amount?: number;
  cash_div_field?: 'cash_div_tax' | 'cash_div';
  supplement_dividend_by_stock?: boolean;
  supplement_financial_indicator_by_stock?: boolean;
}

interface RunFilterValues {
  dataset?: string;
  status?: string;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  limit?: number;
}

// 同步页按业务目标展示会被刷新的范围，避免用户只看到接口名称时无法判断影响面。
const AH_SYNC_SCOPE_ITEMS = ['A/H 溢价榜单', '机会筛选与关注', '基础资料、交易日历、官方比价、港股通名单和汇率'];
const DIVIDEND_SYNC_SCOPE_ITEMS = ['分红再投筛选榜单', '年度再投明细', 'A 股日线、分红、最新估值和 ROE 财务指标'];
const DIVIDEND_CALCULATE_ONLY_SCOPE_ITEMS = [
  '仅使用本地已有 A 股日线、分红、估值和 ROE',
  '重算分红再投筛选榜单',
  '重算年度再投明细，不访问 Tushare'
];

/**
 * 数据同步页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function SyncPage() {
  const [form] = Form.useForm<SyncFormValues>();
  const [batchForm] = Form.useForm<BatchFormValues>();
  const [dividendForm] = Form.useForm<DividendReinvestmentBatchFormValues>();
  const [filterForm] = Form.useForm<RunFilterValues>();
  const [importForm] = Form.useForm<ImportFormValues>();
  const [detailRun, setDetailRun] = useState<SyncRun | null>(null);
  const [runFilters, setRunFilters] = useState<SyncRunFilters>({ limit: 50 });
  const queryClient = useQueryClient();
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: fetchDatasets });
  const runs = useQuery({
    queryKey: ['sync-runs', runFilters],
    queryFn: () => fetchSyncRuns(runFilters)
  });
  const selectedDataset = Form.useWatch('dataset', form);
  const dividendMode = Form.useWatch('mode', dividendForm) || 'incremental';
  const isDividendCalculateOnly = dividendMode === 'calculate_only';
  const dividendScopeItems = isDividendCalculateOnly
    ? DIVIDEND_CALCULATE_ONLY_SCOPE_ITEMS
    : DIVIDEND_SYNC_SCOPE_ITEMS;
  const selectedDatasetInfo = datasets.data?.find((item) => item.name === selectedDataset);
  const datasetInfoMap = useMemo(
    () => new Map((datasets.data || []).map((item) => [item.name, item])),
    [datasets.data]
  );
  const mutation = useMutation({
    mutationFn: createSyncRun,
    onSuccess: (run) => {
      message.success(`任务 ${run.id} 已完成：${run.status}`);
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '同步失败')
  });
  const batchMutation = useMutation({
    mutationFn: createAhPremiumSyncBatch,
    onSuccess: (batchRuns) => {
      const failedCount = batchRuns.filter((item) => item.status === 'FAILED').length;
      message.success(`一键同步完成：${batchRuns.length} 个任务，失败 ${failedCount} 个`);
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '一键同步失败')
  });
  const dividendMutation = useMutation({
    mutationFn: createDividendReinvestmentSyncBatch,
    onSuccess: (run) => {
      message.success(`分红再投数据落地完成：任务 ${run.id}，${run.status}`);
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '分红再投同步失败')
  });
  const importMutation = useMutation({
    mutationFn: (values: ImportFormValues) => importCsv(values.kind, values.content),
    onSuccess: (response) => {
      message.success(`导入完成：${response.imported_rows} 条`);
      importForm.resetFields(['content']);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '导入失败')
  });

  const onFinish = (values: SyncFormValues) => {
    const payload: SyncRunCreate = {
      dataset: values.dataset,
      mode: values.mode || 'manual',
      trade_date: values.trade_date?.format('YYYY-MM-DD'),
      start_date: values.range?.[0]?.format('YYYY-MM-DD'),
      end_date: values.range?.[1]?.format('YYYY-MM-DD'),
      ts_code: values.ts_code?.trim() || undefined,
      type: values.type
    };
    mutation.mutate(payload);
  };

  const onBatchFinish = (values: BatchFormValues) => {
    const payload: SyncBatchCreate = {
      mode: values.mode,
      start_date: values.range?.[0]?.format('YYYY-MM-DD'),
      end_date: values.range?.[1]?.format('YYYY-MM-DD')
    };
    batchMutation.mutate(payload);
  };

  const onDividendBatchFinish = (values: DividendReinvestmentBatchFormValues) => {
    const calculateOnly = values.mode === 'calculate_only';
    // 分红再投同步默认走按区间聚合接口；逐股补数开关只在修复历史分红或 ROE 覆盖缺口时启用。
    // 仅本地回测模式必须把补数开关归零，保证页面提交和后端执行口径一致，不会访问 Tushare。
    const payload: DividendReinvestmentSyncBatchCreate = {
      mode: values.mode,
      start_date: values.range?.[0]?.format('YYYY-MM-DD'),
      end_date: values.range?.[1]?.format('YYYY-MM-DD'),
      initial_amount: values.initial_amount,
      cash_div_field: values.cash_div_field,
      supplement_dividend_by_stock: calculateOnly ? false : values.supplement_dividend_by_stock,
      supplement_financial_indicator_by_stock: calculateOnly
        ? false
        : values.supplement_financial_indicator_by_stock
    };
    dividendMutation.mutate(payload);
  };

  const onFilterFinish = (values: RunFilterValues) => {
    setRunFilters({
      dataset: values.dataset,
      status: values.status,
      start_date: values.range?.[0]?.format('YYYY-MM-DD'),
      end_date: values.range?.[1]?.format('YYYY-MM-DD'),
      limit: values.limit || 50
    });
  };

  return (
    <main className="page">
      <PageHeader
        title="数据同步"
        extra={
          <Button
            title="刷新"
            icon={<RotateCw size={16} />}
            onClick={() => runs.refetch()}
            loading={runs.isFetching}
          />
        }
      />
      <section className="panel sync-workflow-panel">
        <Tabs
          items={[
            {
              key: 'sync',
              label: '推荐同步方案',
              children: (
                <Space direction="vertical" size={16} className="full-width">
                  <Alert
                    type="info"
                    showIcon
                    message="先选择业务目标，再选择同步方式"
                    description="日常补数据优先使用对应业务卡片里的“增量同步”；只有需要重建历史数据时才选择全量重跑。单数据集同步放在高级区，只适合明确知道要补哪张表的场景。"
                  />
                  <div className="sync-action-grid">
                    <article className="sync-action-card">
                      <div className="sync-action-card-head">
                        <div>
                          <Tag color="green">A/H 主链路</Tag>
                          <Typography.Title level={4}>同步 A/H 溢价数据</Typography.Title>
                        </div>
                        <Typography.Text type="secondary">用于刷新溢价榜、关注机会和 A/H 对比。</Typography.Text>
                      </div>
                      <div className="sync-scope-list">
                        {AH_SYNC_SCOPE_ITEMS.map((item) => (
                          <span key={item}>{item}</span>
                        ))}
                      </div>
                      <Form
                        form={batchForm}
                        layout="vertical"
                        onFinish={onBatchFinish}
                        initialValues={{ mode: 'incremental' }}
                      >
                        <div className="sync-batch-grid">
                          <Form.Item label="同步方式" name="mode" rules={[{ required: true }]}>
                            <Select
                              options={[
                                { value: 'incremental', label: '增量同步：补齐缺口' },
                                { value: 'full', label: '全量重跑：重建历史' }
                              ]}
                            />
                          </Form.Item>
                          <Form.Item label="覆盖日期范围" name="range">
                            <DatePicker.RangePicker className="full-width" />
                          </Form.Item>
                          <Form.Item label=" ">
                            <Space wrap>
                              <Button
                                type="primary"
                                htmlType="submit"
                                icon={<Play size={16} />}
                                loading={batchMutation.isPending}
                              >
                                开始同步 A/H 数据
                              </Button>
                            </Space>
                          </Form.Item>
                        </div>
                      </Form>
                    </article>
                    <article className="sync-action-card">
                      <div className="sync-action-card-head">
                        <div>
                          <Tag color="purple">分红再投</Tag>
                          <Typography.Title level={4}>同步分红再投数据</Typography.Title>
                        </div>
                        <Typography.Text type="secondary">用于刷新分红再投筛选和年度再投过程。</Typography.Text>
                      </div>
                      <div className="sync-scope-list">
                        {dividendScopeItems.map((item) => (
                          <span key={item}>{item}</span>
                        ))}
                      </div>
                      <Form
                        form={dividendForm}
                        layout="vertical"
                        onFinish={onDividendBatchFinish}
                        initialValues={{
                          mode: 'incremental',
                          initial_amount: 100000,
                          cash_div_field: 'cash_div_tax',
                          supplement_dividend_by_stock: false,
                          supplement_financial_indicator_by_stock: false
                        }}
                      >
                        <div className="sync-batch-grid dividend-reinvestment-sync-grid">
                          <Form.Item label="同步方式" name="mode" rules={[{ required: true }]}>
                            <Select
                              onChange={(mode: DividendReinvestmentSyncMode) => {
                                if (mode === 'calculate_only') {
                                  dividendForm.setFieldsValue({
                                    supplement_dividend_by_stock: false,
                                    supplement_financial_indicator_by_stock: false
                                  });
                                }
                              }}
                              options={[
                                { value: 'incremental', label: '增量补齐：保留已有原始数据' },
                                { value: 'full', label: '全量重跑：重算最新榜单' },
                                { value: 'calculate_only', label: '仅本地回测：不访问 Tushare' }
                              ]}
                            />
                          </Form.Item>
                          <Form.Item label="回测日期范围" name="range">
                            <DatePicker.RangePicker className="full-width" />
                          </Form.Item>
                          <Form.Item
                            label="初始投入"
                            name="initial_amount"
                            rules={[{ required: true, message: '请输入初始投入金额' }]}
                          >
                            <InputNumber min={1} precision={2} className="full-width" />
                          </Form.Item>
                          <Form.Item label="分红口径" name="cash_div_field" rules={[{ required: true }]}>
                            <Select
                              options={[
                                { value: 'cash_div_tax', label: '税后现金分红' },
                                { value: 'cash_div', label: '税前现金分红' }
                              ]}
                            />
                          </Form.Item>
                          <Form.Item
                            label="历史分红补数"
                            name="supplement_dividend_by_stock"
                            valuePropName="checked"
                          >
                            <Checkbox disabled={isDividendCalculateOnly}>逐股补齐更早分红</Checkbox>
                          </Form.Item>
                          <Form.Item
                            label="财务指标补数"
                            name="supplement_financial_indicator_by_stock"
                            valuePropName="checked"
                          >
                            <Checkbox disabled={isDividendCalculateOnly}>逐股补齐 ROE 财务指标</Checkbox>
                          </Form.Item>
                          <Form.Item label=" ">
                            <Button
                              type="primary"
                              htmlType="submit"
                              icon={<Play size={16} />}
                              loading={dividendMutation.isPending}
                            >
                              {isDividendCalculateOnly ? '开始本地回测' : '开始同步分红再投'}
                            </Button>
                          </Form.Item>
                        </div>
                      </Form>
                    </article>
                  </div>
                  <div className="sync-section-head sync-advanced-head">
                    <div>
                      <div className="panel-title">高级：单数据集同步</div>
                      <Typography.Text type="secondary">
                        只在明确知道要补哪张表时使用。选择数据集后，下方会显示该数据集的用途和同步策略。
                      </Typography.Text>
                    </div>
                    <Tag>精确补数</Tag>
                  </div>
                  <Form
                    form={form}
                    layout="vertical"
                    onFinish={onFinish}
                    initialValues={{ mode: 'manual' }}
                  >
                    <div className="sync-form-grid">
                      <Form.Item
                        label="数据集"
                        name="dataset"
                        rules={[{ required: true, message: '请选择数据集' }]}
                      >
                        <Select
                          placeholder="选择数据集"
                          loading={datasets.isLoading}
                          options={datasets.data?.map((item) => ({
                            value: item.name,
                            label: item.supports_full_sync ? item.label : `${item.label}（已禁用）`,
                            disabled: !item.supports_full_sync
                          }))}
                        />
                      </Form.Item>
                      <Form.Item label="同步模式" name="mode">
                        <Select
                          options={[
                            { value: 'manual', label: '按输入参数' },
                            { value: 'incremental', label: '增量补齐' },
                            { value: 'full', label: '全量重跑' }
                          ]}
                        />
                      </Form.Item>
                      <Form.Item label="交易日" name="trade_date">
                        <DatePicker className="full-width" />
                      </Form.Item>
                      <Form.Item label="日期范围" name="range">
                        <DatePicker.RangePicker className="full-width" />
                      </Form.Item>
                      <Form.Item label="代码" name="ts_code">
                        <Input placeholder="如 600000.SH" />
                      </Form.Item>
                      <Form.Item label="通道" name="type">
                        <Select
                          allowClear
                          options={[
                            { value: 'SH_HK', label: 'SH_HK' },
                            { value: 'SZ_HK', label: 'SZ_HK' },
                            { value: 'HK_SH', label: 'HK_SH' },
                            { value: 'HK_SZ', label: 'HK_SZ' }
                          ]}
                        />
                      </Form.Item>
                      <Form.Item label=" ">
                        <Button
                          type="primary"
                          htmlType="submit"
                          icon={<Play size={16} />}
                          loading={mutation.isPending}
                        >
                          执行单数据集同步
                        </Button>
                      </Form.Item>
                    </div>
                    {selectedDatasetInfo ? (
                      <div className="sync-dataset-note">
                        <div className="sync-dataset-note-item">
                          <Typography.Text className="field-label">数据集说明</Typography.Text>
                          <OverflowCell
                            value={selectedDatasetInfo.description}
                            threshold={36}
                          />
                        </div>
                        <div className="sync-dataset-note-item">
                          <Typography.Text className="field-label">同步策略</Typography.Text>
                          <OverflowCell
                            value={selectedDatasetInfo.sync_strategy}
                            threshold={36}
                          />
                        </div>
                        <div className="sync-dataset-note-item">
                          <Typography.Text className="field-label">默认全量起点</Typography.Text>
                          <Typography.Text>
                            {selectedDatasetInfo.default_full_start_date || '当前全表'}
                          </Typography.Text>
                        </div>
                      </div>
                    ) : null}
                  </Form>
                </Space>
              )
            },
            {
              key: 'manual',
              label: '人工导入',
              children: (
                <Form
                  form={importForm}
                  layout="vertical"
                  onFinish={(values) => importMutation.mutate(values)}
                  initialValues={{ kind: 'ah-pairs' }}
                >
                  <div className="manual-import-grid">
                    <Form.Item label="类型" name="kind" rules={[{ required: true }]}>
                      <Select
                        options={[
                          { value: 'ah-pairs', label: 'AH 配对' },
                          { value: 'fx-rates', label: '汇率' }
                        ]}
                      />
                    </Form.Item>
                    <Form.Item
                      label="CSV"
                      name="content"
                      rules={[{ required: true, message: '请输入 CSV' }]}
                    >
                      <Input.TextArea rows={6} className="mono-text" />
                    </Form.Item>
                    <Form.Item label=" ">
                      <Button
                        type="primary"
                        htmlType="submit"
                        icon={<FileUp size={16} />}
                        loading={importMutation.isPending}
                      >
                        导入
                      </Button>
                    </Form.Item>
                  </div>
                </Form>
              )
            }
          ]}
        />
      </section>

      <section className="panel">
        <div className="query-result-head">
          <div className="panel-title">任务记录</div>
          <Button onClick={() => runs.refetch()} loading={runs.isFetching}>
            刷新记录
          </Button>
        </div>
        <Form
          form={filterForm}
          layout="vertical"
          initialValues={{ limit: 50 }}
          onFinish={onFilterFinish}
        >
          <div className="sync-run-filter-grid">
            <Form.Item label="数据集" name="dataset">
              <Select
                allowClear
                placeholder="全部"
                loading={datasets.isLoading}
                options={datasets.data?.map((item) => ({ value: item.name, label: item.label }))}
              />
            </Form.Item>
            <Form.Item label="状态" name="status">
              <Select
                allowClear
                placeholder="全部"
                options={[
                  { value: 'SUCCESS', label: 'SUCCESS' },
                  { value: 'FAILED', label: 'FAILED' },
                  { value: 'RUNNING', label: 'RUNNING' }
                ]}
              />
            </Form.Item>
            <Form.Item label="开始时间" name="range">
              <DatePicker.RangePicker className="full-width" />
            </Form.Item>
            <Form.Item label="条数" name="limit">
              <InputNumber min={1} max={200} className="full-width" />
            </Form.Item>
            <Form.Item label=" ">
              <Space>
                <Button type="primary" htmlType="submit">
                  筛选
                </Button>
                <Button
                  onClick={() => {
                    filterForm.resetFields();
                    setRunFilters({ limit: 50 });
                  }}
                >
                  重置
                </Button>
              </Space>
            </Form.Item>
          </div>
        </Form>
        <Table<SyncRun>
          rowKey="id"
          loading={runs.isLoading}
          dataSource={runs.data || []}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 72 },
            {
              title: '数据集',
              dataIndex: 'dataset',
              width: 160,
              render: (value) => {
                const info = datasetInfoMap.get(String(value));
                return <OverflowCell value={info?.label || value} threshold={12} />;
              }
            },
            {
              title: '任务说明',
              dataIndex: 'dataset',
              width: 380,
              render: (_value, record) => (
                <OverflowCell
                  value={buildSyncRunDescription(record, datasetInfoMap.get(record.dataset))}
                  threshold={30}
                />
              )
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 110,
              render: (value) => <Tag color={value === 'SUCCESS' ? 'blue' : value === 'FAILED' ? 'red' : 'gold'}>{value}</Tag>
            },
            { title: '行数', dataIndex: 'row_count', width: 96, align: 'right' },
            {
              title: '开始时间',
              dataIndex: 'started_at',
              width: 190,
              render: (value) => <OverflowCell value={value} fieldKey="started_at" threshold={19} />
            },
            {
              title: '结束时间',
              dataIndex: 'finished_at',
              width: 190,
              render: (value) => <OverflowCell value={value} fieldKey="finished_at" threshold={19} />
            },
            {
              title: '参数',
              dataIndex: 'params_json',
              width: 260,
              render: (value) => <OverflowCell value={formatJson(value)} mono threshold={22} />
            },
            {
              title: '错误',
              dataIndex: 'error_message',
              width: 420,
              render: (value, record) =>
                value ? (
                  <div className="sync-error-cell">
                    <Popover
                      arrow
                      placement="topLeft"
                      trigger={['hover', 'click']}
                      overlayClassName="sync-error-popover"
                      content={
                        <div className="sync-error-popover-content">
                          <Typography.Text strong>完整错误</Typography.Text>
                          <pre>{value}</pre>
                        </div>
                      }
                    >
                      <Typography.Text type="danger" className="sync-table-text sync-error-trigger">
                        {value}
                      </Typography.Text>
                    </Popover>
                    <Button type="link" size="small" onClick={() => setDetailRun(record)}>
                      查看
                    </Button>
                  </div>
                ) : (
                  <Typography.Text type="secondary">-</Typography.Text>
                )
            }
          ]}
          scroll={{ x: 1800 }}
        />
      </section>
      <Modal
        open={Boolean(detailRun)}
        title={detailRun ? `同步任务 ${detailRun.id} 错误详情` : '错误详情'}
        width={820}
        footer={[
          <Button key="copy" onClick={() => copyRunDetail(detailRun)}>
            复制详情
          </Button>,
          <Button key="close" type="primary" onClick={() => setDetailRun(null)}>
            关闭
          </Button>
        ]}
        onCancel={() => setDetailRun(null)}
      >
        <div className="sync-detail-grid">
          <Typography.Text type="secondary">数据集</Typography.Text>
          <Typography.Text>{detailRun?.dataset || '-'}</Typography.Text>
          <Typography.Text type="secondary">任务说明</Typography.Text>
          <Typography.Text>
            {detailRun
              ? buildSyncRunDescription(detailRun, datasetInfoMap.get(detailRun.dataset))
              : '-'}
          </Typography.Text>
          <Typography.Text type="secondary">状态</Typography.Text>
          <Typography.Text>{detailRun?.status || '-'}</Typography.Text>
          <Typography.Text type="secondary">参数</Typography.Text>
          <pre className="sync-detail-block">{formatJson(detailRun?.params_json)}</pre>
          <Typography.Text type="secondary">错误</Typography.Text>
          <pre className="sync-detail-block error">{detailRun?.error_message || '-'}</pre>
        </div>
      </Modal>
    </main>
  );
}

function formatJson(value?: string | null) {
  if (!value) {
    return '-';
  }
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

type SyncRunParams = Record<string, unknown>;

function parseRunParams(value?: string | null): SyncRunParams {
  if (!value) {
    return {};
  }
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function runRequestParams(run: SyncRun): SyncRunParams {
  const parsed = parseRunParams(run.params_json);
  const request = parsed.request;
  // 分红再投组合任务会把原始请求和阶段结果拆成 request/result；
  // 普通数据集任务的 params_json 本身就是请求参数，二者统一后便于生成可读任务说明。
  if (typeof request === 'object' && request !== null && !Array.isArray(request)) {
    return request as SyncRunParams;
  }
  return parsed;
}

function runResultParams(run: SyncRun): SyncRunParams {
  const parsed = parseRunParams(run.params_json);
  const result = parsed.result;
  return typeof result === 'object' && result !== null && !Array.isArray(result)
    ? (result as SyncRunParams)
    : {};
}

function textParam(params: SyncRunParams, key: string) {
  const value = params[key];
  return value === undefined || value === null || value === '' ? undefined : String(value);
}

function numberParam(params: SyncRunParams, key: string) {
  const value = Number(params[key]);
  return Number.isFinite(value) ? value : 0;
}

function formatRunMode(mode?: string) {
  const modeMap: Record<string, string> = {
    manual: '按输入参数',
    incremental: '增量补齐',
    full: '全量重跑',
    calculate_only: '仅本地回测'
  };
  return mode ? modeMap[mode] || mode : '按输入参数';
}

function formatRunRange(params: SyncRunParams) {
  const tradeDate = textParam(params, 'trade_date');
  if (tradeDate) {
    return `交易日 ${tradeDate}`;
  }
  const startDate = textParam(params, 'start_date');
  const endDate = textParam(params, 'end_date');
  if (startDate && endDate) {
    return `${startDate} 至 ${endDate}`;
  }
  if (startDate) {
    return `${startDate} 起`;
  }
  if (endDate) {
    return `截至 ${endDate}`;
  }
  return '默认范围';
}

function formatPositiveRows(label: string, count: number) {
  return count > 0 ? `${label}${count}` : '';
}

function buildDividendRunDescription(run: SyncRun, params: SyncRunParams) {
  const mode = textParam(params, 'mode') || 'incremental';
  const range = formatRunRange(params);
  const result = runResultParams(run);
  if (mode === 'calculate_only') {
    const summaryRows = numberParam(result, 'summary_rows');
    const yearlyRows = numberParam(result, 'yearly_rows');
    const resultText = [formatPositiveRows('摘要', summaryRows), formatPositiveRows('年度明细', yearlyRows)]
      .filter(Boolean)
      .join('、');
    return `仅使用本地已有行情、分红、估值和 ROE 重算分红再投榜单，范围 ${range}，不访问 Tushare${resultText ? `；生成${resultText}` : ''}。`;
  }

  const stockDividendRows = numberParam(result, 'stock_dividend_rows');
  const financialRows = numberParam(result, 'financial_indicator_rows');
  const supplementText = [
    stockDividendRows > 0 ? '逐股补历史分红' : '',
    financialRows > 0 ? '逐股补 ROE 财务指标' : ''
  ]
    .filter(Boolean)
    .join('、');
  const rowsText = [
    formatPositiveRows('日线', numberParam(result, 'daily_rows')),
    formatPositiveRows('分红', numberParam(result, 'dividend_rows')),
    formatPositiveRows('估值', numberParam(result, 'daily_basic_rows')),
    formatPositiveRows('ROE', financialRows),
    formatPositiveRows('摘要', numberParam(result, 'summary_rows')),
    formatPositiveRows('年度明细', numberParam(result, 'yearly_rows'))
  ]
    .filter(Boolean)
    .join('、');
  return `${formatRunMode(mode)}分红再投基础数据并重算榜单，范围 ${range}${supplementText ? `，包含${supplementText}` : ''}${rowsText ? `；本次处理${rowsText}` : ''}。`;
}

function buildSyncRunDescription(run: SyncRun, datasetInfo?: DatasetInfo) {
  const params = runRequestParams(run);
  if (run.dataset === 'dividend_reinvestment_data_landing') {
    return buildDividendRunDescription(run, params);
  }
  const mode = formatRunMode(textParam(params, 'mode'));
  const range = formatRunRange(params);
  const target = datasetInfo?.label || run.dataset;
  const strategy = datasetInfo?.sync_strategy || datasetInfo?.description || '同步本地业务数据';
  const tsCode = textParam(params, 'ts_code');
  const type = textParam(params, 'type');
  const extra = [tsCode ? `代码 ${tsCode}` : '', type ? `通道 ${type}` : ''].filter(Boolean).join('，');
  return `${mode}${target}，范围 ${range}${extra ? `，${extra}` : ''}；${strategy}。`;
}

function copyRunDetail(run: SyncRun | null) {
  if (!run) {
    return;
  }
  const content = [
    `任务ID: ${run.id}`,
    `数据集: ${run.dataset}`,
    `状态: ${run.status}`,
    `行数: ${run.row_count}`,
    `参数: ${formatJson(run.params_json)}`,
    `错误: ${run.error_message || '-'}`
  ].join('\n');
  navigator.clipboard
    .writeText(content)
    .then(() => message.success('已复制错误详情'))
    .catch(() => message.error('复制失败'));
}

export default SyncPage;
