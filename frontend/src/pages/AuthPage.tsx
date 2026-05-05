import { Button, Checkbox, Form, Input, Tabs, Typography, message } from 'antd';
import { BarChart3, BriefcaseBusiness, Database, KeyRound, LockKeyhole, UserRound } from 'lucide-react';
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
      setAuthToken(result.token, values.remember_login !== false);
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
        <div className="auth-brand-row">
          <div className="auth-mark">AH</div>
          <Typography.Text strong>港股通 A/H Premium AI</Typography.Text>
        </div>
        <div className="auth-hero-copy">
          <Typography.Title level={1}>智能洞察&nbsp;&nbsp;价值先机</Typography.Title>
          <Typography.Paragraph>
            用自选阈值、价差分位和本地投研知识库，把 A/H 价差机会收进同一个工作台。
          </Typography.Paragraph>
        </div>
        <div className="auth-feature-strip">
          <div className="auth-feature-item">
            <span className="auth-feature-icon auth-feature-blue">
              <BarChart3 size={23} />
            </span>
            <div>
              <Typography.Text strong>价差分析</Typography.Text>
              <Typography.Text>实时捕捉 A/H 价差机会</Typography.Text>
            </div>
          </div>
          <div className="auth-feature-item">
            <span className="auth-feature-icon auth-feature-green">
              <Database size={23} />
            </span>
            <div>
              <Typography.Text strong>知识库</Typography.Text>
              <Typography.Text>本地投研知识沉淀</Typography.Text>
            </div>
          </div>
          <div className="auth-feature-item">
            <span className="auth-feature-icon auth-feature-purple">
              <BriefcaseBusiness size={23} />
            </span>
            <div>
              <Typography.Text strong>工作台</Typography.Text>
              <Typography.Text>一站式智能决策平台</Typography.Text>
            </div>
          </div>
        </div>
        <svg className="auth-chart-svg" viewBox="0 0 920 300" role="img" aria-label="A/H 价差趋势插画">
          <defs>
            <linearGradient id="authLineBlue" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#88e7ff" />
              <stop offset="100%" stopColor="#7fb0ff" />
            </linearGradient>
            <linearGradient id="authLineGreen" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#9fe7db" />
              <stop offset="100%" stopColor="#58e49d" />
            </linearGradient>
          </defs>
          <g opacity="0.18">
            <rect x="18" y="170" width="36" height="90" rx="2" fill="#ffffff" />
            <rect x="74" y="132" width="36" height="128" rx="2" fill="#ffffff" />
            <rect x="130" y="104" width="36" height="156" rx="2" fill="#ffffff" />
            <rect x="186" y="198" width="36" height="62" rx="2" fill="#ffffff" />
          </g>
          <path
            d="M0 250 C92 204, 168 204, 246 222 S382 122, 486 166 602 188, 694 146 822 48, 900 66"
            fill="none"
            opacity="0.9"
            stroke="url(#authLineBlue)"
            strokeLinecap="round"
            strokeWidth="5"
          />
          <path
            d="M0 248 C98 202, 172 210, 250 220 S364 154, 448 134 548 218, 628 132 736 204, 850 96"
            fill="none"
            opacity="0.82"
            stroke="url(#authLineGreen)"
            strokeLinecap="round"
            strokeWidth="5"
          />
          <path
            d="M0 252 C92 208, 166 208, 246 226 S382 128, 486 172 602 194, 694 152 822 54, 900 72"
            fill="none"
            opacity="0.14"
            stroke="#ffffff"
            strokeLinecap="round"
            strokeWidth="18"
          />
          <g fill="#ffffff">
            <circle cx="250" cy="220" r="9" />
            <circle cx="548" cy="176" r="9" />
            <circle cx="736" cy="164" r="9" />
            <circle cx="914" cy="64" r="9" />
          </g>
          <g opacity="0.22">
            <circle cx="250" cy="220" r="22" fill="#59e7a4" />
            <circle cx="548" cy="176" r="22" fill="#75d8ff" />
            <circle cx="736" cy="164" r="22" fill="#66b2ff" />
            <circle cx="914" cy="64" r="22" fill="#66b2ff" />
          </g>
        </svg>
      </section>
      <section className="auth-form-area">
        <div className="auth-panel">
          <svg className="auth-login-illustration" viewBox="0 0 260 150" role="img" aria-label="智能投研插画">
            <defs>
              <linearGradient id="authPanelCard" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0%" stopColor="#dbeafe" />
                <stop offset="100%" stopColor="#8ab8ff" />
              </linearGradient>
              <linearGradient id="authPanelBar" x1="0" x2="0" y1="1" y2="0">
                <stop offset="0%" stopColor="#7dd3fc" />
                <stop offset="100%" stopColor="#2563eb" />
              </linearGradient>
            </defs>
            <ellipse cx="132" cy="110" rx="86" ry="18" fill="#dbeafe" opacity="0.65" />
            <path d="M58 100 C102 72, 158 132, 212 76" fill="none" stroke="#7dd3fc" strokeWidth="6" />
            <path d="M64 100 C104 66, 158 122, 210 72" fill="none" stroke="#2563eb" strokeWidth="4" opacity="0.55" />
            <rect x="92" y="20" width="94" height="92" rx="14" fill="url(#authPanelCard)" opacity="0.86" />
            <path d="M108 66 L130 44 L150 58 L170 32" fill="none" stroke="#ffffff" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5" />
            <rect x="116" y="76" width="13" height="26" rx="3" fill="url(#authPanelBar)" opacity="0.58" />
            <rect x="138" y="64" width="13" height="38" rx="3" fill="url(#authPanelBar)" opacity="0.72" />
            <rect x="160" y="48" width="13" height="54" rx="3" fill="url(#authPanelBar)" />
            <circle cx="172" cy="31" r="8" fill="#ffffff" />
            <rect x="50" y="54" width="26" height="26" rx="3" fill="#dbeafe" />
          </svg>
          <div className="auth-panel-head">
            <Typography.Title level={2}>欢迎登录</Typography.Title>
            <Typography.Text type="secondary">港股通 A/H Premium AI</Typography.Text>
          </div>
          <Tabs
            centered
            items={[
              {
                key: 'login',
                label: '登录',
                children: (
                  <Form
                    initialValues={{ remember_login: true }}
                    layout="vertical"
                    requiredMark={false}
                    onFinish={submitLogin}
                  >
                    <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
                      <Input prefix={<UserRound size={17} />} placeholder="请输入用户名" maxLength={64} />
                    </Form.Item>
                    <Form.Item label="密码" name="password" rules={[{ required: true }]}>
                      <Input.Password prefix={<LockKeyhole size={17} />} placeholder="请输入密码" maxLength={128} />
                    </Form.Item>
                    <Form.Item name="remember_login" valuePropName="checked">
                      <Checkbox>记住登录，一个月内免登录</Checkbox>
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
                  <Form layout="vertical" requiredMark={false} onFinish={submitRegister}>
                    <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
                      <Input prefix={<UserRound size={17} />} placeholder="请输入用户名" maxLength={64} />
                    </Form.Item>
                    <Form.Item label="密码" name="password" rules={[{ required: true }]}>
                      <Input.Password prefix={<LockKeyhole size={17} />} placeholder="请输入密码" maxLength={128} />
                    </Form.Item>
                    <Form.Item label="邀请码" name="invitation_code" rules={[{ required: true }]}>
                      <Input prefix={<KeyRound size={17} />} placeholder="请输入邀请码" maxLength={64} />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" loading={loading} block>
                      使用邀请码注册
                    </Button>
                  </Form>
                )
              }
            ]}
          />
        </div>
      </section>
    </main>
  );
}

export default AuthPage;
