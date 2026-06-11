import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Popover,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  Typography,
  message
} from 'antd';
import ReactECharts from 'echarts-for-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import { Bot, GripVertical, QrCode, Settings, SlidersHorizontal, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type WheelEvent } from 'react';
import LlmProgressNote from '../components/LlmProgressNote';
import PageHeader from '../components/PageHeader';
import { createChatSession, sendChatMessageStream } from '../api/chat';
import {
  fetchOfficialPremiumTrend,
  fetchPremiumPairs,
  fetchRealtimePremiums
} from '../api/market';
import { fetchOverviewChartSettings, updateOverviewChartSettings } from '../api/settings';
import { createPushplusQrCode, fetchPushplusBinding } from '../api/notifications';
import { deleteWatchlistItem, fetchWatchlist, updateWatchlistItem } from '../api/watchlist';
import type {
  HoldingMarket,
  OverviewChartSettings,
  PremiumDirection,
  PremiumPairOption,
  PriceAlertOperator,
  ThresholdRecommendationContext,
  UserInfo,
  WatchlistOpportunity,
  WatchlistTargetType
} from '../types/domain';
import {
  getCachedThresholdRecommendation,
  setCachedThresholdRecommendation
} from '../utils/thresholdRecommendationCache';
import { OVERVIEW_SNIPPETS } from '../constants/overviewSnippets';
import { PUSHPLUS_BIND_SUCCESS_NOTICE } from '../constants/pushplus';

const DEFAULT_PAIR_KEY = '600036.SH|03968.HK';
const DEFAULT_VISIBLE_MONTHS = 3;
const MIN_VISIBLE_POINTS = 20;
const TRACKPAD_WHEEL_UNIT = 80;
const WATCHLIST_REALTIME_REFRESH_MS = 1000;
const AH_REALTIME_MORNING_START_MINUTES = 9 * 60 + 30;
const AH_REALTIME_MORNING_END_MINUTES = 12 * 60;
const AH_REALTIME_AFTERNOON_START_MINUTES = 13 * 60;
const AH_REALTIME_AFTERNOON_END_MINUTES = 16 * 60;
const AH_COLOR = '#e11d48';
const HA_COLOR = '#0891b2';
const MEDIAN60_COLOR = '#475569';
const P20_COLOR = '#16a34a';
const P80_COLOR = '#f59e0b';
const TARGET_COLOR = '#7f1d1d';
const MEDIAN60_LINE_STYLE = { width: 1.8, color: MEDIAN60_COLOR, type: 'dashed' };
const RANDOM_SNIPPET_COUNT = 4;
const DEFAULT_OVERVIEW_CHART_SETTINGS: OverviewChartSettings = {
  metric_premium: true,
  median_60: true,
  p20_60: true,
  p80_60: true,
  target_threshold: true
};
const CHART_INDICATOR_OPTIONS: Array<{
  label: string;
  value: keyof OverviewChartSettings;
  required?: boolean;
}> = [
  { label: '溢价走势', value: 'metric_premium', required: true },
  { label: '60日中位数', value: 'median_60' },
  { label: '20%分位', value: 'p20_60' },
  { label: '80%分位', value: 'p80_60' },
  { label: '目标阈值', value: 'target_threshold' }
];

interface WatchlistFormValues {
  target_type?: WatchlistTargetType;
  display_name?: string;
  preferred_direction: PremiumDirection;
  target_premium_pct?: number | null;
  push_enabled?: boolean;
  a_price_alert_enabled?: boolean;
  a_price_alert_operator?: PriceAlertOperator;
  a_price_alert_target_price?: number | null;
  h_price_alert_enabled?: boolean;
  h_price_alert_operator?: PriceAlertOperator;
  h_price_alert_target_price?: number | null;
  holding_market: HoldingMarket;
}

function splitPairKey(value: string) {
  const [aTsCode, hkTsCode] = value.split('|');
  return { aTsCode, hkTsCode };
}

function formatPairLabel(item: PremiumPairOption) {
  const rawAName = item.a_name?.trim();
  const exRightMatch = exRightNameMatch(rawAName);
  const exRightLabelMap: Record<string, string> = {
    XD: '除息',
    XR: '除权',
    DR: '除权除息'
  };
  const cleanAName = exRightMatch?.[2]?.trim() || rawAName;
  const aName = cleanAName || item.a_ts_code;
  const hkName = item.hk_name?.trim() || item.hk_ts_code;
  const codeLabel = `${item.a_ts_code} / ${item.hk_ts_code}`;
  const exRightLabel = exRightMatch ? exRightLabelMap[exRightMatch[1]] : null;
  const aDisplayName = exRightLabel ? `${aName}（${exRightLabel}）` : aName;

  if (aName === hkName) {
    return `${aDisplayName} (${codeLabel})`;
  }

  return `${aDisplayName} / ${hkName} (${codeLabel})`;
}

function exRightNameMatch(value?: string | null) {
  return value?.trim().match(/^(XD|XR|DR)(.+)$/);
}

function shouldReplacePairOption(current: PremiumPairOption, candidate: PremiumPairOption) {
  return Boolean(exRightNameMatch(current.a_name)) && !exRightNameMatch(candidate.a_name);
}

function getDefaultZoomStartValue(tradeDates: string[]) {
  if (!tradeDates.length) {
    return undefined;
  }
  const latestDate = parseLocalDate(tradeDates[tradeDates.length - 1]);
  latestDate.setMonth(latestDate.getMonth() - DEFAULT_VISIBLE_MONTHS);
  return tradeDates.find((item) => parseLocalDate(item) >= latestDate) || tradeDates[0];
}

function parseLocalDate(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function numberValue(value?: string | null) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function dataZoomValueIndex(value: string | number | undefined, dates: string[], fallback: number) {
  if (value === undefined) {
    return fallback;
  }
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0 && value < dates.length) {
    return value;
  }
  const index = dates.indexOf(String(value));
  return index >= 0 ? index : fallback;
}

function formatPercent(value?: string | null) {
  const parsed = numberValue(value);
  return parsed === null ? '-' : `${parsed.toFixed(2)}%`;
}

function metricToneClass(value?: string | null) {
  const parsed = numberValue(value);
  if (parsed === null) {
    return 'metric-muted';
  }
  if (parsed > 0) {
    return 'metric-positive';
  }
  if (parsed < 0) {
    return 'metric-negative';
  }
  return 'metric-neutral';
}

function percentileToneClass(value?: string | null) {
  const parsed = numberValue(value);
  if (parsed === null) {
    return 'metric-muted';
  }
  if (parsed >= 80) {
    return 'metric-hot';
  }
  if (parsed <= 20) {
    return 'metric-cold';
  }
  return 'metric-neutral';
}

function formatPrice(value?: string | null, market: 'A' | 'H' = 'A') {
  const parsed = numberValue(value);
  if (parsed === null) {
    return '-';
  }
  const symbol = market === 'H' ? 'HK$' : '¥';
  return `${symbol}${parsed.toFixed(market === 'H' ? 3 : 2)}`;
}

function opportunityPrice(item: WatchlistOpportunity, market: 'A' | 'H') {
  if (isPairOpportunity(item)) {
    return market === 'A'
      ? formatPrice(item.premium?.a_close, 'A')
      : formatPrice(item.premium?.hk_close, 'H');
  }
  return formatPrice(item.single_quote?.last_price, market);
}

function singleQuoteStatusTag(item: WatchlistOpportunity) {
  const quality = item.single_quote?.quality || 'UNAVAILABLE';
  const labelMap: Record<string, string> = {
    REALTIME: '实时',
    STALE: '最近快照',
    UNAVAILABLE: '暂无报价'
  };
  const colorMap: Record<string, string> = {
    REALTIME: 'green',
    STALE: 'orange',
    UNAVAILABLE: 'default'
  };
  return <Tag color={colorMap[quality] || 'default'}>{labelMap[quality] || quality}</Tag>;
}

function singleQuoteTimeText(item: WatchlistOpportunity) {
  if (!item.single_quote?.quote_time) {
    return '行情日期缺失';
  }
  const date = new Date(item.single_quote.quote_time);
  if (Number.isNaN(date.getTime())) {
    return '行情日期缺失';
  }
  return `行情日期 ${date.toLocaleDateString('zh-CN')}`;
}

function priceAlertText(item: WatchlistOpportunity) {
  const alerts: string[] = [];
  if (item.watchlist.a_price_alert_enabled && item.watchlist.a_price_alert_target_price !== null) {
    const operator = item.watchlist.a_price_alert_operator === 'LTE' ? '≤' : '≥';
    alerts.push(`A 股 ${operator} ${formatPrice(item.watchlist.a_price_alert_target_price, 'A')}`);
  }
  if (item.watchlist.h_price_alert_enabled && item.watchlist.h_price_alert_target_price !== null) {
    const operator = item.watchlist.h_price_alert_operator === 'LTE' ? '≤' : '≥';
    alerts.push(`H 股 ${operator} ${formatPrice(item.watchlist.h_price_alert_target_price, 'H')}`);
  }
  if (alerts.length === 0) {
    return '股价阈值未设';
  }
  return alerts.join(' / ');
}

function thresholdHelpText(direction?: PremiumDirection) {
  const directionLabel = direction === 'AH' ? 'A/H' : 'H/A';
  return `填写 ${directionLabel} 溢价触发线，单位为百分比；留空则只观察不判断达阈值。系统按“当前${directionLabel}溢价 >= 目标阈值”判定达阈值。`;
}

function hasAlertConfig(values: WatchlistFormValues) {
  return (
    values.target_premium_pct !== null &&
    values.target_premium_pct !== undefined
  ) || Boolean(
    (values.a_price_alert_enabled &&
      values.a_price_alert_target_price !== null &&
      values.a_price_alert_target_price !== undefined) ||
      (values.h_price_alert_enabled &&
        values.h_price_alert_target_price !== null &&
        values.h_price_alert_target_price !== undefined)
  );
}

function isTradingRefreshWindow(now = new Date()) {
  const day = now.getDay();
  if (day === 0 || day === 6) {
    return false;
  }
  const minutes = now.getHours() * 60 + now.getMinutes();
  return (
    (minutes >= AH_REALTIME_MORNING_START_MINUTES && minutes <= AH_REALTIME_MORNING_END_MINUTES) ||
    (minutes >= AH_REALTIME_AFTERNOON_START_MINUTES && minutes <= AH_REALTIME_AFTERNOON_END_MINUTES)
  );
}

function statusTag(status?: string | null) {
  const labelMap: Record<string, string> = {
    REACHED: '已达阈值',
    TRIGGERED: '已达阈值',
    NEAR: '接近阈值',
    NEAR_TARGET: '接近阈值',
    WATCH: '正常观察',
    WATCHING: '正常观察',
    DATA_ISSUE: '数据异常',
    DATA_UNAVAILABLE: '数据缺失',
    DELAYED_ONLY: '行情延迟',
    NO_TARGET: '未设阈值',
    NOT_CONNECT: '不可操作'
  };
  const colorMap: Record<string, string> = {
    REACHED: 'red',
    TRIGGERED: 'red',
    NEAR: 'gold',
    NEAR_TARGET: 'gold',
    WATCH: 'blue',
    WATCHING: 'blue',
    DATA_ISSUE: 'orange',
    DATA_UNAVAILABLE: 'orange',
    DELAYED_ONLY: 'orange',
    NO_TARGET: 'default',
    NOT_CONNECT: 'default'
  };
  const key = status || 'WATCH';
  return <Tag color={colorMap[key] || 'default'}>{labelMap[key] || key}</Tag>;
}

function opportunityName(item: WatchlistOpportunity) {
  return (
    item.watchlist.display_name ||
    item.premium?.a_name ||
    item.premium?.hk_name ||
    item.watchlist.a_ts_code ||
    item.watchlist.hk_ts_code ||
    `自选标的 ${item.watchlist.id}`
  );
}

function opportunityTargetType(item: WatchlistOpportunity): WatchlistTargetType {
  return (item.watchlist.target_type as WatchlistTargetType) || 'PAIR';
}

function isPairOpportunity(item: WatchlistOpportunity) {
  return opportunityTargetType(item) === 'PAIR';
}

function opportunityCodeLabel(item: WatchlistOpportunity) {
  if (isPairOpportunity(item)) {
    return `${item.watchlist.a_ts_code || '-'} / ${item.watchlist.hk_ts_code || '-'}`;
  }
  return item.watchlist.a_ts_code || item.watchlist.hk_ts_code || '-';
}

function opportunityPairKey(item: WatchlistOpportunity) {
  const aTsCode = item.premium?.a_ts_code || item.watchlist.a_ts_code;
  const hkTsCode = item.premium?.hk_ts_code || item.watchlist.hk_ts_code;
  return aTsCode && hkTsCode ? `${aTsCode}|${hkTsCode}` : '';
}

function opportunityDirection(item: WatchlistOpportunity): PremiumDirection {
  return item.premium?.metric_direction || item.watchlist.preferred_direction;
}

function holdingMarketLabel(value?: string | null) {
  const map: Record<string, string> = {
    A: 'A 股',
    H: 'H 股',
    UNKNOWN: '未设置'
  };
  return map[value || 'UNKNOWN'] || value || '未设置';
}

function promptValue(value?: string | null, suffix = '') {
  return value === null || value === undefined || value === '' ? '缺失' : `${value}${suffix}`;
}

function pickRandomSnippets(source: readonly string[], count: number) {
  const pool = [...source];
  for (let index = pool.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    [pool[index], pool[randomIndex]] = [pool[randomIndex], pool[index]];
  }
  return pool.slice(0, count);
}

function reorderOpportunities(items: WatchlistOpportunity[], sourceId: number, targetId: number) {
  const sourceIndex = items.findIndex((item) => item.watchlist.id === sourceId);
  const targetIndex = items.findIndex((item) => item.watchlist.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) {
    return items;
  }
  const nextItems = [...items];
  const [moved] = nextItems.splice(sourceIndex, 1);
  nextItems.splice(targetIndex, 0, moved);
  return nextItems;
}

function buildThresholdRecommendationPrompt(item: WatchlistOpportunity) {
  const premium = item.premium;
  const direction = opportunityDirection(item);
  const directionLabel = direction === 'AH' ? 'A/H' : 'H/A';
  return [
    `请为自选股“${opportunityName(item)}”推荐一个 ${directionLabel} 目标阈值。`,
    '你是 A/H 跨市场价差研究助手，请结合页面给出的价差分位、持有侧和当前阈值，给出稳定、可复核的建议。',
    '',
    '页面数据：',
    `- A 股 / H 股代码：${item.watchlist.a_ts_code} / ${item.watchlist.hk_ts_code}`,
    `- 关注方向：${directionLabel}`,
    `- 持有侧：${holdingMarketLabel(item.watchlist.holding_market)}`,
    `- 当前目标阈值：${promptValue(item.watchlist.target_premium_pct, '%')}`,
    `- 当前 ${directionLabel} 溢价：${promptValue(premium?.metric_premium_pct, '%')}`,
    `- A/H 溢价：${promptValue(premium?.ah_premium_pct, '%')}`,
    `- H/A 溢价：${promptValue(premium?.ha_premium_pct, '%')}`,
    `- 距当前阈值：${promptValue(premium?.distance_to_target_pct, '%')}`,
    `- 60 日中位数：${promptValue(premium?.premium_median_60, '%')}`,
    `- 60 日 20% 分位：${promptValue(premium?.premium_p20_60, '%')}`,
    `- 60 日 80% 分位：${promptValue(premium?.premium_p80_60, '%')}`,
    `- 当前 60 日分位：${promptValue(premium?.premium_percentile_60, '%')}`,
    `- 港股通通道：${premium?.connect_channels || '不可通过港股通操作或缺失'}`,
    '',
    '请严格输出中文 Markdown，并包含以下三个小节。不要输出“不构成投资建议”等免责句。',
    '## 最终答案',
    `用一句话给出建议阈值，格式必须包含“建议将 ${directionLabel} 目标阈值设为 X%”。`,
    '## 推荐理由',
    '用 3-5 条说明采用的分位、当前价差、持有侧、通道可操作性和阈值缓冲。',
    '## 执行条件',
    '给出何时触发、何时上调/下调阈值、需要复核的成交活跃度、汇率和基本面条件。'
  ].join('\n');
}

function buildThresholdDisplayQuestion(item: WatchlistOpportunity) {
  const direction = opportunityDirection(item);
  const directionLabel = direction === 'AH' ? 'A/H' : 'H/A';
  return `为${opportunityName(item)}推荐 ${directionLabel} 目标阈值`;
}

function buildThresholdRecommendationContext(item: WatchlistOpportunity): ThresholdRecommendationContext {
  const premium = item.premium;
  const direction = opportunityDirection(item);
  // 结构化上下文只承载页面已经展示的数据，后端据此走阈值快路径，避免再路由、消歧或查辅助视图。
  return {
    name: opportunityName(item),
    a_ts_code: item.watchlist.a_ts_code,
    hk_ts_code: item.watchlist.hk_ts_code,
    direction,
    holding_market: item.watchlist.holding_market,
    target_premium_pct: numberValue(item.watchlist.target_premium_pct),
    metric_premium_pct: numberValue(premium?.metric_premium_pct),
    ah_premium_pct: numberValue(premium?.ah_premium_pct),
    ha_premium_pct: numberValue(premium?.ha_premium_pct),
    distance_to_target_pct: numberValue(premium?.distance_to_target_pct),
    premium_median_60: numberValue(premium?.premium_median_60),
    premium_p20_60: numberValue(premium?.premium_p20_60),
    premium_p80_60: numberValue(premium?.premium_p80_60),
    premium_percentile_60: numberValue(premium?.premium_percentile_60),
    connect_channels: premium?.connect_channels || null
  };
}

type RecommendationSource = 'fresh' | 'cached';
type OverviewChartMode = 'trend' | 'range' | 'deviation';

interface OverviewPageProps {
  currentUser: UserInfo;
}

const OVERVIEW_CHART_MODE_OPTIONS: Array<{ label: string; value: OverviewChartMode }> = [
  { label: '走势折线', value: 'trend' },
  { label: '分位区间', value: 'range' },
  { label: '偏离柱状', value: 'deviation' }
];

/**
 * 数据总览页面，默认呈现自选股机会状态。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function OverviewPage({ currentUser }: OverviewPageProps) {
  const [watchlistForm] = Form.useForm<WatchlistFormValues>();
  const watchlistTargetType = Form.useWatch('target_type', watchlistForm) || 'PAIR';
  const watchlistDirection = Form.useWatch('preferred_direction', watchlistForm);
  const watchlistPushEnabled = Form.useWatch('push_enabled', watchlistForm);
  const watchlistTargetPremium = Form.useWatch('target_premium_pct', watchlistForm);
  const watchlistAPriceAlertEnabled = Form.useWatch('a_price_alert_enabled', watchlistForm);
  const watchlistAPriceAlertTarget = Form.useWatch('a_price_alert_target_price', watchlistForm);
  const watchlistHPriceAlertEnabled = Form.useWatch('h_price_alert_enabled', watchlistForm);
  const watchlistHPriceAlertTarget = Form.useWatch('h_price_alert_target_price', watchlistForm);
  const chartRef = useRef<ReactECharts | null>(null);
  const wheelDeltaRef = useRef(0);
  const wheelFrameRef = useRef<number | null>(null);
  const zoomRangeRef = useRef({ key: '', start: 0, end: 0 });
  const [pairKey, setPairKey] = useState(DEFAULT_PAIR_KEY);
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<number | null>(null);
  const [fallbackDirection, setFallbackDirection] = useState<PremiumDirection>('HA');
  const [isManualChart, setIsManualChart] = useState(false);
  const [orderedOpportunities, setOrderedOpportunities] = useState<WatchlistOpportunity[]>([]);
  const [draggingWatchlistId, setDraggingWatchlistId] = useState<number | null>(null);
  const [aiRecommendation, setAiRecommendation] = useState('');
  const [aiRecommendationProgress, setAiRecommendationProgress] = useState('');
  const [aiRecommendationSource, setAiRecommendationSource] = useState<RecommendationSource>('fresh');
  const [chartMode, setChartMode] = useState<OverviewChartMode>('trend');
  const [watchlistSettingItem, setWatchlistSettingItem] = useState<WatchlistOpportunity | null>(null);
  const queryClient = useQueryClient();
  const pairs = useQuery({ queryKey: ['premium-pairs'], queryFn: () => fetchPremiumPairs() });
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: () => fetchWatchlist() });
  const shouldFetchRealtimeWatchlist = Boolean(watchlist.data?.length) && isTradingRefreshWindow();
  const pushplusBinding = useQuery({
    queryKey: ['pushplus-binding'],
    queryFn: fetchPushplusBinding
  });
  const hasPushplusChannel = Boolean(
    pushplusBinding.data?.is_bound || currentUser.can_use_personal_pushplus
  );
  const qrCodeMutation = useMutation({
    mutationFn: () => createPushplusQrCode({ expire_seconds: 604800, scan_count: 1 }),
    onError: (error) => message.error(error instanceof Error ? error.message : '生成二维码失败')
  });
  const realtimeWatchlist = useQuery({
    queryKey: ['persist-realtime-watchlist-opportunities'],
    queryFn: () => fetchRealtimePremiums({ only_watchlist: true, page_size: 200 }),
    enabled: shouldFetchRealtimeWatchlist,
    refetchInterval: () =>
      document.visibilityState === 'visible' && isTradingRefreshWindow()
        ? WATCHLIST_REALTIME_REFRESH_MS
        : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    staleTime: WATCHLIST_REALTIME_REFRESH_MS
  });
  useEffect(() => {
    if (realtimeWatchlist.data) {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
    }
  }, [queryClient, realtimeWatchlist.data]);
  useEffect(() => {
    if (!qrCodeMutation.data || pushplusBinding.data?.is_bound) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pushplusBinding.data?.is_bound, qrCodeMutation.data, queryClient]);
  const watchlistAutoRefresh = useQuery({
    queryKey: ['watchlist-auto-refresh'],
    queryFn: () => fetchWatchlist(),
    enabled: shouldFetchRealtimeWatchlist,
    refetchInterval: () =>
      document.visibilityState === 'visible' && isTradingRefreshWindow()
        ? WATCHLIST_REALTIME_REFRESH_MS
        : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    staleTime: WATCHLIST_REALTIME_REFRESH_MS
  });
  const chartSettingsQuery = useQuery({
    queryKey: ['overview-chart-settings'],
    queryFn: fetchOverviewChartSettings
  });
  const principleSnippets = useMemo(
    () => pickRandomSnippets(OVERVIEW_SNIPPETS, RANDOM_SNIPPET_COUNT),
    []
  );
  const pairOptions = useMemo(() => {
    const optionMap = new Map<string, PremiumPairOption>();
    pairs.data?.forEach((item) => {
      const key = `${item.a_ts_code}|${item.hk_ts_code}`;
      const current = optionMap.get(key);
      if (!current) {
        optionMap.set(key, item);
        return;
      }
      if (shouldReplacePairOption(current, item)) {
        optionMap.set(key, {
          ...item,
          latest_trade_date:
            current.latest_trade_date && item.latest_trade_date
              ? current.latest_trade_date > item.latest_trade_date
                ? current.latest_trade_date
                : item.latest_trade_date
              : current.latest_trade_date || item.latest_trade_date
        });
      }
    });
    return Array.from(optionMap.values());
  }, [pairs.data]);
  const serverOpportunities = watchlistAutoRefresh.data || watchlist.data || [];
  const opportunities = orderedOpportunities;
  const selectedOpportunity = opportunities.find((item) => item.watchlist.id === selectedWatchlistId) || null;
  const modalHasAlertConfig = hasAlertConfig({
    target_type: watchlistTargetType,
    preferred_direction: watchlistDirection || 'HA',
    target_premium_pct: watchlistTargetType === 'PAIR' ? watchlistTargetPremium : null,
    a_price_alert_enabled: watchlistAPriceAlertEnabled,
    a_price_alert_target_price: watchlistAPriceAlertTarget,
    h_price_alert_enabled: watchlistHPriceAlertEnabled,
    h_price_alert_target_price: watchlistHPriceAlertTarget,
    holding_market: 'UNKNOWN'
  });
  const modalRequiresBinding = modalHasAlertConfig && watchlistPushEnabled !== false;
  const direction = fallbackDirection;
  const pair = splitPairKey(pairKey);
  const chartWatchlist = opportunities.find(
    (item) => opportunityPairKey(item) === pairKey && opportunityDirection(item) === direction
  );
  const trend = useQuery({
    queryKey: ['official-premium-trend', pair.aTsCode, pair.hkTsCode, direction],
    enabled: Boolean(pair.aTsCode && pair.hkTsCode),
    queryFn: () => fetchOfficialPremiumTrend(pair.aTsCode, pair.hkTsCode, direction)
  });
  const reorderMutation = useMutation({
    mutationFn: (items: WatchlistOpportunity[]) =>
      Promise.all(
        items.map((item, index) =>
          updateWatchlistItem(item.watchlist.id, {
            sort_order: (index + 1) * 10
          })
        )
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
    },
    onError: (error) => {
      setOrderedOpportunities(serverOpportunities);
      message.error(error instanceof Error ? error.message : '自选排序保存失败');
    }
  });
  const watchlistSettingMutation = useMutation({
    mutationFn: ({ item, values }: { item: WatchlistOpportunity; values: WatchlistFormValues }) =>
      updateWatchlistItem(item.watchlist.id, {
        display_name: values.display_name?.trim() || null,
        preferred_direction: values.preferred_direction,
        target_premium_pct: isPairOpportunity(item) ? values.target_premium_pct ?? null : null,
        push_enabled: values.push_enabled ?? true,
        a_price_alert_enabled: item.watchlist.target_type !== 'H_ONLY' && Boolean(values.a_price_alert_enabled),
        a_price_alert_operator: values.a_price_alert_operator || 'GTE',
        a_price_alert_target_price:
          item.watchlist.target_type !== 'H_ONLY' ? values.a_price_alert_target_price ?? null : null,
        h_price_alert_enabled: item.watchlist.target_type !== 'A_ONLY' && Boolean(values.h_price_alert_enabled),
        h_price_alert_operator: values.h_price_alert_operator || 'GTE',
        h_price_alert_target_price:
          item.watchlist.target_type !== 'A_ONLY' ? values.h_price_alert_target_price ?? null : null,
        holding_market: values.holding_market
      }),
    onSuccess: (_, variables) => {
      message.success('自选配置已更新');
      setWatchlistSettingItem(null);
      watchlistForm.resetFields();
      if (variables.item.watchlist.id === selectedWatchlistId && isPairOpportunity(variables.item)) {
        setFallbackDirection(variables.values.preferred_direction);
      }
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存自选失败')
  });
  const removeWatchlistMutation = useMutation({
    mutationFn: (item: WatchlistOpportunity) => deleteWatchlistItem(item.watchlist.id),
    onSuccess: (_, item) => {
      message.success('已取消自选');
      setOrderedOpportunities((items) =>
        items.filter((current) => current.watchlist.id !== item.watchlist.id)
      );
      if (selectedWatchlistId === item.watchlist.id) {
        setSelectedWatchlistId(null);
        setAiRecommendation('');
        setAiRecommendationProgress('');
        setAiRecommendationSource('fresh');
      }
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '取消自选失败')
  });
  const aiRecommendationMutation = useMutation({
    mutationFn: async (item: WatchlistOpportunity) => {
      if (!item.watchlist.a_ts_code || !item.watchlist.hk_ts_code) {
        throw new Error('AI 阈值推荐仅支持 A/H 配对关注');
      }
      // Agent 协议下不再做假进度轮播，等待阶段展示固定通用文案；
      // 首个流式 delta 到达后该提示即被回答内容替换。
      setAiRecommendationProgress('正在分析自选股价差与分位数据...');
      const direction = opportunityDirection(item);
      const cacheInput = {
        aTsCode: item.watchlist.a_ts_code,
        hkTsCode: item.watchlist.hk_ts_code,
        direction
      };
      try {
        const cached = getCachedThresholdRecommendation(cacheInput);
        if (cached) {
          return { answer: cached.answer, source: 'cached' as RecommendationSource };
        }
        const session = await createChatSession(`阈值建议：${opportunityName(item)}`);
        let streamedAnswer = '';
        setAiRecommendation('');
        setAiRecommendationSource('fresh');
        await sendChatMessageStream(session.id, {
          question: buildThresholdRecommendationPrompt(item),
          display_question: buildThresholdDisplayQuestion(item),
          only_watchlist: true,
          ts_code: item.watchlist.a_ts_code,
          threshold_recommendation: buildThresholdRecommendationContext(item)
        }, {
          onDelta: (content) => {
            // 流式片段到达时立即拼接展示，用户不再需要等待完整 LLM 响应结束。
            streamedAnswer += content;
            setAiRecommendation(streamedAnswer);
          },
          onDone: (event) => {
            streamedAnswer = event.answer || streamedAnswer;
          }
        });
        setCachedThresholdRecommendation(cacheInput, streamedAnswer);
        return { answer: streamedAnswer, source: 'fresh' as RecommendationSource };
      } finally {
        setAiRecommendationProgress('');
      }
    },
    onSuccess: (result) => {
      setAiRecommendation(result.answer);
      setAiRecommendationSource(result.source);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : 'AI 推荐失败')
  });
  const chartSettingsMutation = useMutation({
    mutationFn: updateOverviewChartSettings,
    onSuccess: (settings) => {
      queryClient.setQueryData(['overview-chart-settings'], settings);
      message.success('图表指标已保存');
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '指标配置保存失败')
  });

  useEffect(() => {
    setOrderedOpportunities(serverOpportunities);
  }, [serverOpportunities]);

  useEffect(() => {
    if (isManualChart) {
      return;
    }
    const pairOpportunities = opportunities.filter(isPairOpportunity);
    if (!pairOpportunities.length) {
      setSelectedWatchlistId(null);
      return;
    }
    const nextOpportunity =
      pairOpportunities.find((item) => item.watchlist.id === selectedWatchlistId) ||
      pairOpportunities[0];
    setSelectedWatchlistId(nextOpportunity.watchlist.id);
    setPairKey(opportunityPairKey(nextOpportunity));
    setFallbackDirection(opportunityDirection(nextOpportunity));
  }, [isManualChart, opportunities, selectedWatchlistId]);

  useEffect(() => {
    if (!pairOptions.length || (!isManualChart && selectedOpportunity)) {
      return;
    }
    if (pairOptions.some((item) => `${item.a_ts_code}|${item.hk_ts_code}` === pairKey)) {
      return;
    }
    const defaultPair = pairOptions.find(
      (item) => item.a_ts_code === '600036.SH' && item.hk_ts_code === '03968.HK'
    );
    const fallbackPair = defaultPair || pairOptions[0];
    setPairKey(`${fallbackPair.a_ts_code}|${fallbackPair.hk_ts_code}`);
  }, [isManualChart, pairKey, pairOptions, selectedOpportunity]);

  const selectedPair = pairOptions.find((item) => `${item.a_ts_code}|${item.hk_ts_code}` === pairKey);
  const trendTitleName = chartWatchlist ? opportunityName(chartWatchlist) : selectedPair?.a_name || pair.aTsCode;
  const directionLabel = direction === 'HA' ? 'H/A' : 'A/H';
  const premiumColor = direction === 'HA' ? HA_COLOR : AH_COLOR;
  const trendDates = useMemo(() => trend.data?.map((item) => item.trade_date) || [], [trend.data]);
  const defaultZoomStartValue = getDefaultZoomStartValue(trendDates);
  const defaultZoomEndValue = trendDates[trendDates.length - 1];
  const chartKey = `${pair.aTsCode}-${pair.hkTsCode}-${direction}`;
  const defaultZoomStartIndex = defaultZoomStartValue ? trendDates.indexOf(defaultZoomStartValue) : 0;
  const minZoomValueSpan =
    trendDates.length > 1 ? Math.min(Math.max(trendDates.length - 1, 1), MIN_VISIBLE_POINTS) : undefined;
  const targetValue = numberValue(chartWatchlist?.watchlist.target_premium_pct);
  const chartSettings = chartSettingsQuery.data || DEFAULT_OVERVIEW_CHART_SETTINGS;
  const chartIndicatorValues = CHART_INDICATOR_OPTIONS.filter(
    (item) => chartSettings[item.value]
  ).map((item) => item.value);

  useEffect(() => {
    zoomRangeRef.current = {
      key: chartKey,
      start: Math.max(defaultZoomStartIndex, 0),
      end: Math.max(trendDates.length - 1, 0)
    };
    wheelDeltaRef.current = 0;
    if (wheelFrameRef.current !== null) {
      window.cancelAnimationFrame(wheelFrameRef.current);
      wheelFrameRef.current = null;
    }
  }, [chartKey, defaultZoomStartIndex, trendDates.length]);

  useEffect(
    () => () => {
      if (wheelFrameRef.current !== null) {
        window.cancelAnimationFrame(wheelFrameRef.current);
      }
    },
    []
  );

  const onSelectOpportunity = (item: WatchlistOpportunity) => {
    if (!isPairOpportunity(item)) {
      return;
    }
    setIsManualChart(false);
    setSelectedWatchlistId(item.watchlist.id);
    setPairKey(opportunityPairKey(item));
    setFallbackDirection(opportunityDirection(item));
    setAiRecommendation('');
    setAiRecommendationSource('fresh');
  };

  const onChangePair = (value: string) => {
    setIsManualChart(true);
    setSelectedWatchlistId(null);
    setPairKey(value);
  };

  const onChangeDirection = (value: PremiumDirection) => {
    setIsManualChart(true);
    setSelectedWatchlistId(null);
    setFallbackDirection(value);
  };

  const onDropOpportunity = (targetId: number) => {
    if (!draggingWatchlistId || draggingWatchlistId === targetId) {
      setDraggingWatchlistId(null);
      return;
    }
    const nextOpportunities = reorderOpportunities(opportunities, draggingWatchlistId, targetId);
    setOrderedOpportunities(nextOpportunities);
    reorderMutation.mutate(nextOpportunities);
    setDraggingWatchlistId(null);
  };

  const onStartThresholdRecommendation = () => {
    if (!selectedOpportunity || !isPairOpportunity(selectedOpportunity)) {
      message.info('AI 阈值推荐仅支持 A/H 配对关注');
      return;
    }
    setAiRecommendation('');
    setAiRecommendationProgress('');
    setAiRecommendationSource('fresh');
    aiRecommendationMutation.mutate(selectedOpportunity);
  };

  const onOpenWatchlistSetting = (item: WatchlistOpportunity) => {
    watchlistForm.setFieldsValue({
      target_type: opportunityTargetType(item),
      display_name: item.watchlist.display_name || opportunityName(item),
      preferred_direction: item.watchlist.preferred_direction || opportunityDirection(item),
      target_premium_pct: numberValue(item.watchlist.target_premium_pct),
      push_enabled: item.watchlist.push_enabled ?? true,
      a_price_alert_enabled: Boolean(item.watchlist.a_price_alert_enabled),
      a_price_alert_operator: (item.watchlist.a_price_alert_operator as PriceAlertOperator) || 'GTE',
      a_price_alert_target_price: numberValue(item.watchlist.a_price_alert_target_price),
      h_price_alert_enabled: Boolean(item.watchlist.h_price_alert_enabled),
      h_price_alert_operator: (item.watchlist.h_price_alert_operator as PriceAlertOperator) || 'GTE',
      h_price_alert_target_price: numberValue(item.watchlist.h_price_alert_target_price),
      holding_market: (item.watchlist.holding_market as HoldingMarket) || 'UNKNOWN'
    });
    setWatchlistSettingItem(item);
  };

  const onSubmitWatchlistSetting = async () => {
    if (!watchlistSettingItem) {
      return;
    }
    const values = await watchlistForm.validateFields();
    if (hasAlertConfig(values) && values.push_enabled !== false && !hasPushplusChannel) {
      message.warning('设置提醒前请先完成 PushPlus 扫码绑定');
      if (!qrCodeMutation.data && !qrCodeMutation.isPending) {
        qrCodeMutation.mutate();
      }
      return;
    }
    watchlistSettingMutation.mutate({ item: watchlistSettingItem, values });
  };

  const onRemoveWatchlist = (item: WatchlistOpportunity) => {
    Modal.confirm({
      title: '取消自选',
      content: `${opportunityName(item)}（${opportunityCodeLabel(item)}）`,
      okText: '取消自选',
      okButtonProps: { danger: true },
      cancelText: '保留',
      onOk: () => removeWatchlistMutation.mutateAsync(item)
    });
  };

  const onChangeChartIndicators = (values: Array<string | number | boolean>) => {
    const selectedValues = new Set(values.map(String));
    selectedValues.add('metric_premium');
    chartSettingsMutation.mutate({
      metric_premium: true,
      median_60: selectedValues.has('median_60'),
      p20_60: selectedValues.has('p20_60'),
      p80_60: selectedValues.has('p80_60'),
      target_threshold: selectedValues.has('target_threshold')
    });
  };

  const onChartDataZoom = useCallback(
    (params: {
      batch?: Array<{
        start?: number;
        end?: number;
        startValue?: string | number;
        endValue?: string | number;
      }>;
    }) => {
      const payload = params.batch?.[0];
      if (!payload || trendDates.length < 2) {
        return;
      }
      const maxIndex = trendDates.length - 1;
      const start =
        payload.startValue !== undefined
          ? dataZoomValueIndex(payload.startValue, trendDates, 0)
          : Math.round((maxIndex * Number(payload.start ?? 0)) / 100);
      const end =
        payload.endValue !== undefined
          ? dataZoomValueIndex(payload.endValue, trendDates, maxIndex)
          : Math.round((maxIndex * Number(payload.end ?? 100)) / 100);
      zoomRangeRef.current = {
        key: chartKey,
        start: clamp(start >= 0 ? start : 0, 0, maxIndex),
        end: clamp(end >= 0 ? end : maxIndex, 0, maxIndex)
      };
    },
    [chartKey, trendDates]
  );

  const chartEvents = useMemo(() => ({ datazoom: onChartDataZoom }), [onChartDataZoom]);

  // 触摸板横向滚动由外层节流接管，避免 ECharts inside dataZoom 高频 wheel 抖动。
  const onChartWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      if (trendDates.length < 2 || Math.abs(event.deltaX) <= Math.abs(event.deltaY)) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      wheelDeltaRef.current += event.deltaX;
      if (wheelFrameRef.current !== null) {
        return;
      }
      wheelFrameRef.current = window.requestAnimationFrame(() => {
        wheelFrameRef.current = null;
        const delta = wheelDeltaRef.current;
        wheelDeltaRef.current = 0;
        const maxIndex = trendDates.length - 1;
        const currentRange =
          zoomRangeRef.current.key === chartKey
            ? zoomRangeRef.current
            : { key: chartKey, start: Math.max(defaultZoomStartIndex, 0), end: maxIndex };
        const span = Math.max(currentRange.end - currentRange.start, 1);
        const step = Math.max(1, Math.round(Math.abs(delta) / TRACKPAD_WHEEL_UNIT));
        const nextStart = clamp(currentRange.start + Math.sign(delta) * step, 0, maxIndex - span);
        const nextEnd = nextStart + span;
        zoomRangeRef.current = { key: chartKey, start: nextStart, end: nextEnd };
        chartRef.current?.getEchartsInstance().dispatchAction({
          type: 'dataZoom',
          dataZoomIndex: 0,
          startValue: trendDates[nextStart],
          endValue: trendDates[nextEnd]
        });
      });
    },
    [chartKey, defaultZoomStartIndex, trendDates]
  );

  const trendChartOption = useMemo(() => {
    const zoomConfig = [
      {
        type: 'inside',
        throttle: 120,
        startValue: defaultZoomStartValue,
        endValue: defaultZoomEndValue,
        minValueSpan: minZoomValueSpan,
        zoomOnMouseWheel: false,
        moveOnMouseWheel: false,
        moveOnMouseMove: true,
        preventDefaultMouseMove: true
      },
      {
        type: 'slider',
        height: 26,
        bottom: 18,
        brushSelect: false,
        startValue: defaultZoomStartValue,
        endValue: defaultZoomEndValue,
        minValueSpan: minZoomValueSpan
      }
    ];
    const baseTooltip = {
      trigger: 'axis',
      valueFormatter: (value: number | string) => {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? `${parsed.toFixed(2)}%` : '-';
      }
    };
    const series: Array<Record<string, unknown>> = [];
    if (chartSettings.metric_premium) {
      series.push({
        name: `${directionLabel} 溢价`,
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: trend.data?.map((item) => numberValue(item.metric_premium_pct)) || [],
        lineStyle: { width: 3, color: premiumColor },
        itemStyle: { color: premiumColor },
        areaStyle: { color: premiumColor, opacity: 0.08 },
        emphasis: { focus: 'series' }
      });
    }
    if (chartSettings.median_60) {
      series.push({
        name: '60日中位数',
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: trend.data?.map((item) => numberValue(item.premium_median_60)) || [],
        lineStyle: MEDIAN60_LINE_STYLE,
        itemStyle: { color: MEDIAN60_COLOR }
      });
    }
    if (chartSettings.p20_60) {
      series.push({
        name: '20%分位',
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: trend.data?.map((item) => numberValue(item.premium_p20_60)) || [],
        lineStyle: { width: 1.4, color: P20_COLOR, type: 'dotted' },
        itemStyle: { color: P20_COLOR }
      });
    }
    if (chartSettings.p80_60) {
      series.push({
        name: '80%分位',
        type: 'line',
        smooth: false,
        showSymbol: false,
        data: trend.data?.map((item) => numberValue(item.premium_p80_60)) || [],
        lineStyle: { width: 1.4, color: P80_COLOR, type: 'dotted' },
        itemStyle: { color: P80_COLOR }
      });
    }
    if (chartSettings.target_threshold && targetValue !== null) {
      series.push({
        name: '目标阈值',
        type: 'line',
        showSymbol: false,
        data: trendDates.map(() => targetValue),
        lineStyle: { width: 2, color: TARGET_COLOR, type: 'dotted' },
        itemStyle: { color: TARGET_COLOR }
      });
    }
    if (chartMode === 'range') {
      const p20Data = trend.data?.map((item) => numberValue(item.premium_p20_60)) || [];
      const p80Data = trend.data?.map((item) => numberValue(item.premium_p80_60)) || [];
      const bandData = p80Data.map((value, index) => {
        const p20 = p20Data[index];
        return value === null || p20 === null ? null : Number((value - p20).toFixed(2));
      });
      const rangeSeries = [
        {
          name: '20%分位',
          type: 'line',
          showSymbol: false,
          stack: 'percentile-band',
          data: p20Data,
          lineStyle: { width: 1.5, color: P20_COLOR, type: 'dotted' },
          itemStyle: { color: P20_COLOR }
        },
        {
          name: '20%-80%分位带',
          type: 'line',
          showSymbol: false,
          stack: 'percentile-band',
          data: bandData,
          lineStyle: { width: 0, color: P80_COLOR },
          areaStyle: { color: P80_COLOR, opacity: 0.16 },
          itemStyle: { color: P80_COLOR }
        },
        {
          name: `${directionLabel} 当前值`,
          type: 'scatter',
          symbolSize: 8,
          data: trend.data?.map((item) => numberValue(item.metric_premium_pct)) || [],
          itemStyle: { color: premiumColor }
        },
        {
          name: '60日中位数',
          type: 'line',
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_median_60)) || [],
          lineStyle: MEDIAN60_LINE_STYLE,
          itemStyle: { color: MEDIAN60_COLOR }
        },
        ...(targetValue !== null
          ? [
              {
                name: '目标阈值',
                type: 'line',
                showSymbol: false,
                data: trendDates.map(() => targetValue),
                lineStyle: { width: 2, color: TARGET_COLOR, type: 'dotted' },
                itemStyle: { color: TARGET_COLOR }
              }
            ]
          : [])
      ];
      return {
        color: [P20_COLOR, P80_COLOR, premiumColor, MEDIAN60_COLOR, TARGET_COLOR],
        tooltip: baseTooltip,
        legend: { top: 0, right: 16 },
        grid: { left: 54, right: 24, top: 42, bottom: 78 },
        dataZoom: zoomConfig,
        xAxis: { type: 'category', data: trendDates, axisLabel: { hideOverlap: true } },
        yAxis: { type: 'value', scale: true, axisLabel: { formatter: '{value}%' } },
        series: rangeSeries
      };
    }
    if (chartMode === 'deviation') {
      const deviationData =
        trend.data?.map((item) => {
          const current = numberValue(item.metric_premium_pct);
          const median = numberValue(item.premium_median_60);
          return current === null || median === null ? null : Number((current - median).toFixed(2));
        }) || [];
      return {
        color: [premiumColor, TARGET_COLOR],
        tooltip: baseTooltip,
        legend: { top: 0, right: 16 },
        grid: { left: 54, right: 24, top: 42, bottom: 78 },
        dataZoom: zoomConfig,
        xAxis: { type: 'category', data: trendDates, axisLabel: { hideOverlap: true } },
        yAxis: { type: 'value', scale: true, axisLabel: { formatter: '{value}%' } },
        series: [
          {
            name: '偏离60日中位数',
            type: 'bar',
            data: deviationData,
            itemStyle: {
              color: (params: { value: number | null }) => {
                if (params.value === null || params.value === 0) {
                  return MEDIAN60_COLOR;
                }
                return params.value > 0 ? AH_COLOR : P20_COLOR;
              }
            }
          },
          {
            name: '零轴',
            type: 'line',
            showSymbol: false,
            data: trendDates.map(() => 0),
            lineStyle: { width: 1.5, color: MEDIAN60_COLOR, type: 'dashed' },
            itemStyle: { color: MEDIAN60_COLOR }
          }
        ]
      };
    }
    return {
      color: [premiumColor, MEDIAN60_COLOR, P20_COLOR, P80_COLOR, TARGET_COLOR],
      tooltip: baseTooltip,
      legend: { top: 0, right: 16 },
      grid: { left: 54, right: 24, top: 42, bottom: 78 },
      dataZoom: zoomConfig,
      xAxis: {
        type: 'category',
        data: trendDates,
        axisLabel: { hideOverlap: true }
      },
      yAxis: { type: 'value', scale: true, axisLabel: { formatter: '{value}%' } },
      series
    };
  },
    [
      chartSettings.median_60,
      chartSettings.metric_premium,
      chartSettings.p20_60,
      chartSettings.p80_60,
      chartSettings.target_threshold,
      chartMode,
      defaultZoomEndValue,
      defaultZoomStartValue,
      direction,
      directionLabel,
      minZoomValueSpan,
      premiumColor,
      targetValue,
      trend.data,
      trendDates
    ]
  );

  return (
    <main className="page">
      <PageHeader title="自选机会台" />

      <section className="panel premium-principle-panel">
        <div className="principle-main">
          <div className="panel-title">今日投研词条</div>
          <Typography.Paragraph className="principle-text">
            {principleSnippets[0]}
          </Typography.Paragraph>
        </div>
        <div className="principle-points">
          {principleSnippets.slice(1).map((item) => (
            <span className="principle-chip" key={item}>
              {item}
            </span>
          ))}
        </div>
      </section>

      <section className="panel opportunity-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">自选机会</div>
            <Typography.Text type="secondary">
              交易时段实时快照会先写回官方溢价表并打实时标记，卡片始终读取官方表主口径。
            </Typography.Text>
          </div>
          <Button
            icon={<Bot size={16} />}
            loading={aiRecommendationMutation.isPending}
            disabled={!selectedOpportunity || !isPairOpportunity(selectedOpportunity)}
            onClick={onStartThresholdRecommendation}
          >
            AI 推荐阈值
          </Button>
        </div>
        {watchlist.isLoading ? (
          <Skeleton active />
        ) : opportunities.length ? (
          <div className="opportunity-grid">
            {opportunities.map((item) => (
              <div
                key={item.watchlist.id}
                role="button"
                tabIndex={0}
                draggable
                className={`opportunity-card ${item.watchlist.id === selectedWatchlistId ? 'active' : ''}${
                  item.watchlist.id === draggingWatchlistId ? ' dragging' : ''
                }`}
                onDragStart={(event: DragEvent<HTMLDivElement>) => {
                  event.dataTransfer.effectAllowed = 'move';
                  setDraggingWatchlistId(item.watchlist.id);
                }}
                onDragOver={(event: DragEvent<HTMLDivElement>) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'move';
                }}
                onDrop={() => onDropOpportunity(item.watchlist.id)}
                onDragEnd={() => setDraggingWatchlistId(null)}
                onClick={() => onSelectOpportunity(item)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelectOpportunity(item);
                  }
                }}
              >
                <div className="opportunity-card-head">
                  <span className="opportunity-card-title">
                    <GripVertical size={15} className="drag-handle" />
                    <strong>{opportunityName(item)}</strong>
                  </span>
                  <span className="opportunity-card-head-actions">
                    {isPairOpportunity(item)
                      ? statusTag(item.premium?.opportunity_status)
                      : singleQuoteStatusTag(item)}
                    <Button
                      size="small"
                      type="text"
                      icon={<Settings size={15} />}
                      title="设置自选"
                      aria-label="设置自选"
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenWatchlistSetting(item);
                      }}
                    />
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<Trash2 size={15} />}
                      title="取消自选"
                      aria-label="取消自选"
                      loading={removeWatchlistMutation.isPending}
                      onClick={(event) => {
                        event.stopPropagation();
                        onRemoveWatchlist(item);
                      }}
                    />
                  </span>
                </div>
                <div className="opportunity-card-codes">
                  {opportunityCodeLabel(item)}
                </div>
                <div className="opportunity-card-prices">
                  {item.watchlist.target_type !== 'H_ONLY' ? (
                    <span>
                      A 最新价
                      <b>{opportunityPrice(item, 'A')}</b>
                    </span>
                  ) : null}
                  {item.watchlist.target_type !== 'A_ONLY' ? (
                    <span>
                      H 最新价
                      <b>{opportunityPrice(item, 'H')}</b>
                    </span>
                  ) : null}
                </div>
                {isPairOpportunity(item) ? (
                  <div className="opportunity-card-metrics">
                    <span>
                      {item.premium?.metric_direction || item.watchlist.preferred_direction}
                      <b className={opportunityDirection(item) === 'HA' ? 'metric-ha' : 'metric-ah'}>
                        {formatPercent(item.premium?.metric_premium_pct)}
                      </b>
                    </span>
                    <span>
                      目标阈值
                      <b className="metric-target">{formatPercent(item.watchlist.target_premium_pct)}</b>
                    </span>
                    <span>
                      距阈值
                      <b className={metricToneClass(item.premium?.distance_to_target_pct)}>
                        {formatPercent(item.premium?.distance_to_target_pct)}
                      </b>
                    </span>
                    <span>
                      60日分位
                      <b className={percentileToneClass(item.premium?.premium_percentile_60)}>
                        {formatPercent(item.premium?.premium_percentile_60)}
                      </b>
                    </span>
                  </div>
                ) : null}
                <div className="opportunity-card-thresholds">
                  {isPairOpportunity(item) ? (
                    <span>
                      溢价阈值：{opportunityDirection(item)} {formatPercent(item.watchlist.target_premium_pct)}
                    </span>
                  ) : (
                    <span>单股股价提醒</span>
                  )}
                  <span>{priceAlertText(item)}</span>
                </div>
                <div className="opportunity-card-foot">
                  {isPairOpportunity(item) ? (
                    <>
                      <Tag color={item.premium?.is_hk_connect ? 'green' : 'default'}>
                        {item.premium?.connect_channels || '非港股通'}
                      </Tag>
                      <Tag color={item.premium?.is_realtime ? 'green' : 'blue'}>
                        {item.premium?.is_realtime ? '实时' : '快照'}
                      </Tag>
                    </>
                  ) : (
                    <>
                      <Tag color="blue">{opportunityTargetType(item) === 'A_ONLY' ? '仅 A 股' : '仅 H 股'}</Tag>
                      <Tag color="default">{singleQuoteTimeText(item)}</Tag>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Alert
            type="info"
            showIcon
            message="暂无自选股票"
            description="可以在 AH 官方比价页从全市场筛选结果加入自选；加入后首页会优先展示阈值、分位和港股通通道。"
          />
        )}
        {aiRecommendation || aiRecommendationMutation.isPending ? (
          <div className="ai-recommendation-box">
            <div className="ai-recommendation-head">
              <Bot size={16} />
              <strong>{aiRecommendationSource === 'cached' ? '之前 AI 推荐信息' : 'AI 阈值建议'}</strong>
            </div>
            {aiRecommendation ? (
              <div className="markdown-answer">
                <ReactMarkdown>{aiRecommendation}</ReactMarkdown>
              </div>
            ) : (
              <LlmProgressNote
                className="threshold-progress-note"
                text={aiRecommendationProgress}
                fallback="正在推荐阈值..."
              />
            )}
          </div>
        ) : null}
      </section>

      <div className="content-grid overview-grid">
        <section className="panel overview-chart-panel">
          <div className="overview-chart-head">
            <div className="panel-title">
              {trendTitleName} {directionLabel} 溢价走势
            </div>
            <Space wrap>
              <Select
                className="overview-chart-mode-select"
                value={chartMode}
                options={OVERVIEW_CHART_MODE_OPTIONS}
                onChange={setChartMode}
              />
              <Select
                className="overview-pair-select"
                showSearch
                value={pairKey}
                loading={pairs.isLoading}
                optionFilterProp="label"
                options={pairOptions.map((item) => ({
                  value: `${item.a_ts_code}|${item.hk_ts_code}`,
                  label: formatPairLabel(item)
                }))}
                onChange={onChangePair}
              />
              <Select
                value={direction}
                className="overview-direction-select"
                options={[
                  { value: 'HA', label: 'H/A' },
                  { value: 'AH', label: 'A/H' }
                ]}
                onChange={onChangeDirection}
              />
              <Popover
                trigger="click"
                placement="bottomRight"
                content={
                  <Checkbox.Group
                    className="overview-indicator-group"
                    value={chartIndicatorValues}
                    onChange={onChangeChartIndicators}
                  >
                    {CHART_INDICATOR_OPTIONS.map((item) => (
                      <Checkbox key={item.value} value={item.value} disabled={item.required}>
                        {item.label}
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                }
              >
                <Button
                  icon={<SlidersHorizontal size={16} />}
                  loading={chartSettingsQuery.isLoading || chartSettingsMutation.isPending}
                >
                  指标
                </Button>
              </Popover>
            </Space>
          </div>
          {trend.data?.length ? (
            <ReactECharts
              ref={chartRef}
              key={`${pair.aTsCode}-${pair.hkTsCode}-${direction}-${chartMode}`}
              option={trendChartOption}
              notMerge
              onEvents={chartEvents}
              onWheelCapture={onChartWheel}
              className="overview-chart"
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
      </div>
      <Modal
        title="设置自选"
        open={Boolean(watchlistSettingItem)}
        onOk={onSubmitWatchlistSetting}
        confirmLoading={watchlistSettingMutation.isPending}
        onCancel={() => {
          setWatchlistSettingItem(null);
          watchlistForm.resetFields();
        }}
        okText="保存"
        cancelText="取消"
      >
        <Form form={watchlistForm} layout="vertical">
          <Form.Item label="关注类型" name="target_type">
            <Select
              disabled
              options={[
                { value: 'PAIR', label: 'A/H 配对' },
                { value: 'A_ONLY', label: '仅 A 股' },
                { value: 'H_ONLY', label: '仅 H 股' }
              ]}
            />
          </Form.Item>
          <Form.Item label="展示名" name="display_name">
            <Input maxLength={128} />
          </Form.Item>
          {watchlistTargetType === 'PAIR' ? (
            <>
              <Form.Item label="关注方向" name="preferred_direction" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: 'HA', label: 'H/A' },
                    { value: 'AH', label: 'A/H' }
                  ]}
                />
              </Form.Item>
              <Form.Item
                label="目标阈值"
                name="target_premium_pct"
                extra={thresholdHelpText(watchlistDirection)}
              >
                <InputNumber className="full-width" addonAfter="%" precision={2} placeholder="例如 -15 或 30" />
              </Form.Item>
            </>
          ) : (
            <Alert
              showIcon
              type="info"
              message="单 A / 单 H 关注只支持股价提醒"
              description="溢价阈值和 AI 阈值推荐需要 A/H 两侧报价与汇率，单股关注不会展示这些配置。"
            />
          )}
          <Form.Item
            label="消息推送"
            name="push_enabled"
            valuePropName="checked"
            extra="默认开启；关闭后仍保留自选提醒配置，但不会发送 PushPlus 消息。"
          >
            <Switch checkedChildren="开启" unCheckedChildren="关闭" />
          </Form.Item>
          {modalRequiresBinding && !hasPushplusChannel ? (
            <div className="pushplus-alert-bind-box">
              <Alert
                showIcon
                type="warning"
                message="设置提醒前需要绑定 PushPlus 好友"
                description={`当前账号还没有绑定微信推送。${PUSHPLUS_BIND_SUCCESS_NOTICE}`}
              />
              <Space align="start" className="pushplus-alert-bind-actions">
                <Button
                  icon={<QrCode size={16} />}
                  loading={qrCodeMutation.isPending}
                  onClick={() => qrCodeMutation.mutate()}
                >
                  生成绑定二维码
                </Button>
                {qrCodeMutation.data?.qr_code_img_url ? (
                  <Image
                    width={180}
                    src={qrCodeMutation.data.qr_code_img_url}
                    alt="PushPlus 绑定二维码"
                  />
                ) : null}
              </Space>
            </div>
          ) : null}
          {watchlistTargetType !== 'H_ONLY' ? (
          <div className="watchlist-price-alert-grid">
            <Form.Item label="A 股提醒" name="a_price_alert_enabled" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
            <Form.Item label="A 股方向" name="a_price_alert_operator">
              <Select
                options={[
                  { value: 'GTE', label: '大于等于' },
                  { value: 'LTE', label: '小于等于' }
                ]}
              />
            </Form.Item>
            <Form.Item label="A 股目标价" name="a_price_alert_target_price">
              <InputNumber className="full-width" precision={3} placeholder="人民币触发价" />
            </Form.Item>
          </div>
          ) : null}
          {watchlistTargetType !== 'A_ONLY' ? (
          <div className="watchlist-price-alert-grid">
            <Form.Item label="H 股提醒" name="h_price_alert_enabled" valuePropName="checked">
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
            <Form.Item label="H 股方向" name="h_price_alert_operator">
              <Select
                options={[
                  { value: 'GTE', label: '大于等于' },
                  { value: 'LTE', label: '小于等于' }
                ]}
              />
            </Form.Item>
            <Form.Item label="H 股目标价" name="h_price_alert_target_price">
              <InputNumber className="full-width" precision={3} placeholder="港币触发价" />
            </Form.Item>
          </div>
          ) : null}
          {watchlistTargetType === 'PAIR' ? (
          <Form.Item label="持有侧" name="holding_market" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'UNKNOWN', label: '未设置' },
                { value: 'A', label: 'A 股' },
                { value: 'H', label: 'H 股' }
              ]}
            />
          </Form.Item>
          ) : null}
        </Form>
      </Modal>
    </main>
  );
}

export default OverviewPage;
