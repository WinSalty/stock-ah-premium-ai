import { Button, Checkbox, DatePicker, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd';
import { Eye, RefreshCw, RotateCcw, Search, Send, Sparkles } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Dayjs } from 'dayjs';
import { useMemo, useState } from 'react';
import PageHeader from '../components/PageHeader';
import {
  fetchLimitUpDeliveries,
  fetchLimitUpReport,
  fetchLimitUpRecipients,
  fetchLimitUpReports,
  generateLatestLimitUpReport,
  pushLimitUpReport,
  updateLimitUpRecipients,
  type LimitUpDeliveryFilters,
  type LimitUpReportFilters
} from '../api/limitUpPush';
import type { LimitUpDeliveryItem, LimitUpRecipientItem, LimitUpReportListItem } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

interface LimitUpReportSearchForm {
  keyword?: string;
  status?: string;
  trade_date?: Dayjs;
  limit?: number;
}

/**
 * 打板 LLM 报告推送管理页。
 * 创建日期：2026-05-08
 * author: sunshengxian
 */
function LimitUpPushPage() {
  const queryClient = useQueryClient();
  const [reportForm] = Form.useForm<LimitUpReportSearchForm>();
  const [deliveryForm] = Form.useForm<LimitUpDeliveryFilters>();
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [reportFilters, setReportFilters] = useState<LimitUpReportFilters>({ limit: 50 });
  const [deliveryFilters, setDeliveryFilters] = useState<LimitUpDeliveryFilters>({ limit: 150 });
  const recipients = useQuery({ queryKey: ['limit-up-recipients'], queryFn: fetchLimitUpRecipients });
  const reports = useQuery({ queryKey: ['limit-up-reports', reportFilters], queryFn: () => fetchLimitUpReports(reportFilters) });
  const deliveries = useQuery({
    queryKey: ['limit-up-deliveries', deliveryFilters],
    queryFn: () => fetchLimitUpDeliveries(deliveryFilters)
  });
  const selectedReport = useQuery({
    queryKey: ['limit-up-report-detail', selectedReportId],
    queryFn: () => fetchLimitUpReport(selectedReportId as number),
    enabled: Boolean(selectedReportId)
  });
  const enabledRecipientIds = useMemo(
    () => new Set((recipients.data || []).filter((item) => item.enabled).map((item) => item.user_id)),
    [recipients.data]
  );
  const saveRecipients = useMutation({
    mutationFn: (items: LimitUpRecipientItem[]) =>
      updateLimitUpRecipients({ recipients: items.map((item) => ({ user_id: item.user_id, enabled: item.enabled })) }),
    onSuccess: () => {
      message.success('接收人配置已保存');
      queryClient.invalidateQueries({ queryKey: ['limit-up-recipients'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存失败')
  });
  const generateMutation = useMutation({
    mutationFn: generateLatestLimitUpReport,
    onSuccess: (result) => {
      message.success(result.message);
      queryClient.invalidateQueries({ queryKey: ['limit-up-reports'] });
      if (result.report_id) {
        setSelectedReportId(result.report_id);
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '生成失败')
  });
  const pushMutation = useMutation({
    mutationFn: pushLimitUpReport,
    onSuccess: (result) => {
      message.success(`${result.message}，成功 ${result.delivery_count} 个接收人`);
      queryClient.invalidateQueries({ queryKey: ['limit-up-deliveries'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '推送失败')
  });

  const toggleRecipient = (record: LimitUpRecipientItem, checked: boolean) => {
    // 接收人配置只保存系统用户和启用状态，PushPlus token 始终留在后端绑定表；
    // 前端禁止勾选不可推送用户，避免定时任务反复生成 SKIPPED 流水。
    const next = (recipients.data || []).map((item) =>
      item.user_id === record.user_id ? { ...item, enabled: checked } : item
    );
    saveRecipients.mutate(next);
  };

  const submitReportSearch = (values: LimitUpReportSearchForm) => {
    // 报告搜索只把日期转成后端接受的 yyyy-MM-dd，空值交给 API 层忽略，避免残留旧筛选。
    setReportFilters({
      keyword: values.keyword?.trim() || undefined,
      status: values.status || undefined,
      trade_date: values.trade_date?.format('YYYY-MM-DD'),
      limit: values.limit || 50
    });
  };

  const submitDeliverySearch = (values: LimitUpDeliveryFilters) => {
    setDeliveryFilters({
      keyword: values.keyword?.trim() || undefined,
      status: values.status || undefined,
      user_id: values.user_id,
      limit: values.limit || 150
    });
  };

  const openReportModal = (reportId: number) => {
    // 报告列表保持整页宽度用于扫描历史记录，完整 HTML 放进弹窗阅读；
    // 这样长报告不会挤压列表列宽，也不会因为右侧预览导致表格横向信息缺失。
    setSelectedReportId(reportId);
    setIsReportModalOpen(true);
  };

  return (
    <main className="page">
      <PageHeader title="打板推送" />
      <section className="panel user-admin-table-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">报告与推送</div>
            <Typography.Text type="secondary">
              KPL 次日数据同步后自动生成完整 HTML 报告，周末复推复用同一份缓存。
            </Typography.Text>
          </div>
          <Space wrap>
            <Button icon={<RefreshCw size={16} />} onClick={() => queryClient.invalidateQueries()}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<Sparkles size={16} />}
              loading={generateMutation.isPending}
              onClick={() => generateMutation.mutate()}
            >
              生成最新报告
            </Button>
            <Button
              icon={<Send size={16} />}
              disabled={!selectedReportId}
              loading={pushMutation.isPending}
              onClick={() => selectedReportId && pushMutation.mutate(selectedReportId)}
            >
              推送选中报告
            </Button>
          </Space>
        </div>
        <Tabs
          items={[
            {
              key: 'reports',
              label: '报告',
              children: (
                <>
                  <Form className="limit-up-search-form" form={reportForm} layout="inline" onFinish={submitReportSearch}>
                    <Form.Item name="keyword">
                      <Input allowClear prefix={<Search size={16} />} placeholder="搜索标题、正文、质量" />
                    </Form.Item>
                    <Form.Item name="status">
                      <Select
                        allowClear
                        className="pushplus-search-select"
                        placeholder="状态"
                        options={[
                          { label: '已生成', value: 'READY' },
                          { label: '生成中', value: 'GENERATING' },
                          { label: '失败', value: 'FAILED' }
                        ]}
                      />
                    </Form.Item>
                    <Form.Item name="trade_date">
                      <DatePicker placeholder="交易日" />
                    </Form.Item>
                    <Form.Item name="limit" initialValue={50}>
                      <Select
                        className="pushplus-limit-select"
                        options={[
                          { label: '最近 30 条', value: 30 },
                          { label: '最近 50 条', value: 50 },
                          { label: '最近 100 条', value: 100 }
                        ]}
                      />
                    </Form.Item>
                    <Space>
                      <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
                        搜索
                      </Button>
                      <Button
                        icon={<RotateCcw size={16} />}
                        onClick={() => {
                          reportForm.resetFields();
                          setReportFilters({ limit: 50 });
                        }}
                      >
                        重置
                      </Button>
                    </Space>
                  </Form>
                  <Table<LimitUpReportListItem>
                    rowKey="id"
                    size="small"
                    className="limit-up-report-table"
                    loading={reports.isLoading}
                    dataSource={reports.data || []}
                    scroll={{ x: 1080 }}
                    pagination={{ pageSize: 10 }}
                    rowClassName={(record) => (record.id === selectedReportId ? 'selected-row' : '')}
                    onRow={(record) => ({ onClick: () => setSelectedReportId(record.id) })}
                    columns={[
                      { title: '交易日', dataIndex: 'trade_date', width: 118, fixed: 'left' },
                      {
                        title: '报告标题',
                        dataIndex: 'title',
                        minWidth: 260,
                        ellipsis: true
                      },
                      {
                        title: '状态',
                        dataIndex: 'status',
                        width: 104,
                        render: (value) => <Tag color={value === 'READY' ? 'green' : value === 'FAILED' ? 'red' : 'blue'}>{value}</Tag>
                      },
                      { title: '模型', dataIndex: 'model', width: 160 },
                      { title: '提示词版本', dataIndex: 'prompt_version', width: 130 },
                      {
                        title: '生成时间',
                        dataIndex: 'generated_at',
                        width: 178,
                        render: (value) => formatEast8DateTime(value)
                      },
                      {
                        title: '操作',
                        width: 150,
                        fixed: 'right',
                        render: (_, record) => (
                          <Space size={8}>
                            <Button size="small" icon={<Eye size={14} />} onClick={() => openReportModal(record.id)}>
                              查看
                            </Button>
                            <Button
                              size="small"
                              icon={<Send size={14} />}
                              loading={pushMutation.isPending && selectedReportId === record.id}
                              onClick={() => {
                                setSelectedReportId(record.id);
                                pushMutation.mutate(record.id);
                              }}
                            >
                              推送
                            </Button>
                          </Space>
                        )
                      }
                    ]}
                  />
                  <Modal
                    open={isReportModalOpen}
                    title={selectedReport.data?.title || '打板报告'}
                    width={1040}
                    footer={null}
                    destroyOnClose
                    onCancel={() => setIsReportModalOpen(false)}
                  >
                    <div className="limit-up-report-modal-body">
                      {selectedReport.isFetching ? (
                        <Typography.Text type="secondary">报告加载中...</Typography.Text>
                      ) : selectedReport.data?.content_html ? (
                        <div dangerouslySetInnerHTML={{ __html: selectedReport.data.content_html }} />
                      ) : (
                        <Typography.Text type="secondary">暂无报告内容</Typography.Text>
                      )}
                    </div>
                  </Modal>
                </>
              )
            },
            {
              key: 'recipients',
              label: '接收人',
              children: (
                <Table<LimitUpRecipientItem>
                  rowKey="user_id"
                  size="small"
                  loading={recipients.isLoading || saveRecipients.isPending}
                  dataSource={recipients.data || []}
                  pagination={false}
                  columns={[
                    {
                      title: '接收',
                      width: 90,
                      render: (_, record) => (
                        <Checkbox
                          checked={enabledRecipientIds.has(record.user_id)}
                          disabled={!record.can_push}
                          onChange={(event) => toggleRecipient(record, event.target.checked)}
                        />
                      )
                    },
                    { title: '系统用户', render: (_, record) => record.display_name || record.username },
                    { title: '登录名', dataIndex: 'username', width: 160 },
                    {
                      title: 'PushPlus 通道',
                      render: (_, record) =>
                        record.can_push ? <Tag color="green">{record.binding_name || '可推送'}</Tag> : <Tag color="orange">未绑定</Tag>
                    }
                  ]}
                />
              )
            },
            {
              key: 'deliveries',
              label: '推送流水',
              children: (
                <>
                  <Form className="limit-up-search-form" form={deliveryForm} layout="inline" onFinish={submitDeliverySearch}>
                    <Form.Item name="keyword">
                      <Input allowClear prefix={<Search size={16} />} placeholder="搜索标题、用户、错误" />
                    </Form.Item>
                    <Form.Item name="status">
                      <Select
                        allowClear
                        className="pushplus-search-select"
                        placeholder="推送状态"
                        options={[
                          { label: '已发送', value: 'SENT' },
                          { label: '失败', value: 'FAILED' },
                          { label: '跳过', value: 'SKIPPED' },
                          { label: '待发送', value: 'PENDING' }
                        ]}
                      />
                    </Form.Item>
                    <Form.Item name="user_id">
                      <Select
                        allowClear
                        className="pushplus-search-select"
                        placeholder="接收用户"
                        options={(recipients.data || []).map((item) => ({
                          value: item.user_id,
                          label: item.display_name ? `${item.display_name}（${item.username}）` : item.username
                        }))}
                        showSearch
                        optionFilterProp="label"
                      />
                    </Form.Item>
                    <Form.Item name="limit" initialValue={150}>
                      <Select
                        className="pushplus-limit-select"
                        options={[
                          { label: '最近 100 条', value: 100 },
                          { label: '最近 150 条', value: 150 },
                          { label: '最近 300 条', value: 300 }
                        ]}
                      />
                    </Form.Item>
                    <Space>
                      <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
                        搜索
                      </Button>
                      <Button
                        icon={<RotateCcw size={16} />}
                        onClick={() => {
                          deliveryForm.resetFields();
                          setDeliveryFilters({ limit: 150 });
                        }}
                      >
                        重置
                      </Button>
                    </Space>
                  </Form>
                  <Table<LimitUpDeliveryItem>
                    rowKey="id"
                    size="small"
                    loading={deliveries.isLoading}
                    dataSource={deliveries.data || []}
                    scroll={{ x: 1100 }}
                    pagination={{ pageSize: 10 }}
                    columns={[
                      { title: '交易日', dataIndex: 'trade_date', width: 120 },
                      { title: '接收用户', render: (_, record) => record.display_name || record.username || record.user_id, width: 160 },
                      { title: '类型', dataIndex: 'scheduled_kind', width: 160 },
                      {
                        title: '状态',
                        dataIndex: 'status',
                        width: 100,
                        render: (value) => <Tag color={value === 'SENT' ? 'green' : value === 'FAILED' ? 'red' : 'default'}>{value}</Tag>
                      },
                      {
                        title: '计划时间',
                        dataIndex: 'scheduled_at',
                        width: 180,
                        render: (value) => formatEast8DateTime(value)
                      },
                      {
                        title: '发送时间',
                        dataIndex: 'sent_at',
                        width: 180,
                        render: (value) => formatEast8DateTime(value)
                      },
                      { title: '错误', dataIndex: 'error_message', ellipsis: true }
                    ]}
                  />
                </>
              )
            }
          ]}
        />
      </section>
    </main>
  );
}

export default LimitUpPushPage;
