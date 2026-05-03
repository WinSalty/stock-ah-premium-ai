import { useMemo, useState, type ReactNode } from 'react';
import { Layout, Menu, Typography } from 'antd';
import { BarChart3, Bot, DatabaseZap, LayoutDashboard } from 'lucide-react';
import OverviewPage from './pages/OverviewPage';
import SyncPage from './pages/SyncPage';
import PremiumPage from './pages/PremiumPage';
import ChatPage from './pages/ChatPage';

type PageKey = 'overview' | 'sync' | 'premium' | 'chat';

const pages: Record<PageKey, ReactNode> = {
  overview: <OverviewPage />,
  sync: <SyncPage />,
  premium: <PremiumPage />,
  chat: <ChatPage />
};

/**
 * 应用根布局与导航。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function App() {
  const [page, setPage] = useState<PageKey>('overview');
  const menuItems = useMemo(
    () => [
      { key: 'overview', icon: <LayoutDashboard size={18} />, label: '总览' },
      { key: 'sync', icon: <DatabaseZap size={18} />, label: '同步' },
      { key: 'premium', icon: <BarChart3 size={18} />, label: '溢价' },
      { key: 'chat', icon: <Bot size={18} />, label: '问答' }
    ],
    []
  );

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
      </Layout.Sider>
      <Layout.Content className="app-content">{pages[page]}</Layout.Content>
    </Layout>
  );
}

export default App;
