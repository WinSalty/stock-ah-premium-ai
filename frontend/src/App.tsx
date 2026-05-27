import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button, Drawer, Layout, Menu, Skeleton, Typography, message } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  BarChart3,
  Bot,
  DatabaseZap,
  Image as ImageIcon,
  LayoutDashboard,
  LogOut,
  Menu as MenuIcon,
  MessageCircleMore,
  RadioTower,
  Send,
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
import PushplusAdminPage from './pages/PushplusAdminPage';
import LimitUpPushPage from './pages/LimitUpPushPage';
import LimitUpSharePage from './pages/LimitUpSharePage';
import ProfilePage from './pages/ProfilePage';
import LlmMetricsPage from './pages/LlmMetricsPage';
import XueqiuPublishPage from './pages/XueqiuPublishPage';
import ImageGenerationPage from './pages/ImageGenerationPage';
import { fetchCurrentUser } from './api/auth';
import { clearAuthToken, getAuthToken } from './api/client';
import type { AuthTokenResponse, UserInfo } from './types/domain';

type PageKey =
  | 'overview'
  | 'sync'
  | 'query'
  | 'premium'
  | 'chat'
  | 'image_generation'
  | 'llm_metrics'
  | 'users'
  | 'pushplus'
  | 'limit_up_push'
  | 'xueqiu_publish'
  | 'profile';

type AppMenuItem = {
  key: PageKey;
  icon: ReactNode;
  label: string;
};

const MOBILE_APP_MEDIA_QUERY = '(max-width: 720px)';
const MOBILE_PRIMARY_PAGE_KEYS: PageKey[] = ['chat', 'image_generation', 'premium', 'overview', 'profile'];

const allMenuItems: AppMenuItem[] = [
  { key: 'overview', icon: <LayoutDashboard size={18} />, label: '总览' },
  { key: 'sync', icon: <DatabaseZap size={18} />, label: '同步' },
  { key: 'query', icon: <TableProperties size={18} />, label: '查询' },
  { key: 'premium', icon: <BarChart3 size={18} />, label: '机会筛选与关注' },
  { key: 'chat', icon: <Bot size={18} />, label: '问答' },
  { key: 'image_generation', icon: <ImageIcon size={18} />, label: '图片生成' },
  { key: 'llm_metrics', icon: <Activity size={18} />, label: 'LLM 耗时' },
  { key: 'users', icon: <Users size={18} />, label: '用户管理' },
  { key: 'pushplus', icon: <MessageCircleMore size={18} />, label: 'PushPlus' },
  { key: 'limit_up_push', icon: <RadioTower size={18} />, label: '打板推送' },
  { key: 'xueqiu_publish', icon: <Send size={18} />, label: '雪球发布' },
  { key: 'profile', icon: <UserCircle size={18} />, label: '个人信息' }
];

function getPermittedPageKeys(permissions: string[]) {
  return allMenuItems.filter((item) => permissions.includes(item.key)).map((item) => item.key);
}

/**
 * 根据当前端形态选择进入页面，移动端优先把问答作为主界面，且必须严格受菜单权限约束。
 * 创建日期：2026-05-18
 * author: sunshengxian
 */
function chooseInitialPage(user: UserInfo, isMobileApp: boolean): PageKey {
  const permittedKeys = getPermittedPageKeys(user.permissions);
  const preferredKeys: PageKey[] = isMobileApp ? MOBILE_PRIMARY_PAGE_KEYS : ['overview', 'chat'];
  return preferredKeys.find((key) => permittedKeys.includes(key)) || permittedKeys[0] || 'overview';
}

/**
 * 监听移动端断点，用独立应用壳承接手机端交互，避免改动桌面端布局路径。
 * 创建日期：2026-05-18
 * author: sunshengxian
 */
function useMobileAppViewport() {
  const [isMobileApp, setIsMobileApp] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(MOBILE_APP_MEDIA_QUERY).matches
  );

  useEffect(() => {
    const media = window.matchMedia(MOBILE_APP_MEDIA_QUERY);
    const handleChange = (event: MediaQueryListEvent) => setIsMobileApp(event.matches);
    setIsMobileApp(media.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  return isMobileApp;
}

/**
 * 应用根布局与导航。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function App() {
  const queryClient = useQueryClient();
  const isMobileApp = useMobileAppViewport();
  const hasAppliedMobileDefaultRef = useRef(false);
  const shareToken = window.location.pathname.match(/^\/limit-up-share\/([^/]+)$/)?.[1];
  const [page, setPage] = useState<PageKey>('overview');
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(Boolean(getAuthToken()));
  const pages: Partial<Record<PageKey, ReactNode>> = {
    overview: user ? <OverviewPage currentUser={user} /> : null,
    sync: <SyncPage />,
    query: <DataQueryPage />,
    premium: user ? <PremiumPage currentUser={user} /> : null,
    chat: user ? <ChatPage currentUser={user} /> : null,
    image_generation: user ? <ImageGenerationPage currentUser={user} /> : null,
    llm_metrics: <LlmMetricsPage />,
    users: user ? <UserAdminPage currentUser={user} onUserUpdated={setUser} /> : null,
    pushplus: <PushplusAdminPage />,
    limit_up_push: user ? <LimitUpPushPage currentUser={user} /> : null,
    xueqiu_publish: <XueqiuPublishPage />,
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

  useEffect(() => {
    hasAppliedMobileDefaultRef.current = false;
  }, [user?.id]);

  useEffect(() => {
    if (!user || !isMobileApp || hasAppliedMobileDefaultRef.current) {
      return;
    }
    hasAppliedMobileDefaultRef.current = true;
    setPage(chooseInitialPage(user, true));
  }, [isMobileApp, user]);

  const onAuthenticated = (result: AuthTokenResponse) => {
    queryClient.clear();
    setUser(result.user);
    setPage(chooseInitialPage(result.user, isMobileApp));
  };

  const onLogout = () => {
    clearAuthToken();
    queryClient.clear();
    setUser(null);
    setPage('overview');
    message.success('已退出登录');
  };

  if (shareToken) {
    // 临时分享链接是独立公开入口，必须先于登录态判断渲染，避免查看人被带到登录页。
    return <LimitUpSharePage token={decodeURIComponent(shareToken)} />;
  }

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

  if (isMobileApp) {
    return (
      <MobileAppShell
        user={user}
        page={page}
        pages={pages}
        menuItems={menuItems}
        permittedPage={permittedPage}
        onPageChange={setPage}
        onLogout={onLogout}
      />
    );
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

interface MobileAppShellProps {
  user: UserInfo;
  page: PageKey;
  pages: Partial<Record<PageKey, ReactNode>>;
  menuItems: AppMenuItem[];
  permittedPage: boolean;
  onPageChange: (page: PageKey) => void;
  onLogout: () => void;
}

/**
 * 移动端应用壳：用顶部栏、底部导航和更多抽屉替代桌面侧边栏，保证手机端主流程像 App 一样聚焦。
 * 创建日期：2026-05-18
 * author: sunshengxian
 */
function MobileAppShell({
  user,
  page,
  pages,
  menuItems,
  permittedPage,
  onPageChange,
  onLogout
}: MobileAppShellProps) {
  const contentRef = useRef<HTMLElement | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const activePage = permittedPage ? page : (menuItems[0]?.key as PageKey);
  const primaryItems = MOBILE_PRIMARY_PAGE_KEYS
    .map((key) => menuItems.find((item) => item.key === key))
    .filter((item): item is AppMenuItem => Boolean(item));
  const fallbackPrimaryItems = primaryItems.length ? primaryItems : menuItems.slice(0, 4);
  const overflowItems = menuItems.filter((item) => !fallbackPrimaryItems.some((primary) => primary.key === item.key));
  const activeMenuItem = menuItems.find((item) => item.key === activePage);
  const displayName = user.display_name || user.username;

  const handlePageChange = (nextPage: PageKey) => {
    onPageChange(nextPage);
    setIsMenuOpen(false);
  };

  useEffect(() => {
    const content = contentRef.current;
    if (!content) {
      return;
    }
    // 移动端页面复用同一个滚动容器，切换菜单后必须回到顶部，避免沿用上个页面的滚动位置。
    content.scrollTo({ top: 0, left: 0 });
    window.scrollTo({ top: 0, left: 0 });
    window.requestAnimationFrame(() => {
      content.scrollTo({ top: 0, left: 0 });
    });
  }, [activePage]);

  return (
    <Layout className="mobile-app-shell">
      <header className="mobile-app-header">
        <div className="mobile-app-brand">
          <span className="mobile-brand-mark">AH</span>
          <div>
            <Typography.Text strong>{activeMenuItem?.label || 'Premium AI'}</Typography.Text>
            <Typography.Text type="secondary">{displayName}</Typography.Text>
          </div>
        </div>
        <Button
          type="text"
          aria-label="打开更多菜单"
          title="打开更多菜单"
          icon={<MenuIcon size={20} />}
          onClick={() => setIsMenuOpen(true)}
        />
      </header>
      <Layout.Content ref={contentRef} className={`mobile-app-content mobile-page-${activePage}`}>
        {menuItems.length && activePage ? pages[activePage] : null}
      </Layout.Content>
      <nav className="mobile-app-tabbar" aria-label="移动端主导航">
        {fallbackPrimaryItems.map((item) => (
          <button
            type="button"
            key={item.key}
            className={`mobile-tab-item${activePage === item.key ? ' active' : ''}`}
            onClick={() => handlePageChange(item.key)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
        {overflowItems.length ? (
          <button type="button" className="mobile-tab-item" onClick={() => setIsMenuOpen(true)}>
            <MenuIcon size={18} />
            <span>更多</span>
          </button>
        ) : null}
      </nav>
      <Drawer
        title="更多功能"
        placement="right"
        width="86vw"
        open={isMenuOpen}
        onClose={() => setIsMenuOpen(false)}
        className="mobile-menu-drawer"
      >
        <div className="mobile-menu-user">
          <div>
            <Typography.Text strong>{displayName}</Typography.Text>
            <Typography.Text type="secondary">{user.role === 'ADMIN' ? '管理员' : '普通用户'}</Typography.Text>
          </div>
          <Button type="text" danger icon={<LogOut size={16} />} onClick={onLogout}>
            退出
          </Button>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activePage]}
          items={menuItems}
          onClick={(info) => handlePageChange(info.key as PageKey)}
        />
      </Drawer>
    </Layout>
  );
}

export default App;
