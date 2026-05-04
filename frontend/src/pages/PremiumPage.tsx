import {
  Button,
  Checkbox,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  message
} from 'antd';
import ReactECharts from 'echarts-for-react';
import { Calculator, Search } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { calculatePremium, fetchPremiumTrend, fetchPremiums } from '../api/market';
import { createWatchlistItem } from '../api/watchlist';
import type { PremiumDirection, PremiumItem } from '../types/domain';
import type { PremiumQueryParams } from '../api/market';

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

function numberValue(value?: string | null) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

/**
 * AH 官方比价查询和官方派生指标重算页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function PremiumPage() {
  const [form] = Form.useForm<FilterValues>();
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<PremiumQueryParams>({
    direction: 'HA',
    only_hk_connect: true
  });
  const [selected, setSelected] = useState<PremiumItem | null>(null);
  const queryClient = useQueryClient();
  const premiums = useQuery({
    queryKey: ['premiums', filters, page],
    queryFn: () => fetchPremiums({ ...filters, page, page_size: 30 })
  });
  const trend = useQuery({
    queryKey: ['premium-trend', selected?.a_ts_code, selected?.hk_ts_code, selected?.metric_direction],
    queryFn: () => fetchPremiumTrend(selected!.a_ts_code, selected!.hk_ts_code, selected!.metric_direction),
    enabled: Boolean(selected)
  });
  const calculateMutation = useMutation({
    mutationFn: calculatePremium,
    onSuccess: (result) => {
      message.success(`派生指标重算完成：${result.calculated_rows} 条`);
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '计算失败')
  });
  const watchlistMutation = useMutation({
    mutationFn: createWatchlistItem,
    onSuccess: () => {
      message.success('已加入自选');
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '加入自选失败')
  });

  const trendOption = useMemo(
    () => ({
      tooltip: { trigger: 'axis' },
      legend: { top: 0, right: 16 },
      grid: { left: 48, right: 24, top: 42, bottom: 38 },
      xAxis: { type: 'category', data: trend.data?.map((item) => item.trade_date) || [] },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        {
          name: selected?.metric_direction === 'AH' ? 'A/H 溢价' : 'H/A 溢价',
          type: 'line',
          smooth: true,
          symbolSize: 7,
          data: trend.data?.map((item) => numberValue(item.metric_premium_pct)) || [],
          lineStyle: { color: '#2563eb', width: 3 },
          itemStyle: { color: '#0f766e' },
          areaStyle: { color: 'rgba(37, 99, 235, 0.12)' }
        },
        {
          name: '20日均值',
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_avg_20)) || [],
          lineStyle: { color: '#64748b', width: 1.5, type: 'dashed' }
        },
        {
          name: '60日均值',
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: trend.data?.map((item) => numberValue(item.premium_avg_60)) || [],
          lineStyle: { color: '#f59e0b', width: 1.5, type: 'dashed' }
        }
      ]
    }),
    [selected?.metric_direction, trend.data]
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

  const onCalculate = () => {
    const tradeDate = form.getFieldValue('trade_date') as dayjs.Dayjs | undefined;
    const targetDate = tradeDate || dayjs();
    calculateMutation.mutate({ start_date: targetDate.format('YYYY-MM-DD') });
  };

  const onAddWatchlist = (item: PremiumItem) => {
    watchlistMutation.mutate({
      a_ts_code: item.a_ts_code,
      hk_ts_code: item.hk_ts_code,
      display_name: item.a_name || item.hk_name || undefined,
      preferred_direction: item.metric_direction || 'HA',
      holding_market: 'UNKNOWN'
    });
  };

  return (
    <main className="page">
      <PageHeader title="AH 官方比价" />
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
                <Button icon={<Calculator size={16} />} onClick={onCalculate} loading={calculateMutation.isPending}>
                  重算派生
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
    </main>
  );
}

export default PremiumPage;
