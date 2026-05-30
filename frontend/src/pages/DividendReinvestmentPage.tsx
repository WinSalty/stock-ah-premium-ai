import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography
} from 'antd';
import type { TableColumnsType, TableProps } from 'antd';
import ReactECharts from 'echarts-for-react';
import { Eye, Info, RotateCw, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import {
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
  const [formulaOpen, setFormulaOpen] = useState(false);
  const [sortBy, setSortBy] = useState<
    'annualized_return_pct' | 'total_return_pct' | 'total_cash_dividend' | 'latest_dividend_yield_ttm'
  >('total_cash_dividend');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const runs = useQuery({
    queryKey: ['dividend-reinvestment-runs'],
    queryFn: () => fetchDividendReinvestmentRuns(50)
  });
  const queryParams: DividendReinvestmentSummaryParams = {
    ...filters,
    sort_by: sortBy,
    sort_order: sortOrder,
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
  const yearlyChartOption = useMemo(() => buildYearlyChartOption(yearly.data || []), [yearly.data]);

  const columns = useMemo<TableColumnsType<DividendReinvestmentSummaryItem>>(
    () => [
      {
        title: '代码',
        dataIndex: 'ts_code',
        width: 126,
        render: renderText
      },
      { title: '名称', dataIndex: 'name', width: 120 },
      { title: '行业', dataIndex: 'industry', width: 130, render: renderText },
      {
        title: '年化收益率',
        dataIndex: 'annualized_return_pct',
        width: 120,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'annualized_return_pct' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      {
        title: '累计收益率',
        dataIndex: 'total_return_pct',
        width: 110,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'total_return_pct' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      { title: '期末市值', dataIndex: 'final_market_value', width: 120, align: 'right', render: renderNumber },
      {
        title: '累计分红',
        dataIndex: 'total_cash_dividend',
        width: 120,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'total_cash_dividend' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderNumber
      },
      { title: '分红年数', dataIndex: 'dividend_year_count', width: 96, align: 'right' },
      { title: '连续分红', dataIndex: 'consecutive_dividend_years', width: 96, align: 'right' },
      {
        title: '最新股息率',
        dataIndex: 'latest_dividend_yield_ttm',
        width: 110,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'latest_dividend_yield_ttm' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      { title: 'PE_TTM', dataIndex: 'latest_pe_ttm', width: 100, align: 'right', render: renderNumber },
      { title: 'PB', dataIndex: 'latest_pb', width: 90, align: 'right', render: renderNumber },
      { title: '数据质量', dataIndex: 'data_quality', width: 110, render: renderQuality },
      { title: '问题', dataIndex: 'data_issue', width: 220, render: renderText },
      {
        title: '明细',
        key: 'detail',
        fixed: 'right',
        width: 112,
        render: (_, record) => (
          <Button type="primary" size="small" icon={<Eye size={14} />} onClick={() => setDetailStock(record)}>
            年度
          </Button>
        )
      }
    ],
    [sortBy, sortOrder]
  );

  // 提交筛选条件时剔除空值，避免空字符串误伤后端的精确枚举和数值条件。
  const applyFilters = (values: FilterValues) => {
    setFilters(normalizeFilterValues(values));
    setPage(1);
  };

  // 重置筛选条件后回到第一页，保证用户看到的是最新批次的完整榜单起点。
  const resetFilters = () => {
    form.resetFields();
    setFilters({});
    setPage(1);
  };

  // 同时刷新批次和榜单，避免同步刚结束时下拉批次与当前列表状态不一致。
  const refreshAll = () => {
    runs.refetch();
    summaries.refetch();
  };

  // 表格分页或排序前读取当前筛选表单，避免用户改了筛选条件后直接点排序时仍沿用旧请求。
  const handleTableChange: TableProps<DividendReinvestmentSummaryItem>['onChange'] = (
    pagination,
    _filters,
    sorter,
    extra
  ) => {
    const currentFilters = normalizeFilterValues(form.getFieldsValue());
    setFilters(currentFilters);
    if (extra.action === 'paginate') {
      setPage(pagination.current || 1);
      setPageSize(pagination.pageSize || DEFAULT_PAGE_SIZE);
      return;
    }
    const activeSorter = Array.isArray(sorter) ? sorter[0] : sorter;
    if (
      activeSorter?.field === 'total_return_pct' ||
      activeSorter?.field === 'total_cash_dividend' ||
      activeSorter?.field === 'latest_dividend_yield_ttm'
    ) {
      setSortBy(activeSorter.field);
      setSortOrder(activeSorter.order === 'ascend' ? 'asc' : 'desc');
    } else {
      setSortBy('total_cash_dividend');
      setSortOrder(activeSorter?.order === 'ascend' ? 'asc' : 'desc');
    }
    setPage(1);
  };

  return (
    <main className="page">
      <PageHeader
        title="分红再投筛选"
        extra={
          <Button title="刷新" icon={<RotateCw size={16} />} onClick={refreshAll} loading={summaries.isFetching} />
        }
      />

      <section className="panel">
        <Form form={form} layout="vertical" onFinish={applyFilters}>
          <div className="dividend-filter-grid">
            <Form.Item label="回测批次" name="run_id">
              <Select
                allowClear
                placeholder="最新成功批次"
                loading={runs.isLoading}
                options={runs.data?.filter((item) => item.status === 'SUCCESS').map((item) => ({
                  value: item.id,
                  label: `#${item.id} ${item.start_date}~${item.end_date}`
                }))}
              />
            </Form.Item>
            <Form.Item label="关键词" name="keyword">
              <Input allowClear placeholder="代码 / 名称 / 行业" />
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

      <section className="panel dividend-formula-banner">
        <div>
          <div className="panel-title">测算口径</div>
          <Typography.Text type="secondary">
            默认 2016 年起、初始投入 100000 元、现金分红按除权除息日收盘价再投入，榜单默认按累计分红降序。
          </Typography.Text>
        </div>
        <Button type="primary" icon={<Info size={16} />} onClick={() => setFormulaOpen(true)}>
          查看公式
        </Button>
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
          scroll={{ x: 1760 }}
          onChange={handleTableChange}
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
        <ReactECharts option={yearlyChartOption} style={{ height: 300, marginBottom: 16 }} showLoading={yearly.isLoading} />
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

      <Modal
        title="测算口径与公式"
        open={formulaOpen}
        onCancel={() => setFormulaOpen(false)}
        footer={null}
        width={760}
      >
        <div className="formula-dialog">
          <Typography.Paragraph>
            默认起点为 2016-01-01，初始投入金额 100000 元；起始买入价取起点之后第一个可用交易日收盘价，持股允许小数股。
          </Typography.Paragraph>
          <Typography.Paragraph>
            现金分红默认使用 Tushare `cash_div_tax`，再投入价格取除权除息日收盘价；若当天无行情，取之后 10 个交易日内第一个可用收盘价。
          </Typography.Paragraph>
          <Typography.Paragraph>
            期末市值 = 当前持股数 * 年末或最新收盘价；累计收益率 = (期末市值 - 初始投入金额) / 初始投入金额 * 100%。
          </Typography.Paragraph>
          <Typography.Paragraph>
            年化收益率 = (期末市值 / 初始投入金额) ^ (1 / 持有年数) - 1；榜单默认按累计分红降序排列。
          </Typography.Paragraph>
        </div>
      </Modal>
    </main>
  );
}

/** 统一清洗筛选表单，保证筛选、分页和排序触发的接口参数完全一致。 */
function normalizeFilterValues(values: FilterValues): FilterValues {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== undefined && value !== '')
  );
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
  return numberValue.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

/** 构建年度明细图表，用市值和收益率同时观察长期再投入表现。 */
function buildYearlyChartOption(rows: DividendReinvestmentYearlyItem[]) {
  const years = rows.map((item) => String(item.year));
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number | string) => formatChartTooltipValue(value)
    },
    legend: { top: 0, data: ['市值', '累计收益率', '年化收益率'] },
    grid: { left: 76, right: 72, top: 48, bottom: 42 },
    xAxis: { type: 'category', data: years },
    yAxis: [
      {
        type: 'value',
        name: '市值',
        axisLabel: { formatter: (value: number) => formatChartAxisValue(value) }
      },
      {
        type: 'value',
        name: '收益率',
        axisLabel: { formatter: (value: number) => `${value.toFixed(0)}%` }
      }
    ],
    series: [
      {
        name: '市值',
        type: 'bar',
        yAxisIndex: 0,
        data: rows.map((item) => toChartNumber(item.market_value))
      },
      {
        name: '累计收益率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: rows.map((item) => toChartNumber(item.return_pct))
      },
      {
        name: '年化收益率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: rows.map((item) => toChartNumber(item.annualized_return_pct))
      }
    ]
  };
}

/** 大额市值轴按万/亿缩写，避免 y 轴标签被裁切。 */
function formatChartAxisValue(value: number) {
  if (Math.abs(value) >= 100000000) {
    return `${(value / 100000000).toFixed(1)}亿`;
  }
  if (Math.abs(value) >= 10000) {
    return `${(value / 10000).toFixed(1)}万`;
  }
  return value.toFixed(0);
}

/** tooltip 保留完整两位小数，让轴标签缩写不影响精确读数。 */
function formatChartTooltipValue(value: number | string) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue)) {
    return String(value);
  }
  return numberValue.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 图表只接受有限数值，空值保留 null 让 ECharts 自动断点。 */
function toChartNumber(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? Number(numberValue.toFixed(2)) : null;
}

export default DividendReinvestmentPage;
