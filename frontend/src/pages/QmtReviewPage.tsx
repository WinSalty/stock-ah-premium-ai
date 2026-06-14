import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  DatePicker,
  Empty,
  Segmented,
  Select,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Button
} from 'antd';
import type { TableColumnsType } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import ReactECharts from 'echarts-for-react';
import { RotateCw, TrendingUp, Wallet, Activity, Layers, Info } from 'lucide-react';
import { useQuery, useQueryClient, useIsFetching } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import {
  fetchQmtAccounts,
  fetchQmtDailySummary,
  fetchQmtHistory,
  fetchQmtPositions,
  fetchQmtTrades,
  type NumLike,
  type QmtPositionItem,
  type QmtTradeItem
} from '../api/qmt';
import { formatEast8DateTime } from '../utils/datetime';

const QK = 'qmt-review';

// ---------------------------------------------------------------------------
// 展示口径工具：金额/比率归一与「红涨绿跌」配色（A 股约定，与全站一致）。
// ---------------------------------------------------------------------------

/** Decimal 字段（number|string|null）归一为 number|null，屏蔽 NaN。 */
function toNum(v: NumLike): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** 金额千分位；null→「-」。 */
function fmtMoney(v: NumLike, digits = 2): string {
  const n = toNum(v);
  if (n === null) return '-';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** 带正负号金额（盈亏用）。 */
function fmtSigned(v: NumLike, digits = 2): string {
  const n = toNum(v);
  if (n === null) return '-';
  const sign = n > 0 ? '+' : '';
  return sign + fmtMoney(n, digits);
}

/** 比率→百分比；null→「-」。 */
function fmtPct(v: NumLike, digits = 2): string {
  const n = toNum(v);
  if (n === null) return '-';
  return `${(n * 100).toFixed(digits)}%`;
}

/** 盈亏方向 className：正→红(up)，负→绿(down)，0/空→中性。 */
function pnlClass(v: NumLike): string {
  const n = toNum(v);
  if (n === null || n === 0) return 'qmt-flat';
  return n > 0 ? 'qmt-up' : 'qmt-down';
}

interface KpiCardProps {
  label: string;
  value: string;
  tone?: NumLike | 'neutral';
  sub?: string;
  hint?: string;
}

/** 单个 KPI 卡片：值按盈亏方向着色（tone='neutral' 则中性）。 */
function KpiCard({ label, value, tone = 'neutral', sub, hint }: KpiCardProps) {
  const cls = tone === 'neutral' ? 'qmt-flat' : pnlClass(tone);
  return (
    <div className="qmt-kpi-card">
      <div className="qmt-kpi-label">
        {label}
        {hint ? (
          <Tooltip title={hint}>
            <Info size={13} className="qmt-kpi-hint" />
          </Tooltip>
        ) : null}
      </div>
      <div className={`qmt-kpi-value ${cls}`}>{value}</div>
      {sub ? <div className="qmt-kpi-sub">{sub}</div> : null}
    </div>
  );
}

const DATE_FMT = 'YYYY-MM-DD';

/**
 * QMT 实盘复盘看板页（仅 admin 可见）。
 *
 * 数据全部来自后端 /api/review/*（口径单一来源，前端不二次推算盈亏）；金额展示遵循「红涨绿跌」。
 * 当前 admin 默认可见全部账户；非 admin 多账户隔离待 qmt_account 绑定表落地。
 * 「交易质量 / 闭环归因」深化口径（FIFO 撮合滑点、信号→收益归因物化）待数据底座阶段，
 * 此处先把已可得的真实指标（成功率/买不进、信号标签成交分布）呈现，并标注深化口径出处，避免造假数据。
 *
 * 创建日期：2026-06-14
 * author: claude
 */
export default function QmtReviewPage() {
  const queryClient = useQueryClient();
  const fetching = useIsFetching({ queryKey: [QK] });

  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  const [tradeDate, setTradeDate] = useState<Dayjs | null>(null);
  const [side, setSide] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [tradePage, setTradePage] = useState(1);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [tab, setTab] = useState('daily');

  // 账户清单：加载后自动选中最新账户与其最新交易日（仅首次）。
  const accountsQuery = useQuery({ queryKey: [QK, 'accounts'], queryFn: fetchQmtAccounts });
  const accounts = accountsQuery.data ?? [];

  useEffect(() => {
    if (!accountId && accounts.length > 0) {
      const first = [...accounts].sort((a, b) =>
        (b.latest_trade_date ?? '').localeCompare(a.latest_trade_date ?? '')
      )[0];
      setAccountId(first.account_id);
      if (first.latest_trade_date) setTradeDate(dayjs(first.latest_trade_date));
    }
  }, [accounts, accountId]);

  const dateStr = tradeDate ? tradeDate.format(DATE_FMT) : undefined;
  const ready = accountsQuery.isSuccess; // 账户清单就绪后再拉子查询，空库则展示空态

  const dailyQuery = useQuery({
    queryKey: [QK, 'daily', accountId, dateStr],
    queryFn: () => fetchQmtDailySummary({ account_id: accountId, trade_date: dateStr }),
    enabled: ready && accounts.length > 0
  });
  const tradesQuery = useQuery({
    queryKey: [QK, 'trades', accountId, dateStr, side, tradePage],
    queryFn: () =>
      fetchQmtTrades({
        account_id: accountId,
        trade_date: dateStr,
        side: side === 'ALL' ? undefined : side,
        page: tradePage,
        page_size: 20
      }),
    enabled: ready && accounts.length > 0
  });
  const positionsQuery = useQuery({
    queryKey: [QK, 'positions', accountId, dateStr],
    queryFn: () => fetchQmtPositions({ account_id: accountId, trade_date: dateStr }),
    enabled: ready && accounts.length > 0
  });
  const historyQuery = useQuery({
    queryKey: [QK, 'history', accountId, range?.[0]?.format(DATE_FMT), range?.[1]?.format(DATE_FMT)],
    queryFn: () =>
      fetchQmtHistory({
        account_id: accountId,
        start: range?.[0]?.format(DATE_FMT),
        end: range?.[1]?.format(DATE_FMT)
      }),
    enabled: ready && accounts.length > 0
  });

  const daily = dailyQuery.data;
  const history = historyQuery.data;

  const refresh = () => queryClient.invalidateQueries({ queryKey: [QK] });

  // 顶部账户/日期控制条。
  const controls = (
    <div className="qmt-controls">
      <Select
        size="middle"
        style={{ minWidth: 200 }}
        placeholder="选择账户"
        value={accountId}
        loading={accountsQuery.isLoading}
        onChange={(v) => {
          setAccountId(v);
          setTradePage(1);
        }}
        options={accounts.map((a) => ({
          value: a.account_id,
          label: `账户 ${a.account_id}${a.latest_trade_date ? ` · 至 ${a.latest_trade_date}` : ''}`
        }))}
      />
      {tab === 'history' ? (
        <DatePicker.RangePicker
          value={range ?? undefined}
          onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
          allowClear
        />
      ) : (
        <DatePicker
          value={tradeDate ?? undefined}
          onChange={(v) => {
            setTradeDate(v);
            setTradePage(1);
          }}
          allowClear={false}
          placeholder="交易日"
        />
      )}
      <Button title="刷新" icon={<RotateCw size={16} />} onClick={refresh} loading={fetching > 0} />
    </div>
  );

  // 全库无回流数据：统一空态，避免误以为接口异常。
  if (accountsQuery.isSuccess && accounts.length === 0) {
    return (
      <main className="page">
        <PageHeader title="实盘复盘" />
        <div className="panel">
          <Empty
            description={
              <div className="qmt-empty-rich">
                <Typography.Text strong>执行侧尚未回流任何账户数据</Typography.Text>
                <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                  待 miniQMT 执行侧盘后通过 <code>POST /api/internal/qmt/ingest</code> 回流成交 / 委托 /
                  持仓 / 账户日快照后，本看板将自动呈现当日复盘与历史净值。
                </Typography.Paragraph>
              </div>
            }
          />
        </div>
      </main>
    );
  }

  return (
    <main className="page qmt-review-page">
      <PageHeader title="实盘复盘" extra={controls} />
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'daily',
            label: (
              <span className="qmt-tab-label">
                <Wallet size={15} /> 当日复盘
              </span>
            ),
            children: (
              <DailyTab
                loading={dailyQuery.isLoading}
                daily={daily}
                tradesLoading={tradesQuery.isLoading}
                trades={tradesQuery.data}
                side={side}
                onSideChange={(s) => {
                  setSide(s);
                  setTradePage(1);
                }}
                page={tradePage}
                onPageChange={setTradePage}
                positionsLoading={positionsQuery.isLoading}
                positions={positionsQuery.data ?? []}
              />
            )
          },
          {
            key: 'history',
            label: (
              <span className="qmt-tab-label">
                <TrendingUp size={15} /> 历史净值
              </span>
            ),
            children: <HistoryTab loading={historyQuery.isLoading} history={history} />
          },
          {
            key: 'positions',
            label: (
              <span className="qmt-tab-label">
                <Layers size={15} /> 持仓明细
              </span>
            ),
            children: (
              <PositionsTable loading={positionsQuery.isLoading} positions={positionsQuery.data ?? []} />
            )
          },
          {
            key: 'quality',
            label: (
              <span className="qmt-tab-label">
                <Activity size={15} /> 交易质量
              </span>
            ),
            children: <QualityTab daily={daily} />
          }
        ]}
      />
    </main>
  );
}

// ---------------------------------------------------------------------------
// 当日复盘
// ---------------------------------------------------------------------------

interface DailyTabProps {
  loading: boolean;
  daily: import('../api/qmt').QmtDailySummary | undefined;
  tradesLoading: boolean;
  trades: import('../api/qmt').QmtTradesPage | undefined;
  side: 'ALL' | 'BUY' | 'SELL';
  onSideChange: (s: 'ALL' | 'BUY' | 'SELL') => void;
  page: number;
  onPageChange: (p: number) => void;
  positionsLoading: boolean;
  positions: QmtPositionItem[];
}

function DailyTab({
  loading,
  daily,
  tradesLoading,
  trades,
  side,
  onSideChange,
  page,
  onPageChange,
  positionsLoading,
  positions
}: DailyTabProps) {
  if (loading) return <PanelSpin />;
  if (!daily || !daily.has_data) {
    return (
      <div className="panel">
        <Empty description={`${daily?.trade_date ?? '该交易日'} 暂无回流数据`} />
      </div>
    );
  }
  return (
    <div className="qmt-daily">
      <section className="panel">
        <div className="panel-title">盈亏概览 · {daily.trade_date}</div>
        <div className="qmt-kpi-grid">
          <KpiCard
            label="当日盈亏"
            value={fmtSigned(daily.daily_pnl)}
            tone={daily.daily_pnl}
            hint="账户口径当日盈亏，已剔除当日净出入金。"
          />
          <KpiCard label="浮动盈亏" value={fmtSigned(daily.float_pnl)} tone={daily.float_pnl} hint="收盘持仓盯市浮盈浮亏合计。" />
          <KpiCard
            label="已实现盈亏"
            value={fmtSigned(daily.realized_pnl_approx)}
            tone={daily.realized_pnl_approx}
            hint="近似口径＝当日盈亏－浮动盈亏；精确 FIFO 交易级盈亏待数据底座。"
          />
          <KpiCard label="当日收益率" value={fmtPct(daily.daily_return)} tone={daily.daily_return} />
          <KpiCard label="收盘总资产" value={fmtMoney(daily.total_asset)} tone="neutral" />
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">成交与委托</div>
        <div className="qmt-kpi-grid">
          <KpiCard
            label="买入"
            value={`${daily.buy_count} 笔`}
            tone="neutral"
            sub={`成交额 ${fmtMoney(daily.buy_amount)}`}
          />
          <KpiCard
            label="卖出"
            value={`${daily.sell_count} 笔`}
            tone="neutral"
            sub={`成交额 ${fmtMoney(daily.sell_amount)}`}
          />
          <KpiCard
            label="下单成功率"
            value={fmtPct(daily.order_success_rate)}
            tone="neutral"
            sub="当日买入委托有成交占比"
          />
          <KpiCard
            label="买不进"
            value={`${daily.no_fill_count} 只`}
            tone="neutral"
            sub="委托终态零成交"
          />
        </div>
      </section>

      <section className="panel">
        <div className="qmt-section-head">
          <div className="panel-title" style={{ marginBottom: 0 }}>
            当日成交明细
          </div>
          <Segmented
            size="small"
            value={side}
            onChange={(v) => onSideChange(v as 'ALL' | 'BUY' | 'SELL')}
            options={[
              { label: '全部', value: 'ALL' },
              { label: '买入', value: 'BUY' },
              { label: '卖出', value: 'SELL' }
            ]}
          />
        </div>
        <TradesTable
          loading={tradesLoading}
          trades={trades}
          page={page}
          onPageChange={onPageChange}
        />
      </section>

      <section className="panel">
        <div className="panel-title">当日持仓</div>
        <PositionsTable loading={positionsLoading} positions={positions} compact />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 成交明细表
// ---------------------------------------------------------------------------

function sideTag(s: string) {
  if (s === 'BUY') return <Tag color="red">买入</Tag>;
  if (s === 'SELL') return <Tag color="green">卖出</Tag>;
  return <Tag>{s}</Tag>;
}

interface TradesTableProps {
  loading: boolean;
  trades: import('../api/qmt').QmtTradesPage | undefined;
  page: number;
  onPageChange: (p: number) => void;
}

function TradesTable({ loading, trades, page, onPageChange }: TradesTableProps) {
  const columns: TableColumnsType<QmtTradeItem> = [
    {
      title: '成交时间',
      dataIndex: 'traded_time_east8',
      width: 160,
      render: (v: string | null) => (v ? formatEast8DateTime(v, { naiveAsEast8: true }) : '-')
    },
    {
      title: '证券',
      key: 'security',
      width: 160,
      render: (_, r) => (
        <div className="qmt-cell-stack">
          <span className="qmt-strong">{r.name ?? r.ts_code}</span>
          <span className="qmt-muted">{r.ts_code}</span>
        </div>
      )
    },
    { title: '方向', dataIndex: 'trade_side', width: 76, render: (v: string) => sideTag(v) },
    {
      title: '成交价',
      dataIndex: 'traded_price',
      align: 'right',
      width: 100,
      render: (v: NumLike) => fmtMoney(v, 3)
    },
    {
      title: '数量(股)',
      dataIndex: 'traded_volume',
      align: 'right',
      width: 110,
      render: (v: number) => v.toLocaleString('zh-CN')
    },
    {
      title: '成交额',
      dataIndex: 'traded_amount',
      align: 'right',
      width: 130,
      render: (v: NumLike) => fmtMoney(v)
    },
    {
      title: '回挂信号',
      key: 'signal',
      width: 240,
      render: (_, r) => {
        if (!r.signal_trade_date && !r.strategy_family && !r.role) {
          return <span className="qmt-muted">—</span>;
        }
        return (
          <div className="qmt-signal-tags">
            {r.strategy_family ? <Tag color="volcano">{r.strategy_family}</Tag> : null}
            {r.setup ? <Tag>{r.setup}</Tag> : null}
            {r.role ? <Tag color="gold">{r.role}</Tag> : null}
            {r.market_state ? <Tag color="blue">{r.market_state}</Tag> : null}
            {r.signal_trade_date ? (
              <span className="qmt-muted">信号日 {r.signal_trade_date}</span>
            ) : null}
          </div>
        );
      }
    }
  ];
  return (
    <Table
      size="small"
      rowKey={(r) => `${r.trade_date}-${r.traded_id}`}
      loading={loading}
      columns={columns}
      dataSource={trades?.items ?? []}
      scroll={{ x: 920 }}
      locale={{ emptyText: <Empty description="当日无成交" /> }}
      pagination={{
        current: page,
        pageSize: trades?.page_size ?? 20,
        total: trades?.total ?? 0,
        onChange: onPageChange,
        showSizeChanger: false,
        showTotal: (t) => `共 ${t} 笔`
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// 持仓表
// ---------------------------------------------------------------------------

function PositionsTable({
  loading,
  positions,
  compact
}: {
  loading: boolean;
  positions: QmtPositionItem[];
  compact?: boolean;
}) {
  const columns: TableColumnsType<QmtPositionItem> = [
    {
      title: '证券',
      key: 'security',
      width: 160,
      render: (_, r) => (
        <div className="qmt-cell-stack">
          <span className="qmt-strong">{r.name ?? r.ts_code}</span>
          <span className="qmt-muted">{r.ts_code}</span>
        </div>
      )
    },
    {
      title: '持仓 / 可用',
      key: 'volume',
      align: 'right',
      width: 130,
      render: (_, r) => `${r.volume.toLocaleString('zh-CN')} / ${r.can_use_volume.toLocaleString('zh-CN')}`
    },
    { title: '成本价', dataIndex: 'avg_price', align: 'right', width: 100, render: (v: NumLike) => fmtMoney(v, 3) },
    { title: '现价', dataIndex: 'last_price', align: 'right', width: 100, render: (v: NumLike) => fmtMoney(v, 3) },
    { title: '市值', dataIndex: 'market_value', align: 'right', width: 130, render: (v: NumLike) => fmtMoney(v) },
    {
      title: '浮动盈亏',
      dataIndex: 'float_profit',
      align: 'right',
      width: 130,
      render: (v: NumLike) => <span className={pnlClass(v)}>{fmtSigned(v)}</span>
    },
    {
      title: '浮盈比例',
      dataIndex: 'profit_rate',
      align: 'right',
      width: 110,
      render: (v: NumLike) => <span className={pnlClass(v)}>{fmtPct(v)}</span>
    }
  ];
  const body = (
    <Table
      size="small"
      rowKey="ts_code"
      loading={loading}
      columns={columns}
      dataSource={positions}
      pagination={false}
      scroll={{ x: 820 }}
      locale={{ emptyText: <Empty description="当前无持仓" /> }}
    />
  );
  return compact ? body : <div className="panel">{body}</div>;
}

// ---------------------------------------------------------------------------
// 历史净值
// ---------------------------------------------------------------------------

function HistoryTab({
  loading,
  history
}: {
  loading: boolean;
  history: import('../api/qmt').QmtHistoryStats | undefined;
}) {
  const option = useMemo(() => buildNavOption(history), [history]);
  if (loading) return <PanelSpin />;
  if (!history || history.trading_days === 0) {
    return (
      <div className="panel">
        <Empty description="所选区间暂无收盘账户快照" />
      </div>
    );
  }
  return (
    <div className="qmt-history">
      <section className="panel">
        <div className="panel-title">绩效指标 · {history.start_date} ~ {history.end_date}</div>
        <div className="qmt-kpi-grid">
          <KpiCard label="累计收益" value={fmtPct(history.cumulative_return)} tone={history.cumulative_return} />
          <KpiCard label="年化收益" value={fmtPct(history.annualized_return)} tone={history.annualized_return} />
          <KpiCard
            label="最大回撤"
            value={fmtPct(history.max_drawdown)}
            tone={history.max_drawdown}
            hint="区间内净值相对历史峰值的最大跌幅。"
          />
          <KpiCard
            label="夏普"
            value={toNum(history.sharpe) === null ? '-' : String(toNum(history.sharpe))}
            tone="neutral"
            hint="日频年化、无风险利率取 0；样本不足时为空。"
          />
          <KpiCard label="日胜率" value={fmtPct(history.win_rate)} tone="neutral" />
          <KpiCard label="交易日数" value={`${history.trading_days} 日`} tone="neutral" />
        </div>
      </section>
      <section className="panel">
        <div className="qmt-section-head">
          <div className="panel-title" style={{ marginBottom: 0 }}>
            净值与回撤曲线
          </div>
          <Tooltip title="净值＝总资产简单归一（起点=1，未剔出入金）；精确 TWR 待出入金台账落地。">
            <span className="qmt-nav-note">
              <Info size={13} /> 口径说明
            </span>
          </Tooltip>
        </div>
        <ReactECharts option={option} style={{ height: 420, width: '100%' }} notMerge />
      </section>
    </div>
  );
}

/** 构造净值(折线,左轴) + 回撤(面积,右轴) 双轴 echarts option。 */
function buildNavOption(history: import('../api/qmt').QmtHistoryStats | undefined) {
  const points = history?.points ?? [];
  const dates = points.map((p) => p.trade_date);
  const navs = points.map((p) => toNum(p.nav));
  const dds = points.map((p) => {
    const n = toNum(p.drawdown);
    return n === null ? null : Number((n * 100).toFixed(3));
  });
  return {
    grid: { left: 56, right: 56, top: 36, bottom: 48 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: undefined,
      formatter: (params: Array<{ axisValue: string; seriesName: string; data: number | null; marker: string }>) => {
        if (!params.length) return '';
        const head = `<div style="font-weight:600;margin-bottom:4px">${params[0].axisValue}</div>`;
        const lines = params
          .map((p) => {
            const val =
              p.seriesName === '回撤'
                ? `${(p.data ?? 0).toFixed(2)}%`
                : (p.data ?? 0).toFixed(4);
            return `${p.marker}${p.seriesName}：${val}`;
          })
          .join('<br/>');
        return head + lines;
      }
    },
    legend: { data: ['净值', '回撤'], top: 4, right: 8 },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: { color: '#64748b' },
      axisLine: { lineStyle: { color: '#cbd5e1' } }
    },
    yAxis: [
      {
        type: 'value',
        name: '净值',
        scale: true,
        nameTextStyle: { color: '#64748b' },
        axisLabel: { color: '#64748b', formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: '#eef2f7' } }
      },
      {
        type: 'value',
        name: '回撤(%)',
        max: 0,
        position: 'right',
        nameTextStyle: { color: '#64748b' },
        axisLabel: { color: '#94a3b8', formatter: (v: number) => `${v.toFixed(0)}%` },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '净值',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: navs,
        lineStyle: { width: 2.4, color: '#1d4ed8' },
        itemStyle: { color: '#1d4ed8' },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#94a3b8', type: 'dashed' },
          data: [{ yAxis: 1 }]
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(29,78,216,0.18)' },
              { offset: 1, color: 'rgba(29,78,216,0.01)' }
            ]
          }
        }
      },
      {
        name: '回撤',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        showSymbol: false,
        data: dds,
        lineStyle: { width: 1, color: '#dc2626' },
        itemStyle: { color: '#dc2626' },
        areaStyle: { color: 'rgba(220,38,38,0.10)' }
      }
    ]
  };
}

// ---------------------------------------------------------------------------
// 交易质量（已可得真实指标 + 深化口径出处标注）
// ---------------------------------------------------------------------------

function QualityTab({ daily }: { daily: import('../api/qmt').QmtDailySummary | undefined }) {
  return (
    <div className="qmt-quality">
      <section className="panel">
        <div className="panel-title">当日下单质量</div>
        {daily && daily.has_data ? (
          <div className="qmt-kpi-grid">
            <KpiCard
              label="下单成功率"
              value={fmtPct(daily.order_success_rate)}
              tone="neutral"
              sub="买入委托有成交占比"
            />
            <KpiCard label="买不进" value={`${daily.no_fill_count} 只`} tone="neutral" sub="委托终态零成交" />
            <KpiCard label="买入成交" value={`${daily.buy_count} 笔`} tone="neutral" sub={`额 ${fmtMoney(daily.buy_amount)}`} />
            <KpiCard label="卖出成交" value={`${daily.sell_count} 笔`} tone="neutral" sub={`额 ${fmtMoney(daily.sell_amount)}`} />
          </div>
        ) : (
          <Empty description="该交易日暂无委托数据" />
        )}
      </section>
      <section className="panel">
        <Alert
          type="info"
          showIcon
          message="更细的成交质量指标在建设中"
          description={
            <span>
              滑点（成交价 vs 委托价 / 信号价）、FIFO 撮合的交易级盈亏与持有时长、买不进归因（封单不足 / 撤单
              / 涨停打开）等，依赖「数据底座」阶段补齐委托-成交配对与基准价快照后上线；当前优先保证账户级与
              委托级真实口径不造假。
            </span>
          }
        />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 公共：面板内 loading
// ---------------------------------------------------------------------------

function PanelSpin() {
  return (
    <div className="panel qmt-panel-spin">
      <Spin />
    </div>
  );
}
