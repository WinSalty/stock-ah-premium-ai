import { Button, Checkbox, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag, Typography, message } from 'antd';
import { Edit3, KeyRound, Plus } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import PageHeader from '../components/PageHeader';
import { createInvitation, fetchInvitations, fetchUsers, updateUser } from '../api/auth';
import {
  fetchImageGenerationQuotas,
  resetImageGenerationQuota,
  updateImageGenerationQuota
} from '../api/imageGeneration';
import type {
  ImageGenerationAdminQuota,
  InvitationResponse,
  UserInfo,
  UserUpdateRequest
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

const menuPermissionOptions = [
  { label: '总览', value: 'overview' },
  { label: '同步', value: 'sync' },
  { label: '查询', value: 'query' },
  { label: '机会筛选与关注', value: 'premium' },
  { label: '分红再投筛选', value: 'dividend_reinvestment' },
  { label: '问答', value: 'chat' },
  { label: '图片生成', value: 'image_generation' },
  { label: 'LLM 耗时', value: 'llm_metrics' },
  { label: '用户管理', value: 'users' },
  { label: 'PushPlus', value: 'pushplus' },
  { label: '打板推送', value: 'limit_up_push' },
  { label: '雪球发布', value: 'xueqiu_publish' },
  { label: '问答发布雪球', value: 'chat_xueqiu_publish' },
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
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null);
  const [quotaDrafts, setQuotaDrafts] = useState<Record<number, number>>({});
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers
  });
  const invitations = useQuery({
    queryKey: ['invitations'],
    queryFn: fetchInvitations
  });
  const imageQuotas = useQuery({
    queryKey: ['image-generation-admin-quotas'],
    queryFn: fetchImageGenerationQuotas
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
  const updateQuotaMutation = useMutation({
    mutationFn: ({ userId, dailyLimit }: { userId: number; dailyLimit: number }) =>
      updateImageGenerationQuota(userId, dailyLimit),
    onSuccess: () => {
      message.success('图片生成次数已更新');
      queryClient.invalidateQueries({ queryKey: ['image-generation-admin-quotas'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存次数失败')
  });
  const resetQuotaMutation = useMutation({
    mutationFn: resetImageGenerationQuota,
    onSuccess: () => {
      message.success('今日已用次数已重置');
      queryClient.invalidateQueries({ queryKey: ['image-generation-admin-quotas'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '重置失败')
  });

  useEffect(() => {
    if (!imageQuotas.data) {
      return;
    }
    // 管理员维护次数时先把服务端配置映射为本地草稿，避免输入框改动立刻写库。
    setQuotaDrafts(Object.fromEntries(imageQuotas.data.map((item) => [item.user_id, item.daily_limit])));
  }, [imageQuotas.data]);

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
            <div className="panel-title">文生图次数</div>
            <Typography.Text type="secondary">
              默认每人每天 10 次；调用失败会返还次数，管理员可在这里调整上限或重置今日已用次数。
            </Typography.Text>
          </div>
        </div>
        <Table<ImageGenerationAdminQuota>
          rowKey="user_id"
          loading={imageQuotas.isLoading}
          dataSource={imageQuotas.data || []}
          pagination={false}
          scroll={{ x: 920 }}
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
              width: 110,
              render: (_, record) => (record.role === 'ADMIN' ? <Tag color="blue">管理员</Tag> : <Tag>普通用户</Tag>)
            },
            {
              title: '每日上限',
              width: 170,
              render: (_, record) => (
                <InputNumber
                  min={0}
                  max={100}
                  value={quotaDrafts[record.user_id] ?? record.daily_limit}
                  onChange={(value) =>
                    setQuotaDrafts((items) => ({ ...items, [record.user_id]: Number(value ?? 0) }))
                  }
                />
              )
            },
            { title: '今日已用', dataIndex: 'used_count', width: 100 },
            { title: '今日剩余', dataIndex: 'remaining_count', width: 100 },
            { title: '计数日期', dataIndex: 'quota_date', width: 130 },
            {
              title: '最近重置',
              width: 180,
              render: (_, record) => (record.last_reset_at ? formatEast8DateTime(record.last_reset_at) : '-')
            },
            {
              title: '操作',
              width: 180,
              fixed: 'right',
              render: (_, record) => (
                <Space>
                  <Button
                    size="small"
                    loading={updateQuotaMutation.isPending}
                    onClick={() =>
                      updateQuotaMutation.mutate({
                        userId: record.user_id,
                        dailyLimit: quotaDrafts[record.user_id] ?? record.daily_limit
                      })
                    }
                  >
                    保存
                  </Button>
                  <Button
                    size="small"
                    onClick={() => resetQuotaMutation.mutate(record.user_id)}
                    loading={resetQuotaMutation.isPending}
                  >
                    重置
                  </Button>
                </Space>
              )
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

export default UserAdminPage;
