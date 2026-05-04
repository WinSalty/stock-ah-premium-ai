import { Button, Form, Input, Tabs, Typography, message } from 'antd';
import { LockKeyhole, UserRound } from 'lucide-react';
import { useState } from 'react';
import { login, register } from '../api/auth';
import { setAuthToken } from '../api/client';
import type { AuthTokenResponse, LoginRequest, RegisterRequest } from '../types/domain';

interface AuthPageProps {
  onAuthenticated: (result: AuthTokenResponse) => void;
}

/**
 * 登录注册页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function AuthPage({ onAuthenticated }: AuthPageProps) {
  const [loading, setLoading] = useState(false);

  const submitLogin = async (values: LoginRequest) => {
    setLoading(true);
    try {
      const result = await login(values);
      setAuthToken(result.token);
      onAuthenticated(result);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const submitRegister = async (values: RegisterRequest) => {
    setLoading(true);
    try {
      const result = await register(values);
      setAuthToken(result.token);
      onAuthenticated(result);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-visual">
        <div className="auth-mark">AH</div>
        <Typography.Title level={1}>港股通 A/H Premium AI</Typography.Title>
        <Typography.Paragraph>
          用自选阈值、价差分位和本地投研知识库，把 A/H 价差机会收进同一个工作台。
        </Typography.Paragraph>
        <svg className="auth-chart-svg" viewBox="0 0 540 260" role="img" aria-label="A/H 价差趋势插画">
          <rect x="28" y="26" width="484" height="208" rx="8" fill="#ffffff" opacity="0.92" />
          <path d="M70 184 C125 128, 165 144, 214 96 S310 62, 364 122 440 150, 478 74" fill="none" stroke="#2563eb" strokeWidth="8" strokeLinecap="round" />
          <path d="M70 144 C126 162, 168 108, 220 136 S308 184, 366 118 434 82, 478 128" fill="none" stroke="#0f766e" strokeWidth="8" strokeLinecap="round" />
          <line x1="70" y1="156" x2="478" y2="156" stroke="#dc2626" strokeWidth="4" strokeDasharray="10 10" />
          <circle cx="364" cy="122" r="12" fill="#0f766e" />
          <circle cx="478" cy="74" r="12" fill="#2563eb" />
        </svg>
      </section>
      <section className="auth-panel">
        <Typography.Title level={2}>登录工作台</Typography.Title>
        <Tabs
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form layout="vertical" onFinish={submitLogin}>
                  <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
                    <Input prefix={<UserRound size={16} />} maxLength={64} />
                  </Form.Item>
                  <Form.Item label="密码" name="password" rules={[{ required: true }]}>
                    <Input.Password prefix={<LockKeyhole size={16} />} maxLength={128} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} block>
                    登录
                  </Button>
                </Form>
              )
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form layout="vertical" onFinish={submitRegister}>
                  <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
                    <Input prefix={<UserRound size={16} />} maxLength={64} />
                  </Form.Item>
                  <Form.Item label="密码" name="password" rules={[{ required: true }]}>
                    <Input.Password prefix={<LockKeyhole size={16} />} maxLength={128} />
                  </Form.Item>
                  <Form.Item label="邀请码" name="invitation_code" rules={[{ required: true }]}>
                    <Input maxLength={64} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading} block>
                    使用邀请码注册
                  </Button>
                </Form>
              )
            }
          ]}
        />
      </section>
    </main>
  );
}

export default AuthPage;
