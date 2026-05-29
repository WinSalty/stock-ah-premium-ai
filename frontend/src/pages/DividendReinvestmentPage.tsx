import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography
} from 'antd';
import type { TableColumnsType } from 'antd';
import { RotateCw, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import {
  fetchDividendReinvestmentHealth,
  fetchDividendReinvestmentRuns,
  fetchDividendReinvestmentSummaries,
  fetchDividendReinvestmentYearly
} from '../api/dividendReinvestment';
import type {
  DividendReinvestmentSummaryItem,
  DividendReinvestmentSummaryParams,
  DividendReinvestmentYearlyItem
} from '../types/domain';

interface FilterValues {
  run_id?: number;
  keyword?: string;
  data_quality?: string;
  min_annualized_return_pct?: number;
  min_dividend_year_count?: number;
  min_consecutive_dividend_years?: number;
  min_latest_dividend_yield_ttm?: number;
  max_latest_pe_ttm?: number;
}

const DEFAULT_PAGE_SIZE = 30;

/** 分红再投入筛选页面。创建日期：2026-05-30 author: sunshengxian */
function DividendReinvestmentPage() {
  const [form] = Form.useForm<FilterValues>();
  const [filters, setFilters] = useState<FilterValues>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [detailStock, setDetailStock] = useState<DividendReinvestmentSummaryItem | null>(null);
  const health = useQuery({
    queryKey: ['dividend-reinvestment-health'],
    queryFn: fetchDividendReinvestmentHealth
  });
  const runs = useQuery({
    queryKey: ['dividend-reinvestment-runs'],
    queryFn: () => fetchDividendReinvestmentRuns(50)
  });
  const queryParams: DividendReinvestmentSummaryParams = {
    ...filters,
    page,
    page_size: pageSize
  };
  const summaries = useQuery({
    queryKey: ['dividend-reinvestment-summaries', queryParams],
    queryFn: () => fetchDividendReinvestmentSummaries(queryParams)
  });
  const yearly = useQuery({
    queryKey: ['dividend-reinvestment-yearly', detailStock?.run_id, detailStock?.ts_code],
    enabled: Boolean(detailStock),
    queryFn: () =>
      fetchDividendReinvestmentYearly(detailStock!.ts_code, detailStock!.run_id)
  });

  const columns = useMemo<TableColumnsType<DividendReinvestmentSummaryItem>>(
    () => [
      {
        title: '代码',
        dataIndex: 'ts_code',
        width: 126,
        render: (value, record) => (
          <Button type="link" onClick={() => setDetailStock(record)}>
            {value}
          </Button>
        )
      },
      { title: '名称', dataIndex: 'name', width: 120 },
      { title: '行业', dataIndex: 'industry', width: 130, render: renderText },
      { title: '年化收益率', dataIndex: 'annualized_return_pct', width: 120, align: 'right', render: renderPct },
      { title: '累计收益率', dataIndex: 'total_return_pct', width: 110, align: 'right', render: renderPct },
      { title: '期末市值', dataIndex: 'final_market_value', width: 120, align: 'right', render: renderNumber },
      { title: '累计分红', dataIndex: 'total_cash_dividend', width: 120, align: 'right', render: renderNumber },
      { title: '分红年数', dataIndex: 'dividend_year_count', width: 96, align: 'right' },
      { title: '连续分红', dataIndex: 'consecutive_dividend_years', width: 96, align: 'right' },
      { title: '最新股息率', dataIndex: 'latest_dividend_yield_ttm', width: 110, align: 'right', render: renderPct },
      { title: 'PE_TTM', dataIndex: 'latest_pe_ttm', width: 100, align: 'right', render: renderNumber },
      { title: 'PB', dataIndex: 'latest_pb', width: 90, align: 'right', render: renderNumber },
      { title: '数据质量', dataIndex: 'data_quality', width: 110, render: renderQuality },
      { title: '问题', dataIndex: 'data_issue', width: 220, render: renderText }
    ],
    []
  );

  // 提交筛选条件时剔除空值，避免空字符串误伤后端的精确枚举和数值条件。
  const applyFilters = (values: FilterValues) => {
    setFilters(Object.fromEntries(Object.entries(values).filter(([, value]) => value !== undefined && value !== '')));
    setPage(1);
  };

  // 重置筛选条件后回到第一页，保证用户看到的是最新批次的完整榜单起点。
  const resetFilters = () => {
    form.resetFields();
    setFilters({});
    setPage(1);
  };

  // 同时刷新健康状态、批次和榜单，避免同步刚结束时页面各区域状态不一致。
  const refreshAll = () => {
    health.refetch();
    runs.refetch();
    summaries.refetch();
  };

  return (
    <main className="page">
      <PageHeader
        title="分红再投筛选"
        extra={<Button title="刷新" icon={<RotateCw size={16} />} onClick={refreshAll} loading={summaries.isFetching} />}
      />

      <section className="dividend-health-grid">
        <HealthCard title="A 股基础" value={health.data?.stock_count} detail="股票池" />
        <HealthCard title="日线行情" value={health.data?.daily_quote.row_count} detail={formatRange(health.data?.daily_quote.min_date, health.data?.daily_quote.max_date)} />
        <HealthCard title="分红数据" value={health.data?.dividend.row_count} detail={formatRange(health.data?.dividend.min_date, health.data?.dividend.max_date)} />
        <HealthCard title="最新指标" value={health.data?.daily_basic.row_count} detail={formatRange(health.data?.daily_basic.min_date, health.data?.daily_basic.max_date)} />
      </section>

      <section className="panel">
        <Form form={form} layout="vertical" onFinish={applyFilters}>
          <div className="dividend-filter-grid">
            <Form.Item label="回测批次" name="run_id">
              <Select
                allowClear
                placeholder="最新成功批次"
                loading={runs.isLoading}
                options={runs.data?.map((item) => ({
                  value: item.id,
                  label: `#${item.id} ${item.status} ${item.start_date}~${item.end_date}`
                }))}
              />
            </Form.Item>
            <Form.Item label="关键词" name="keyword">
              <Input allowClear placeholder="代码 / 名称 / 行业" />
            </Form.Item>
            <Form.Item label="数据质量" name="data_quality">
              <Select
                allowClear
                options={[
                  { value: 'COMPLETE', label: 'COMPLETE' },
                  { value: 'NO_DIVIDEND', label: 'NO_DIVIDEND' }
                ]}
              />
            </Form.Item>
            <Form.Item label="最低年化收益率" name="min_annualized_return_pct">
              <InputNumber className="full-width" precision={2} />
            </Form.Item>
            <Form.Item label="最低分红年数" name="min_dividend_year_count">
              <InputNumber min={0} className="full-width" />
            </Form.Item>
            <Form.Item label="最低连续分红" name="min_consecutive_dividend_years">
              <InputNumber min={0} className="full-width" />
            </Form.Item>
            <Form.Item label="最低股息率" name="min_latest_dividend_yield_ttm">
              <InputNumber min={0} precision={2} className="full-width" />
            </Form.Item>
            <Form.Item label="最高 PE_TTM" name="max_latest_pe_ttm">
              <InputNumber min={0} precision={2} className="full-width" />
            </Form.Item>
            <Form.Item label=" ">
              <Space>
                <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
                  筛选
                </Button>
                <Button icon={<X size={16} />} onClick={resetFilters}>
                  清空
                </Button>
              </Space>
            </Form.Item>
          </div>
        </Form>
      </section>

      <section className="panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">回测榜单</div>
            <Typography.Text type="secondary">
              当前批次：{summaries.data?.run_id ? `#${summaries.data.run_id}` : '暂无成功批次'}
            </Typography.Text>
          </div>
          <Tag color="blue">{summaries.data?.total ?? 0} 条</Tag>
        </div>
        <Table<DividendReinvestmentSummaryItem>
          rowKey={(record) => `${record.run_id}-${record.ts_code}`}
          loading={summaries.isLoading || summaries.isFetching}
          dataSource={summaries.data?.items || []}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 1680 }}
          pagination={{
            current: page,
            pageSize,
            total: summaries.data?.total || 0,
            showSizeChanger: true,
            pageSizeOptions: [20, 30, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            }
          }}
        />
      </section>

      <Drawer
        title={detailStock ? `${detailStock.name} 年度明细` : '年度明细'}
        open={Boolean(detailStock)}
        onClose={() => setDetailStock(null)}
        width={980}
      >
        <Table<DividendReinvestmentYearlyItem>
          rowKey={(record) => `${record.run_id}-${record.ts_code}-${record.year}`}
          loading={yearly.isLoading || yearly.isFetching}
          dataSource={yearly.data || []}
          columns={[
            { title: '年份', dataIndex: 'year', width: 80 },
            { title: '股价', dataIndex: 'year_end_price', width: 100, align: 'right', render: renderNumber },
            { title: '每股分红', dataIndex: 'cash_div_per_share', width: 110, align: 'right', render: renderNumber },
            { title: '分红金额', dataIndex: 'cash_div_amount', width: 110, align: 'right', render: renderNumber },
            { title: '再投均价', dataIndex: 'reinvest_price_avg', width: 110, align: 'right', render: renderNumber },
            { title: '再投股数', dataIndex: 'reinvested_shares', width: 110, align: 'right', render: renderNumber },
            { title: '持仓股数', dataIndex: 'holding_shares', width: 120, align: 'right', render: renderNumber },
            { title: '市值', dataIndex: 'market_value', width: 120, align: 'right', render: renderNumber },
            { title: '收益率', dataIndex: 'return_pct', width: 100, align: 'right', render: renderPct },
            { title: '年化', dataIndex: 'annualized_return_pct', width: 100, align: 'right', render: renderPct },
            { title: '备注', dataIndex: 'note', width: 180, render: renderText }
          ]}
          pagination={false}
          scroll={{ x: 1220 }}
        />
      </Drawer>
    </main>
  );
}

function HealthCard({ title, value, detail }: { title: string; value?: number; detail: string }) {
  return (
    <section className="panel dividend-health-card">
      <Typography.Text type="secondary">{title}</Typography.Text>
      <Typography.Title level={3}>{value ?? 0}</Typography.Title>
      <Typography.Text>{detail}</Typography.Text>
    </section>
  );
}

/** 展示原始数据日期覆盖范围，缺任一端时保留占位方便识别数据缺口。 */
function formatRange(minDate?: string | null, maxDate?: string | null) {
  if (!minDate && !maxDate) {
    return '暂无数据';
  }
  return `${minDate || '-'} ~ ${maxDate || '-'}`;
}

/** 统一处理空文本和长文本，避免股票名称、行业或问题说明撑破表格。 */
function renderText(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  return <OverflowCell value={String(value)} threshold={18} />;
}

/** 标识回测数据质量，后续如增加异常类型可集中扩展颜色规则。 */
function renderQuality(value: unknown) {
  const text = String(value || '-');
  return <Tag color={text === 'COMPLETE' ? 'blue' : text === 'NO_DIVIDEND' ? 'gold' : 'default'}>{text}</Tag>;
}

/** 数值列统一格式化为中文千分位，异常值保留原文便于排查源数据。 */
function renderNumber(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return <OverflowCell value={String(value)} threshold={12} />;
  }
  return numberValue.toLocaleString('zh-CN', { maximumFractionDigits: 3 });
}

/** 百分比列保留两位小数，和后端已经落库的百分比口径保持一致。 */
function renderPct(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return <OverflowCell value={String(value)} threshold={12} />;
  }
  return `${numberValue.toFixed(2)}%`;
}

export default DividendReinvestmentPage;
