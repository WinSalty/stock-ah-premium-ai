import { Button, DatePicker, Empty, Input, Select, Space, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { RotateCw, Search, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import PageHeader from '../components/PageHeader';
import { fetchQueryDatasets, fetchQueryRows } from '../api/query';
import type { QueryCellValue, QueryColumn } from '../types/domain';

type QueryRow = Record<string, QueryCellValue> & { __rowKey: string };
type DateRange = [dayjs.Dayjs, dayjs.Dayjs] | null;

/**
 * 同步数据查询页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function DataQueryPage() {
  const [dataset, setDataset] = useState<string>();
  const [draftKeyword, setDraftKeyword] = useState('');
  const [keyword, setKeyword] = useState('');
  const [draftRange, setDraftRange] = useState<DateRange>(null);
  const [dateRange, setDateRange] = useState<DateRange>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);

  const datasets = useQuery({ queryKey: ['query-datasets'], queryFn: fetchQueryDatasets });
  const selectedDataset = datasets.data?.find((item) => item.name === dataset);
  const rows = useQuery({
    queryKey: [
      'query-rows',
      dataset,
      keyword,
      dateRange?.[0]?.format('YYYY-MM-DD'),
      dateRange?.[1]?.format('YYYY-MM-DD'),
      page,
      pageSize
    ],
    enabled: Boolean(dataset),
    queryFn: () =>
      fetchQueryRows({
        dataset: dataset!,
        keyword: keyword || undefined,
        start_date: dateRange?.[0]?.format('YYYY-MM-DD'),
        end_date: dateRange?.[1]?.format('YYYY-MM-DD'),
        page,
        page_size: pageSize
      })
  });

  useEffect(() => {
    if (!dataset && datasets.data?.length) {
      setDataset(datasets.data[0].name);
    }
  }, [dataset, datasets.data]);

  const tableColumns = useMemo<TableColumnsType<QueryRow>>(() => {
    const sourceColumns = rows.data?.columns || selectedDataset?.columns || [];
    return sourceColumns.map((column) => ({
      title: column.label,
      dataIndex: column.key,
      key: column.key,
      width: column.width || 120,
      ellipsis: true,
      render: (value: QueryCellValue) => renderCell(value, column)
    }));
  }, [rows.data?.columns, selectedDataset?.columns]);

  const dataSource = useMemo<QueryRow[]>(
    () =>
      (rows.data?.rows || []).map((item, index) => ({
        ...item,
        __rowKey: `${rows.data?.dataset || dataset}-${page}-${index}-${item.id || ''}`
      })),
    [dataset, page, rows.data?.dataset, rows.data?.rows]
  );

  const applyFilters = () => {
    setKeyword(draftKeyword.trim());
    setDateRange(draftRange);
    setPage(1);
  };

  const resetFilters = () => {
    setDraftKeyword('');
    setKeyword('');
    setDraftRange(null);
    setDateRange(null);
    setPage(1);
  };

  return (
    <main className="page">
      <PageHeader
        title="数据查询"
        extra={
          <Button
            title="刷新"
            icon={<RotateCw size={16} />}
            onClick={() => rows.refetch()}
            loading={rows.isFetching}
          />
        }
      />

      <section className="panel">
        <div className="query-filter-grid">
          <div>
            <Typography.Text className="field-label">数据集</Typography.Text>
            <Select
              className="full-width"
              value={dataset}
              loading={datasets.isLoading}
              options={datasets.data?.map((item) => ({ value: item.name, label: item.label }))}
              onChange={(value) => {
                setDataset(value);
                resetFilters();
              }}
            />
          </div>
          <div>
            <Typography.Text className="field-label">关键词</Typography.Text>
            <Input
              allowClear
              value={draftKeyword}
              placeholder="代码 / 名称 / 状态"
              onChange={(event) => setDraftKeyword(event.target.value)}
              onPressEnter={applyFilters}
            />
          </div>
          <div>
            <Typography.Text className="field-label">日期范围</Typography.Text>
            <DatePicker.RangePicker
              className="full-width"
              value={draftRange}
              disabled={!selectedDataset?.date_field}
              onChange={(value) => setDraftRange(value as DateRange)}
            />
          </div>
          <Space className="query-actions">
            <Button type="primary" icon={<Search size={16} />} onClick={applyFilters}>
              查询
            </Button>
            <Button icon={<X size={16} />} onClick={resetFilters}>
              清空
            </Button>
          </Space>
        </div>
      </section>

      <section className="panel">
        <div className="query-result-head">
          <div>
            <div className="panel-title">{selectedDataset?.label || '数据'}</div>
            <Typography.Text type="secondary">{selectedDataset?.description || ''}</Typography.Text>
          </div>
          <Tag color="blue">{rows.data?.total ?? 0} 条</Tag>
        </div>
        <Table<QueryRow>
          rowKey="__rowKey"
          loading={rows.isLoading || rows.isFetching}
          dataSource={dataSource}
          columns={tableColumns}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          scroll={{ x: Math.max(960, tableColumns.reduce((sum, item) => sum + Number(item.width || 120), 0)) }}
          pagination={{
            current: page,
            pageSize,
            total: rows.data?.total || 0,
            showSizeChanger: true,
            pageSizeOptions: [20, 30, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            }
          }}
        />
      </section>
    </main>
  );
}

function renderCell(value: QueryCellValue, column: QueryColumn) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  if (typeof value === 'boolean') {
    return <Tag color={value ? 'blue' : 'default'}>{value ? '是' : '否'}</Tag>;
  }
  if (column.key === 'status' || column.key === 'calc_status') {
    const status = String(value);
    const color = status === 'SUCCESS' || status === 'OK' ? 'blue' : status === 'FAILED' ? 'red' : 'gold';
    return <Tag color={color}>{status}</Tag>;
  }
  return <span className={column.key.includes('json') || column.key.includes('code') ? 'mono-text' : undefined}>{String(value)}</span>;
}

export default DataQueryPage;
