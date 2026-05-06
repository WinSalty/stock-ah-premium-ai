import { Button, Checkbox, Form, Input, Modal, Select, Space, Switch, Table, Tag, Tooltip, Typography, message } from 'antd';
import { Edit3, KeyRound, Link2, Plus, RefreshCw } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import PageHeader from '../components/PageHeader';
import { createInvitation, fetchInvitations, fetchUsers, updateUser } from '../api/auth';
import {
  adminBindPushplusFriend,
  fetchAdminPushplusBindings,
  fetchAdminPushplusMessages,
  fetchPushplusFriends
} from '../api/notifications';
import type {
  AdminPushplusBindRequest,
  InvitationResponse,
  PushplusBinding,
  PushplusFriend,
  PushplusMessageLog,
  UserInfo,
  UserUpdateRequest
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

const menuPermissionOptions = [
  { label: '总览', value: 'overview' },
  { label: '同步', value: 'sync' },
  { label: '查询', value: 'query' },
  { label: 'AH 机会筛选', value: 'premium' },
  { label: '问答', value: 'chat' },
  { label: 'LLM 耗时', value: 'llm_metrics' },
  { label: '用户管理', value: 'users' },
  { label: '个人信息', value: 'profile' }
];

interface UserAdminPageProps {
  currentUser: UserInfo;
  onUserUpdated: (user: UserInfo) => void;
}

/**
 * 管理员用户、菜单权限和邀请码页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function UserAdminPage({ currentUser, onUserUpdated }: UserAdminPageProps) {
  const [invitationForm] = Form.useForm<{ note?: string }>();
  const [editForm] = Form.useForm<UserUpdateRequest>();
  const [pushplusBindForm] = Form.useForm<AdminPushplusBindRequest>();
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null);
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers
  });
  const invitations = useQuery({
    queryKey: ['invitations'],
    queryFn: fetchInvitations
  });
  const pushplusBindings = useQuery({
    queryKey: ['pushplus-admin-bindings'],
    queryFn: fetchAdminPushplusBindings
  });
  const pushplusFriends = useQuery({
    queryKey: ['pushplus-friends'],
    queryFn: fetchPushplusFriends,
    enabled: false
  });
  const pushplusMessages = useQuery({
    queryKey: ['pushplus-admin-messages'],
    queryFn: fetchAdminPushplusMessages
  });
  const createMutation = useMutation({
    mutationFn: createInvitation,
    onSuccess: () => {
      message.success('邀请码已生成');
      invitationForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['invitations'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '生成失败')
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: UserUpdateRequest }) => updateUser(id, payload),
    onSuccess: (updatedUser) => {
      message.success('用户信息已更新');
      setEditingUser(null);
      queryClient.invalidateQueries({ queryKey: ['users'] });
      if (updatedUser.id === currentUser.id) {
        onUserUpdated(updatedUser);
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存失败')
  });
  const bindPushplusMutation = useMutation({
    mutationFn: adminBindPushplusFriend,
    onSuccess: () => {
      message.success('PushPlus 好友绑定已保存');
      pushplusBindForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['pushplus-admin-bindings'] });
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '绑定失败')
  });

  const openEditModal = (user: UserInfo) => {
    setEditingUser(user);
    editForm.setFieldsValue({
      role: user.role,
      is_active: user.is_active,
      display_name: user.display_name,
      email: user.email,
      phone: user.phone,
      bio: user.bio,
      permissions: user.permissions
    });
  };

  return (
    <main className="page">
      <PageHeader title="用户管理" />
      <section className="panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">用户与菜单权限</div>
            <Typography.Text type="secondary">
              菜单按用户单独授权，调整后用户下次刷新或重新进入页面即按新权限展示。
            </Typography.Text>
          </div>
        </div>
        <Table<UserInfo>
          rowKey="id"
          loading={users.isLoading}
          dataSource={users.data || []}
          scroll={{ x: 960 }}
          pagination={false}
          columns={[
            {
              title: '用户',
              width: 180,
              render: (_, record) => (
                <div className="user-cell">
                  <Typography.Text strong>{record.display_name || record.username}</Typography.Text>
                  <Typography.Text type="secondary">{record.username}</Typography.Text>
                </div>
              )
            },
            {
              title: '角色',
              width: 120,
              render: (_, record) =>
                record.role === 'ADMIN' ? <Tag color="blue">管理员</Tag> : <Tag>普通用户</Tag>
            },
            {
              title: '状态',
              width: 100,
              render: (_, record) =>
                record.is_active ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>
            },
            {
              title: '菜单权限',
              render: (_, record) => (
                <Space size={[4, 6]} wrap>
                  {record.permissions.map((permission) => {
                    const option = menuPermissionOptions.find((item) => item.value === permission);
                    return <Tag key={permission}>{option?.label || permission}</Tag>;
                  })}
                </Space>
              )
            },
            { title: '邮箱', dataIndex: 'email', width: 180, render: (value) => value || '-' },
            { title: '电话', dataIndex: 'phone', width: 140, render: (value) => value || '-' },
            {
              title: '操作',
              width: 110,
              fixed: 'right',
              render: (_, record) => (
                <Button icon={<Edit3 size={16} />} onClick={() => openEditModal(record)}>
                  编辑
                </Button>
              )
            }
          ]}
        />
      </section>
      <section className="panel user-admin-table-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">PushPlus 绑定管理</div>
            <Typography.Text type="secondary">
              用户扫码成为系统推送账号好友后，绑定状态会写入这里；好友列表仅用于排查。
            </Typography.Text>
          </div>
          <Space wrap>
            <Button
              icon={<RefreshCw size={16} />}
              loading={pushplusBindings.isFetching}
              onClick={() => pushplusBindings.refetch()}
            >
              刷新绑定
            </Button>
            <Button
              icon={<RefreshCw size={16} />}
              loading={pushplusFriends.isFetching}
              onClick={() => pushplusFriends.refetch()}
            >
              刷新好友
            </Button>
          </Space>
        </div>
        <Form
          className="pushplus-manual-bind-form"
          form={pushplusBindForm}
          layout="inline"
          onFinish={(values) => bindPushplusMutation.mutate(values)}
        >
          <Form.Item
            name="user_id"
            rules={[{ required: true, message: '请选择系统用户' }]}
          >
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
          <Form.Item
            name="friend_id"
            rules={[{ required: true, message: '请选择 PushPlus 好友' }]}
          >
            <Select
              className="pushplus-manual-bind-select"
              placeholder="选择 PushPlus 好友"
              options={(pushplusFriends.data || []).map((item) => ({
                value: item.friend_id,
                label: item.remark || item.nick_name || `好友 ${item.friend_id}`
              }))}
              showSearch
              optionFilterProp="label"
              notFoundContent="请先刷新好友列表"
            />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            icon={<Link2 size={16} />}
            loading={bindPushplusMutation.isPending}
          >
            手动绑定
          </Button>
        </Form>
        <div className="pushplus-admin-grid">
          <Table<PushplusBinding>
            rowKey={(record) => `${record.user_id}-${record.friend_id || 'none'}`}
            size="small"
            loading={pushplusBindings.isLoading}
            dataSource={pushplusBindings.data || []}
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
            loading={pushplusFriends.isFetching}
            dataSource={pushplusFriends.data || []}
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
            <div className="panel-title">PushPlus 推送记录</div>
            <Typography.Text type="secondary">记录每一次实际提交给 PushPlus 的消息、接收对象和发送结果。</Typography.Text>
          </div>
          <Button
            icon={<RefreshCw size={16} />}
            loading={pushplusMessages.isFetching}
            onClick={() => pushplusMessages.refetch()}
          >
            刷新记录
          </Button>
        </div>
        <Table<PushplusMessageLog>
          className="pushplus-message-table"
          rowKey="id"
          loading={pushplusMessages.isLoading}
          dataSource={pushplusMessages.data || []}
          scroll={{ x: 1680 }}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: '推送时间',
              dataIndex: 'sent_at',
              width: 180,
              render: (_, record) => formatEast8DateTime(record.sent_at || record.created_at, { naiveAsEast8: true })
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
            {
              title: '标题',
              dataIndex: 'message_title',
              width: 180,
              ellipsis: true
            },
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
            {
              title: '状态',
              width: 100,
              render: (_, record) => renderPushStatus(record.push_status)
            },
            {
              title: '流水号',
              dataIndex: 'push_message_id',
              width: 150,
              render: (value) => value || '-'
            },
            {
              title: '错误',
              dataIndex: 'error_message',
              width: 180,
              ellipsis: true,
              render: (value) => value || '-'
            }
          ]}
        />
      </section>
      <section className="panel user-admin-table-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">生成邀请码</div>
            <Typography.Text type="secondary">新用户使用邀请码注册后默认是普通角色。</Typography.Text>
          </div>
        </div>
        <Form form={invitationForm} layout="inline" onFinish={(values) => createMutation.mutate(values)}>
          <Form.Item name="note">
            <Input placeholder="备注，例如给谁使用" prefix={<KeyRound size={16} />} />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<Plus size={16} />} loading={createMutation.isPending}>
            生成
          </Button>
        </Form>
      </section>
      <section className="panel user-admin-table-panel">
        <div className="panel-title">邀请码记录</div>
        <Table<InvitationResponse>
          rowKey="id"
          loading={invitations.isLoading}
          dataSource={invitations.data || []}
          pagination={false}
          scroll={{ x: 760 }}
          columns={[
            { title: '邀请码', dataIndex: 'code', width: 180 },
            { title: '备注', dataIndex: 'note' },
            {
              title: '状态',
              width: 110,
              render: (_, record) =>
                record.used_by_user_id ? <Tag color="default">已使用</Tag> : <Tag color="green">可用</Tag>
            },
            {
              title: '使用时间',
              width: 180,
              render: (_, record) => (record.used_at ? formatEast8DateTime(record.used_at) : '-')
            },
            {
              title: '创建时间',
              width: 180,
              render: (_, record) => formatEast8DateTime(record.created_at)
            }
          ]}
        />
      </section>
      <Modal
        title="编辑用户"
        open={Boolean(editingUser)}
        onCancel={() => setEditingUser(null)}
        onOk={() => editForm.submit()}
        confirmLoading={updateMutation.isPending}
        destroyOnClose
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => editingUser && updateMutation.mutate({ id: editingUser.id, payload: values })}
        >
          <Form.Item label="角色" name="role" rules={[{ required: true, message: '请选择角色' }]}>
            <Select
              options={[
                { label: '管理员', value: 'ADMIN' },
                { label: '普通用户', value: 'USER' }
              ]}
            />
          </Form.Item>
          <Form.Item label="启用状态" name="is_active" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item label="展示名称" name="display_name">
            <Input placeholder="用于侧边栏和用户列表展示" />
          </Form.Item>
          <Form.Item label="邮箱" name="email">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="电话" name="phone">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="简介" name="bio">
            <Input.TextArea rows={3} placeholder="投资偏好、负责范围或备注" />
          </Form.Item>
          <Form.Item label="菜单权限" name="permissions" rules={[{ required: true, message: '请选择至少一个菜单' }]}>
            <Checkbox.Group className="permission-checkbox-grid" options={menuPermissionOptions} />
          </Form.Item>
        </Form>
      </Modal>
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

export default UserAdminPage;
