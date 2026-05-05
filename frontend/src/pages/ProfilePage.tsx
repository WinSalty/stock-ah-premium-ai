import { Alert, Button, Empty, Form, Image, Input, Select, Space, Typography, message } from 'antd';
import { Link2Off, QrCode, RefreshCw, Save, Send } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import PageHeader from '../components/PageHeader';
import { updateProfile } from '../api/auth';
import {
  bindPushplusFriend,
  createPushplusQrCode,
  fetchPushplusBinding,
  fetchPushplusFriends,
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
  const [selectedFriendId, setSelectedFriendId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const binding = useQuery({
    queryKey: ['pushplus-binding'],
    queryFn: fetchPushplusBinding
  });
  const friends = useQuery({
    queryKey: ['pushplus-friends'],
    queryFn: fetchPushplusFriends,
    enabled: false
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
  const bindMutation = useMutation({
    mutationFn: (friendId: number) => bindPushplusFriend({ friend_id: friendId }),
    onSuccess: () => {
      message.success('PushPlus 好友已绑定');
      setSelectedFriendId(null);
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '绑定失败')
  });
  const testPushMutation = useMutation({
    mutationFn: () =>
      sendTestPush({
        title: 'AH 提醒测试',
        content: 'PushPlus 好友消息推送已连通。'
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

  useEffect(() => {
    form.setFieldsValue({
      display_name: user.display_name,
      email: user.email,
      phone: user.phone,
      bio: user.bio
    });
  }, [form, user]);

  return (
    <main className="page">
      <PageHeader title="个人信息" />
      <section className="panel profile-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">基础资料</div>
            <Typography.Text type="secondary">这些信息只用于本系统内展示和用户识别。</Typography.Text>
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
      <section className="panel profile-panel profile-notification-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">PushPlus 好友推送</div>
            <Typography.Text type="secondary">
              绑定后，阈值提醒和股价提醒会通过 PushPlus 好友消息推送。
            </Typography.Text>
          </div>
          <Space wrap>
            <Button
              icon={<Send size={16} />}
              disabled={!binding.data?.is_bound}
              loading={testPushMutation.isPending}
              onClick={() => testPushMutation.mutate()}
            >
              测试推送
            </Button>
            <Button
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
            description={binding.data.is_follow ? '好友已关注 PushPlus 微信公众号。' : '好友尚未关注公众号，可能无法收到微信消息。'}
          />
        ) : (
          <Alert showIcon type="info" message="当前账号尚未绑定 PushPlus 好友。" />
        )}
        <div className="pushplus-bind-grid">
          <div className="pushplus-qr-pane">
            <Space wrap>
              <Button
                type="primary"
                icon={<QrCode size={16} />}
                loading={qrCodeMutation.isPending}
                onClick={() => qrCodeMutation.mutate()}
              >
                生成绑定二维码
              </Button>
              <Button
                icon={<RefreshCw size={16} />}
                loading={friends.isFetching}
                onClick={() => friends.refetch()}
              >
                刷新好友
              </Button>
            </Space>
            {qrCodeMutation.data?.qr_code_img_url ? (
              <Image
                className="pushplus-qr-image"
                width={220}
                src={qrCodeMutation.data.qr_code_img_url}
                alt="PushPlus 绑定二维码"
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="二维码待生成" />
            )}
          </div>
          <div className="pushplus-friend-pane">
            <Typography.Text strong>选择扫码后的好友</Typography.Text>
            <Space.Compact className="pushplus-friend-control">
              <Select
                className="full-width"
                placeholder="刷新后选择好友"
                value={selectedFriendId}
                onChange={setSelectedFriendId}
                options={(friends.data || []).map((friend) => ({
                  value: friend.friend_id,
                  label: friend.remark || friend.nick_name || `好友 ${friend.friend_id}`
                }))}
              />
              <Button
                type="primary"
                disabled={!selectedFriendId}
                loading={bindMutation.isPending}
                onClick={() => selectedFriendId && bindMutation.mutate(selectedFriendId)}
              >
                绑定
              </Button>
            </Space.Compact>
          </div>
        </div>
      </section>
    </main>
  );
}

export default ProfilePage;
