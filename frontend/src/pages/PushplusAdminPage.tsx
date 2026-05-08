import { Button, Form, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography, message } from 'antd';
import { Link2, RefreshCw, Search, RotateCcw } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import PageHeader from '../components/PageHeader';
import { fetchUsers } from '../api/auth';
import {
  adminBindPushplusFriend,
  fetchAdminPushplusBindings,
  fetchAdminPushplusMessages,
  fetchPushplusFriends,
  type PushplusMessageFilters
} from '../api/notifications';
import type {
  AdminPushplusBindRequest,
  PushplusBinding,
  PushplusFriend,
  PushplusMessageLog
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

/**
 * PushPlus 绑定、好友和推送流水管理页。
 * 创建日期：2026-05-08
 * author: sunshengxian
 */
function PushplusAdminPage() {
  const [bindForm] = Form.useForm<AdminPushplusBindRequest>();
  const [searchForm] = Form.useForm<PushplusMessageFilters>();
  const [messageFilters, setMessageFilters] = useState<PushplusMessageFilters>({ limit: 100 });
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers
  });
  const bindings = useQuery({
    queryKey: ['pushplus-admin-bindings'],
    queryFn: fetchAdminPushplusBindings
  });
  const friends = useQuery({
    queryKey: ['pushplus-friends'],
    queryFn: fetchPushplusFriends,
    enabled: false
  });
  const messages = useQuery({
    queryKey: ['pushplus-admin-messages', messageFilters],
    queryFn: () => fetchAdminPushplusMessages(messageFilters)
  });
  const bindMutation = useMutation({
    mutationFn: adminBindPushplusFriend,
    onSuccess: () => {
      message.success('PushPlus 好友绑定已保存');
      bindForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['pushplus-admin-bindings'] });
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '绑定失败')
  });

  const submitSearch = (values: PushplusMessageFilters) => {
    // 搜索条件保留 limit，空字符串会在 API 层被清理，避免刷新记录时丢失当前筛选口径。
    setMessageFilters({
      keyword: values.keyword?.trim() || undefined,
      status: values.status || undefined,
      user_id: values.user_id,
      limit: values.limit || 100
    });
  };

  const resetSearch = () => {
    searchForm.resetFields();
    setMessageFilters({ limit: 100 });
  };

  return (
    <main className="page">
      <PageHeader title="PushPlus" />
      <section className="panel user-admin-table-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">绑定管理</div>
            <Typography.Text type="secondary">
              用户扫码成为系统推送账号好友后，绑定状态会写入这里；好友列表仅用于排查。
            </Typography.Text>
          </div>
          <Space wrap>
            <Button icon={<RefreshCw size={16} />} loading={bindings.isFetching} onClick={() => bindings.refetch()}>
              刷新绑定
            </Button>
            <Button icon={<RefreshCw size={16} />} loading={friends.isFetching} onClick={() => friends.refetch()}>
              刷新好友
            </Button>
          </Space>
        </div>
        <Form
          className="pushplus-manual-bind-form"
          form={bindForm}
          layout="inline"
          onFinish={(values) => bindMutation.mutate(values)}
        >
          <Form.Item name="user_id" rules={[{ required: true, message: '请选择系统用户' }]}>
            <Select
              className="pushplus-manual-bind-select"
              placeholder="选择系统用户"
              options={(users.data || []).map((item) => ({
                value: item.id,
                label: item.display_name ? `${item.display_name}（${item.username}）` : item.username
              }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item name="friend_id" rules={[{ required: true, message: '请选择 PushPlus 好友' }]}>
            <Select
              className="pushplus-manual-bind-select"
              placeholder="选择 PushPlus 好友"
              options={(friends.data || []).map((item) => ({
                value: item.friend_id,
                label: item.remark || item.nick_name || `好友 ${item.friend_id}`
              }))}
              showSearch
              optionFilterProp="label"
              notFoundContent="请先刷新好友列表"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<Link2 size={16} />} loading={bindMutation.isPending}>
            手动绑定
          </Button>
        </Form>
        <div className="pushplus-admin-grid">
          <Table<PushplusBinding>
            rowKey={(record) => `${record.user_id}-${record.friend_id || 'none'}`}
            size="small"
            loading={bindings.isLoading}
            dataSource={bindings.data || []}
            pagination={false}
            columns={[
              { title: '系统用户', dataIndex: 'username', width: 160 },
              {
                title: '绑定好友',
                render: (_, record) => record.friend_remark || record.friend_nick_name || record.friend_id || '-'
              },
              {
                title: '状态',
                width: 110,
                render: (_, record) => (
                  <Tag color={record.is_bound ? 'green' : 'default'}>
                    {record.is_bound ? '已绑定' : record.status}
                  </Tag>
                )
              },
              {
                title: '关注',
                width: 100,
                render: (_, record) =>
                  record.is_follow ? <Tag color="green">已关注</Tag> : <Tag color="orange">未关注</Tag>
              }
            ]}
          />
          <Table<PushplusFriend>
            rowKey="friend_id"
            size="small"
            loading={friends.isFetching}
            dataSource={friends.data || []}
            pagination={false}
            locale={{ emptyText: '点击刷新好友获取列表' }}
            columns={[
              {
                title: 'PushPlus 好友',
                render: (_, record) => record.remark || record.nick_name || `好友 ${record.friend_id}`
              },
              {
                title: '状态',
                width: 100,
                render: (_, record) =>
                  record.is_follow ? <Tag color="green">已关注</Tag> : <Tag color="orange">未关注</Tag>
              }
            ]}
          />
        </div>
      </section>
      <section className="panel user-admin-table-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">推送记录</div>
            <Typography.Text type="secondary">记录每一次实际提交给 PushPlus 的消息、接收对象和发送结果。</Typography.Text>
          </div>
          <Button icon={<RefreshCw size={16} />} loading={messages.isFetching} onClick={() => messages.refetch()}>
            刷新记录
          </Button>
        </div>
        <Form className="pushplus-message-search-form" form={searchForm} layout="inline" onFinish={submitSearch}>
          <Form.Item name="keyword">
            <Input allowClear prefix={<Search size={16} />} placeholder="搜索标题、内容、接收人、用户" />
          </Form.Item>
          <Form.Item name="status">
            <Select
              allowClear
              className="pushplus-search-select"
              placeholder="发送状态"
              options={[
                { label: '已发送', value: 'SENT' },
                { label: '失败', value: 'FAILED' },
                { label: '待发送', value: 'PENDING' }
              ]}
            />
          </Form.Item>
          <Form.Item name="user_id">
            <Select
              allowClear
              className="pushplus-search-select"
              placeholder="系统用户"
              options={(users.data || []).map((item) => ({
                value: item.id,
                label: item.display_name ? `${item.display_name}（${item.username}）` : item.username
              }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item name="limit" initialValue={100}>
            <Select
              className="pushplus-limit-select"
              options={[
                { label: '最近 100 条', value: 100 },
                { label: '最近 200 条', value: 200 },
                { label: '最近 500 条', value: 500 }
              ]}
            />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
              搜索
            </Button>
            <Button icon={<RotateCcw size={16} />} onClick={resetSearch}>
              重置
            </Button>
          </Space>
        </Form>
        <Table<PushplusMessageLog>
          className="pushplus-message-table"
          rowKey="id"
          loading={messages.isLoading}
          dataSource={messages.data || []}
          scroll={{ x: 1680 }}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: '推送时间',
              dataIndex: 'sent_at',
              width: 180,
              render: (_, record) => {
                // 推送流水时间由后端按 UTC-naive 入库，沿用全站通用格式化规则统一转成东八区展示。
                return formatEast8DateTime(record.sent_at || record.created_at);
              }
            },
            {
              title: '系统用户',
              width: 180,
              render: (_, record) => (
                <div className="user-cell">
                  <Typography.Text strong>{record.display_name || record.username || `用户 ${record.user_id}`}</Typography.Text>
                  <Typography.Text type="secondary">{record.username || record.user_id}</Typography.Text>
                </div>
              )
            },
            {
              title: '推送给',
              width: 190,
              render: (_, record) => (
                <div className="user-cell">
                  <Typography.Text>{record.recipient_name || '-'}</Typography.Text>
                  <Typography.Text type="secondary">
                    {record.recipient_type === 'PERSONAL'
                      ? '个人账号'
                      : record.recipient_friend_id
                        ? `好友 ${record.recipient_friend_id}`
                        : '好友消息'}
                  </Typography.Text>
                </div>
              )
            },
            { title: '标题', dataIndex: 'message_title', width: 180, ellipsis: true },
            {
              title: '内容',
              dataIndex: 'message_content',
              width: 520,
              render: (value: string, record) => {
                const text = pushplusMessageText(value);
                return (
                  <div className="pushplus-message-cell">
                    <Tooltip
                      overlayClassName="pushplus-message-tooltip"
                      title={<span className="pushplus-message-tooltip-content">{text}</span>}
                    >
                      <Typography.Text className="pushplus-message-preview">
                        {pushplusMessagePreview(value)}
                      </Typography.Text>
                    </Tooltip>
                    <Button
                      type="link"
                      size="small"
                      className="pushplus-message-detail-button"
                      onClick={() => {
                        Modal.info({
                          title: record.message_title || '推送内容',
                          width: 760,
                          okText: '关闭',
                          content: <pre className="pushplus-message-modal-content">{text || '-'}</pre>
                        });
                      }}
                    >
                      查看详情
                    </Button>
                  </div>
                );
              }
            },
            { title: '状态', width: 100, render: (_, record) => renderPushStatus(record.push_status) },
            { title: '流水号', dataIndex: 'push_message_id', width: 150, render: (value) => value || '-' },
            { title: '错误', dataIndex: 'error_message', width: 180, ellipsis: true, render: (value) => value || '-' }
          ]}
        />
      </section>
    </main>
  );
}

function renderPushStatus(status: string) {
  const normalized = status || 'PENDING';
  if (normalized === 'SENT') {
    return <Tag color="green">已发送</Tag>;
  }
  if (normalized === 'FAILED') {
    return <Tag color="red">失败</Tag>;
  }
  return <Tag color="blue">待发送</Tag>;
}

function pushplusMessagePreview(value: string) {
  const text = pushplusMessageText(value);
  return text.length > 96 ? `${text.slice(0, 96)}...` : text || '-';
}

function pushplusMessageText(value: string) {
  return value
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(div|p|tr|table|tbody)>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .split('\n')
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('\n');
}

export default PushplusAdminPage;
