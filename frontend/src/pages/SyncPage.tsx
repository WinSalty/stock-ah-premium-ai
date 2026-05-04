import {
  Button,
  DatePicker,
  Form,
  Input,
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
import { useState } from 'react';
import PageHeader from '../components/PageHeader';
import { createSyncRun, fetchDatasets, fetchSyncRuns } from '../api/sync';
import type { SyncRun, SyncRunCreate } from '../types/domain';
import { importCsv, type ImportKind } from '../api/imports';

interface SyncFormValues {
  dataset: string;
  trade_date?: dayjs.Dayjs;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  ts_code?: string;
  type?: string;
}

interface ImportFormValues {
  kind: ImportKind;
  content: string;
}

/**
 * 数据同步页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function SyncPage() {
  const [form] = Form.useForm<SyncFormValues>();
  const [importForm] = Form.useForm<ImportFormValues>();
  const [detailRun, setDetailRun] = useState<SyncRun | null>(null);
  const queryClient = useQueryClient();
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: fetchDatasets });
  const runs = useQuery({ queryKey: ['sync-runs'], queryFn: fetchSyncRuns });
  const mutation = useMutation({
    mutationFn: createSyncRun,
    onSuccess: (run) => {
      message.success(`任务 ${run.id} 已完成：${run.status}`);
      queryClient.invalidateQueries({ queryKey: ['sync-runs'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '同步失败')
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
      trade_date: values.trade_date?.format('YYYY-MM-DD'),
      start_date: values.range?.[0]?.format('YYYY-MM-DD'),
      end_date: values.range?.[1]?.format('YYYY-MM-DD'),
      ts_code: values.ts_code?.trim() || undefined,
      type: values.type
    };
    mutation.mutate(payload);
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
                <Form form={form} layout="vertical" onFinish={onFinish}>
                  <div className="sync-form-grid">
                    <Form.Item
                      label="数据集"
                      name="dataset"
                      rules={[{ required: true, message: '请选择数据集' }]}
                    >
                      <Select
                        placeholder="选择数据集"
                        loading={datasets.isLoading}
                        options={datasets.data?.map((item) => ({ value: item.name, label: item.label }))}
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
                </Form>
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
        <div className="panel-title">任务记录</div>
        <Table<SyncRun>
          rowKey="id"
          loading={runs.isLoading}
          dataSource={runs.data || []}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 72 },
            { title: '数据集', dataIndex: 'dataset', width: 150 },
            {
              title: '状态',
              dataIndex: 'status',
              width: 110,
              render: (value) => <Tag color={value === 'SUCCESS' ? 'blue' : value === 'FAILED' ? 'red' : 'gold'}>{value}</Tag>
            },
            { title: '行数', dataIndex: 'row_count', width: 96, align: 'right' },
            { title: '开始', dataIndex: 'started_at', width: 180 },
            { title: '结束', dataIndex: 'finished_at', width: 180 },
            {
              title: '参数',
              dataIndex: 'params_json',
              width: 260,
              render: (value) => <span className="mono-text sync-table-text">{value || '-'}</span>
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
          scroll={{ x: 1280 }}
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
