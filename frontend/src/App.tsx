import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, Layout, Menu, Skeleton, Typography, message } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  BarChart3,
  Bot,
  DatabaseZap,
  LayoutDashboard,
  LogOut,
  TableProperties,
  UserCircle,
  Users
} from 'lucide-react';
import OverviewPage from './pages/OverviewPage';
import SyncPage from './pages/SyncPage';
import PremiumPage from './pages/PremiumPage';
import ChatPage from './pages/ChatPage';
import DataQueryPage from './pages/DataQueryPage';
import AuthPage from './pages/AuthPage';
import UserAdminPage from './pages/UserAdminPage';
import ProfilePage from './pages/ProfilePage';
import LlmMetricsPage from './pages/LlmMetricsPage';
import { fetchCurrentUser } from './api/auth';
import { clearAuthToken, getAuthToken } from './api/client';
import type { AuthTokenResponse, UserInfo } from './types/domain';

type PageKey = 'overview' | 'sync' | 'query' | 'premium' | 'chat' | 'llm_metrics' | 'users' | 'profile';

const allMenuItems = [
  { key: 'overview', icon: <LayoutDashboard size={18} />, label: '总览' },
  { key: 'sync', icon: <DatabaseZap size={18} />, label: '同步' },
  { key: 'query', icon: <TableProperties size={18} />, label: '查询' },
  { key: 'premium', icon: <BarChart3 size={18} />, label: 'AH 机会筛选' },
  { key: 'chat', icon: <Bot size={18} />, label: '问答' },
  { key: 'llm_metrics', icon: <Activity size={18} />, label: 'LLM 耗时' },
  { key: 'users', icon: <Users size={18} />, label: '用户管理' },
  { key: 'profile', icon: <UserCircle size={18} />, label: '个人信息' }
];

/**
 * 应用根布局与导航。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function App() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState<PageKey>('overview');
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(Boolean(getAuthToken()));
  const pages: Partial<Record<PageKey, ReactNode>> = {
    overview: <OverviewPage />,
    sync: <SyncPage />,
    query: <DataQueryPage />,
    premium: <PremiumPage />,
    chat: <ChatPage />,
    llm_metrics: <LlmMetricsPage />,
    users: user ? <UserAdminPage currentUser={user} onUserUpdated={setUser} /> : null,
    profile: user ? <ProfilePage user={user} onUserUpdated={setUser} /> : null
  };
  const menuItems = useMemo(() => {
    const permissions = new Set(user?.permissions || []);
    return allMenuItems.filter((item) => permissions.has(item.key));
  }, [user?.permissions]);
  const permittedPage = menuItems.some((item) => item.key === page);

  useEffect(() => {
    if (!getAuthToken()) {
      setIsCheckingAuth(false);
      return;
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => {
        clearAuthToken();
        setUser(null);
      })
      .finally(() => setIsCheckingAuth(false));
  }, []);

  useEffect(() => {
    if (menuItems.length && !permittedPage) {
      setPage(menuItems[0].key as PageKey);
    }
  }, [menuItems, permittedPage]);

  const onAuthenticated = (result: AuthTokenResponse) => {
    queryClient.clear();
    setUser(result.user);
    setPage(result.user.permissions.includes('overview') ? 'overview' : (result.user.permissions[0] as PageKey));
  };

  const onLogout = () => {
    clearAuthToken();
    queryClient.clear();
    setUser(null);
    setPage('overview');
    message.success('已退出登录');
  };

  if (isCheckingAuth) {
    return (
      <main className="auth-loading">
        <Skeleton active paragraph={{ rows: 4 }} />
      </main>
    );
  }

  if (!user) {
    return <AuthPage onAuthenticated={onAuthenticated} />;
  }

  return (
    <Layout className="app-shell">
      <Layout.Sider className="app-sider" width={216} breakpoint="lg" collapsedWidth={64}>
        <div className="brand-block">
          <div className="brand-mark">AH</div>
          <div className="brand-text">
            <Typography.Text strong>港股通 A/H</Typography.Text>
            <Typography.Text type="secondary">Premium AI</Typography.Text>
          </div>
        </div>
        <Menu
          className="app-menu"
          mode="inline"
          selectedKeys={[page]}
          items={menuItems}
          onClick={(info) => setPage(info.key as PageKey)}
        />
        <div className="app-user-block">
          <div>
            <Typography.Text strong>{user.display_name || user.username}</Typography.Text>
            <Typography.Text type="secondary">{user.role === 'ADMIN' ? '管理员' : '普通用户'}</Typography.Text>
          </div>
          <Button type="text" icon={<LogOut size={16} />} onClick={onLogout} />
        </div>
      </Layout.Sider>
      <Layout.Content className="app-content">
        {menuItems.length ? pages[permittedPage ? page : (menuItems[0]?.key as PageKey)] : null}
      </Layout.Content>
    </Layout>
  );
}

export default App;
