import { Alert, Button, Empty, Form, Image, Input, Space, Typography, message } from 'antd';
import { Link2Off, QrCode, RefreshCw, Save, Send } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import PageHeader from '../components/PageHeader';
import { updateProfile } from '../api/auth';
import {
  createPushplusQrCode,
  fetchPushplusBinding,
  sendTestPush,
  unbindPushplusFriend
} from '../api/notifications';
import type { ProfileUpdateRequest, UserInfo } from '../types/domain';

interface ProfilePageProps {
  user: UserInfo;
  onUserUpdated: (user: UserInfo) => void;
}

/**
 * 当前用户个人信息维护页。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function ProfilePage({ user, onUserUpdated }: ProfilePageProps) {
  const [form] = Form.useForm<ProfileUpdateRequest>();
  const queryClient = useQueryClient();
  const binding = useQuery({
    queryKey: ['pushplus-binding'],
    queryFn: fetchPushplusBinding
  });
  const updateMutation = useMutation({
    mutationFn: updateProfile,
    onSuccess: (updatedUser) => {
      message.success('个人信息已保存');
      onUserUpdated(updatedUser);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存失败')
  });
  const qrCodeMutation = useMutation({
    mutationFn: () => createPushplusQrCode({ expire_seconds: 604800, scan_count: 1 }),
    onError: (error) => message.error(error instanceof Error ? error.message : '生成二维码失败')
  });
  const testPushMutation = useMutation({
    mutationFn: () =>
      sendTestPush({
        title: 'AH 提醒测试',
        content: user.can_use_personal_pushplus
          ? 'PushPlus 一对一消息推送已连通。'
          : 'PushPlus 好友消息推送已连通。'
      }),
    onSuccess: () => message.success('测试推送已提交'),
    onError: (error) => message.error(error instanceof Error ? error.message : '测试推送失败')
  });
  const unbindMutation = useMutation({
    mutationFn: unbindPushplusFriend,
    onSuccess: () => {
      message.success('PushPlus 绑定已解除');
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '解除绑定失败')
  });
  const hasPushplusChannel = Boolean(binding.data?.is_bound || user.can_use_personal_pushplus);

  useEffect(() => {
    form.setFieldsValue({
      display_name: user.display_name,
      email: user.email,
      phone: user.phone,
      bio: user.bio
    });
  }, [form, user]);

  useEffect(() => {
    if (!qrCodeMutation.data || binding.data?.is_bound) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [binding.data?.is_bound, qrCodeMutation.data, queryClient]);

  return (
    <main className="page">
      <PageHeader title="个人信息" />
      <section className="panel profile-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">基础资料</div>
            <Typography.Text type="secondary">维护账号展示信息和提醒接收方式。</Typography.Text>
          </div>
        </div>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            display_name: user.display_name,
            email: user.email,
            phone: user.phone,
            bio: user.bio
          }}
          onFinish={(values) => updateMutation.mutate(values)}
        >
          <div className="profile-form-grid">
            <Form.Item label="用户名">
              <Input value={user.username} disabled />
            </Form.Item>
            <Form.Item label="角色">
              <Input value={user.role === 'ADMIN' ? '管理员' : '普通用户'} disabled />
            </Form.Item>
            <Form.Item label="展示名称" name="display_name">
              <Input placeholder="例如姓名或昵称" />
            </Form.Item>
            <Form.Item label="邮箱" name="email">
              <Input placeholder="可选" />
            </Form.Item>
            <Form.Item label="电话" name="phone">
              <Input placeholder="可选" />
            </Form.Item>
          </div>
          <div className="profile-pushplus-card">
            <div className="profile-pushplus-head">
              <div>
                <Typography.Text strong>消息接收</Typography.Text>
                <Typography.Text type="secondary">绑定后，自选股提醒会通过微信推送给你。</Typography.Text>
              </div>
              <Space wrap>
                <Button
                  htmlType="button"
                  icon={<Send size={16} />}
                  disabled={!hasPushplusChannel}
                  loading={testPushMutation.isPending}
                  onClick={() => testPushMutation.mutate()}
                >
                  测试推送
                </Button>
                <Button
                  htmlType="button"
                  danger
                  icon={<Link2Off size={16} />}
                  disabled={!binding.data?.is_bound}
                  loading={unbindMutation.isPending}
                  onClick={() => unbindMutation.mutate()}
                >
                  解除绑定
                </Button>
              </Space>
            </div>
            {binding.data?.is_bound ? (
              <Alert
                showIcon
                type="success"
                message={`已绑定：${binding.data.friend_remark || binding.data.friend_nick_name || binding.data.friend_id}`}
                description={binding.data.is_follow ? '后续提醒将发送到当前微信。' : '请先关注 PushPlus 微信公众号，避免错过提醒。'}
              />
            ) : (
              <>
                <Alert
                  showIcon
                  type="info"
                  message={
                    user.can_use_personal_pushplus
                      ? '当前账号将使用 PushPlus 一对一消息'
                      : '当前账号尚未绑定微信推送'
                  }
                  description={
                    user.can_use_personal_pushplus
                      ? '管理员账号会使用当前 PushPlus token 直接接收提醒，无需添加自己为好友。'
                      : '扫码完成绑定，绑定后回到本页刷新状态。'
                  }
                />
                {!user.can_use_personal_pushplus ? <div className="pushplus-bind-grid">
                  <div className="pushplus-qr-pane">
                    <Button
                      htmlType="button"
                      type="primary"
                      icon={<QrCode size={16} />}
                      loading={qrCodeMutation.isPending}
                      onClick={() => qrCodeMutation.mutate()}
                    >
                      生成绑定二维码
                    </Button>
                    {qrCodeMutation.data?.qr_code_img_url ? (
                      <Image
                        className="pushplus-qr-image"
                        width={220}
                        src={qrCodeMutation.data.qr_code_img_url}
                        alt="PushPlus 绑定二维码"
                      />
                    ) : (
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成后扫码绑定" />
                    )}
                  </div>
                  <div className="pushplus-friend-pane">
                    <Typography.Text strong>绑定状态</Typography.Text>
                    <Typography.Text type="secondary">
                      扫码后回到本页查看状态；若页面未变化，可手动刷新。
                    </Typography.Text>
                    <Button
                      htmlType="button"
                      icon={<RefreshCw size={16} />}
                      loading={binding.isFetching}
                      onClick={() => binding.refetch()}
                    >
                      刷新绑定状态
                    </Button>
                  </div>
                </div> : null}
              </>
            )}
          </div>
          <Form.Item label="简介" name="bio">
            <Input.TextArea rows={4} placeholder="投资偏好、关注市场或备注" />
          </Form.Item>
          <div className="profile-actions">
            <Button type="primary" htmlType="submit" icon={<Save size={16} />} loading={updateMutation.isPending}>
              保存
            </Button>
          </div>
        </Form>
      </section>
    </main>
  );
}

export default ProfilePage;
