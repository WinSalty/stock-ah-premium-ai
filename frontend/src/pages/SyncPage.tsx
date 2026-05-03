import { Button, DatePicker, Form, Input, Select, Space, Table, Tag, message } from 'antd';
import { Play, RotateCw } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import { createSyncRun, fetchDatasets, fetchSyncRuns } from '../api/sync';
import type { SyncRun, SyncRunCreate } from '../types/domain';

interface SyncFormValues {
  dataset: string;
  trade_date?: dayjs.Dayjs;
  range?: [dayjs.Dayjs, dayjs.Dayjs];
  ts_code?: string;
  type?: string;
}

/**
 * 数据同步页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function SyncPage() {
  const [form] = Form.useForm<SyncFormValues>();
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
        <Form form={form} layout="vertical" onFinish={onFinish}>
          <div className="sync-form-grid">
            <Form.Item label="数据集" name="dataset" rules={[{ required: true, message: '请选择数据集' }]}>
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
              <Button type="primary" htmlType="submit" icon={<Play size={16} />} loading={mutation.isPending}>
                执行同步
              </Button>
            </Form.Item>
          </div>
        </Form>
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
              ellipsis: true,
              render: (value) => <span className="mono-text">{value || '-'}</span>
            },
            { title: '错误', dataIndex: 'error_message', ellipsis: true }
          ]}
          scroll={{ x: 1050 }}
        />
      </section>
    </main>
  );
}

export default SyncPage;
