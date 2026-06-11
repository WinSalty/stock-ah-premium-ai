import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';
import type {
  ChartAxis,
  ChartSeries,
  ChartSpec,
  ChartYAxis
} from '../types/domain';

/**
 * 智能问答内嵌图表组件：把受控 ChartSpec 映射为 ECharts option 并渲染。
 *
 * 设计口径（chat-agent-refactor-design-and-plan.md 3.5 节）：
 * - 受控字段杜绝任意 HTML/JS 注入，仅按 chart_type 联动映射；
 * - 6 种图型（line/bar/pie/scatter/kline/dual_axis）+ 空数据占位 + 未知类型占位；
 * - 移动端（窗口宽度 < 768）降低高度，容器宽度自适应；
 * - note 字段渲染为图表下方小字数据来源说明。
 *
 * 创建日期：2026-06-12
 * author: sunshengxian
 */

interface ChatChartProps {
  spec: ChartSpec;
}

/**
 * 统一色板：6 色，取自现有页面（PremiumPage / OverviewPage）的 ECharts 风格，保证视觉协调。
 * 顺序兼顾冷暖对比，便于多系列折线/柱状区分。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
const CHAT_CHART_PALETTE = [
  '#2563eb', // 蓝（主色，与提问气泡同系）
  '#0891b2', // 青
  '#16a34a', // 绿
  '#f59e0b', // 橙
  '#e11d48', // 红
  '#7c3aed', // 紫
  '#475569', // 灰蓝（基准/中位线常用）
  '#0f766e' // 墨绿
];

// 移动端断点：窗口宽度小于该值时降低图表高度，避免移动端纵向占屏过高。
const MOBILE_BREAKPOINT = 768;
const DESKTOP_HEIGHT = 360;
const MOBILE_HEIGHT = 280;

// kline 涨跌配色（红涨绿跌，符合 A 股习惯）。
const KLINE_UP_COLOR = '#e11d48';
const KLINE_DOWN_COLOR = '#16a34a';

/**
 * 监听窗口宽度判断是否移动端视图（< 768）。
 * 用一个简单的 resize 监听 + useState，避免引入额外依赖。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < MOBILE_BREAKPOINT
  );
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return isMobile;
}

/**
 * 判断一个 series.values 是否为 kline 四元组列表（元素为数组）。
 * 仅用于运行时健壮性兜底：字段缺失或类型不符时不崩溃。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function isQuadValues(values: ChartSeries['values']): values is number[][] {
  return Array.isArray(values) && values.length > 0 && Array.isArray(values[0]);
}

/**
 * 判断 spec 是否「无可渲染数据」：缺 series、所有 series 的 values 均为空，
 * 或标量系列全为 null。命中则渲染占位提示而非交给 ECharts 报错。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function isEmptySpec(spec: ChartSpec): boolean {
  if (!Array.isArray(spec.series) || spec.series.length === 0) {
    return true;
  }
  return spec.series.every((series) => {
    const values = series.values;
    if (!Array.isArray(values) || values.length === 0) {
      return true;
    }
    if (isQuadValues(values)) {
      // kline：四元组列表只要有任意一组合法（长度 4）即视为有数据。
      return !values.some((item) => Array.isArray(item) && item.length === 4);
    }
    // 标量系列：全为 null / 非数字视为无数据。
    return (values as (number | null)[]).every((v) => v === null || typeof v !== 'number');
  });
}

/**
 * 根据 y_axis.unit 构造数值格式化函数：
 * - 单位含「%」→ 追加百分号；
 * - 绝对值 >= 1000 → 千分位分隔；
 * - 其余原样（保留至多 2 位小数，去掉多余尾零）。
 * 同一函数用于数值轴 axisLabel.formatter 与 tooltip。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildValueFormatter(unit?: string) {
  const isPercent = Boolean(unit && unit.includes('%'));
  return (value: number | null | undefined): string => {
    if (value === null || value === undefined || typeof value !== 'number' || Number.isNaN(value)) {
      return '-';
    }
    // 大数走千分位；小数最多保留 2 位并去掉尾零，避免「12.300000」。
    const absValue = Math.abs(value);
    const rounded = Math.round(value * 100) / 100;
    const text =
      absValue >= 1000
        ? rounded.toLocaleString('en-US', { maximumFractionDigits: 2 })
        : String(rounded);
    return isPercent ? `${text}%` : unit ? `${text}${unit}` : text;
  };
}

/**
 * 构造紧凑 grid 边距：双轴图右侧留出空间给右轴标签。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildGrid(isDualAxis: boolean) {
  return {
    left: 52,
    right: isDualAxis ? 56 : 24,
    top: 48,
    bottom: 40,
    containLabel: true
  };
}

/**
 * legend 配置：超过 4 项时启用滚动型 legend（type:'scroll'）避免溢出遮挡图区。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildLegend(seriesCount: number) {
  return {
    top: 6,
    type: seriesCount > 4 ? ('scroll' as const) : ('plain' as const),
    // 滚动 legend 居中并预留两侧滚动箭头空间；普通 legend 靠右。
    ...(seriesCount > 4 ? { left: 'center' as const } : { right: 16 })
  };
}

/**
 * 标准类目轴系列图（line / bar / scatter）的 option 映射。
 * x_axis.values 作类目轴，每个 series 一条；line 适度平滑、bar 普通柱、scatter 点。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildCategoryOption(spec: ChartSpec, xAxis: ChartAxis, formatValue: (v: number | null | undefined) => string) {
  const echartsType = spec.chart_type === 'bar' ? 'bar' : spec.chart_type === 'scatter' ? 'scatter' : 'line';
  // scatter 用 'item' 触发（按点提示），line/bar 用 'axis'（按类目竖线提示）。
  const isScatter = spec.chart_type === 'scatter';
  return {
    color: CHAT_CHART_PALETTE,
    tooltip: {
      trigger: isScatter ? 'item' : 'axis',
      valueFormatter: (value: number) => formatValue(value)
    },
    legend: buildLegend(spec.series.length),
    grid: buildGrid(false),
    xAxis: {
      type: 'category',
      name: xAxis.label || '',
      nameGap: 26,
      data: xAxis.values,
      boundaryGap: spec.chart_type === 'bar'
    },
    yAxis: {
      type: 'value',
      name: spec.y_axis?.left_label || '',
      axisLabel: { formatter: (value: number) => formatValue(value) }
    },
    series: spec.series.map((series, index) => ({
      name: series.name,
      type: echartsType,
      // line 适度平滑（smooth:0.2），点小一些；bar/scatter 不平滑。
      ...(echartsType === 'line' ? { smooth: 0.2, symbolSize: 6 } : {}),
      ...(echartsType === 'scatter' ? { symbolSize: 10 } : {}),
      data: (series.values as (number | null)[]).map((v) =>
        typeof v === 'number' ? v : null
      ),
      itemStyle: { color: CHAT_CHART_PALETTE[index % CHAT_CHART_PALETTE.length] }
    }))
  };
}

/**
 * 饼图 option 映射：取 series[0]，扇区名用 x_axis.values，配对其数值。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildPieOption(spec: ChartSpec, xAxis: ChartAxis, formatValue: (v: number | null | undefined) => string) {
  const firstSeries = spec.series[0];
  const values = (firstSeries.values as (number | null)[]) || [];
  // 扇区名与数值按下标配对；缺失项用「-」占位避免错位。
  const pieData = xAxis.values.map((name, index) => ({
    name,
    value: typeof values[index] === 'number' ? values[index] : 0
  }));
  return {
    color: CHAT_CHART_PALETTE,
    tooltip: {
      trigger: 'item',
      // pie 提示同时给出占比，数值走单位格式化。
      formatter: (params: { name: string; value: number; percent: number }) =>
        `${params.name}：${formatValue(params.value)}（${params.percent}%）`
    },
    legend: { ...buildLegend(pieData.length), type: pieData.length > 4 ? 'scroll' : 'plain' },
    series: [
      {
        name: firstSeries.name,
        type: 'pie',
        radius: ['38%', '66%'],
        center: ['50%', '56%'],
        avoidLabelOverlap: true,
        label: { formatter: '{b}: {d}%' },
        data: pieData
      }
    ]
  };
}

/**
 * K 线图 option 映射：ECharts candlestick，series.values 为 [open, close, low, high] 四元组列表。
 * ECharts candlestick 的 data 顺序也是 [open, close, low, high]，与后端口径一致，无需重排。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildKlineOption(spec: ChartSpec, xAxis: ChartAxis, formatValue: (v: number | null | undefined) => string) {
  const firstSeries = spec.series[0];
  const quad = isQuadValues(firstSeries.values) ? firstSeries.values : [];
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' }
    },
    legend: buildLegend(1),
    grid: buildGrid(false),
    xAxis: {
      type: 'category',
      name: xAxis.label || '',
      nameGap: 26,
      data: xAxis.values
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: spec.y_axis?.left_label || '',
      axisLabel: { formatter: (value: number) => formatValue(value) }
    },
    series: [
      {
        name: firstSeries.name,
        type: 'candlestick',
        data: quad,
        itemStyle: {
          color: KLINE_UP_COLOR,
          color0: KLINE_DOWN_COLOR,
          borderColor: KLINE_UP_COLOR,
          borderColor0: KLINE_DOWN_COLOR
        }
      }
    ]
  };
}

/**
 * 双轴图 option 映射：左右两个 yAxis，series 按其 y_axis 字段（left/right）挂到对应轴；
 * 左右轴标签取 y_axis.left_label / right_label。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildDualAxisOption(
  spec: ChartSpec,
  xAxis: ChartAxis,
  yAxis: ChartYAxis,
  formatValue: (v: number | null | undefined) => string
) {
  return {
    color: CHAT_CHART_PALETTE,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => formatValue(value)
    },
    legend: buildLegend(spec.series.length),
    grid: buildGrid(true),
    xAxis: {
      type: 'category',
      name: xAxis.label || '',
      nameGap: 26,
      data: xAxis.values
    },
    yAxis: [
      {
        type: 'value',
        name: yAxis.left_label || '',
        position: 'left',
        axisLabel: { formatter: (value: number) => formatValue(value) }
      },
      {
        type: 'value',
        name: yAxis.right_label || '',
        position: 'right',
        axisLabel: { formatter: (value: number) => formatValue(value) }
      }
    ],
    series: spec.series.map((series, index) => ({
      name: series.name,
      type: 'line',
      smooth: 0.2,
      symbolSize: 6,
      // y_axis === 'right' 挂到第 2 根轴（yAxisIndex:1），默认左轴（0）。
      yAxisIndex: series.y_axis === 'right' ? 1 : 0,
      data: (series.values as (number | null)[]).map((v) =>
        typeof v === 'number' ? v : null
      ),
      itemStyle: { color: CHAT_CHART_PALETTE[index % CHAT_CHART_PALETTE.length] }
    }))
  };
}

function ChatChart({ spec }: ChatChartProps) {
  const isMobile = useIsMobile();
  const height = isMobile ? MOBILE_HEIGHT : DESKTOP_HEIGHT;

  // 数值格式化函数依赖 y_axis.unit，缓存避免每次渲染重建。
  const formatValue = useMemo(() => buildValueFormatter(spec.y_axis?.unit), [spec.y_axis?.unit]);

  // 按 chart_type 映射 ECharts option；未知类型或缺字段时返回 null 触发占位渲染。
  const option = useMemo(() => {
    // 空数据态：series 全空 / values 为空，统一走占位提示。
    if (isEmptySpec(spec)) {
      return null;
    }
    const xAxis: ChartAxis = spec.x_axis ?? { values: [] };
    const yAxis: ChartYAxis = spec.y_axis ?? {};
    try {
      switch (spec.chart_type) {
        case 'line':
        case 'bar':
        case 'scatter':
          return buildCategoryOption(spec, xAxis, formatValue);
        case 'pie':
          // pie 必须有扇区名（x_axis.values），缺失则视为无法渲染。
          if (!xAxis.values.length) {
            return null;
          }
          return buildPieOption(spec, xAxis, formatValue);
        case 'kline':
          return buildKlineOption(spec, xAxis, formatValue);
        case 'dual_axis':
          return buildDualAxisOption(spec, xAxis, yAxis, formatValue);
        default:
          // 未知 chart_type：返回 null 渲染占位而非抛错。
          return null;
      }
    } catch {
      // 任意映射异常（字段类型不符等）兜底为占位，保证组件不崩溃。
      return null;
    }
  }, [spec, formatValue]);

  // 标题始终展示（即便空数据），便于用户知道这是哪张缺数据的图。
  const title = spec.title || '图表';

  if (!option) {
    // 占位态：未知类型 / 空数据 / 映射失败统一展示「暂无图表数据」。
    return (
      <figure className="chat-chart chat-chart-empty">
        <div className="chat-chart-title">{title}</div>
        <div className="chat-chart-placeholder">暂无图表数据</div>
        {spec.note ? <figcaption className="chat-chart-note">{spec.note}</figcaption> : null}
      </figure>
    );
  }

  return (
    <figure className="chat-chart">
      <div className="chat-chart-title">{title}</div>
      <ReactECharts
        option={option}
        style={{ width: '100%', height }}
        notMerge
        opts={{ renderer: 'canvas' }}
      />
      {/* note 渲染为图表下方小字数据来源说明 */}
      {spec.note ? <figcaption className="chat-chart-note">{spec.note}</figcaption> : null}
    </figure>
  );
}

export default ChatChart;
