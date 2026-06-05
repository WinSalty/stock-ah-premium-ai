import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button, Drawer, Layout, Menu, Skeleton, Typography, message } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  BarChart3,
  Bot,
  Coins,
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
import DividendReinvestmentPage from './pages/DividendReinvestmentPage';
import { fetchCurrentUser } from './api/auth';
import { clearAuthToken, getAuthToken } from './api/client';
import type { AuthTokenResponse, UserInfo } from './types/domain';

type PageKey =
  | 'overview'
  | 'sync'
  | 'query'
  | 'premium'
  | 'dividend_reinvestment'
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
const MOBILE_KEYBOARD_INSET_THRESHOLD = 80;
const MOBILE_PRIMARY_PAGE_KEYS: PageKey[] = ['chat', 'image_generation', 'premium', 'overview', 'profile'];
const PAGE_QUERY_KEY = 'page';

const allMenuItems: AppMenuItem[] = [
  { key: 'overview', icon: <LayoutDashboard size={18} />, label: '总览' },
  { key: 'sync', icon: <DatabaseZap size={18} />, label: '同步' },
  { key: 'query', icon: <TableProperties size={18} />, label: '查询' },
  { key: 'premium', icon: <BarChart3 size={18} />, label: '机会筛选与关注' },
  { key: 'dividend_reinvestment', icon: <Coins size={18} />, label: '分红再投筛选' },
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
function chooseInitialPage(user: UserInfo, isMobileApp: boolean, requestedPage?: PageKey | null): PageKey {
  const permittedKeys = getPermittedPageKeys(user.permissions);
  if (requestedPage && permittedKeys.includes(requestedPage)) {
    return requestedPage;
  }
  const preferredKeys: PageKey[] = isMobileApp ? MOBILE_PRIMARY_PAGE_KEYS : ['overview', 'chat'];
  return preferredKeys.find((key) => permittedKeys.includes(key)) || permittedKeys[0] || 'overview';
}

/** 从地址栏恢复当前菜单页，刷新浏览器后仍停留在用户最后查看的功能页。创建日期：2026-06-02 author: sunshengxian */
function getPageFromLocation(): PageKey | null {
  if (typeof window === 'undefined') {
    return null;
  }
  const rawPage = new URLSearchParams(window.location.search).get(PAGE_QUERY_KEY);
  return allMenuItems.some((item) => item.key === rawPage) ? (rawPage as PageKey) : null;
}

/** 把当前菜单写入地址栏但不堆叠历史记录，避免刷新丢页面同时不打乱浏览器返回行为。创建日期：2026-06-02 author: sunshengxian */
function replacePageInUrl(page: PageKey | null) {
  if (typeof window === 'undefined') {
    return;
  }
  const nextUrl = new URL(window.location.href);
  if (page) {
    nextUrl.searchParams.set(PAGE_QUERY_KEY, page);
  } else {
    nextUrl.searchParams.delete(PAGE_QUERY_KEY);
  }
  const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextPath !== currentPath) {
    window.history.replaceState(window.history.state, '', nextPath);
  }
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
 * 同步移动端实际可视高度到 CSS 变量，避免浏览器地址栏或 WebView 高度变化时把底部导航挤到页面中部。
 * 创建日期：2026-05-30
 * author: sunshengxian
 */
function useMobileVisualViewportHeight(enabled: boolean) {
  const stableViewportHeightRef = useRef<number | null>(null);
  const scrollResetFrameRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      return;
    }

    const root = document.documentElement;
    root.classList.add('mobile-app-viewport');
    const updateViewportHeight = () => {
      // visualViewport 能反映移动端地址栏收起、横竖屏切换和键盘弹起后的真实可见高度；
      // iOS 部分浏览器会在键盘弹起时同步缩小 innerHeight，因此这里用最近一次非键盘稳定高度
      // 反推键盘遮挡量，避免差值被算成 0 后整页被浏览器聚焦滚动顶到上方。
      const layoutHeight = window.innerHeight;
      const visualViewport = window.visualViewport;
      const viewportHeight = visualViewport?.height || layoutHeight;
      const viewportOffsetTop = visualViewport?.offsetTop || 0;
      const observedViewportBottom = Math.round(viewportHeight + viewportOffsetTop);
      const previousStableHeight = stableViewportHeightRef.current || Math.max(layoutHeight, observedViewportBottom);
      const keyboardInset = Math.max(
        0,
        layoutHeight - viewportHeight - viewportOffsetTop,
        previousStableHeight - viewportHeight - viewportOffsetTop
      );
      const isKeyboardOpen = keyboardInset > MOBILE_KEYBOARD_INSET_THRESHOLD;
      if (!isKeyboardOpen || stableViewportHeightRef.current === null) {
        stableViewportHeightRef.current = Math.max(
          stableViewportHeightRef.current || 0,
          layoutHeight,
          observedViewportBottom
        );
      }
      const appHeight = isKeyboardOpen
        ? stableViewportHeightRef.current || viewportHeight
        : viewportHeight;
      root.style.setProperty('--mobile-app-height', `${Math.round(appHeight)}px`);
      root.style.setProperty('--mobile-keyboard-inset', `${Math.round(keyboardInset)}px`);
      root.classList.toggle('mobile-keyboard-open', isKeyboardOpen);
      if (isKeyboardOpen && scrollResetFrameRef.current === null) {
        // 键盘聚焦时移动端浏览器可能会尝试滚动文档来暴露输入框；应用壳本身固定在视口内，
        // 因此把外层文档滚回顶部，真正的内容滚动只交给问答历史区处理。
        scrollResetFrameRef.current = window.requestAnimationFrame(() => {
          scrollResetFrameRef.current = null;
          window.scrollTo({ top: 0, left: 0 });
        });
      }
    };

    const resetViewportHeight = () => {
      // 横竖屏切换会改变布局基准，高度缓存必须清空后重算，避免沿用上一方向误判键盘遮挡。
      stableViewportHeightRef.current = null;
      updateViewportHeight();
    };

    updateViewportHeight();
    window.addEventListener('resize', updateViewportHeight);
    window.addEventListener('orientationchange', resetViewportHeight);
    window.visualViewport?.addEventListener('resize', updateViewportHeight);
    window.visualViewport?.addEventListener('scroll', updateViewportHeight);

    return () => {
      if (scrollResetFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollResetFrameRef.current);
        scrollResetFrameRef.current = null;
      }
      window.removeEventListener('resize', updateViewportHeight);
      window.removeEventListener('orientationchange', resetViewportHeight);
      window.visualViewport?.removeEventListener('resize', updateViewportHeight);
      window.visualViewport?.removeEventListener('scroll', updateViewportHeight);
      root.style.removeProperty('--mobile-app-height');
      root.style.removeProperty('--mobile-keyboard-inset');
      root.classList.remove('mobile-app-viewport');
      root.classList.remove('mobile-keyboard-open');
      stableViewportHeightRef.current = null;
    };
  }, [enabled]);
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
  const initialPageFromUrlRef = useRef<PageKey | null>(getPageFromLocation());
  const shareToken = window.location.pathname.match(/^\/limit-up-share\/([^/]+)$/)?.[1];
  const [page, setPage] = useState<PageKey>(() => initialPageFromUrlRef.current || 'overview');
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(Boolean(getAuthToken()));
  // 视觉视口锁只服务登录后的移动端应用壳；登录页需要保留浏览器原生滚动，避免密码框聚焦后卡住。
  useMobileVisualViewportHeight(isMobileApp && Boolean(user));
  const pages: Partial<Record<PageKey, ReactNode>> = {
    overview: user ? <OverviewPage currentUser={user} /> : null,
    sync: <SyncPage />,
    query: <DataQueryPage />,
    premium: user ? <PremiumPage currentUser={user} /> : null,
    dividend_reinvestment: <DividendReinvestmentPage />,
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
    const handlePopState = () => {
      // 用户使用浏览器前进/后退时重新读取菜单参数，权限不匹配时交给 permittedPage 兜底逻辑修正。
      setPage(getPageFromLocation() || 'overview');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    if (!user || !permittedPage || shareToken) {
      return;
    }
    replacePageInUrl(page);
  }, [page, permittedPage, shareToken, user]);

  useEffect(() => {
    hasAppliedMobileDefaultRef.current = false;
  }, [user?.id]);

  useEffect(() => {
    if (!user || !isMobileApp || hasAppliedMobileDefaultRef.current || initialPageFromUrlRef.current) {
      return;
    }
    hasAppliedMobileDefaultRef.current = true;
    setPage(chooseInitialPage(user, true));
  }, [isMobileApp, user]);

  const onAuthenticated = (result: AuthTokenResponse) => {
    queryClient.clear();
    setUser(result.user);
    setPage(chooseInitialPage(result.user, isMobileApp, initialPageFromUrlRef.current));
  };

  const onLogout = () => {
    clearAuthToken();
    queryClient.clear();
    setUser(null);
    setPage('overview');
    replacePageInUrl(null);
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
