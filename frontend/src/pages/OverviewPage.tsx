import {
  Alert,
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
import { useEffect, useMemo, useState } from 'react';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { fetchOfficialPremiumTrend, fetchPremiumPairs, fetchPremiumSummary } from '../api/market';
import { deleteWatchlistItem, fetchWatchlist } from '../api/watchlist';
import type { PremiumDirection, PremiumItem, PremiumPairOption, WatchlistOpportunity } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

const DEFAULT_PAIR_KEY = '600036.SH|03968.HK';
const DEFAULT_VISIBLE_MONTHS = 3;
const MIN_VISIBLE_POINTS = 20;

function splitPairKey(value: string) {
  const [aTsCode, hkTsCode] = value.split('|');
  return { aTsCode, hkTsCode };
}

function formatPairLabel(item: PremiumPairOption) {
  const rawAName = item.a_name?.trim();
  const aName = rawAName || item.a_ts_code;
  const hkName = item.hk_name?.trim() || item.hk_ts_code;
  const codeLabel = `${item.a_ts_code} / ${item.hk_ts_code}`;
  const aDisplayName = rawAName?.startsWith('XD') ? `${aName}（除息）` : aName;

  if (aName === hkName) {
    return `${aDisplayName} (${codeLabel})`;
  }

  return `${aDisplayName} / ${hkName} (${codeLabel})`;
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

/**
 * 数据总览页面，默认呈现自选股机会状态。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function OverviewPage() {
  const [pairKey, setPairKey] = useState(DEFAULT_PAIR_KEY);
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<number | null>(null);
  const [fallbackDirection, setFallbackDirection] = useState<PremiumDirection>('HA');
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['premium-summary'],
    queryFn: fetchPremiumSummary
  });
  const pairs = useQuery({ queryKey: ['premium-pairs'], queryFn: () => fetchPremiumPairs() });
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: () => fetchWatchlist() });
  const opportunities = watchlist.data || [];
  const selectedOpportunity =
    opportunities.find((item) => item.watchlist.id === selectedWatchlistId) || opportunities[0];
  const selectedPremium = selectedOpportunity?.premium || null;
  const direction = selectedPremium?.metric_direction || fallbackDirection;
  const chartPairKey = selectedPremium
    ? `${selectedPremium.a_ts_code}|${selectedPremium.hk_ts_code}`
    : pairKey;
  const pair = splitPairKey(chartPairKey);
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

  useEffect(() => {
    if (!opportunities.length) {
      setSelectedWatchlistId(null);
      return;
    }
    if (!selectedWatchlistId || !opportunities.some((item) => item.watchlist.id === selectedWatchlistId)) {
      setSelectedWatchlistId(opportunities[0].watchlist.id);
    }
  }, [opportunities, selectedWatchlistId]);

  useEffect(() => {
    if (!pairs.data?.length || selectedPremium) {
      return;
    }
    if (pairs.data.some((item) => `${item.a_ts_code}|${item.hk_ts_code}` === pairKey)) {
      return;
    }
    const defaultPair = pairs.data.find(
      (item) => item.a_ts_code === '600036.SH' && item.hk_ts_code === '03968.HK'
    );
    const fallbackPair = defaultPair || pairs.data[0];
    setPairKey(`${fallbackPair.a_ts_code}|${fallbackPair.hk_ts_code}`);
  }, [pairKey, pairs.data, selectedPremium]);

  const watchlistPremiums = opportunities
    .map((item) => item.premium)
    .filter((item): item is PremiumItem => Boolean(item));
  const statusCounts = opportunities.reduce<Record<string, number>>((acc, item) => {
    const key = item.premium?.opportunity_status || 'DATA_ISSUE';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const selectedPair = pairs.data?.find((item) => `${item.a_ts_code}|${item.hk_ts_code}` === pairKey);
  const trendTitleName =
    selectedOpportunity ? opportunityName(selectedOpportunity) : selectedPair?.a_name || pair.aTsCode;
  const directionLabel = direction === 'HA' ? 'H/A' : 'A/H';
  const trendDates = useMemo(() => trend.data?.map((item) => item.trade_date) || [], [trend.data]);
  const defaultZoomStartValue = getDefaultZoomStartValue(trendDates);
  const defaultZoomEndValue = trendDates[trendDates.length - 1];
  const minZoomValueSpan = Math.min(Math.max(trendDates.length - 1, 1), MIN_VISIBLE_POINTS);
  const targetValue = numberValue(selectedOpportunity?.watchlist.target_premium_pct);

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

  const trendChartOption = useMemo(
    () => ({
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
          zoomOnMouseWheel: 'shift',
          moveOnMouseWheel: true,
          moveOnMouseMove: false
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
          smooth: true,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.metric_premium_pct)) || [],
          lineStyle: { width: 3, color: direction === 'HA' ? '#0f766e' : '#2563eb' },
          itemStyle: { color: direction === 'HA' ? '#0f766e' : '#2563eb' },
          areaStyle: { opacity: 0.08 },
          emphasis: { focus: 'series' }
        },
        {
          name: '20日均值',
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_avg_20)) || [],
          lineStyle: { width: 1.5, color: '#64748b', type: 'dashed' }
        },
        {
          name: '60日均值',
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_avg_60)) || [],
          lineStyle: { width: 1.5, color: '#f59e0b', type: 'dashed' }
        },
        targetValue === null
          ? null
          : {
              name: '目标阈值',
              type: 'line',
              showSymbol: false,
              data: trendDates.map(() => targetValue),
              lineStyle: { width: 2, color: '#dc2626', type: 'dotted' }
            }
      ].filter(Boolean)
    }),
    [
      defaultZoomEndValue,
      defaultZoomStartValue,
      direction,
      directionLabel,
      minZoomValueSpan,
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

      <section className="panel opportunity-panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">自选机会</div>
            <Typography.Text type="secondary">
              官方 AH 口径，H/A 由 A/H 反推；港股通通道来自当日沪深港通名单。
            </Typography.Text>
          </div>
        </div>
        {watchlist.isLoading ? (
          <Skeleton active />
        ) : opportunities.length ? (
          <div className="opportunity-grid">
            {opportunities.map((item) => (
              <button
                key={item.watchlist.id}
                className={`opportunity-card ${item.watchlist.id === selectedWatchlistId ? 'active' : ''}`}
                onClick={() => setSelectedWatchlistId(item.watchlist.id)}
              >
                <div className="opportunity-card-head">
                  <strong>{opportunityName(item)}</strong>
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
      </section>

      <div className="content-grid overview-grid">
        <section className="panel overview-chart-panel">
          <div className="overview-chart-head">
            <div className="panel-title">
              {trendTitleName} {directionLabel} 溢价走势
            </div>
            {!selectedOpportunity ? (
              <Space wrap>
                <Select
                  className="overview-pair-select"
                  showSearch
                  value={pairKey}
                  loading={pairs.isLoading}
                  optionFilterProp="label"
                  options={pairs.data?.map((item) => ({
                    value: `${item.a_ts_code}|${item.hk_ts_code}`,
                    label: formatPairLabel(item)
                  }))}
                  onChange={setPairKey}
                />
                <Select
                  value={fallbackDirection}
                  className="overview-direction-select"
                  options={[
                    { value: 'HA', label: 'H/A' },
                    { value: 'AH', label: 'A/H' }
                  ]}
                  onChange={setFallbackDirection}
                />
              </Space>
            ) : null}
          </div>
          {trend.data?.length ? (
            <ReactECharts option={trendChartOption} className="overview-chart" />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
        <section className="panel overview-rank-panel">
          <div className="panel-title">自选明细</div>
          {watchlist.isLoading ? (
            <Skeleton active />
          ) : watchlistPremiums.length ? (
            <PremiumTable data={watchlistPremiums} pagination={false} onRemoveWatchlist={onRemoveWatchlist} />
          ) : data?.top_premiums.length ? (
            <PremiumTable data={data.top_premiums} pagination={false} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
      </div>
    </main>
  );
}

export default OverviewPage;
