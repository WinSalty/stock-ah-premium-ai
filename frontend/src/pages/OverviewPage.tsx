import { Card, Col, Empty, Row, Select, Skeleton, Space, Statistic } from 'antd';
import ReactECharts from 'echarts-for-react';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { fetchOfficialPremiumTrend, fetchPremiumPairs, fetchPremiumSummary } from '../api/market';

type PremiumDirection = 'AH' | 'HA';

const DEFAULT_PAIR_KEY = '600036.SH|03968.HK';

function splitPairKey(value: string) {
  const [aTsCode, hkTsCode] = value.split('|');
  return { aTsCode, hkTsCode };
}

/**
 * 数据总览页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function OverviewPage() {
  const [pairKey, setPairKey] = useState(DEFAULT_PAIR_KEY);
  const [direction, setDirection] = useState<PremiumDirection>('HA');
  const { data, isLoading } = useQuery({
    queryKey: ['premium-summary'],
    queryFn: fetchPremiumSummary
  });
  const pairs = useQuery({ queryKey: ['premium-pairs'], queryFn: () => fetchPremiumPairs() });
  const pair = splitPairKey(pairKey);
  const trend = useQuery({
    queryKey: ['official-premium-trend', pair.aTsCode, pair.hkTsCode],
    enabled: Boolean(pair.aTsCode && pair.hkTsCode),
    queryFn: () => fetchOfficialPremiumTrend(pair.aTsCode, pair.hkTsCode)
  });

  useEffect(() => {
    if (!pairs.data?.length) {
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
  }, [pairKey, pairs.data]);

  const selectedPair = pairs.data?.find((item) => `${item.a_ts_code}|${item.hk_ts_code}` === pairKey);
  const trendTitleName = selectedPair?.a_name || trend.data?.[0]?.a_name || pair.aTsCode;
  const directionLabel = direction === 'HA' ? 'H/A' : 'A/H';

  const trendChartOption = useMemo(
    () => ({
      tooltip: { trigger: 'axis', valueFormatter: (value: number) => `${value.toFixed(2)}%` },
      grid: { left: 48, right: 20, top: 28, bottom: 34 },
      xAxis: {
        type: 'category',
        data: trend.data?.map((item) => item.trade_date) || []
      },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        {
          type: 'line',
          smooth: true,
          symbolSize: 7,
          data:
            trend.data?.map((item) =>
              Number(direction === 'HA' ? item.ha_premium_pct || 0 : item.ah_premium_pct || 0)
            ) || [],
          lineStyle: { width: 3, color: direction === 'HA' ? '#0f766e' : '#2563eb' },
          itemStyle: { color: direction === 'HA' ? '#0f766e' : '#2563eb' },
          areaStyle: { opacity: 0.08 }
        }
      ]
    }),
    [direction, trend.data]
  );

  return (
    <main className="page">
      <PageHeader title="数据总览" />
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="最新交易日" value={data?.latest_trade_date || '-'} loading={isLoading} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="已计算配对" value={data?.calculated_count || 0} loading={isLoading} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="异常记录" value={data?.issue_count || 0} loading={isLoading} />
          </Card>
        </Col>
      </Row>

      <div className="content-grid overview-grid">
        <section className="panel">
          <div className="overview-chart-head">
            <div className="panel-title">{trendTitleName} {directionLabel} 溢价走势</div>
            <Space wrap>
              <Select
                className="overview-pair-select"
                showSearch
                value={pairKey}
                loading={pairs.isLoading}
                optionFilterProp="label"
                options={pairs.data?.map((item) => ({
                  value: `${item.a_ts_code}|${item.hk_ts_code}`,
                  label: `${item.a_name || item.a_ts_code} / ${item.hk_name || item.hk_ts_code}`
                }))}
                onChange={setPairKey}
              />
              <Select
                value={direction}
                className="overview-direction-select"
                options={[
                  { value: 'HA', label: 'H/A' },
                  { value: 'AH', label: 'A/H' }
                ]}
                onChange={setDirection}
              />
            </Space>
          </div>
          {trend.data?.length ? (
            <ReactECharts option={trendChartOption} style={{ height: 360 }} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
        <section className="panel">
          <div className="panel-title">溢价榜</div>
          {isLoading ? (
            <Skeleton active />
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
