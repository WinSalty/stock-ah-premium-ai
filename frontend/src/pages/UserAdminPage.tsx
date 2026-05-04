import { Button, Form, Input, Table, Tag, Typography, message } from 'antd';
import { KeyRound, Plus } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import { createInvitation, fetchInvitations } from '../api/auth';
import type { InvitationResponse } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

/**
 * 管理员邀请码页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function UserAdminPage() {
  const [form] = Form.useForm<{ note?: string }>();
  const queryClient = useQueryClient();
  const invitations = useQuery({
    queryKey: ['invitations'],
    queryFn: fetchInvitations
  });
  const createMutation = useMutation({
    mutationFn: createInvitation,
    onSuccess: () => {
      message.success('邀请码已生成');
      form.resetFields();
      queryClient.invalidateQueries({ queryKey: ['invitations'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '生成失败')
  });

  return (
    <main className="page">
      <PageHeader title="用户权限" />
      <section className="panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">生成邀请码</div>
            <Typography.Text type="secondary">
              新用户使用邀请码注册后默认是普通角色，只能访问总览、AH 机会筛选和问答。
            </Typography.Text>
          </div>
        </div>
        <Form form={form} layout="inline" onFinish={(values) => createMutation.mutate(values)}>
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
    </main>
  );
}

export default UserAdminPage;
