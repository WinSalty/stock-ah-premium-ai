import {
  Alert,
  Button,
  Checkbox,
  DatePicker,
  Drawer,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Switch,
  message
} from 'antd';
import ReactECharts from 'echarts-for-react';
import ReactMarkdown from 'react-markdown';
import { Bot, QrCode, Search } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import dayjs from 'dayjs';
import LlmProgressNote from '../components/LlmProgressNote';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { createChatSession, sendChatMessage } from '../api/chat';
import { fetchPremiumTrend, fetchPremiums } from '../api/market';
import { createPushplusQrCode, fetchPushplusBinding } from '../api/notifications';
import { createWatchlistItem, deleteWatchlistItem, updateWatchlistItem } from '../api/watchlist';
import type {
  HoldingMarket,
  PremiumDirection,
  PremiumItem,
  PriceAlertOperator,
  UserInfo
} from '../types/domain';
import type { PremiumQueryParams } from '../api/market';
import {
  getCachedThresholdRecommendation,
  setCachedThresholdRecommendation
} from '../utils/thresholdRecommendationCache';
import { THRESHOLD_RECOMMENDATION_PROGRESS_STEPS } from '../constants/llmProgress';
import { PUSHPLUS_BIND_SUCCESS_NOTICE } from '../constants/pushplus';

const AH_COLOR = '#2563eb';
const HA_COLOR = '#0f766e';
const MEDIAN60_COLOR = '#334155';
const P20_COLOR = '#14b8a6';
const P80_COLOR = '#f97316';

interface FilterValues {
  trade_date?: dayjs.Dayjs;
  keyword?: string;
  min_premium?: number;
  max_premium?: number;
  min_ha_premium?: number;
  max_ha_premium?: number;
  direction?: PremiumDirection;
  channel?: string;
  only_hk_connect?: boolean;
  only_watchlist?: boolean;
}

interface WatchlistFormValues {
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
  note?: string;
}

interface WatchlistModalState {
  mode: 'create' | 'edit';
  item: PremiumItem;
}

function numberValue(value?: string | null) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function thresholdHelpText(direction?: PremiumDirection) {
  const directionLabel = direction === 'AH' ? 'A/H' : 'H/A';
  return `填写 ${directionLabel} 溢价触发线，单位为百分比，只填数字不带 %；留空则只观察不判断达阈值。系统按“当前${directionLabel}溢价 >= 目标阈值”判定达阈值，并按“目标阈值 - 当前${directionLabel}溢价”显示距阈值。`;
}

function promptValue(value?: string | number | null, suffix = '') {
  return value === null || value === undefined || value === '' ? '缺失' : `${value}${suffix}`;
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

function holdingMarketLabel(value?: HoldingMarket | string | null) {
  const map: Record<string, string> = {
    A: 'A 股',
    H: 'H 股',
    UNKNOWN: '未设置'
  };
  return map[value || 'UNKNOWN'] || value || '未设置';
}

function buildModalThresholdPrompt(item: PremiumItem, values: WatchlistFormValues) {
  const direction = values.preferred_direction || item.metric_direction || 'HA';
  const directionLabel = direction === 'AH' ? 'A/H' : 'H/A';
  const metricPremium = direction === 'AH' ? item.ah_premium_pct : item.ha_premium_pct;
  return [
    `请为“${values.display_name || item.a_name || item.hk_name || item.a_ts_code}”推荐一个 ${directionLabel} 目标阈值。`,
    '场景是用户正在设置自选股提醒阈值。请优先按知识库中的“自选阈值推荐逻辑”给出稳定、可复核的建议。',
    '',
    '当前页面数据：',
    `- A 股 / H 股代码：${item.a_ts_code} / ${item.hk_ts_code}`,
    `- 关注方向：${directionLabel}`,
    `- 持有侧：${holdingMarketLabel(values.holding_market)}`,
    `- 当前填写阈值：${promptValue(values.target_premium_pct, '%')}`,
    `- 当前 ${directionLabel} 溢价：${promptValue(metricPremium, '%')}`,
    `- A/H 溢价：${promptValue(item.ah_premium_pct, '%')}`,
    `- H/A 溢价：${promptValue(item.ha_premium_pct, '%')}`,
    `- 60 日中位数：${promptValue(item.premium_median_60, '%')}`,
    `- 60 日 20% 分位：${promptValue(item.premium_p20_60, '%')}`,
    `- 60 日 80% 分位：${promptValue(item.premium_p80_60, '%')}`,
    `- 当前 60 日分位：${promptValue(item.premium_percentile_60, '%')}`,
    `- 港股通通道：${item.connect_channels || '不可通过港股通操作或缺失'}`,
    '',
    '请严格输出中文 Markdown，并包含以下三个小节。不要输出“不构成投资建议”等免责句。',
    '## 最终答案',
    `一句话给出“建议将 ${directionLabel} 目标阈值设为 X%”。`,
    '## 推荐理由',
    '3-5 条，必须覆盖历史分位、当前价差、持有侧、港股通可操作性和阈值缓冲。',
    '## 执行条件',
    '给出何时触发、何时上调/下调阈值、需要复核的成交活跃度、汇率和基本面条件。'
  ].join('\n');
}

function buildModalThresholdDisplayQuestion(item: PremiumItem, values: WatchlistFormValues) {
  const direction = values.preferred_direction || item.metric_direction || 'HA';
  const directionLabel = direction === 'AH' ? 'A/H' : 'H/A';
  return `为${values.display_name || item.a_name || item.hk_name || item.a_ts_code}推荐 ${directionLabel} 目标阈值`;
}

type RecommendationSource = 'fresh' | 'cached';

interface PremiumPageProps {
  currentUser: UserInfo;
}

/**
 * AH 官方比价查询和自选机会筛选页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function PremiumPage({ currentUser }: PremiumPageProps) {
  const [form] = Form.useForm<FilterValues>();
  const [watchlistForm] = Form.useForm<WatchlistFormValues>();
  const watchlistDirection = Form.useWatch('preferred_direction', watchlistForm);
  const watchlistPushEnabled = Form.useWatch('push_enabled', watchlistForm);
  const watchlistTargetPremium = Form.useWatch('target_premium_pct', watchlistForm);
  const watchlistAPriceAlertEnabled = Form.useWatch('a_price_alert_enabled', watchlistForm);
  const watchlistAPriceAlertTarget = Form.useWatch('a_price_alert_target_price', watchlistForm);
  const watchlistHPriceAlertEnabled = Form.useWatch('h_price_alert_enabled', watchlistForm);
  const watchlistHPriceAlertTarget = Form.useWatch('h_price_alert_target_price', watchlistForm);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<PremiumQueryParams>({
    direction: 'HA',
    only_hk_connect: true
  });
  const [selected, setSelected] = useState<PremiumItem | null>(null);
  const [watchlistModal, setWatchlistModal] = useState<WatchlistModalState | null>(null);
  const [thresholdRecommendation, setThresholdRecommendation] = useState('');
  const [thresholdRecommendationProgress, setThresholdRecommendationProgress] = useState('');
  const [thresholdRecommendationSource, setThresholdRecommendationSource] =
    useState<RecommendationSource>('fresh');
  const queryClient = useQueryClient();
  const premiums = useQuery({
    queryKey: ['premiums', filters, page],
    queryFn: () => fetchPremiums({ ...filters, page, page_size: 30 })
  });
  const pushplusBinding = useQuery({
    queryKey: ['pushplus-binding'],
    queryFn: fetchPushplusBinding
  });
  const hasPushplusChannel = Boolean(
    pushplusBinding.data?.is_bound || currentUser.can_use_personal_pushplus
  );
  const trend = useQuery({
    queryKey: ['premium-trend', selected?.a_ts_code, selected?.hk_ts_code, selected?.metric_direction],
    queryFn: () => fetchPremiumTrend(selected!.a_ts_code, selected!.hk_ts_code, selected!.metric_direction),
    enabled: Boolean(selected)
  });
  const qrCodeMutation = useMutation({
    mutationFn: () => createPushplusQrCode({ expire_seconds: 604800, scan_count: 1 }),
    onError: (error) => message.error(error instanceof Error ? error.message : '生成二维码失败')
  });
  const watchlistMutation = useMutation({
    mutationFn: ({ mode, item, values }: WatchlistModalState & { values: WatchlistFormValues }) => {
      const displayName = values.display_name?.trim();
      const note = values.note?.trim();
      if (mode === 'edit') {
        if (!item.watchlist_id) {
          throw new Error('自选股不存在');
        }
        return updateWatchlistItem(item.watchlist_id, {
          display_name: displayName || null,
          preferred_direction: values.preferred_direction,
          target_premium_pct: values.target_premium_pct ?? null,
          push_enabled: values.push_enabled ?? true,
          a_price_alert_enabled: Boolean(values.a_price_alert_enabled),
          a_price_alert_operator: values.a_price_alert_operator || 'GTE',
          a_price_alert_target_price: values.a_price_alert_target_price ?? null,
          h_price_alert_enabled: Boolean(values.h_price_alert_enabled),
          h_price_alert_operator: values.h_price_alert_operator || 'GTE',
          h_price_alert_target_price: values.h_price_alert_target_price ?? null,
          holding_market: values.holding_market
        });
      }
      return createWatchlistItem({
        a_ts_code: item.a_ts_code,
        hk_ts_code: item.hk_ts_code,
        display_name: displayName || undefined,
        preferred_direction: values.preferred_direction,
        target_premium_pct: values.target_premium_pct ?? undefined,
        push_enabled: values.push_enabled ?? true,
        a_price_alert_enabled: Boolean(values.a_price_alert_enabled),
        a_price_alert_operator: values.a_price_alert_operator || 'GTE',
        a_price_alert_target_price: values.a_price_alert_target_price ?? undefined,
        h_price_alert_enabled: Boolean(values.h_price_alert_enabled),
        h_price_alert_operator: values.h_price_alert_operator || 'GTE',
        h_price_alert_target_price: values.h_price_alert_target_price ?? undefined,
        holding_market: values.holding_market,
        note: note || undefined
      });
    },
    onSuccess: (_, variables) => {
      message.success(variables.mode === 'edit' ? '自选配置已更新' : '已加入自选');
      setWatchlistModal(null);
      watchlistForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '保存自选失败')
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
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '取消自选失败')
  });
  const thresholdRecommendationMutation = useMutation({
    mutationFn: async () => {
      if (!watchlistModal) {
        throw new Error('请选择股票');
      }
      setThresholdRecommendationProgress(THRESHOLD_RECOMMENDATION_PROGRESS_STEPS[0]);
      let progressIndex = 0;
      let progressTimer: number | null = window.setInterval(() => {
        progressIndex = Math.min(progressIndex + 1, THRESHOLD_RECOMMENDATION_PROGRESS_STEPS.length - 1);
        setThresholdRecommendationProgress(THRESHOLD_RECOMMENDATION_PROGRESS_STEPS[progressIndex]);
      }, 2600);
      const values = watchlistForm.getFieldsValue();
      const direction = values.preferred_direction || watchlistModal.item.metric_direction || 'HA';
      const cacheInput = {
        aTsCode: watchlistModal.item.a_ts_code,
        hkTsCode: watchlistModal.item.hk_ts_code,
        direction
      };
      try {
        const cached = getCachedThresholdRecommendation(cacheInput);
        if (cached) {
          return { answer: cached.answer, source: 'cached' as RecommendationSource };
        }
        const session = await createChatSession(
          `阈值建议：${values.display_name || watchlistModal.item.a_name || watchlistModal.item.a_ts_code}`
        );
        const result = await sendChatMessage(session.id, {
          question: buildModalThresholdPrompt(watchlistModal.item, values),
          display_question: buildModalThresholdDisplayQuestion(watchlistModal.item, values),
          only_watchlist: true,
          ts_code: watchlistModal.item.a_ts_code
        });
        setCachedThresholdRecommendation(cacheInput, result.answer);
        return { answer: result.answer, source: 'fresh' as RecommendationSource };
      } finally {
        if (progressTimer !== null) {
          window.clearInterval(progressTimer);
          progressTimer = null;
        }
        setThresholdRecommendationProgress('');
      }
    },
    onSuccess: (result) => {
      setThresholdRecommendation(result.answer);
      setThresholdRecommendationSource(result.source);
    },
    onError: (error) => message.error(error instanceof Error ? error.message : 'AI 推荐失败')
  });

  const trendMetricColor = selected?.metric_direction === 'AH' ? AH_COLOR : HA_COLOR;
  const modalHasAlertConfig = hasAlertConfig({
    preferred_direction: watchlistDirection || 'HA',
    target_premium_pct: watchlistTargetPremium,
    a_price_alert_enabled: watchlistAPriceAlertEnabled,
    a_price_alert_target_price: watchlistAPriceAlertTarget,
    h_price_alert_enabled: watchlistHPriceAlertEnabled,
    h_price_alert_target_price: watchlistHPriceAlertTarget,
    holding_market: 'UNKNOWN'
  });
  const modalRequiresBinding = modalHasAlertConfig && watchlistPushEnabled !== false;
  useEffect(() => {
    if (!qrCodeMutation.data || pushplusBinding.data?.is_bound) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['pushplus-binding'] });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [pushplusBinding.data?.is_bound, qrCodeMutation.data, queryClient]);

  const trendOption = useMemo(
    () => ({
      color: [trendMetricColor, MEDIAN60_COLOR, P20_COLOR, P80_COLOR],
      tooltip: { trigger: 'axis' },
      legend: { top: 0, right: 16 },
      grid: { left: 48, right: 24, top: 42, bottom: 38 },
      xAxis: { type: 'category', data: trend.data?.map((item) => item.trade_date) || [] },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        {
          name: selected?.metric_direction === 'AH' ? 'A/H 溢价' : 'H/A 溢价',
          type: 'line',
          smooth: false,
          symbolSize: 7,
          data: trend.data?.map((item) => numberValue(item.metric_premium_pct)) || [],
          lineStyle: { color: trendMetricColor, width: 3 },
          itemStyle: { color: trendMetricColor },
          areaStyle: { color: trendMetricColor, opacity: 0.12 }
        },
        {
          name: '60日中位数',
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_median_60)) || [],
          lineStyle: { color: MEDIAN60_COLOR, width: 1.8, type: 'dashed' },
          itemStyle: { color: MEDIAN60_COLOR }
        },
        {
          name: '20%分位',
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_p20_60)) || [],
          lineStyle: { color: P20_COLOR, width: 1.4, type: 'dotted' },
          itemStyle: { color: P20_COLOR }
        },
        {
          name: '80%分位',
          type: 'line',
          smooth: false,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_p80_60)) || [],
          lineStyle: { color: P80_COLOR, width: 1.4, type: 'dotted' },
          itemStyle: { color: P80_COLOR }
        }
      ]
    }),
    [selected?.metric_direction, trend.data, trendMetricColor]
  );

  const onSearch = (values: FilterValues) => {
    setPage(1);
    setFilters({
      trade_date: values.trade_date?.format('YYYY-MM-DD'),
      keyword: values.keyword?.trim() || undefined,
      min_premium: values.min_premium,
      max_premium: values.max_premium,
      min_ha_premium: values.min_ha_premium,
      max_ha_premium: values.max_ha_premium,
      direction: values.direction || 'HA',
      channel: values.channel,
      only_hk_connect: values.only_hk_connect,
      only_watchlist: values.only_watchlist
    });
  };

  const onAddWatchlist = (item: PremiumItem) => {
    watchlistForm.setFieldsValue({
      display_name: item.a_name || item.hk_name || undefined,
      preferred_direction: item.metric_direction || filters.direction || 'HA',
      target_premium_pct: undefined,
      push_enabled: true,
      a_price_alert_enabled: false,
      a_price_alert_operator: 'GTE',
      a_price_alert_target_price: undefined,
      h_price_alert_enabled: false,
      h_price_alert_operator: 'GTE',
      h_price_alert_target_price: undefined,
      holding_market: 'UNKNOWN',
      note: undefined
    });
    setThresholdRecommendation('');
    setThresholdRecommendationProgress('');
    setThresholdRecommendationSource('fresh');
    setWatchlistModal({ mode: 'create', item });
  };

  const onEditWatchlist = (item: PremiumItem) => {
    watchlistForm.setFieldsValue({
      display_name: item.watchlist_display_name || item.a_name || item.hk_name || undefined,
      preferred_direction: item.preferred_direction || item.metric_direction || 'HA',
      target_premium_pct: numberValue(item.target_premium_pct),
      push_enabled: item.push_enabled ?? true,
      a_price_alert_enabled: Boolean(item.a_price_alert_enabled),
      a_price_alert_operator: (item.a_price_alert_operator as PriceAlertOperator) || 'GTE',
      a_price_alert_target_price: numberValue(item.a_price_alert_target_price),
      h_price_alert_enabled: Boolean(item.h_price_alert_enabled),
      h_price_alert_operator: (item.h_price_alert_operator as PriceAlertOperator) || 'GTE',
      h_price_alert_target_price: numberValue(item.h_price_alert_target_price),
      holding_market: (item.holding_market as HoldingMarket) || 'UNKNOWN',
      note: undefined
    });
    setThresholdRecommendation('');
    setThresholdRecommendationProgress('');
    setThresholdRecommendationSource('fresh');
    setWatchlistModal({ mode: 'edit', item });
  };

  const onSubmitWatchlist = async () => {
    if (!watchlistModal) {
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
    watchlistMutation.mutate({ ...watchlistModal, values });
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

  return (
    <main className="page">
      <PageHeader title="AH 机会筛选" />
      <section className="panel">
        <Form
          form={form}
          layout="vertical"
          onFinish={onSearch}
          initialValues={{ direction: 'HA', only_hk_connect: true }}
        >
          <div className="premium-filter-grid">
            <Form.Item label="交易日" name="trade_date">
              <DatePicker className="full-width" />
            </Form.Item>
            <Form.Item label="股票" name="keyword">
              <Input placeholder="代码或名称" />
            </Form.Item>
            <Form.Item label="方向" name="direction">
              <Select
                options={[
                  { value: 'HA', label: 'H/A' },
                  { value: 'AH', label: 'A/H' }
                ]}
              />
            </Form.Item>
            <Form.Item label="通道" name="channel">
              <Select
                allowClear
                placeholder="全部"
                options={[
                  { value: 'SH_HK', label: 'SH_HK' },
                  { value: 'SZ_HK', label: 'SZ_HK' }
                ]}
              />
            </Form.Item>
            <Form.Item label="最小 A/H" name="min_premium">
              <InputNumber className="full-width" addonAfter="%" />
            </Form.Item>
            <Form.Item label="最大 A/H" name="max_premium">
              <InputNumber className="full-width" addonAfter="%" />
            </Form.Item>
            <Form.Item label="最小 H/A" name="min_ha_premium">
              <InputNumber className="full-width" addonAfter="%" />
            </Form.Item>
            <Form.Item label="最大 H/A" name="max_ha_premium">
              <InputNumber className="full-width" addonAfter="%" />
            </Form.Item>
            <Form.Item label="范围" name="only_hk_connect" valuePropName="checked">
              <Checkbox>只看港股通</Checkbox>
            </Form.Item>
            <Form.Item label="自选" name="only_watchlist" valuePropName="checked">
              <Checkbox>只看自选</Checkbox>
            </Form.Item>
            <Form.Item label=" ">
              <Space>
                <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
                  查询
                </Button>
              </Space>
            </Form.Item>
          </div>
        </Form>
      </section>

      <section className="panel">
        <PremiumTable
          data={premiums.data?.items || []}
          loading={premiums.isLoading}
          pagination={{
            current: page,
            pageSize: 30,
            total: premiums.data?.total || 0,
            onChange: setPage
          }}
          onTrend={setSelected}
          onAddWatchlist={onAddWatchlist}
          onEditWatchlist={onEditWatchlist}
          onRemoveWatchlist={onRemoveWatchlist}
        />
      </section>

      <Drawer
        title={selected ? `${selected.a_name || selected.a_ts_code} / ${selected.hk_name || selected.hk_ts_code}` : ''}
        width={680}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
      >
        <ReactECharts option={trendOption} style={{ height: 360 }} showLoading={trend.isLoading} />
      </Drawer>

      <Modal
        title={watchlistModal?.mode === 'edit' ? '编辑自选' : '加入自选'}
        open={Boolean(watchlistModal)}
        onOk={onSubmitWatchlist}
        confirmLoading={watchlistMutation.isPending}
        onCancel={() => {
          setWatchlistModal(null);
          watchlistForm.resetFields();
          setThresholdRecommendation('');
          setThresholdRecommendationProgress('');
          setThresholdRecommendationSource('fresh');
        }}
        okText="保存"
        cancelText="取消"
      >
        <Form form={watchlistForm} layout="vertical">
          <Form.Item label="展示名" name="display_name">
            <Input maxLength={128} />
          </Form.Item>
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
            extra={thresholdHelpText(watchlistDirection)}
          >
            <Space.Compact className="threshold-recommend-control">
              <Form.Item name="target_premium_pct" noStyle>
                <InputNumber addonAfter="%" precision={2} placeholder="例如 -15 或 30" />
              </Form.Item>
              <Button
                htmlType="button"
                icon={<Bot size={16} />}
                loading={thresholdRecommendationMutation.isPending}
                onClick={() => {
                  setThresholdRecommendation('');
                  setThresholdRecommendationProgress('');
                  setThresholdRecommendationSource('fresh');
                  thresholdRecommendationMutation.mutate();
                }}
              >
                AI 推荐
              </Button>
            </Space.Compact>
          </Form.Item>
          {thresholdRecommendation || thresholdRecommendationMutation.isPending ? (
            <div className="ai-recommendation-box modal-ai-recommendation">
              <div className="ai-recommendation-head">
                <Bot size={16} />
                <strong>
                  {thresholdRecommendationSource === 'cached' ? '之前 AI 推荐信息' : 'AI 阈值建议'}
                </strong>
              </div>
              {thresholdRecommendation ? (
                <div className="markdown-answer">
                  <ReactMarkdown>{thresholdRecommendation}</ReactMarkdown>
                </div>
              ) : (
                <LlmProgressNote
                  className="threshold-progress-note"
                  text={thresholdRecommendationProgress}
                  fallback="正在推荐阈值..."
                />
              )}
            </div>
          ) : null}
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
          <Form.Item label="持有侧" name="holding_market" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'UNKNOWN', label: '未设置' },
                { value: 'A', label: 'A 股' },
                { value: 'H', label: 'H 股' }
              ]}
            />
          </Form.Item>
          {watchlistModal?.mode === 'create' ? (
            <Form.Item label="备注" name="note">
              <Input.TextArea rows={3} />
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
    </main>
  );
}

export default PremiumPage;
