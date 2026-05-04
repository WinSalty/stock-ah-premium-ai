import { Button, DatePicker, Drawer, Form, Input, InputNumber, Space, message } from 'antd';
import ReactECharts from 'echarts-for-react';
import { Calculator, Search } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import PremiumTable from '../components/PremiumTable';
import { calculatePremium, fetchPremiumTrend, fetchPremiums } from '../api/market';
import type { PremiumItem } from '../types/domain';
import type { PremiumQueryParams } from '../api/market';

interface FilterValues {
  trade_date?: dayjs.Dayjs;
  keyword?: string;
  min_premium?: number;
  max_premium?: number;
}

/**
 * AH 官方比价查询和实时计算页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function PremiumPage() {
  const [form] = Form.useForm<FilterValues>();
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<PremiumQueryParams>({});
  const [selected, setSelected] = useState<PremiumItem | null>(null);
  const queryClient = useQueryClient();
  const premiums = useQuery({
    queryKey: ['premiums', filters, page],
    queryFn: () => fetchPremiums({ ...filters, page, page_size: 30 })
  });
  const trend = useQuery({
    queryKey: ['premium-trend', selected?.a_ts_code, selected?.hk_ts_code],
    queryFn: () => fetchPremiumTrend(selected!.a_ts_code, selected!.hk_ts_code),
    enabled: Boolean(selected)
  });
  const calculateMutation = useMutation({
    mutationFn: calculatePremium,
    onSuccess: (result) => {
      message.success(`计算完成：${result.calculated_rows} 条`);
      queryClient.invalidateQueries({ queryKey: ['premiums'] });
      queryClient.invalidateQueries({ queryKey: ['premium-summary'] });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '计算失败')
  });

  const trendOption = useMemo(
    () => ({
      tooltip: { trigger: 'axis' },
      grid: { left: 48, right: 24, top: 26, bottom: 38 },
      xAxis: { type: 'category', data: trend.data?.map((item) => item.trade_date) || [] },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        {
          type: 'line',
          smooth: true,
          symbolSize: 7,
          data: trend.data?.map((item) => Number(item.ah_premium_pct || 0)) || [],
          lineStyle: { color: '#2563eb', width: 3 },
          itemStyle: { color: '#0f766e' },
          areaStyle: { color: 'rgba(37, 99, 235, 0.12)' }
        }
      ]
    }),
    [trend.data]
  );

  const onSearch = (values: FilterValues) => {
    setPage(1);
    setFilters({
      trade_date: values.trade_date?.format('YYYY-MM-DD'),
      keyword: values.keyword?.trim() || undefined,
      min_premium: values.min_premium,
      max_premium: values.max_premium
    });
  };

  const onCalculate = () => {
    const tradeDate = form.getFieldValue('trade_date') as dayjs.Dayjs | undefined;
    const targetDate = tradeDate || dayjs();
    calculateMutation.mutate({ start_date: targetDate.format('YYYY-MM-DD') });
  };

  return (
    <main className="page">
      <PageHeader title="AH 官方比价" />
      <section className="panel">
        <Form form={form} layout="vertical" onFinish={onSearch}>
          <div className="premium-filter-grid">
            <Form.Item label="交易日" name="trade_date">
              <DatePicker className="full-width" />
            </Form.Item>
            <Form.Item label="股票" name="keyword">
              <Input placeholder="代码或名称" />
            </Form.Item>
            <Form.Item label="最小溢价" name="min_premium">
              <InputNumber className="full-width" addonAfter="%" />
            </Form.Item>
            <Form.Item label="最大溢价" name="max_premium">
              <InputNumber className="full-width" addonAfter="%" />
            </Form.Item>
            <Form.Item label=" ">
              <Space>
                <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
                  查询
                </Button>
                <Button icon={<Calculator size={16} />} onClick={onCalculate} loading={calculateMutation.isPending}>
                  刷新实时
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
