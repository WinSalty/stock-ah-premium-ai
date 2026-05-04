import { Button, Space, Table, Tag, Tooltip } from 'antd';
import { Info, LineChart, Settings, Star, StarOff } from 'lucide-react';
import type { ColumnsType } from 'antd/es/table';
import type { PremiumItem } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

interface PremiumTableProps {
  data: PremiumItem[];
  loading?: boolean;
  pagination?: false | { current: number; pageSize: number; total: number; onChange: (page: number) => void };
  onTrend?: (item: PremiumItem) => void;
  onAddWatchlist?: (item: PremiumItem) => void;
  onEditWatchlist?: (item: PremiumItem) => void;
  onRemoveWatchlist?: (item: PremiumItem) => void;
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

function statusTag(value: string | null) {
  const labelMap: Record<string, string> = {
    REACHED: '达阈值',
    NEAR: '接近',
    WATCH: '观察',
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
  if (!value) {
    return <Tag color="default">未自选</Tag>;
  }
  return <Tag color={colorMap[value] || 'default'}>{labelMap[value] || value}</Tag>;
}

function channelsTag(record: PremiumItem) {
  if (!record.is_hk_connect) {
    return <Tag color="default">非港股通</Tag>;
  }
  return (
    <Tooltip title={record.connect_channels || '港股通'}>
      <Tag color="green">{record.connect_channels || '港股通'}</Tag>
    </Tooltip>
  );
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
function PremiumTable({
  data,
  loading,
  pagination,
  onTrend,
  onAddWatchlist,
  onEditWatchlist,
  onRemoveWatchlist
}: PremiumTableProps) {
  const columns: ColumnsType<PremiumItem> = [
    {
      title: '关注',
      width: 104,
      fixed: 'left',
      render: (_, record) => (
        <div className="premium-watch-cell">
          {record.is_watchlist ? <Tag color="purple">自选</Tag> : <Tag color="default">未加</Tag>}
          {statusTag(record.opportunity_status)}
        </div>
      )
    },
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
      title: '港股通',
      width: 118,
      render: (_, record) => channelsTag(record)
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
      title: '60日分位',
      dataIndex: 'premium_percentile_60',
      align: 'right',
      width: 108,
      render: (value) => (value === null ? '-' : `${formatNumber(value)}%`)
    },
    {
      title: '偏离60均',
      dataIndex: 'premium_deviation_from_60d_avg',
      align: 'right',
      width: 108,
      render: (value) => formatPercentTag(value)
    },
    {
      title: (
        <FormulaTitle
          label="距阈值"
          formula="距阈值 = 目标阈值 - 当前关注方向溢价；小于等于 0 表示已达阈值"
        />
      ),
      dataIndex: 'distance_to_target_pct',
      align: 'right',
      width: 100,
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
      width: 132,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Button
            aria-label="趋势"
            title="趋势"
            type="text"
            icon={<LineChart size={16} />}
            onClick={() => onTrend?.(record)}
          />
          {record.is_watchlist ? (
            <>
              {onEditWatchlist ? (
                <Button
                  aria-label="编辑自选"
                  title="编辑自选"
                  type="text"
                  icon={<Settings size={16} />}
                  onClick={() => onEditWatchlist(record)}
                />
              ) : null}
              {onRemoveWatchlist ? (
                <Button
                  aria-label="取消自选"
                  title="取消自选"
                  type="text"
                  danger
                  icon={<StarOff size={16} />}
                  onClick={() => onRemoveWatchlist(record)}
                />
              ) : null}
            </>
          ) : onAddWatchlist ? (
            <Button
              aria-label="加入自选"
              title="加入自选"
              type="text"
              icon={<Star size={16} />}
              onClick={() => onAddWatchlist(record)}
            />
          ) : null}
        </Space>
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
      scroll={{ x: 1724 }}
      size="middle"
    />
  );
}

export default PremiumTable;
