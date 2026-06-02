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
  Tooltip,
  Typography,
  message
} from 'antd';
import type { TableColumnsType, TableProps } from 'antd';
import ReactECharts from 'echarts-for-react';
import { saveAs } from 'file-saver';
import { CircleHelp, Download, Eye, Info, RotateCw, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import OverflowCell from '../components/OverflowCell';
import {
  exportDividendReinvestmentSummaries,
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
  min_ten_year_avg_annualized_return_pct?: number;
  min_dividend_year_count?: number;
  min_consecutive_dividend_years?: number;
  min_latest_dividend_yield_ttm?: number;
  max_latest_pe?: number;
  max_latest_pe_ttm?: number;
  min_latest_roe?: number;
}

const DEFAULT_PAGE_SIZE = 30;
type DividendSortField =
  | 'annualized_return_pct'
  | 'ten_year_avg_annualized_return_pct'
  | 'total_return_pct'
  | 'total_cash_dividend'
  | 'latest_dividend_yield_ttm'
  | 'latest_pe'
  | 'latest_pe_ttm'
  | 'latest_roe';
const DIVIDEND_SORT_FIELDS: DividendSortField[] = [
  'annualized_return_pct',
  'ten_year_avg_annualized_return_pct',
  'total_return_pct',
  'total_cash_dividend',
  'latest_dividend_yield_ttm',
  'latest_pe',
  'latest_pe_ttm',
  'latest_roe'
];

const DIVIDEND_HEADER_HELP: Record<string, string> = {
  代码: '股票代码，带交易所后缀，例如 600000.SH。',
  名称: 'A 股上市公司简称。',
  行业: '上市公司所属行业，用于快速识别业务属性。',
  年化收益率: '从回测起点买入并把现金分红再投入后，按持有天数折算的年化收益率。',
  十年均年化: '逐年计算最近十个自然年度的年化收益率后取平均；历史不足十年时按可用年度计算。',
  PE: '最新市盈率，用于观察当前估值水平。',
  PE_TTM: '滚动市盈率，用最近四个季度盈利计算当前估值。',
  ROE: '最新报告期净资产收益率，用于观察股东权益的盈利效率。',
  累计收益率: '期末市值相对初始投入金额的总收益率，包含现金分红再投入后的持仓市值变化。',
  期末市值: '回测期末持仓股数乘以期末或最新收盘价得到的市值。',
  累计分红: '回测期内累计收到并用于再投入的现金分红金额。',
  分红年数: '回测期内存在有效实施分红的自然年度数量。',
  连续分红: '截至回测末期向前连续存在有效分红的最长年度数量。',
  最新股息率: '最近滚动口径股息率，用于观察分红相对股价的回报水平。',
  PB: '最新市净率，用于观察股价相对每股净资产的估值水平。',
  数据质量: '标记该股票在回测期内是否有有效实施分红；无分红会标为 NO_DIVIDEND。',
  问题: '记录影响回测可解释性的原因，例如回测期内无有效实施分红。',
  明细: '打开该股票的年度分红再投过程、持仓市值和年度收益明细。',
  年份: '年度明细所属自然年。',
  股价: '该年度末或最新可用交易日的收盘价。',
  每股分红: '该年度有效现金分红折算的每股分红金额。',
  分红金额: '按当年持仓股数计算得到的现金分红总额。',
  再投均价: '现金分红再投入时使用的平均买入价格。',
  再投股数: '当年现金分红按再投价格买入的新增股数。',
  持仓股数: '年度结束后的累计持仓股数，允许小数股。',
  市值: '年度结束后的持仓股数乘以年度末价格。',
  收益率: '截至该年度末，市值相对初始投入金额的累计收益率。',
  年化: '截至该年度末，按持有时间折算的年化收益率。',
  备注: '记录该年度分红、再投或行情匹配过程中的补充说明。'
};

// 表头说明和排序图标会共享紧凑空间；问号点击不触发表格排序，避免用户查看口径时误改榜单顺序。
const renderHeaderTitle = (title: string) => {
  const help = DIVIDEND_HEADER_HELP[title];
  return (
    <span className="help-title table-header-nowrap">
      <span className="help-title-text">{title}</span>
      {help ? (
        <Tooltip title={help}>
          <span className="help-title-icon-hitbox" onClick={(event) => event.stopPropagation()}>
            <CircleHelp size={13} className="help-title-icon" />
          </span>
        </Tooltip>
      ) : null}
    </span>
  );
};

/** 分红再投入筛选页面。创建日期：2026-05-30 author: sunshengxian */
function DividendReinvestmentPage() {
  const [form] = Form.useForm<FilterValues>();
  const [filters, setFilters] = useState<FilterValues>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [detailStock, setDetailStock] = useState<DividendReinvestmentSummaryItem | null>(null);
  const [formulaOpen, setFormulaOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [sortBy, setSortBy] = useState<DividendSortField>('total_cash_dividend');
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
        title: renderHeaderTitle('代码'),
        dataIndex: 'ts_code',
        width: 126,
        render: renderText
      },
      { title: renderHeaderTitle('名称'), dataIndex: 'name', width: 120 },
      { title: renderHeaderTitle('行业'), dataIndex: 'industry', width: 130, render: renderText },
      {
        title: renderHeaderTitle('年化收益率'),
        key: 'annualized_return_pct',
        dataIndex: 'annualized_return_pct',
        width: 120,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'annualized_return_pct' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      {
        title: renderHeaderTitle('十年均年化'),
        key: 'ten_year_avg_annualized_return_pct',
        dataIndex: 'ten_year_avg_annualized_return_pct',
        width: 126,
        align: 'right',
        sorter: true,
        sortOrder:
          sortBy === 'ten_year_avg_annualized_return_pct'
            ? sortOrder === 'asc'
              ? 'ascend'
              : 'descend'
            : null,
        render: renderPct
      },
      {
        title: renderHeaderTitle('PE'),
        key: 'latest_pe',
        dataIndex: 'latest_pe',
        width: 90,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'latest_pe' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderNumber
      },
      {
        title: renderHeaderTitle('PE_TTM'),
        key: 'latest_pe_ttm',
        dataIndex: 'latest_pe_ttm',
        width: 112,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'latest_pe_ttm' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderNumber
      },
      {
        title: renderHeaderTitle('ROE'),
        key: 'latest_roe',
        dataIndex: 'latest_roe',
        width: 92,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'latest_roe' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      {
        title: renderHeaderTitle('累计收益率'),
        key: 'total_return_pct',
        dataIndex: 'total_return_pct',
        width: 124,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'total_return_pct' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      { title: renderHeaderTitle('期末市值'), dataIndex: 'final_market_value', width: 120, align: 'right', render: renderNumber },
      {
        title: renderHeaderTitle('累计分红'),
        key: 'total_cash_dividend',
        dataIndex: 'total_cash_dividend',
        width: 120,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'total_cash_dividend' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderNumber
      },
      { title: renderHeaderTitle('分红年数'), dataIndex: 'dividend_year_count', width: 96, align: 'right' },
      { title: renderHeaderTitle('连续分红'), dataIndex: 'consecutive_dividend_years', width: 96, align: 'right' },
      {
        title: renderHeaderTitle('最新股息率'),
        key: 'latest_dividend_yield_ttm',
        dataIndex: 'latest_dividend_yield_ttm',
        width: 124,
        align: 'right',
        sorter: true,
        sortOrder: sortBy === 'latest_dividend_yield_ttm' ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null,
        render: renderPct
      },
      { title: renderHeaderTitle('PB'), dataIndex: 'latest_pb', width: 90, align: 'right', render: renderNumber },
      { title: renderHeaderTitle('数据质量'), dataIndex: 'data_quality', width: 110, render: renderQuality },
      { title: renderHeaderTitle('问题'), dataIndex: 'data_issue', width: 220, render: renderText },
      {
        title: renderHeaderTitle('明细'),
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

  // 导出前读取表单当前值，保证用户刚改筛选条件后直接点导出也能使用最新条件。
  const exportCurrentFilters = async () => {
    const currentFilters = normalizeFilterValues(form.getFieldsValue());
    setFilters(currentFilters);
    setPage(1);
    setExporting(true);
    try {
      const result = await exportDividendReinvestmentSummaries({
        ...currentFilters,
        sort_by: sortBy,
        sort_order: sortOrder,
        page: 1,
        page_size: pageSize
      });
      saveAs(result.blob, result.filename);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导出失败');
    } finally {
      setExporting(false);
    }
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
    const nextSortBy = normalizeSortField(activeSorter?.field || activeSorter?.columnKey);
    if (!activeSorter?.order || !nextSortBy) {
      setSortBy('total_cash_dividend');
      setSortOrder('desc');
    } else {
      setSortBy(nextSortBy);
      setSortOrder(activeSorter.order === 'ascend' ? 'asc' : 'desc');
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
            <Form.Item label="最低十年均年化" name="min_ten_year_avg_annualized_return_pct">
              <InputNumber className="full-width" precision={2} />
            </Form.Item>
            <Form.Item label="最高 PE" name="max_latest_pe">
              <InputNumber min={0} precision={2} className="full-width" />
            </Form.Item>
            <Form.Item label="最高 PE_TTM" name="max_latest_pe_ttm">
              <InputNumber min={0} precision={2} className="full-width" />
            </Form.Item>
            <Form.Item label="最低 ROE" name="min_latest_roe">
              <InputNumber precision={2} className="full-width" />
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
            <Form.Item label=" ">
              <Space>
                <Button type="primary" htmlType="submit" icon={<Search size={16} />}>
                  筛选
                </Button>
                <Button icon={<X size={16} />} onClick={resetFilters}>
                  清空
                </Button>
                <Button
                  title="导出 Excel"
                  icon={<Download size={16} />}
                  onClick={() => void exportCurrentFilters()}
                  loading={exporting}
                >
                  导出 Excel
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
          className="dividend-summary-table"
          rowKey={(record) => `${record.run_id}-${record.ts_code}`}
          loading={summaries.isLoading || summaries.isFetching}
          dataSource={summaries.data?.items || []}
          columns={columns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: 2082 }}
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
            { title: renderHeaderTitle('年份'), dataIndex: 'year', width: 80 },
            { title: renderHeaderTitle('股价'), dataIndex: 'year_end_price', width: 100, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('每股分红'), dataIndex: 'cash_div_per_share', width: 110, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('分红金额'), dataIndex: 'cash_div_amount', width: 110, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('再投均价'), dataIndex: 'reinvest_price_avg', width: 110, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('再投股数'), dataIndex: 'reinvested_shares', width: 110, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('持仓股数'), dataIndex: 'holding_shares', width: 120, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('市值'), dataIndex: 'market_value', width: 120, align: 'right', render: renderNumber },
            { title: renderHeaderTitle('收益率'), dataIndex: 'return_pct', width: 100, align: 'right', render: renderPct },
            { title: renderHeaderTitle('年化'), dataIndex: 'annualized_return_pct', width: 100, align: 'right', render: renderPct },
            { title: renderHeaderTitle('备注'), dataIndex: 'note', width: 180, render: renderText }
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
            现金分红默认使用税前现金分红口径，再投入价格取除权除息日收盘价；若当天无行情，取之后 10 个交易日内第一个可用收盘价。
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

/** 统一识别 Ant Design Table 的排序字段，避免自定义表头或 columnKey 差异导致切换排序失效。 */
function normalizeSortField(value: unknown): DividendSortField | null {
  const field = Array.isArray(value) ? value.join('.') : String(value || '');
  return DIVIDEND_SORT_FIELDS.includes(field as DividendSortField) ? (field as DividendSortField) : null;
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
