import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Row,
  Select,
  Skeleton,
  Space,
  Statistic,
  Tag,
  Typography,
  message
} from 'antd';
import ReactECharts from 'echarts-for-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import { Bot, GripVertical } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type WheelEvent } from 'react';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { createChatSession, sendChatMessage } from '../api/chat';
import { fetchOfficialPremiumTrend, fetchPremiumPairs, fetchPremiumSummary } from '../api/market';
import { deleteWatchlistItem, fetchWatchlist, updateWatchlistItem } from '../api/watchlist';
import type { PremiumDirection, PremiumItem, PremiumPairOption, WatchlistOpportunity } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';
import {
  getCachedThresholdRecommendation,
  setCachedThresholdRecommendation
} from '../utils/thresholdRecommendationCache';

const DEFAULT_PAIR_KEY = '600036.SH|03968.HK';
const DEFAULT_VISIBLE_MONTHS = 3;
const MIN_VISIBLE_POINTS = 20;
const TRACKPAD_WHEEL_UNIT = 80;
const AH_COLOR = '#2563eb';
const HA_COLOR = '#0f766e';
const MEDIAN60_COLOR = '#334155';
const P20_COLOR = '#14b8a6';
const P80_COLOR = '#f97316';
const TARGET_COLOR = '#dc2626';

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

function statusTag(status?: string | null) {
  const labelMap: Record<string, string> = {
    REACHED: '已达阈值',
    NEAR: '接近阈值',
    WATCH: '正常观察',
    DATA_ISSUE: '数据异常',
    NOT_CONNECT: '不可操作'
  };
  const colorMap: Record<string, string> = {
    REACHED: 'red',
    NEAR: 'gold',
    WATCH: 'blue',
    DATA_ISSUE: 'orange',
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
    `${item.watchlist.a_ts_code} / ${item.watchlist.hk_ts_code}`
  );
}

function opportunityPairKey(item: WatchlistOpportunity) {
  const aTsCode = item.premium?.a_ts_code || item.watchlist.a_ts_code;
  const hkTsCode = item.premium?.hk_ts_code || item.watchlist.hk_ts_code;
  return `${aTsCode}|${hkTsCode}`;
}

function opportunityDirection(item: WatchlistOpportunity): PremiumDirection {
  return item.premium?.metric_direction || item.watchlist.preferred_direction;
}

function premiumDirection(value?: string | null): PremiumDirection {
  return value === 'AH' ? 'AH' : 'HA';
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
    '你是 A/H 跨市场价差研究助手，请优先按知识库中的“自选阈值推荐逻辑”给出稳定、可复核的建议。',
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

type RecommendationSource = 'fresh' | 'cached';

/**
 * 数据总览页面，默认呈现自选股机会状态。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function OverviewPage() {
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
  const [aiRecommendationSource, setAiRecommendationSource] = useState<RecommendationSource>('fresh');
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['premium-summary'],
    queryFn: fetchPremiumSummary
  });
  const pairs = useQuery({ queryKey: ['premium-pairs'], queryFn: () => fetchPremiumPairs() });
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: () => fetchWatchlist() });
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
  const serverOpportunities = useMemo(() => watchlist.data || [], [watchlist.data]);
  const opportunities = orderedOpportunities;
  const selectedOpportunity = opportunities.find((item) => item.watchlist.id === selectedWatchlistId) || null;
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
  const removeWatchlistMutation = useMutation({
    mutationFn: (item: PremiumItem) => {
      if (!item.watchlist_id) {
        throw new Error('自选股不存在');
      }
      return deleteWatchlistItem(item.watchlist_id);
    },
    onSuccess: () => {
      message.success('已取消自选');
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '取消自选失败')
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
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
    },
    onError: (error) => {
      setOrderedOpportunities(serverOpportunities);
      message.error(error instanceof Error ? error.message : '自选排序保存失败');
    }
  });
  const aiRecommendationMutation = useMutation({
    mutationFn: async (item: WatchlistOpportunity) => {
      const direction = opportunityDirection(item);
      const cacheInput = {
        aTsCode: item.watchlist.a_ts_code,
        hkTsCode: item.watchlist.hk_ts_code,
        direction
      };
      const cached = getCachedThresholdRecommendation(cacheInput);
      if (cached) {
        return { answer: cached.answer, source: 'cached' as RecommendationSource };
      }
      const session = await createChatSession(`阈值建议：${opportunityName(item)}`);
      const result = await sendChatMessage(session.id, {
        question: buildThresholdRecommendationPrompt(item),
        display_question: buildThresholdDisplayQuestion(item),
        only_watchlist: true,
        ts_code: item.watchlist.a_ts_code
      });
      setCachedThresholdRecommendation(cacheInput, result.answer);
      return { answer: result.answer, source: 'fresh' as RecommendationSource };
    },
    onSuccess: (result) => {
      setAiRecommendation(result.answer);
      setAiRecommendationSource(result.source);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : 'AI 推荐失败')
  });

  useEffect(() => {
    setOrderedOpportunities(serverOpportunities);
  }, [serverOpportunities]);

  useEffect(() => {
    if (isManualChart) {
      return;
    }
    if (!opportunities.length) {
      setSelectedWatchlistId(null);
      return;
    }
    const nextOpportunity =
      opportunities.find((item) => item.watchlist.id === selectedWatchlistId) || opportunities[0];
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

  const watchlistPremiums = opportunities
    .map((item) => item.premium)
    .filter((item): item is PremiumItem => Boolean(item));
  const statusCounts = opportunities.reduce<Record<string, number>>((acc, item) => {
    const key = item.premium?.opportunity_status || 'DATA_ISSUE';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
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

  const onRemoveWatchlist = (item: PremiumItem) => {
    Modal.confirm({
      title: '取消自选',
      content: `${item.a_name || item.a_ts_code} / ${item.hk_name || item.hk_ts_code}`,
      okText: '取消自选',
      okButtonProps: { danger: true },
      cancelText: '保留',
      onOk: () => removeWatchlistMutation.mutateAsync(item)
    });
  };

  const onShowPremiumTrend = (item: PremiumItem) => {
    setIsManualChart(!item.watchlist_id);
    setSelectedWatchlistId(item.watchlist_id || null);
    setPairKey(`${item.a_ts_code}|${item.hk_ts_code}`);
    setFallbackDirection(premiumDirection(item.metric_direction));
    setAiRecommendation('');
    setAiRecommendationSource('fresh');
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
    if (!selectedOpportunity) {
      message.info('先选择一只自选股票');
      return;
    }
    setAiRecommendation('');
    setAiRecommendationSource('fresh');
    aiRecommendationMutation.mutate(selectedOpportunity);
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

  const trendChartOption = useMemo(
    () => ({
      color:
        targetValue === null
          ? [premiumColor, MEDIAN60_COLOR, P20_COLOR, P80_COLOR]
          : [premiumColor, MEDIAN60_COLOR, P20_COLOR, P80_COLOR, TARGET_COLOR],
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${value.toFixed(2)}%` },
      legend: { top: 0, right: 16 },
      grid: { left: 54, right: 24, top: 42, bottom: 78 },
      dataZoom: [
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
      ],
      xAxis: {
        type: 'category',
        data: trendDates,
        axisLabel: { hideOverlap: true }
      },
      yAxis: { type: 'value', scale: true, axisLabel: { formatter: '{value}%' } },
      series: [
        {
          name: `${directionLabel} 溢价`,
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.metric_premium_pct)) || [],
          lineStyle: { width: 3, color: premiumColor },
          itemStyle: { color: premiumColor },
          areaStyle: { color: premiumColor, opacity: 0.08 },
          emphasis: { focus: 'series' }
        },
        {
          name: '60日中位数',
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_median_60)) || [],
          lineStyle: { width: 1.8, color: MEDIAN60_COLOR, type: 'dashed' },
          itemStyle: { color: MEDIAN60_COLOR }
        },
        {
          name: '20%分位',
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_p20_60)) || [],
          lineStyle: { width: 1.4, color: P20_COLOR, type: 'dotted' },
          itemStyle: { color: P20_COLOR }
        },
        {
          name: '80%分位',
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_p80_60)) || [],
          lineStyle: { width: 1.4, color: P80_COLOR, type: 'dotted' },
          itemStyle: { color: P80_COLOR }
        },
        targetValue === null
          ? null
          : {
              name: '目标阈值',
              type: 'line',
              showSymbol: false,
              data: trendDates.map(() => targetValue),
              lineStyle: { width: 2, color: TARGET_COLOR, type: 'dotted' },
              itemStyle: { color: TARGET_COLOR }
            }
      ].filter(Boolean)
    }),
    [
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
      <Row gutter={[16, 16]}>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="最新交易日" value={data?.latest_trade_date || '-'} loading={isLoading} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="港股通 AH 记录" value={data?.hk_connect_count || 0} loading={isLoading} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="自选股票" value={data?.watchlist_count || 0} loading={watchlist.isLoading} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="达阈值 / 接近" value={`${statusCounts.REACHED || 0} / ${statusCounts.NEAR || 0}`} />
          </Card>
        </Col>
      </Row>

      <section className="panel premium-principle-panel">
        <div>
          <div className="panel-title">A/H 价差怎么用</div>
          <Typography.Paragraph className="principle-text">
            A/H 比价把 A 股人民币价格与 H 股港币价格按汇率折成人民币后比较。A/H 溢价高，通常表示
            A 股相对 H 股更贵；H/A 溢价高，通常表示 H 股相对 A 股更贵。实际使用时更适合作为跨市场换仓、
            替代配置和提醒阈值，不应理解为无风险套利。
          </Typography.Paragraph>
        </div>
        <div className="principle-points">
          <Tag color="blue">看方向</Tag>
          <Tag color="green">看港股通</Tag>
          <Tag color="gold">看分位</Tag>
          <Tag color="red">看成本与流动性</Tag>
        </div>
      </section>

      <section className="panel opportunity-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">自选机会</div>
            <Typography.Text type="secondary">
              官方 AH 口径，H/A 由 A/H 反推；港股通通道来自当日沪深港通名单。
            </Typography.Text>
          </div>
          <Button
            icon={<Bot size={16} />}
            loading={aiRecommendationMutation.isPending}
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
              <button
                key={item.watchlist.id}
                draggable
                className={`opportunity-card ${item.watchlist.id === selectedWatchlistId ? 'active' : ''}${
                  item.watchlist.id === draggingWatchlistId ? ' dragging' : ''
                }`}
                onDragStart={(event: DragEvent<HTMLButtonElement>) => {
                  event.dataTransfer.effectAllowed = 'move';
                  setDraggingWatchlistId(item.watchlist.id);
                }}
                onDragOver={(event: DragEvent<HTMLButtonElement>) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'move';
                }}
                onDrop={() => onDropOpportunity(item.watchlist.id)}
                onDragEnd={() => setDraggingWatchlistId(null)}
                onClick={() => onSelectOpportunity(item)}
              >
                <div className="opportunity-card-head">
                  <span className="opportunity-card-title">
                    <GripVertical size={15} className="drag-handle" />
                    <strong>{opportunityName(item)}</strong>
                  </span>
                  {statusTag(item.premium?.opportunity_status)}
                </div>
                <div className="opportunity-card-codes">
                  {item.watchlist.a_ts_code} / {item.watchlist.hk_ts_code}
                </div>
                <div className="opportunity-card-metrics">
                  <span>
                    {item.premium?.metric_direction || item.watchlist.preferred_direction}
                    <b>{formatPercent(item.premium?.metric_premium_pct)}</b>
                  </span>
                  <span>
                    距阈值
                    <b>{formatPercent(item.premium?.distance_to_target_pct)}</b>
                  </span>
                  <span>
                    60日分位
                    <b>{formatPercent(item.premium?.premium_percentile_60)}</b>
                  </span>
                </div>
                <div className="opportunity-card-foot">
                  <Tag color={item.premium?.is_hk_connect ? 'green' : 'default'}>
                    {item.premium?.connect_channels || '非港股通'}
                  </Tag>
                  <span>
                    {item.premium?.source_updated_at
                      ? formatEast8DateTime(item.premium.source_updated_at)
                      : item.premium?.trade_date || '无数据'}
                  </span>
                </div>
              </button>
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
              <Skeleton active paragraph={{ rows: 4 }} />
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
            </Space>
          </div>
          {trend.data?.length ? (
            <ReactECharts
              ref={chartRef}
              key={`${pair.aTsCode}-${pair.hkTsCode}-${direction}`}
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
        <section className="panel overview-rank-panel">
          <div className="panel-title">自选明细</div>
          {watchlist.isLoading ? (
            <Skeleton active />
          ) : watchlistPremiums.length ? (
            <PremiumTable
              data={watchlistPremiums}
              pagination={false}
              onTrend={onShowPremiumTrend}
              onRemoveWatchlist={onRemoveWatchlist}
            />
          ) : data?.top_premiums.length ? (
            <PremiumTable data={data.top_premiums} pagination={false} onTrend={onShowPremiumTrend} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
      </div>
    </main>
  );
}

export default OverviewPage;
