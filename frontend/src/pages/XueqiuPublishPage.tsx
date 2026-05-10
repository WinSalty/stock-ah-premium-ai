import { Alert, Button, Checkbox, Form, Input, Modal, Popconfirm, Radio, Space, Switch, Table, Tabs, Tag, Typography, message } from 'antd';
import { Eye, RefreshCw, Save, Send, ShieldCheck } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import PageHeader from '../components/PageHeader';
import {
  fetchXueqiuCredential,
  fetchXueqiuPreview,
  fetchXueqiuRecord,
  fetchXueqiuRecords,
  fetchXueqiuPublishSetting,
  publishXueqiuArticle,
  saveXueqiuCredential,
  saveXueqiuPublishSetting,
  verifyXueqiuCredential
} from '../api/xueqiuPublish';
import type { XueqiuCredentialRequest, XueqiuPublishRecordItem, XueqiuPublishSettingRequest } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

const DEFAULT_XUEQIU_COVER_PIC = 'https://xqimg.imedao.com/19e0d23ff40328673fdcf12c.png';

interface CredentialFormValues {
  enabled: boolean;
  cookie_text: string;
  user_agent: string;
  expires_at?: string;
}

interface PublishSettingFormValues {
  scheduler_enabled: boolean;
  auto_publish: boolean;
  poll_hours: string;
  poll_minutes: string;
  default_cover_pic?: string;
}

/**
 * 雪球长文发布管理页。
 * 创建日期：2026-05-10
 * author: sunshengxian
 */
function XueqiuPublishPage() {
  const queryClient = useQueryClient();
  const [credentialForm] = Form.useForm<CredentialFormValues>();
  const [settingForm] = Form.useForm<PublishSettingFormValues>();
  const [analysisId, setAnalysisId] = useState<number | null>(null);
  const [coverPic, setCoverPic] = useState(DEFAULT_XUEQIU_COVER_PIC);
  const [force, setForce] = useState(false);
  const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);
  const credential = useQuery({ queryKey: ['xueqiu-credential'], queryFn: fetchXueqiuCredential });
  const setting = useQuery({
    queryKey: ['xueqiu-publish-setting'],
    queryFn: fetchXueqiuPublishSetting
  });
  const preview = useQuery({
    queryKey: ['xueqiu-preview', analysisId],
    queryFn: () => fetchXueqiuPreview(analysisId),
    retry: false
  });
  const records = useQuery({ queryKey: ['xueqiu-records'], queryFn: () => fetchXueqiuRecords({ limit: 100 }) });
  const recordDetail = useQuery({
    queryKey: ['xueqiu-record-detail', selectedRecordId],
    queryFn: () => fetchXueqiuRecord(selectedRecordId as number),
    enabled: Boolean(selectedRecordId)
  });

  useEffect(() => {
    if (!setting.data) {
      return;
    }
    // 配置接口异步返回后同步到表单和本次发布封面，避免 initialValues 只在首次渲染生效导致页面显示旧默认值。
    const defaultCover = setting.data.default_cover_pic || DEFAULT_XUEQIU_COVER_PIC;
    settingForm.setFieldsValue({
      scheduler_enabled: setting.data.scheduler_enabled,
      auto_publish: setting.data.auto_publish,
      poll_hours: setting.data.poll_hours,
      poll_minutes: setting.data.poll_minutes,
      default_cover_pic: defaultCover
    });
    setCoverPic(defaultCover);
  }, [setting.data, settingForm]);
  const saveCredential = useMutation({
    mutationFn: (values: CredentialFormValues) => {
      const payload: XueqiuCredentialRequest = {
        enabled: values.enabled,
        cookie_text: values.cookie_text,
        user_agent: values.user_agent,
        expires_at: values.expires_at?.trim() || null
      };
      return saveXueqiuCredential(payload);
    },
    onSuccess: () => {
      message.success('雪球登录态已保存');
      credentialForm.resetFields(['cookie_text']);
      queryClient.invalidateQueries({ queryKey: ['xueqiu-credential'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存失败')
  });
  const saveSetting = useMutation({
    mutationFn: (values: PublishSettingFormValues) => {
      const payload: XueqiuPublishSettingRequest = {
        scheduler_enabled: values.scheduler_enabled,
        auto_publish: values.auto_publish,
        poll_hours: values.poll_hours,
        poll_minutes: values.poll_minutes,
        default_cover_pic: values.default_cover_pic?.trim() || null
      };
      return saveXueqiuPublishSetting(payload);
    },
    onSuccess: (result) => {
      message.success('雪球发布配置已保存');
      setCoverPic(result.default_cover_pic || '');
      queryClient.invalidateQueries({ queryKey: ['xueqiu-publish-setting'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存配置失败')
  });
  const verifyCredential = useMutation({
    mutationFn: verifyXueqiuCredential,
    onSuccess: () => {
      message.success('登录态验证完成');
      queryClient.invalidateQueries({ queryKey: ['xueqiu-credential'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '验证失败')
  });
  const publishMutation = useMutation({
    mutationFn: (publish: boolean) =>
      publishXueqiuArticle({ analysis_id: analysisId, publish, force, cover_pic: coverPic.trim() || null }),
    onSuccess: (result) => {
      message.success(result.message);
      queryClient.invalidateQueries({ queryKey: ['xueqiu-records'] });
      if (result.article_url) {
        Modal.success({
          title: '雪球长文已发布',
          content: <Typography.Link href={result.article_url} target="_blank">{result.article_url}</Typography.Link>
        });
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '操作失败')
  });

  const statusTag = (status: string) => {
    const color = status === 'PUBLISHED' ? 'green' : status === 'DRAFTED' ? 'blue' : status === 'FAILED' ? 'red' : 'default';
    return <Tag color={color}>{status}</Tag>;
  };

  const applyDefaultCover = (value?: string | null) => {
    const nextCover = value || DEFAULT_XUEQIU_COVER_PIC;
    setCoverPic(nextCover);
    settingForm.setFieldValue('default_cover_pic', nextCover);
  };

  return (
    <main className="page">
      <PageHeader title="雪球发布" />
      <section className="panel user-admin-table-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">雪球长文发布</div>
            <Typography.Text type="secondary">
              将最新打板报告转换为雪球长文，可先保存草稿，再按需正式发布。
            </Typography.Text>
          </div>
          <Button icon={<RefreshCw size={16} />} onClick={() => queryClient.invalidateQueries()}>刷新</Button>
        </div>
        <Alert
          className="xueqiu-risk-alert"
          type="warning"
          showIcon
          message="登录态与发布风险"
          description="本功能使用你提供的雪球创作者后台 Cookie 调用网页接口，不保存账号密码。Cookie 只应从你自己的已登录浏览器复制；遇到验证码、风控或接口变更时需要人工处理。"
        />
        <Tabs
          items={[
            {
              key: 'credential',
              label: '登录态',
              children: (
                <Space direction="vertical" size={16} className="xueqiu-tab-body">
                  <div className="xueqiu-credential-summary">
                    <Typography.Text strong>当前状态：</Typography.Text>
                    {credential.data?.configured ? (
                      <Space wrap>
                        <Tag color={credential.data.enabled ? 'green' : 'default'}>
                          {credential.data.enabled ? '已启用' : '已停用'}
                        </Tag>
                        <Typography.Text type="secondary">Cookie: {credential.data.cookie_preview}</Typography.Text>
                        <Typography.Text type="secondary">
                          验证：{formatEast8DateTime(credential.data.last_verified_at, { naiveAsEast8: true })}
                        </Typography.Text>
                      </Space>
                    ) : (
                      <Tag>未配置</Tag>
                    )}
                  </div>
                  {credential.data?.last_error ? <Alert type="error" showIcon message={credential.data.last_error} /> : null}
                  <Form
                    form={credentialForm}
                    layout="vertical"
                    initialValues={{ enabled: true, user_agent: credential.data?.user_agent || '' }}
                    onFinish={(values) => saveCredential.mutate(values)}
                  >
                    <Form.Item name="enabled" valuePropName="checked">
                      <Checkbox>启用雪球发布登录态</Checkbox>
                    </Form.Item>
                    <Form.Item
                      name="cookie_text"
                      label="Cookie"
                      rules={[{ required: true, message: '请粘贴雪球创作者后台 Cookie' }]}
                    >
                      <Input.TextArea rows={6} placeholder="从浏览器开发者工具复制 mp.xueqiu.com 请求 Cookie" />
                    </Form.Item>
                    <Form.Item name="user_agent" label="User-Agent">
                      <Input placeholder="留空则使用后端默认浏览器 UA" />
                    </Form.Item>
                    <Form.Item name="expires_at" label="过期时间（可选，ISO 时间）">
                      <Input placeholder="例如 2026-05-31T23:59:59" />
                    </Form.Item>
                    <Space wrap>
                      <Button type="primary" icon={<Save size={16} />} htmlType="submit" loading={saveCredential.isPending}>
                        保存登录态
                      </Button>
                      <Button icon={<ShieldCheck size={16} />} loading={verifyCredential.isPending} onClick={() => verifyCredential.mutate()}>
                        验证登录态
                      </Button>
                    </Space>
                  </Form>
                </Space>
              )
            },
            {
              key: 'publish',
              label: '发布',
              children: (
                <Space direction="vertical" size={16} className="xueqiu-tab-body">
                  <Form
                    form={settingForm}
                    layout="vertical"
                    className="xueqiu-setting-form"
                    initialValues={{
                      scheduler_enabled: setting.data?.scheduler_enabled ?? false,
                      auto_publish: setting.data?.auto_publish ?? false,
                      poll_hours: setting.data?.poll_hours || '8',
                      poll_minutes: setting.data?.poll_minutes || '30',
                      default_cover_pic: setting.data?.default_cover_pic || DEFAULT_XUEQIU_COVER_PIC
                    }}
                    onFinish={(values) => saveSetting.mutate(values)}
                  >
                    <div className="xueqiu-setting-grid">
                      <Form.Item
                        label="工作日定时"
                        name="scheduler_enabled"
                        valuePropName="checked"
                        extra="开启后由后端调度器在工作日触发；进程级调度总开关仍需部署环境启用。"
                      >
                        <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                      </Form.Item>
                      <Form.Item label="执行动作" name="auto_publish" extra="草稿更稳妥；正式发布会公开发到雪球。">
                        <Radio.Group optionType="button" buttonStyle="solid">
                          <Radio.Button value={false}>保存草稿</Radio.Button>
                          <Radio.Button value={true}>正式发布</Radio.Button>
                        </Radio.Group>
                      </Form.Item>
                      <Form.Item label="小时" name="poll_hours" rules={[{ required: true, message: '请填写小时' }]}>
                        <Input placeholder="8" />
                      </Form.Item>
                      <Form.Item label="分钟" name="poll_minutes" rules={[{ required: true, message: '请填写分钟' }]}>
                        <Input placeholder="30" />
                      </Form.Item>
                    </div>
                    <Form.Item label="默认封面图" name="default_cover_pic">
                      <Input
                        placeholder="留空表示不带封面"
                        onChange={(event) => setCoverPic(event.target.value)}
                      />
                    </Form.Item>
                    <Space wrap>
                      <Button type="primary" htmlType="submit" loading={saveSetting.isPending}>
                        保存定时配置
                      </Button>
                      <Button onClick={() => applyDefaultCover(setting.data?.default_cover_pic)}>
                        使用默认图
                      </Button>
                      <Button
                        onClick={() => {
                          setCoverPic('');
                          settingForm.setFieldValue('default_cover_pic', '');
                        }}
                      >
                        去掉封面
                      </Button>
                      <Typography.Text type="secondary">
                        当前进程调度：{setting.data?.effective_scheduler_registered ? '已注册' : '未注册'}
                      </Typography.Text>
                    </Space>
                  </Form>
                  <Space wrap>
                    <Input
                      className="xueqiu-analysis-input"
                      placeholder="报告 ID，留空使用最新 READY 报告"
                      value={analysisId ?? ''}
                      onChange={(event) => {
                        const value = event.target.value.trim();
                        setAnalysisId(value ? Number(value) : null);
                      }}
                    />
                    <Input
                      className="xueqiu-cover-input"
                      placeholder="本次封面图 URL，留空则不带封面"
                      value={coverPic}
                      onChange={(event) => setCoverPic(event.target.value)}
                    />
                    <Button onClick={() => applyDefaultCover(setting.data?.default_cover_pic)}>默认封面</Button>
                    <Button onClick={() => setCoverPic('')}>去掉封面</Button>
                    <Checkbox checked={force} onChange={(event) => setForce(event.target.checked)}>强制新建/重试</Checkbox>
                    <Button icon={<RefreshCw size={16} />} onClick={() => preview.refetch()}>刷新预览</Button>
                  </Space>
                  {preview.data ? (
                    <div className="xueqiu-preview-grid">
                      <div className="xueqiu-preview-meta">
                        <Typography.Title level={4}>{preview.data.title}</Typography.Title>
                        <Typography.Text type="secondary">
                          报告 ID {preview.data.analysis_id} · 交易日 {preview.data.trade_date}
                        </Typography.Text>
                        <Typography.Paragraph type="secondary" className="xueqiu-force-hint">
                          默认复用同一报告同一模式的最近流水；如果你已在雪球网页删除草稿，请勾选“强制新建/重试”后再次保存，系统会新增流水并重新创建草稿。
                        </Typography.Paragraph>
                        <Typography.Paragraph className="xueqiu-preview-text">
                          {preview.data.content_text.slice(0, 1200)}
                        </Typography.Paragraph>
                        <Space wrap>
                          <Button
                            icon={<Save size={16} />}
                            loading={publishMutation.isPending}
                            onClick={() => publishMutation.mutate(false)}
                          >
                            保存草稿
                          </Button>
                          <Popconfirm
                            title="确认发布到雪球？"
                            description="该操作会使用已配置登录态向雪球发布公开长文。"
                            onConfirm={() => publishMutation.mutate(true)}
                          >
                            <Button type="primary" danger icon={<Send size={16} />} loading={publishMutation.isPending}>
                              正式发布
                            </Button>
                          </Popconfirm>
                        </Space>
                      </div>
                      <article className="limit-up-share-content" dangerouslySetInnerHTML={{ __html: preview.data.content_html }} />
                    </div>
                  ) : (
                    <Alert type="info" showIcon message="暂无可预览报告" description="请先在打板推送中生成 READY 报告。" />
                  )}
                </Space>
              )
            },
            {
              key: 'records',
              label: '流水',
              children: (
                <Table<XueqiuPublishRecordItem>
                  rowKey="id"
                  loading={records.isLoading}
                  dataSource={records.data || []}
                  pagination={{ pageSize: 12 }}
                  columns={[
                    { title: 'ID', dataIndex: 'id', width: 72 },
                    { title: '交易日', dataIndex: 'trade_date', width: 120 },
                    { title: '模式', dataIndex: 'publish_mode', width: 96 },
                    { title: '状态', dataIndex: 'status', width: 110, render: statusTag },
                    { title: '标题', dataIndex: 'title', ellipsis: true },
                    { title: '草稿', dataIndex: 'draft_id', width: 130, ellipsis: true },
                    {
                      title: '文章',
                      dataIndex: 'article_url',
                      width: 140,
                      render: (url: string | null) => (url ? <Typography.Link href={url} target="_blank">打开</Typography.Link> : '-')
                    },
                    {
                      title: '时间',
                      dataIndex: 'created_at',
                      width: 180,
                      render: (value: string) => formatEast8DateTime(value, { naiveAsEast8: true })
                    },
                    {
                      title: '操作',
                      width: 90,
                      render: (_, record) => (
                        <Button type="link" icon={<Eye size={15} />} onClick={() => setSelectedRecordId(record.id)}>
                          详情
                        </Button>
                      )
                    }
                  ]}
                />
              )
            }
          ]}
        />
      </section>
      <Modal
        title="雪球发布详情"
        open={Boolean(selectedRecordId)}
        onCancel={() => setSelectedRecordId(null)}
        footer={null}
        width={900}
      >
        <Space direction="vertical" size={12} className="xueqiu-tab-body">
          {recordDetail.data ? (
            <>
              <Typography.Title level={4}>{recordDetail.data.title}</Typography.Title>
              <Typography.Text type="secondary">
                状态 {recordDetail.data.status} · 创建 {formatEast8DateTime(recordDetail.data.created_at, { naiveAsEast8: true })}
              </Typography.Text>
              {recordDetail.data.error_message ? <Alert type="error" showIcon message={recordDetail.data.error_message} /> : null}
              <Typography.Paragraph copyable={{ text: recordDetail.data.request_payload_json || '' }}>
                <pre className="llm-json-pre">{recordDetail.data.request_payload_json || '无请求摘要'}</pre>
              </Typography.Paragraph>
              <Typography.Paragraph copyable={{ text: recordDetail.data.response_json || '' }}>
                <pre className="llm-json-pre">{recordDetail.data.response_json || '无响应内容'}</pre>
              </Typography.Paragraph>
            </>
          ) : null}
        </Space>
      </Modal>
    </main>
  );
}

export default XueqiuPublishPage;
