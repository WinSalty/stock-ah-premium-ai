import { Button, Table, Tag } from 'antd';
import { LineChart } from 'lucide-react';
import type { ColumnsType } from 'antd/es/table';
import type { PremiumItem } from '../types/domain';

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
      width: 112,
      fixed: 'left'
    },
    {
      title: 'A 股',
      width: 168,
      render: (_, record) => (
        <div className="stock-cell">
          <strong>{record.a_name || '-'}</strong>
          <span>{record.a_ts_code}</span>
        </div>
      )
    },
    {
      title: 'H 股',
      width: 168,
      render: (_, record) => (
        <div className="stock-cell">
          <strong>{record.hk_name || '-'}</strong>
          <span>{record.hk_ts_code}</span>
        </div>
      )
    },
    {
      title: 'A 收盘',
      dataIndex: 'a_close_cny',
      align: 'right',
      width: 100,
      render: (value) => formatNumber(value)
    },
    {
      title: 'H 收盘',
      dataIndex: 'h_close_hkd',
      align: 'right',
      width: 100,
      render: (value) => formatNumber(value)
    },
    {
      title: 'HKD/CNY',
      dataIndex: 'hkd_cny',
      align: 'right',
      width: 108,
      render: (value) => formatNumber(value, 4)
    },
    {
      title: '溢价率',
      dataIndex: 'ah_premium_pct',
      align: 'right',
      width: 110,
      render: (value) => {
        const number = Number(value);
        const color = number >= 0 ? 'red' : 'green';
        return value === null ? '-' : <Tag color={color}>{number.toFixed(2)}%</Tag>;
      }
    },
    {
      title: '官方比价',
      dataIndex: 'official_ah_ratio',
      align: 'right',
      width: 112,
      render: (value) => formatNumber(value, 2)
    },
    {
      title: '官方溢价',
      dataIndex: 'official_ah_premium_pct',
      align: 'right',
      width: 112,
      render: (value) => {
        const number = Number(value);
        const color = number >= 0 ? 'red' : 'green';
        return value === null ? '-' : <Tag color={color}>{number.toFixed(2)}%</Tag>;
      }
    },
    {
      title: '差异',
      dataIndex: 'diff_from_official_pct',
      align: 'right',
      width: 100,
      render: (value) => formatNumber(value)
    },
    {
      title: '通道',
      dataIndex: 'connect_channels',
      width: 130,
      render: (value) => value || '-'
    },
    {
      title: '状态',
      dataIndex: 'calc_status',
      width: 120,
      render: (value) => <Tag color={value === 'OK' ? 'blue' : 'orange'}>{value}</Tag>
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
      scroll={{ x: 1470 }}
      size="middle"
    />
  );
}

export default PremiumTable;
