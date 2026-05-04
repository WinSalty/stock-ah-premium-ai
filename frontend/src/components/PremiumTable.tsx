import { Button, Table, Tag, Tooltip } from 'antd';
import { Info, LineChart } from 'lucide-react';
import type { ColumnsType } from 'antd/es/table';
import type { PremiumItem } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

interface PremiumTableProps {
  data: PremiumItem[];
  loading?: boolean;
  pagination?: false | { current: number; pageSize: number; total: number; onChange: (page: number) => void };
  onTrend?: (item: PremiumItem) => void;
}

function formatNumber(value: string | null, digits = 2) {
  if (value === null) {
    return '-';
  }
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : value;
}

function formatPercentTag(value: string | null) {
  if (value === null) {
    return '-';
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value;
  }
  return <Tag color={number >= 0 ? 'red' : 'green'}>{number.toFixed(2)}%</Tag>;
}

function FormulaTitle({ label, formula }: { label: string; formula: string }) {
  return (
    <span className="formula-title">
      {label}
      <Tooltip title={formula}>
        <Info size={13} className="formula-icon" />
      </Tooltip>
    </span>
  );
}

/**
 * 股票名称和代码单元格。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function StockCell({ name, code }: { name: string | null; code: string }) {
  const displayName = name || '-';
  return (
    <div className="stock-cell">
      <Tooltip title={displayName}>
        <strong className="stock-name-text">{displayName}</strong>
      </Tooltip>
      <span>{code}</span>
    </div>
  );
}

/**
 * AH 溢价结果表格。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function PremiumTable({ data, loading, pagination, onTrend }: PremiumTableProps) {
  const columns: ColumnsType<PremiumItem> = [
    {
      title: '日期',
      dataIndex: 'trade_date',
      width: 128,
      fixed: 'left'
    },
    {
      title: 'A 股',
      width: 168,
      render: (_, record) => <StockCell name={record.a_name} code={record.a_ts_code} />
    },
    {
      title: 'H 股',
      width: 168,
      render: (_, record) => <StockCell name={record.hk_name} code={record.hk_ts_code} />
    },
    {
      title: 'A 收盘',
      dataIndex: 'a_close',
      align: 'right',
      width: 100,
      render: (value) => formatNumber(value)
    },
    {
      title: 'A 涨跌幅',
      dataIndex: 'a_pct_chg',
      align: 'right',
      width: 104,
      render: (value) => (value === null ? '-' : `${formatNumber(value)}%`)
    },
    {
      title: 'H 收盘',
      dataIndex: 'hk_close',
      align: 'right',
      width: 100,
      render: (value) => formatNumber(value)
    },
    {
      title: 'H 涨跌幅',
      dataIndex: 'hk_pct_chg',
      align: 'right',
      width: 104,
      render: (value) => (value === null ? '-' : `${formatNumber(value)}%`)
    },
    {
      title: (
        <FormulaTitle
          label="A/H 比价"
          formula="A/H 比价 = A 股价格(人民币) ÷ (H 股价格(港币) × HKD/CNY)"
        />
      ),
      dataIndex: 'ah_ratio',
      align: 'right',
      width: 118,
      render: (value) => formatNumber(value, 4)
    },
    {
      title: (
        <FormulaTitle label="A/H 溢价" formula="A/H 溢价 = (A/H 比价 - 1) × 100%" />
      ),
      dataIndex: 'ah_premium_pct',
      align: 'right',
      width: 118,
      render: (value) => formatPercentTag(value)
    },
    {
      title: <FormulaTitle label="H/A 比价" formula="H/A 比价 = 1 ÷ A/H 比价" />,
      dataIndex: 'ha_ratio',
      align: 'right',
      width: 118,
      render: (value) => formatNumber(value, 4)
    },
    {
      title: (
        <FormulaTitle label="H/A 溢价" formula="H/A 溢价 = (H/A 比价 - 1) × 100%" />
      ),
      dataIndex: 'ha_premium_pct',
      align: 'right',
      width: 118,
      render: (value) => formatPercentTag(value)
    },
    {
      title: '来源',
      width: 128,
      render: (_, record) => (
        <Tooltip
          title={
            record.source_updated_at
              ? `更新时间：${formatEast8DateTime(record.source_updated_at)}`
              : record.data_source
          }
        >
          <Tag color={record.is_realtime ? 'green' : 'blue'}>
            {record.is_realtime ? '实时' : '官方'}
          </Tag>
        </Tooltip>
      )
    },
    {
      title: '',
      width: 56,
      fixed: 'right',
      render: (_, record) => (
        <Button
          aria-label="趋势"
          title="趋势"
          type="text"
          icon={<LineChart size={16} />}
          onClick={() => onTrend?.(record)}
        />
      )
    }
  ];

  return (
    <Table
      rowKey={(record) => `${record.trade_date}-${record.a_ts_code}-${record.hk_ts_code}`}
      columns={columns}
      dataSource={data}
      loading={loading}
      pagination={pagination}
      scroll={{ x: 1280 }}
      size="middle"
    />
  );
}

export default PremiumTable;
