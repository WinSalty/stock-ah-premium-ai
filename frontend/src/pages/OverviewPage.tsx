import { Card, Col, Empty, Row, Skeleton, Statistic } from 'antd';
import ReactECharts from 'echarts-for-react';
import { useQuery } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { fetchPremiumSummary } from '../api/market';

/**
 * 数据总览页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function OverviewPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['premium-summary'],
    queryFn: fetchPremiumSummary
  });

  const chartOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 20, top: 28, bottom: 34 },
    xAxis: {
      type: 'category',
      data: data?.top_premiums.map((item) => item.hk_name || item.hk_ts_code) || [],
      axisLabel: { interval: 0, rotate: 28 }
    },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      {
        type: 'bar',
        data: data?.top_premiums.map((item) => Number(item.ah_premium_pct || 0)) || [],
        itemStyle: { color: '#ef4444' },
        barMaxWidth: 28
      }
    ]
  };

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

      <div className="content-grid">
        <section className="panel panel-wide">
          <div className="panel-title">溢价榜</div>
          {isLoading ? (
            <Skeleton active />
          ) : data?.top_premiums.length ? (
            <PremiumTable data={data.top_premiums} pagination={false} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
        <section className="panel">
          <div className="panel-title">Top 10 分布</div>
          {data?.top_premiums.length ? (
            <ReactECharts option={chartOption} style={{ height: 360 }} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
      </div>
    </main>
  );
}

export default OverviewPage;
