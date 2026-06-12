import { Alert, Button, Checkbox, DatePicker, Form, Input, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd';
import { Ban, Eye, RefreshCw, RotateCcw, Search, Send, Share2, Sparkles } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Dayjs } from 'dayjs';
import { useMemo, useState } from 'react';
import PageHeader from '../components/PageHeader';
import {
  createLimitUpReportShare,
  fetchLimitUpDeliveries,
  fetchLimitUpReport,
  fetchLimitUpRecipients,
  fetchLimitUpReports,
  fetchLimitUpReportShares,
  fetchNineTurnDeliveries,
  fetchNineTurnReport,
  fetchNineTurnReports,
  generateLatestLimitUpReport,
  generateLatestNineTurnReport,
  publishNineTurnReportToXueqiu,
  pushLimitUpReport,
  pushNineTurnReport,
  regenerateLimitUpAdvice,
  revokeLimitUpReportShare,
  updateLimitUpRecipients,
  type LimitUpDeliveryFilters,
  type LimitUpReportFilters
} from '../api/limitUpPush';
import type {
  LimitUpDeliveryItem,
  LimitUpPushRequest,
  LimitUpRecipientItem,
  LimitUpReportDetail,
  LimitUpReportListItem,
  LimitUpShareItem,
  NineTurnDeliveryItem,
  NineTurnReportListItem,
  UserInfo
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';
import { copyTextToClipboard } from '../utils/clipboard';

const NINE_TURN_FEATURE_DISABLED = true;
const NINE_TURN_DISABLED_TEXT = 'Tushare stk_nineturn 权限尚未开通，神奇九转同步和推送入口暂时关闭';
// 投资建议尚未生成时的空态说明：建议由推送流程懒生成回填，不代表报告本身异常。
const ADVICE_EMPTY_TEXT = '建议尚未生成，推送时将自动回填';
// 推送确认弹窗顶部说明：推送正文（建议优先还是完整报告）由服务端配置决定，前端只负责选接收人。
const PUSH_CONTENT_HINT = '推送内容由服务端配置决定：默认推送投资建议（高风险），建议未就绪时可能降级为完整报告。';

// 投资建议生成状态到标签颜色/文案的映射，与后端 advice_status 枚举（PENDING/GENERATING/READY/FAILED）一一对应。
const ADVICE_STATUS_TAG_MAP: Record<string, { color: string; label: string }> = {
  READY: { color: 'green', label: '已生成' },
  FAILED: { color: 'red', label: '失败' },
  GENERATING: { color: 'blue', label: '生成中' },
  PENDING: { color: 'default', label: '待生成' }
};

/**
 * 渲染投资建议状态标签；未知状态（如后端新增枚举或字段缺失）按原值灰色兜底展示，避免页面报错。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function renderAdviceStatusTag(status: string | null | undefined) {
  const config = ADVICE_STATUS_TAG_MAP[status || 'PENDING'];
  if (!config) {
    return <Tag>{status}</Tag>;
  }
  return <Tag color={config.color}>{config.label}</Tag>;
}

function recordText(record: Record<string, unknown>, key: string) {
  const value = record[key];
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  return String(value);
}

function nestedRecordText(record: Record<string, unknown>, objectKey: string, key: string) {
  const nested = record[objectKey];
  if (!nested || typeof nested !== 'object' || Array.isArray(nested)) {
    return '-';
  }
  return recordText(nested as Record<string, unknown>, key);
}

function renderStagePanel(report: LimitUpReportDetail) {
  const stageRows = report.stage_quality.map((item, index) => ({ ...item, row_key: `${recordText(item, 'stage_key')}-${index}` }));
  // 首板名单为本次后端重构新增字段，旧报告详情可能不返回，这里兜底为空数组避免历史数据渲染报错。
  const firstBoardRows = (report.selected_first_board_stocks || []).map((item, index) => ({ ...item, row_key: `${recordText(item, 'ts_code')}-${index}` }));
  const chainRows = report.selected_chain_stocks.map((item, index) => ({ ...item, row_key: `${recordText(item, 'ts_code')}-${index}` }));
  const highRows = report.selected_high_board_stocks.map((item, index) => ({ ...item, row_key: `${recordText(item, 'ts_code')}-${index}` }));

  return (
    <div className="limit-up-report-modal-body">
      <Space direction="vertical" size={18} style={{ width: '100%' }}>
        <div>
          <Typography.Title level={5}>阶段质量</Typography.Title>
          <Table<Record<string, unknown>>
            rowKey="row_key"
            size="small"
            pagination={false}
            dataSource={stageRows}
            locale={{ emptyText: '暂无阶段质量记录' }}
            columns={[
              { title: '阶段', dataIndex: 'stage_key', width: 180 },
              {
                title: '状态',
                dataIndex: 'status',
                width: 130,
                render: (value) => <Tag color={String(value).includes('FAILED') ? 'red' : String(value).includes('FALLBACK') ? 'orange' : 'green'}>{String(value || '-')}</Tag>
              },
              { title: '说明', dataIndex: 'message' }
            ]}
          />
        </div>
        <div>
          <Typography.Title level={5}>首板入选名单</Typography.Title>
          <Table<Record<string, unknown>>
            rowKey="row_key"
            size="small"
            pagination={false}
            dataSource={firstBoardRows}
            locale={{ emptyText: '暂无首板入选记录' }}
            columns={[
              { title: '股票', dataIndex: 'name', width: 130 },
              { title: '代码', dataIndex: 'ts_code', width: 120 },
              { title: '状态', dataIndex: 'status', width: 100 },
              { title: '题材', dataIndex: 'theme', width: 160 },
              { title: 'LLM 角色', render: (_, record) => nestedRecordText(record, 'selection', 'theme_role') },
              { title: '入选理由', render: (_, record) => nestedRecordText(record, 'selection', 'selection_reason') }
            ]}
          />
        </div>
        <div>
          <Typography.Title level={5}>两连三连入选名单</Typography.Title>
          <Table<Record<string, unknown>>
            rowKey="row_key"
            size="small"
            pagination={false}
            dataSource={chainRows}
            locale={{ emptyText: '暂无两连三连入选记录' }}
            columns={[
              { title: '股票', dataIndex: 'name', width: 130 },
              { title: '代码', dataIndex: 'ts_code', width: 120 },
              { title: '状态', dataIndex: 'status', width: 100 },
              { title: '题材', dataIndex: 'theme', width: 160 },
              { title: 'LLM 角色', render: (_, record) => nestedRecordText(record, 'selection', 'theme_role') },
              { title: '入选理由', render: (_, record) => nestedRecordText(record, 'selection', 'selection_reason') }
            ]}
          />
        </div>
        <div>
          <Typography.Title level={5}>高连板入选名单</Typography.Title>
          <Table<Record<string, unknown>>
            rowKey="row_key"
            size="small"
            pagination={false}
            dataSource={highRows}
            locale={{ emptyText: '暂无高连板入选记录' }}
            columns={[
              { title: '股票', dataIndex: 'name', width: 130 },
              { title: '代码', dataIndex: 'ts_code', width: 120 },
              { title: '状态', dataIndex: 'status', width: 100 },
              { title: '题材', dataIndex: 'theme', width: 160 },
              { title: '龙头角色', render: (_, record) => nestedRecordText(record, 'selection', 'leader_role') },
              { title: '风险', render: (_, record) => nestedRecordText(record, 'selection', 'risk_level') },
              { title: '入选理由', render: (_, record) => nestedRecordText(record, 'selection', 'selection_reason') }
            ]}
          />
        </div>
      </Space>
    </div>
  );
}

interface LimitUpReportSearchForm {
  keyword?: string;
  status?: string;
  trade_date?: Dayjs;
  limit?: number;
}

interface LimitUpPushPageProps {
  currentUser: UserInfo;
}

/**
 * 打板 LLM 报告推送管理页。
 * 创建日期：2026-05-08
 * author: sunshengxian
 */
function LimitUpPushPage({ currentUser }: LimitUpPushPageProps) {
  const queryClient = useQueryClient();
  const [reportForm] = Form.useForm<LimitUpReportSearchForm>();
  const [deliveryForm] = Form.useForm<LimitUpDeliveryFilters>();
  const [pushForm] = Form.useForm<LimitUpPushRequest>();
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [reportViewMode, setReportViewMode] = useState('preview');
  const [pushTargetReportId, setPushTargetReportId] = useState<number | null>(null);
  const [shareTargetReportId, setShareTargetReportId] = useState<number | null>(null);
  const [shareExpiresHours, setShareExpiresHours] = useState<number | null>(24);
  const [reportFilters, setReportFilters] = useState<LimitUpReportFilters>({ limit: 50 });
  const [deliveryFilters, setDeliveryFilters] = useState<LimitUpDeliveryFilters>({ limit: 150 });
  const isAdmin = currentUser.role === 'ADMIN';
  const recipients = useQuery({
    queryKey: ['limit-up-recipients'],
    queryFn: fetchLimitUpRecipients,
    enabled: isAdmin
  });
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
  const reportShares = useQuery({
    queryKey: ['limit-up-report-shares', shareTargetReportId],
    queryFn: () => fetchLimitUpReportShares(shareTargetReportId as number),
    enabled: isAdmin && Boolean(shareTargetReportId)
  });
  const enabledRecipientIds = useMemo(
    () => new Set((recipients.data || []).filter((item) => item.enabled).map((item) => item.user_id)),
    [recipients.data]
  );
  const pushableRecipients = useMemo(
    () => (recipients.data || []).filter((item) => item.enabled && item.can_push),
    [recipients.data]
  );
  const saveRecipients = useMutation({
    mutationFn: (items: LimitUpRecipientItem[]) =>
      updateLimitUpRecipients({
        recipients: items.map((item) => ({
          user_id: item.user_id,
          enabled: item.enabled,
          weekend_replay_enabled: item.weekend_replay_enabled
        }))
      }),
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
    mutationFn: ({ reportId, payload }: { reportId: number; payload: LimitUpPushRequest }) => pushLimitUpReport(reportId, payload),
    onSuccess: (result) => {
      message.success(`${result.message}，成功 ${result.delivery_count} 个接收人`);
      setPushTargetReportId(null);
      queryClient.invalidateQueries({ queryKey: ['limit-up-deliveries'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '推送失败')
  });
  // 管理员强制重跑投资建议：后端会覆盖旧建议并重置 advice_status，
  // 成功后必须同时刷新报告详情（弹窗建议正文）与报告列表（建议状态标签），避免两处状态不一致。
  const regenerateAdviceMutation = useMutation({
    mutationFn: (reportId: number) => regenerateLimitUpAdvice(reportId),
    onSuccess: (result) => {
      // 后端重生成失败也返回 HTTP 200 + ok:false，必须按 ok 分支提示，
      // 否则失败信息会带成功样式误导管理员；两种情况都要刷新详情与列表。
      if (result.ok) {
        message.success(result.message);
      } else {
        message.error(result.message);
      }
      queryClient.invalidateQueries({ queryKey: ['limit-up-report-detail'] });
      queryClient.invalidateQueries({ queryKey: ['limit-up-reports'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '重新生成建议失败')
  });
  const shareMutation = useMutation({
    mutationFn: ({ reportId, expiresInHours }: { reportId: number; expiresInHours: number | null }) =>
      createLimitUpReportShare(reportId, { expires_in_hours: expiresInHours || null }),
    onSuccess: async (result) => {
      // 分享链接始终使用当前前端域名拼接，避免开发态后端代理端口被复制给外部查看人。
      const shareUrl = new URL(`/limit-up-share/${result.token}`, window.location.origin).toString();
      // 经 copyTextToClipboard 兼容 HTTP 非安全上下文；失败不阻断弹窗（弹窗内可手动复制）。
      await copyTextToClipboard(shareUrl).catch(() => false);
      queryClient.invalidateQueries({ queryKey: ['limit-up-report-shares', shareTargetReportId] });
      Modal.success({
        title: '分享链接已生成',
        content: (
          <Space direction="vertical" size={8}>
            <Typography.Text type="secondary">
              {result.permanent ? '永久有效' : `有效期至 ${formatEast8DateTime(result.expires_at)}`}
            </Typography.Text>
            <Typography.Paragraph copyable={{ text: shareUrl }}>{shareUrl}</Typography.Paragraph>
          </Space>
        )
      });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '分享失败')
  });
  const revokeShareMutation = useMutation({
    mutationFn: ({ reportId, shareId }: { reportId: number; shareId: number }) =>
      revokeLimitUpReportShare(reportId, shareId),
    onSuccess: () => {
      message.success('分享链接已失效');
      queryClient.invalidateQueries({ queryKey: ['limit-up-report-shares', shareTargetReportId] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '失效失败')
  });

  const updateRecipient = (record: LimitUpRecipientItem, patch: Partial<LimitUpRecipientItem>) => {
    // 接收人配置只保存系统用户、启用状态和周末复推偏好，PushPlus token 始终留在后端绑定表；
    // 周末晚间开关只影响 SATURDAY_REPLAY/SUNDAY_REPLAY，常规早盘和手动推送仍按 enabled 执行。
    const next = (recipients.data || []).map((item) =>
      item.user_id === record.user_id ? { ...item, ...patch } : item
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

  const openPushModal = (reportId: number) => {
    // 管理员手动推送必须从已配置且可推送的接收人里选，默认一键推送全部；
    // 这让临时推送和定时推送共用同一份接收白名单，避免绕过授权配置。
    setSelectedReportId(reportId);
    setPushTargetReportId(reportId);
    pushForm.setFieldsValue({ send_all: true, user_ids: pushableRecipients.map((item) => item.user_id) });
  };

  const openShareModal = (reportId: number) => {
    // 临时分享只针对已生成报告创建独立链接，不会把接收人配置或后台权限授予给查看人。
    setSelectedReportId(reportId);
    setShareExpiresHours(24);
    setShareTargetReportId(reportId);
  };

  const submitShare = () => {
    if (!shareTargetReportId) {
      return;
    }
    shareMutation.mutate({ reportId: shareTargetReportId, expiresInHours: shareExpiresHours });
  };

  const copyShareUrl = async (shareUrl: string) => {
    // 经 copyTextToClipboard 兼容 HTTP 非安全上下文，并按真实结果提示。
    const ok = await copyTextToClipboard(shareUrl);
    if (ok) {
      message.success('分享链接已复制');
    } else {
      message.error('复制失败，请手动选择链接复制');
    }
  };

  const submitPush = (values: LimitUpPushRequest) => {
    if (!pushTargetReportId) {
      return;
    }
    const payload = {
      send_all: values.send_all,
      user_ids: values.send_all ? [] : values.user_ids || []
    };
    if (!payload.send_all && !payload.user_ids.length) {
      message.warning('请选择至少一个接收人');
      return;
    }
    pushMutation.mutate({ reportId: pushTargetReportId, payload });
  };

  const openReportModal = (reportId: number) => {
    // 报告列表保持整页宽度用于扫描历史记录，完整 HTML 放进弹窗阅读；
    // 查看弹窗提供渲染预览和原始源码，便于排查 LLM 输出结构，同时避免列表页承载长 HTML。
    setSelectedReportId(reportId);
    setReportViewMode('preview');
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
            {isAdmin ? (
              <>
                <Button
                  type="primary"
                  icon={<Sparkles size={16} />}
                  loading={generateMutation.isPending}
                  onClick={() => generateMutation.mutate()}
                >
                  生成最新报告
                </Button>
              </>
            ) : null}
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
                    scroll={{ x: 1180 }}
                    pagination={{ pageSize: 10 }}
                    rowClassName={(record) => (record.id === selectedReportId ? 'selected-row' : '')}
                    onRow={(record) => ({ onClick: () => setSelectedReportId(record.id) })}
                    columns={[
                      { title: '交易日', dataIndex: 'trade_date', width: 118, fixed: 'left' },
                      {
                        title: '报告标题',
                        dataIndex: 'title',
                        minWidth: 220,
                        ellipsis: true
                      },
                      {
                        title: '状态',
                        dataIndex: 'status',
                        width: 104,
                        render: (value) => <Tag color={value === 'READY' ? 'green' : value === 'FAILED' ? 'red' : 'blue'}>{value}</Tag>
                      },
                      {
                        // 建议列展示投资建议附加产物的生成状态，便于管理员判断推送时会发建议还是降级发完整报告。
                        title: '建议',
                        dataIndex: 'advice_status',
                        width: 96,
                        render: (value) => renderAdviceStatusTag(value)
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
                        width: isAdmin ? 196 : 78,
                        fixed: 'right',
                        render: (_, record) => (
                          <Space
                            size={4}
                            className="limit-up-report-row-actions"
                            // 行点击负责选中当前报告；操作按钮区阻止事件冒泡，避免点击查看/分享/推送时同时改变外层选择态。
                            onClick={(event) => event.stopPropagation()}
                          >
                            <Button size="small" icon={<Eye size={14} />} onClick={() => openReportModal(record.id)}>
                              查看
                            </Button>
                            {isAdmin ? (
                              <>
                                <Button size="small" icon={<Share2 size={14} />} onClick={() => openShareModal(record.id)}>
                                  分享
                                </Button>
                                <Button size="small" icon={<Send size={14} />} onClick={() => openPushModal(record.id)}>
                                  推送
                                </Button>
                              </>
                            ) : null}
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
                    {selectedReport.isFetching ? (
                      <div className="limit-up-report-modal-body">
                        <Typography.Text type="secondary">报告加载中...</Typography.Text>
                      </div>
                    ) : selectedReport.data?.content_html ? (
                      <Tabs
                        activeKey={reportViewMode}
                        onChange={setReportViewMode}
                        items={[
                          {
                            key: 'preview',
                            label: '预览',
                            children: (
                              <div className="limit-up-report-modal-body">
                                <div dangerouslySetInnerHTML={{ __html: selectedReport.data.content_html }} />
                              </div>
                            )
                          },
                          {
                            key: 'source',
                            label: '源码',
                            children: (
                              <pre className="limit-up-report-code-block">
                                <code>{selectedReport.data.content_html}</code>
                              </pre>
                            )
                          },
                          {
                            key: 'stages',
                            label: '阶段',
                            children: renderStagePanel(selectedReport.data)
                          },
                          {
                            key: 'advice',
                            label: '建议',
                            children: (
                              <div className="limit-up-report-modal-body">
                                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                                  {/* 顶部操作区：仅管理员可强制重跑建议；生成时间帮助判断建议是否基于最新一次报告生成。 */}
                                  {isAdmin || selectedReport.data.advice_generated_at ? (
                                    <Space wrap>
                                      {isAdmin ? (
                                        <Button
                                          size="small"
                                          icon={<Sparkles size={14} />}
                                          loading={regenerateAdviceMutation.isPending}
                                          onClick={() => {
                                            // 弹窗内重跑时一定已有选中报告；空值兜底防御异常状态下误发请求。
                                            if (selectedReportId) {
                                              regenerateAdviceMutation.mutate(selectedReportId);
                                            }
                                          }}
                                        >
                                          重新生成建议
                                        </Button>
                                      ) : null}
                                      {selectedReport.data.advice_generated_at ? (
                                        <Typography.Text type="secondary">
                                          建议生成时间：{formatEast8DateTime(selectedReport.data.advice_generated_at)}
                                        </Typography.Text>
                                      ) : null}
                                    </Space>
                                  ) : null}
                                  {/* 失败态优先展示错误原因，方便管理员决定是否点击重跑。 */}
                                  {selectedReport.data.advice_status === 'FAILED' ? (
                                    <Alert
                                      type="error"
                                      showIcon
                                      message="投资建议生成失败"
                                      description={selectedReport.data.advice_error || '未返回错误详情'}
                                    />
                                  ) : null}
                                  {selectedReport.data.advice_html ? (
                                    // 建议正文与"预览"Tab 同源渲染方式：后端产出的受信 HTML 直接注入并复用同一套弹窗样式。
                                    <div dangerouslySetInnerHTML={{ __html: selectedReport.data.advice_html }} />
                                  ) : selectedReport.data.advice_status !== 'FAILED' ? (
                                    // 空态仅覆盖待生成/生成中：失败场景已由上方 Alert 说明，避免"自动回填"文案误导。
                                    <Typography.Text type="secondary">{ADVICE_EMPTY_TEXT}</Typography.Text>
                                  ) : null}
                                </Space>
                              </div>
                            )
                          }
                        ]}
                      />
                    ) : (
                      <div className="limit-up-report-modal-body">
                        <Typography.Text type="secondary">暂无报告内容</Typography.Text>
                      </div>
                    )}
                  </Modal>
                  {isAdmin ? (
                    <Modal
                      open={Boolean(pushTargetReportId)}
                      title="选择推送接收人"
                      onCancel={() => setPushTargetReportId(null)}
                      onOk={() => pushForm.submit()}
                      confirmLoading={pushMutation.isPending}
                      destroyOnClose
                    >
                      {/* 推送正文形态（建议优先/降级完整报告）由服务端配置控制，这里提示管理员实际推送内容可能与列表建议状态相关。 */}
                      <Alert type="info" showIcon message={PUSH_CONTENT_HINT} style={{ marginBottom: 16 }} />
                      <Form form={pushForm} layout="vertical" initialValues={{ send_all: true, user_ids: [] }} onFinish={submitPush}>
                        <Form.Item name="send_all" valuePropName="checked">
                          <Checkbox>一键推送给所有已配置且可推送的接收人</Checkbox>
                        </Form.Item>
                        <Form.Item shouldUpdate noStyle>
                          {({ getFieldValue }) =>
                            getFieldValue('send_all') ? (
                              <Typography.Text type="secondary">
                                当前可推送接收人 {pushableRecipients.length} 个。
                              </Typography.Text>
                            ) : (
                              <Form.Item label="单独选择接收人" name="user_ids" rules={[{ required: true, message: '请选择接收人' }]}>
                                <Select
                                  mode="multiple"
                                  placeholder="只允许选择已配置且可推送的接收人"
                                  options={pushableRecipients.map((item) => ({
                                    value: item.user_id,
                                    label: item.display_name ? `${item.display_name}（${item.username}）` : item.username
                                  }))}
                                  optionFilterProp="label"
                                />
                              </Form.Item>
                            )
                          }
                        </Form.Item>
                      </Form>
                    </Modal>
                  ) : null}
                  {isAdmin ? (
                    <Modal
                      open={Boolean(shareTargetReportId)}
                      title="分享链接"
                      onCancel={() => setShareTargetReportId(null)}
                      onOk={submitShare}
                      okText="生成链接"
                      confirmLoading={shareMutation.isPending}
                      width={860}
                      destroyOnClose
                    >
                      <Space direction="vertical" size={12} className="limit-up-share-modal-body">
                        <Typography.Text type="secondary">
                          分享链接无需登录即可查看该报告；有限期链接到期后自动失效，也可以手动置为失效。
                        </Typography.Text>
                        <Select
                          className="pushplus-search-select"
                          value={shareExpiresHours}
                          onChange={setShareExpiresHours}
                          options={[
                            { label: '1 小时', value: 1 },
                            { label: '24 小时', value: 24 },
                            { label: '72 小时', value: 72 },
                            { label: '7 天', value: 168 },
                            { label: '永久链接', value: 0 }
                          ]}
                        />
                        <Table<LimitUpShareItem>
                          rowKey="id"
                          size="small"
                          loading={reportShares.isLoading || revokeShareMutation.isPending}
                          dataSource={reportShares.data || []}
                          pagination={false}
                          locale={{ emptyText: '暂无已生成分享链接' }}
                          columns={[
                            {
                              title: '链接',
                              dataIndex: 'share_url',
                              ellipsis: true,
                              render: (value) => (
                                <Typography.Link onClick={() => copyShareUrl(value)}>{value}</Typography.Link>
                              )
                            },
                            {
                              title: '状态',
                              dataIndex: 'status',
                              width: 92,
                              render: (value) => renderShareStatus(value)
                            },
                            {
                              title: '有效期',
                              width: 176,
                              render: (_, record) =>
                                record.permanent ? '永久有效' : formatEast8DateTime(record.expires_at)
                            },
                            { title: '访问', dataIndex: 'view_count', width: 74 },
                            {
                              title: '创建时间',
                              dataIndex: 'created_at',
                              width: 176,
                              render: (value) => formatEast8DateTime(value)
                            },
                            {
                              title: '操作',
                              width: 102,
                              render: (_, record) =>
                                record.status === 'ACTIVE' && shareTargetReportId ? (
                                  <Popconfirm
                                    title="确认让这个分享链接失效？"
                                    okText="失效"
                                    cancelText="取消"
                                    onConfirm={() =>
                                      revokeShareMutation.mutate({
                                        reportId: shareTargetReportId,
                                        shareId: record.id
                                      })
                                    }
                                  >
                                    <Button size="small" danger icon={<Ban size={14} />}>
                                      失效
                                    </Button>
                                  </Popconfirm>
                                ) : (
                                  '-'
                                )
                            }
                          ]}
                        />
                      </Space>
                    </Modal>
                  ) : null}
                </>
              )
            },
            {
              key: 'nine-turn',
              label: '神奇九转',
              children: (
                <NineTurnPushPanel
                  isAdmin={isAdmin}
                  pushableRecipients={pushableRecipients}
                />
              )
            },
            ...(isAdmin ? [{
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
                          onChange={(event) => updateRecipient(record, { enabled: event.target.checked })}
                        />
                      )
                    },
                    {
                      title: '周末晚间',
                      width: 120,
                      render: (_, record) => (
                        <Checkbox
                          checked={record.weekend_replay_enabled}
                          disabled={!record.enabled || !record.can_push}
                          onChange={(event) => updateRecipient(record, { weekend_replay_enabled: event.target.checked })}
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
            }] : []),
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
                    {isAdmin ? (
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
                    ) : null}
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

interface NineTurnPushPanelProps {
  isAdmin: boolean;
  pushableRecipients: LimitUpRecipientItem[];
}

/**
 * 神奇九转报告管理面板，挂在打板推送菜单下并复用同一批推送接收人。
 * 创建日期：2026-06-01
 * author: sunshengxian
 */
function NineTurnPushPanel({ isAdmin, pushableRecipients }: NineTurnPushPanelProps) {
  const queryClient = useQueryClient();
  const [reportForm] = Form.useForm<LimitUpReportSearchForm>();
  const [deliveryForm] = Form.useForm<LimitUpDeliveryFilters>();
  const [pushForm] = Form.useForm<LimitUpPushRequest>();
  const [reportFilters, setReportFilters] = useState<LimitUpReportFilters>({ limit: 50 });
  const [deliveryFilters, setDeliveryFilters] = useState<LimitUpDeliveryFilters>({ limit: 150 });
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [reportViewMode, setReportViewMode] = useState('preview');
  const [pushTargetReportId, setPushTargetReportId] = useState<number | null>(null);
  const reports = useQuery({ queryKey: ['nine-turn-reports', reportFilters], queryFn: () => fetchNineTurnReports(reportFilters) });
  const deliveries = useQuery({
    queryKey: ['nine-turn-deliveries', deliveryFilters],
    queryFn: () => fetchNineTurnDeliveries(deliveryFilters)
  });
  const selectedReport = useQuery({
    queryKey: ['nine-turn-report-detail', selectedReportId],
    queryFn: () => fetchNineTurnReport(selectedReportId as number),
    enabled: Boolean(selectedReportId)
  });
  const generateMutation = useMutation({
    mutationFn: generateLatestNineTurnReport,
    onSuccess: (result) => {
      message.success(result.message);
      queryClient.invalidateQueries({ queryKey: ['nine-turn-reports'] });
      if (result.report_id) {
        setSelectedReportId(result.report_id);
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '生成失败')
  });
  const pushMutation = useMutation({
    mutationFn: ({ reportId, payload }: { reportId: number; payload: LimitUpPushRequest }) => pushNineTurnReport(reportId, payload),
    onSuccess: (result) => {
      message.success(`${result.message}，成功 ${result.delivery_count} 个接收人`);
      setPushTargetReportId(null);
      queryClient.invalidateQueries({ queryKey: ['nine-turn-deliveries'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '推送失败')
  });
  const xueqiuMutation = useMutation({
    mutationFn: publishNineTurnReportToXueqiu,
    onSuccess: (result) => {
      if (result.ok) {
        message.success(result.message);
      } else {
        message.warning(result.message);
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '提交雪球失败')
  });

  const submitReportSearch = (values: LimitUpReportSearchForm) => {
    // 九转报告搜索沿用打板报告的日期和状态筛选口径，避免同一菜单内出现两套交互规则。
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
    // 九转 LLM 输出既用于 PushPlus，也会原样进入雪球草稿；保留源码视图便于核对 HTML 结构。
    setSelectedReportId(reportId);
    setReportViewMode('preview');
    setIsReportModalOpen(true);
  };

  const openPushModal = (reportId: number) => {
    if (NINE_TURN_FEATURE_DISABLED) {
      message.warning(NINE_TURN_DISABLED_TEXT);
      return;
    }
    // 神奇九转手动推送只允许选择打板推送已启用且可推送的接收人，确保权限和名单一致。
    setSelectedReportId(reportId);
    setPushTargetReportId(reportId);
    pushForm.setFieldsValue({ send_all: true, user_ids: pushableRecipients.map((item) => item.user_id) });
  };

  const submitPush = (values: LimitUpPushRequest) => {
    if (!pushTargetReportId) {
      return;
    }
    const payload = {
      send_all: values.send_all,
      user_ids: values.send_all ? [] : values.user_ids || []
    };
    if (!payload.send_all && !payload.user_ids.length) {
      message.warning('请选择至少一个接收人');
      return;
    }
    pushMutation.mutate({ reportId: pushTargetReportId, payload });
  };

  return (
    <Space direction="vertical" size={16} className="limit-up-share-modal-body">
      <div className="query-result-head">
        <div>
          <div className="panel-title">神奇九转报告</div>
          <Typography.Text type="secondary">
            当前因 Tushare stk_nineturn 权限尚未开通，已暂停九转同步、推送和雪球发文入口；历史报告仍可查询。
          </Typography.Text>
        </div>
        {isAdmin ? (
          <Button
            type="primary"
            icon={<Sparkles size={16} />}
            loading={generateMutation.isPending}
            disabled={NINE_TURN_FEATURE_DISABLED}
            title={NINE_TURN_DISABLED_TEXT}
            onClick={() => generateMutation.mutate()}
          >
            生成最新九转报告
          </Button>
        ) : null}
      </div>
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
      <Table<NineTurnReportListItem>
        rowKey="id"
        size="small"
        loading={reports.isLoading}
        dataSource={reports.data || []}
        scroll={{ x: 1120 }}
        pagination={{ pageSize: 10 }}
        rowClassName={(record) => (record.id === selectedReportId ? 'selected-row' : '')}
        onRow={(record) => ({ onClick: () => setSelectedReportId(record.id) })}
        columns={[
          { title: '交易日', dataIndex: 'trade_date', width: 118, fixed: 'left' },
          { title: '频率', dataIndex: 'freq', width: 92 },
          { title: '报告标题', dataIndex: 'title', minWidth: 220, ellipsis: true },
          {
            title: '状态',
            dataIndex: 'status',
            width: 104,
            render: (value) => <Tag color={value === 'READY' ? 'green' : value === 'FAILED' ? 'red' : 'blue'}>{value}</Tag>
          },
          { title: '模型', dataIndex: 'model', width: 160 },
          { title: '提示词版本', dataIndex: 'prompt_version', width: 130 },
          { title: '生成时间', dataIndex: 'generated_at', width: 178, render: (value) => formatEast8DateTime(value) },
          {
            title: '操作',
            width: isAdmin ? 234 : 78,
            fixed: 'right',
            render: (_, record) => (
              <Space size={4} className="limit-up-report-row-actions" onClick={(event) => event.stopPropagation()}>
                <Button size="small" icon={<Eye size={14} />} onClick={() => openReportModal(record.id)}>
                  查看
                </Button>
                {isAdmin ? (
                  <>
                    <Button
                      size="small"
                      icon={<Send size={14} />}
                      disabled={NINE_TURN_FEATURE_DISABLED}
                      title={NINE_TURN_DISABLED_TEXT}
                      onClick={() => openPushModal(record.id)}
                    >
                      推送
                    </Button>
                    <Button
                      size="small"
                      icon={<Share2 size={14} />}
                      loading={xueqiuMutation.isPending}
                      disabled={NINE_TURN_FEATURE_DISABLED}
                      title={NINE_TURN_DISABLED_TEXT}
                      onClick={() => xueqiuMutation.mutate(record.id)}
                    >
                      雪球
                    </Button>
                  </>
                ) : null}
              </Space>
            )
          }
        ]}
      />
      <div className="panel-title">神奇九转推送流水</div>
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
      <Table<NineTurnDeliveryItem>
        rowKey="id"
        size="small"
        loading={deliveries.isLoading}
        dataSource={deliveries.data || []}
        scroll={{ x: 980 }}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '交易日', dataIndex: 'trade_date', width: 120 },
          { title: '接收用户', render: (_, record) => record.display_name || record.username || record.user_id, width: 160 },
          { title: '类型', dataIndex: 'scheduled_kind', width: 150 },
          {
            title: '状态',
            dataIndex: 'status',
            width: 100,
            render: (value) => <Tag color={value === 'SENT' ? 'green' : value === 'FAILED' ? 'red' : 'default'}>{value}</Tag>
          },
          { title: '计划时间', dataIndex: 'scheduled_at', width: 180, render: (value) => formatEast8DateTime(value) },
          { title: '发送时间', dataIndex: 'sent_at', width: 180, render: (value) => formatEast8DateTime(value) },
          { title: '错误', dataIndex: 'error_message', ellipsis: true }
        ]}
      />
      <Modal
        open={isReportModalOpen}
        title={selectedReport.data?.title || '神奇九转报告'}
        width={1040}
        footer={null}
        destroyOnClose
        onCancel={() => setIsReportModalOpen(false)}
      >
        {selectedReport.isFetching ? (
          <div className="limit-up-report-modal-body">
            <Typography.Text type="secondary">报告加载中...</Typography.Text>
          </div>
        ) : selectedReport.data?.content_html ? (
          <Tabs
            activeKey={reportViewMode}
            onChange={setReportViewMode}
            items={[
              {
                key: 'preview',
                label: '预览',
                children: (
                  <div className="limit-up-report-modal-body">
                    <div dangerouslySetInnerHTML={{ __html: selectedReport.data.content_html }} />
                  </div>
                )
              },
              {
                key: 'source',
                label: '源码',
                children: (
                  <pre className="limit-up-report-code-block">
                    <code>{selectedReport.data.content_html}</code>
                  </pre>
                )
              }
            ]}
          />
        ) : (
          <div className="limit-up-report-modal-body">
            <Typography.Text type="secondary">暂无报告内容</Typography.Text>
          </div>
        )}
      </Modal>
      {isAdmin ? (
        <Modal
          open={Boolean(pushTargetReportId)}
          title="选择神奇九转推送接收人"
          onCancel={() => setPushTargetReportId(null)}
          onOk={() => pushForm.submit()}
          confirmLoading={pushMutation.isPending}
          destroyOnClose
        >
          <Form form={pushForm} layout="vertical" initialValues={{ send_all: true, user_ids: [] }} onFinish={submitPush}>
            <Form.Item name="send_all" valuePropName="checked">
              <Checkbox>一键推送给所有打板推送已配置且可推送的接收人</Checkbox>
            </Form.Item>
            <Form.Item shouldUpdate noStyle>
              {({ getFieldValue }) =>
                getFieldValue('send_all') ? (
                  <Typography.Text type="secondary">当前可推送接收人 {pushableRecipients.length} 个。</Typography.Text>
                ) : (
                  <Form.Item label="单独选择接收人" name="user_ids" rules={[{ required: true, message: '请选择接收人' }]}>
                    <Select
                      mode="multiple"
                      placeholder="只允许选择打板推送已配置且可推送的接收人"
                      options={pushableRecipients.map((item) => ({
                        value: item.user_id,
                        label: item.display_name ? `${item.display_name}（${item.username}）` : item.username
                      }))}
                      optionFilterProp="label"
                    />
                  </Form.Item>
                )
              }
            </Form.Item>
          </Form>
        </Modal>
      ) : null}
    </Space>
  );
}

function renderShareStatus(status: string) {
  if (status === 'ACTIVE') {
    return <Tag color="green">有效</Tag>;
  }
  if (status === 'EXPIRED') {
    return <Tag color="orange">已过期</Tag>;
  }
  if (status === 'REVOKED') {
    return <Tag color="default">已失效</Tag>;
  }
  return <Tag>{status}</Tag>;
}

export default LimitUpPushPage;
