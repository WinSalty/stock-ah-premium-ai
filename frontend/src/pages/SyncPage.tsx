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
  DividendReinvestmentSyncBatchCreate,
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

interface DividendReinvestmentBatchFormValues extends BatchFormValues {
  initial_amount?: number;
  cash_div_field?: 'cash_div_tax' | 'cash_div';
  supplement_dividend_by_stock?: boolean;
}

interface RunFilterValues {
  dataset?: string;
  status?: string;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  limit?: number;
}

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
    // 分红再投同步默认走按区间聚合接口；勾选历史分红补数时才逐股补早期分红，避免日常同步消耗过多 Tushare 请求次数。
    const payload: DividendReinvestmentSyncBatchCreate = {
      mode: values.mode,
      start_date: values.range?.[0]?.format('YYYY-MM-DD'),
      end_date: values.range?.[1]?.format('YYYY-MM-DD'),
      initial_amount: values.initial_amount,
      cash_div_field: values.cash_div_field,
      supplement_dividend_by_stock: values.supplement_dividend_by_stock
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
      <section className="panel">
        <Tabs
          items={[
            {
              key: 'sync',
              label: '接口同步',
              children: (
                <Space direction="vertical" size={16} className="full-width">
                  <Alert
                    type="info"
                    showIcon
                    message="同步说明"
                    description="建议先用一键增量同步补齐 AH 溢价所需数据；需要重建本地数据时选择一键全量重跑。后端已按东八区定时增量：9:25/9:28 港股通名单、16:15 A 股日线、17:10 官方 AH 比价、7:30 外汇日线；单个数据集也支持按交易日、日期范围或代码同步，行情类全市场范围会按日拆分请求。"
                  />
                  <Form
                    form={batchForm}
                    layout="vertical"
                    onFinish={onBatchFinish}
                    initialValues={{ mode: 'incremental' }}
                  >
                    <div className="sync-batch-grid">
                      <Form.Item label="一键模式" name="mode" rules={[{ required: true }]}>
                        <Select
                          options={[
                            { value: 'incremental', label: '增量同步' },
                            { value: 'full', label: '全量重跑' }
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
                            一键同步 AH 所需数据
                          </Button>
                        </Space>
                      </Form.Item>
                    </div>
                  </Form>
                  <Form
                    form={dividendForm}
                    layout="vertical"
                    onFinish={onDividendBatchFinish}
                    initialValues={{
                      mode: 'incremental',
                      initial_amount: 100000,
                      cash_div_field: 'cash_div_tax',
                      supplement_dividend_by_stock: false
                    }}
                  >
                    <div className="sync-batch-grid dividend-reinvestment-sync-grid">
                      <Form.Item label="再投模式" name="mode" rules={[{ required: true }]}>
                        <Select
                          options={[
                            { value: 'incremental', label: '增量补齐' },
                            { value: 'full', label: '全量重跑' }
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
                        <Checkbox>逐股补齐更早分红</Checkbox>
                      </Form.Item>
                      <Form.Item label=" ">
                        <Button
                          type="primary"
                          htmlType="submit"
                          icon={<Play size={16} />}
                          loading={dividendMutation.isPending}
                        >
                          同步分红再投数据
                        </Button>
                      </Form.Item>
                    </div>
                  </Form>
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
                          执行同步
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
              title: '数据集说明',
              dataIndex: 'dataset',
              width: 260,
              render: (value) => (
                <OverflowCell
                  value={datasetInfoMap.get(String(value))?.description || '-'}
                  threshold={18}
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
