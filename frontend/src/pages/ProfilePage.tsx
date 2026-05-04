import { Button, Form, Input, Typography, message } from 'antd';
import { Save } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { useEffect } from 'react';
import PageHeader from '../components/PageHeader';
import { updateProfile } from '../api/auth';
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
  const updateMutation = useMutation({
    mutationFn: updateProfile,
    onSuccess: (updatedUser) => {
      message.success('个人信息已保存');
      onUserUpdated(updatedUser);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存失败')
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
    </main>
  );
}

export default ProfilePage;
