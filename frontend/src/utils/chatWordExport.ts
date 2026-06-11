import {
  AlignmentType,
  BorderStyle,
  Document,
  HeadingLevel,
  PageOrientation,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableLayoutType,
  TableRow,
  TextRun,
  VerticalAlignTable,
  WidthType
} from 'docx';
import { saveAs } from 'file-saver';
import type { ChartSpec, ChatTurnExportItem } from '../types/domain';

const SAFE_FILENAME_PATTERN = /[\\/:*?"<>|]/g;
const LANDSCAPE_A4_WIDTH_TWIP = 16838;
const LANDSCAPE_A4_HEIGHT_TWIP = 11906;
const PAGE_MARGIN_TWIP = 720;
const CONTENT_WIDTH_TWIP = LANDSCAPE_A4_WIDTH_TWIP - PAGE_MARGIN_TWIP * 2;
const TABLE_CELL_MARGIN_TWIP = 90;

/**
 * 导出问答回答为点击即下载的 Word 文档。
 * 创建日期：2026-05-07
 * author: sunshengxian
 */
export async function exportChatAnswersToWord(title: string, turns: ChatTurnExportItem[]) {
  const answeredTurns = turns.filter((turn) => turn.answer.trim());
  const children = [
    new Paragraph({
      text: title || '智能问答回答导出',
      heading: HeadingLevel.TITLE,
      spacing: { after: 260 }
    }),
    new Paragraph({
      children: [new TextRun({ text: `导出时间：${formatExportTime()}`, color: '64748B' })],
      spacing: { after: 360 }
    }),
    ...answeredTurns.flatMap((turn, index) => buildTurnBlocks(turn, index))
  ];
  const document = new Document({
    sections: [
      {
        properties: {
          page: {
            size: {
              orientation: PageOrientation.LANDSCAPE,
              width: LANDSCAPE_A4_WIDTH_TWIP,
              height: LANDSCAPE_A4_HEIGHT_TWIP
            },
            margin: {
              top: PAGE_MARGIN_TWIP,
              right: PAGE_MARGIN_TWIP,
              bottom: PAGE_MARGIN_TWIP,
              left: PAGE_MARGIN_TWIP
            }
          }
        },
        children
      }
    ]
  });
  const blob = await Packer.toBlob(document);
  saveAs(blob, `${safeFilename(title || '智能问答回答')}.docx`);
}

// 匹配回答正文中的图表占位符 {{chart:cN}}，捕获 chart_id；与前端渲染口径一致。
const CHART_PLACEHOLDER_PATTERN = /\{\{chart:([a-zA-Z0-9_-]+)\}\}/g;

/**
 * 构造单轮问答导出块，问题、回答分区展示，避免多轮回答混在同一段里。
 * 创建日期：2026-05-07
 * 更新日期：2026-06-12（回答正文按 {{chart:id}} 占位符将图表降级为「【图表】标题 + 数据表格」）
 * author: sunshengxian
 */
function buildTurnBlocks(turn: ChatTurnExportItem, index: number) {
  return [
    new Paragraph({
      text: `问题 ${index + 1}`,
      heading: HeadingLevel.HEADING_1,
      spacing: { before: index === 0 ? 0 : 360, after: 140 }
    }),
    new Paragraph({
      children: [new TextRun({ text: turn.question, bold: true })],
      spacing: { after: 220 }
    }),
    new Paragraph({
      text: '回答',
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 80, after: 120 }
    }),
    ...answerWithChartsToBlocks(turn.answer, turn.charts)
  ];
}

/**
 * 把回答正文按 {{chart:id}} 占位符切分：文本段走原有 markdownToBlocks，
 * 图表段按 chart_id 找到对应 spec 降级输出「【图表】标题 + 数据表格」；
 * 正文未引用的图表追加在末尾（与前端兜底渲染口径一致）。
 * 占位符引用但找不到对应 spec 的，丢弃残留占位符文本不输出。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function answerWithChartsToBlocks(answer: string, charts: ChartSpec[] | undefined) {
  const chartList = charts || [];
  // 无图表时退化为原有纯 Markdown 导出路径，保持既有行为不变。
  if (!chartList.length) {
    return markdownToBlocks(answer);
  }
  const chartMap = new Map<string, ChartSpec>();
  chartList.forEach((spec) => {
    if (spec.chart_id) {
      chartMap.set(spec.chart_id, spec);
    }
  });
  const blocks: Array<Paragraph | Table> = [];
  const referencedIds = new Set<string>();
  let lastIndex = 0;
  CHART_PLACEHOLDER_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CHART_PLACEHOLDER_PATTERN.exec(answer)) !== null) {
    const chartId = match[1];
    // 占位符之前的文本段先按 Markdown 转块。
    const textBefore = answer.slice(lastIndex, match.index);
    if (textBefore.trim()) {
      blocks.push(...markdownToBlocks(textBefore));
    }
    referencedIds.add(chartId);
    const spec = chartMap.get(chartId);
    if (spec) {
      blocks.push(...chartToBlocks(spec));
    }
    // 未命中：不输出任何内容，丢弃残留 {{chart:x}} 文本。
    lastIndex = match.index + match[0].length;
  }
  const tail = answer.slice(lastIndex);
  if (tail.trim()) {
    blocks.push(...markdownToBlocks(tail));
  }
  // 兜底：正文未引用的图表追加在末尾。
  chartList.forEach((spec) => {
    if (!spec.chart_id || !referencedIds.has(spec.chart_id)) {
      blocks.push(...chartToBlocks(spec));
    }
  });
  return blocks.length ? blocks : [new Paragraph({ text: answer })];
}

/**
 * 把单个 ChartSpec 降级为 Word 块：「【图表】标题」标题段 + 由 spec 还原的数据表格 + note 说明。
 * 还原口径：
 * - line/bar/scatter/dual_axis：x_axis.values 作首列（类目），各 series 作一列（标量）；
 * - pie：取 series[0]，x_axis.values 作「类别」列，数值作「数值」列；
 * - kline：x_axis.values 作首列，四元组拆为「开/收/低/高」四列。
 * 数据不足以成表时仅保留标题段，避免空表。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function chartToBlocks(spec: ChartSpec): Array<Paragraph | Table> {
  const blocks: Array<Paragraph | Table> = [
    new Paragraph({
      children: [new TextRun({ text: `【图表】${spec.title || '未命名图表'}`, bold: true })],
      spacing: { before: 160, after: 100 }
    })
  ];
  const table = chartSpecToTable(spec);
  if (table) {
    blocks.push(table);
  }
  if (spec.note) {
    blocks.push(
      new Paragraph({
        children: [new TextRun({ text: spec.note, color: '64748B', size: 18 })],
        spacing: { before: 60, after: 140 }
      })
    );
  }
  return blocks;
}

/**
 * 由 ChartSpec 还原一个 Word 数据表格（复用 markdownTableToDocx 的固定布局表格）。
 * 数值为 null 时输出空串。无法构表（无类目、无系列）返回 null。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function chartSpecToTable(spec: ChartSpec): Table | null {
  const categories = spec.x_axis?.values || [];
  const series = spec.series || [];
  if (!series.length) {
    return null;
  }

  // pie：取首系列，「类别 / 数值」两列。
  if (spec.chart_type === 'pie') {
    const values = series[0].values as (number | null)[];
    if (!categories.length) {
      return null;
    }
    const header = ['类别', series[0].name || '数值'];
    const rows = categories.map((name, index) => [name, formatCell(values[index])]);
    return buildSpecTable([header, ...rows]);
  }

  // kline：四元组拆为「开盘 / 收盘 / 最低 / 最高」四列，首列为类目。
  if (spec.chart_type === 'kline') {
    const quad = series[0].values as number[][];
    if (!Array.isArray(quad) || !quad.length) {
      return null;
    }
    const header = [spec.x_axis?.label || '时间', '开盘', '收盘', '最低', '最高'];
    const rows = quad.map((item, index) => [
      categories[index] ?? String(index + 1),
      formatCell(item?.[0]),
      formatCell(item?.[1]),
      formatCell(item?.[2]),
      formatCell(item?.[3])
    ]);
    return buildSpecTable([header, ...rows]);
  }

  // line/bar/scatter/dual_axis：首列类目，每个 series 一列（标量）。
  if (!categories.length) {
    return null;
  }
  const header = [spec.x_axis?.label || '类目', ...series.map((item) => item.name || '系列')];
  const rows = categories.map((name, index) => [
    name,
    ...series.map((item) => formatCell((item.values as (number | null)[])[index]))
  ]);
  return buildSpecTable([header, ...rows]);
}

/**
 * 把数值单元格格式化为字符串：null/非数字输出空串，数字原样（保留至多 2 位小数）。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function formatCell(value: number | null | undefined): string {
  if (value === null || value === undefined || typeof value !== 'number' || Number.isNaN(value)) {
    return '';
  }
  return String(Math.round(value * 100) / 100);
}

/**
 * 将回答 Markdown 转为 Word 块级结构，只覆盖导出所需的标题、列表、代码和 GFM 表格。
 * 创建日期：2026-05-07
 * author: sunshengxian
 */
function markdownToBlocks(markdown: string) {
  const blocks: Array<Paragraph | Table> = [];
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  let paragraphLines: string[] = [];
  let codeLines: string[] = [];
  let tableLines: string[] = [];
  let inCodeBlock = false;

  const flushParagraph = () => {
    if (!paragraphLines.length) {
      return;
    }
    blocks.push(
      new Paragraph({
        children: parseInlineRuns(paragraphLines.join(' ')),
        spacing: { after: 140 }
      })
    );
    paragraphLines = [];
  };
  const flushCode = () => {
    if (!codeLines.length) {
      return;
    }
    blocks.push(...buildCodeParagraphs(codeLines));
    codeLines = [];
  };
  const flushTable = () => {
    if (!tableLines.length) {
      return;
    }
    const table = markdownTableToDocx(tableLines);
    if (table) {
      blocks.push(table);
    } else {
      blocks.push(
        new Paragraph({
          text: tableLines.join('\n'),
          spacing: { after: 140 }
        })
      );
    }
    tableLines = [];
  };

  // 逐行解析块级 Markdown；切换块类型前先 flush，避免表格、列表和段落互相吞内容。
  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    if (line.trim().startsWith('```')) {
      flushParagraph();
      flushTable();
      if (inCodeBlock) {
        flushCode();
      }
      inCodeBlock = !inCodeBlock;
      return;
    }
    if (inCodeBlock) {
      codeLines.push(rawLine);
      return;
    }
    if (isMarkdownTableLine(line)) {
      flushParagraph();
      tableLines.push(line);
      return;
    }
    flushTable();
    if (!line.trim()) {
      flushParagraph();
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      blocks.push(
        new Paragraph({
          children: parseInlineRuns(heading[2]),
          heading: heading[1].length <= 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
          spacing: { before: 200, after: 100 }
        })
      );
      return;
    }
    const list = line.match(/^[-*]\s+(.+)$/) || line.match(/^\d+\.\s+(.+)$/);
    if (list) {
      flushParagraph();
      blocks.push(
        new Paragraph({
          children: parseInlineRuns(list[1]),
          bullet: { level: 0 },
          spacing: { after: 80 }
        })
      );
      return;
    }
    paragraphLines.push(line);
  });
  flushParagraph();
  flushTable();
  flushCode();
  return blocks.length ? blocks : [new Paragraph({ text: markdown })];
}

/**
 * 代码块按多段落输出，避免在部分非 macOS Word/WPS 中单个 TextRun 换行不稳定。
 * 创建日期：2026-05-07
 * author: sunshengxian
 */
function buildCodeParagraphs(lines: string[]) {
  return lines.map(
    (line) =>
      new Paragraph({
        children: [
          new TextRun({
            text: line || ' ',
            font: 'Consolas',
            size: 20
          })
        ],
        shading: { fill: 'F1F5F9' },
        spacing: { after: 40 }
      })
  );
}

/**
 * 解析行内加粗、代码和链接；链接只保留文字，避免导出文档里出现冗长 URL。
 * 创建日期：2026-05-07
 * author: sunshengxian
 */
function parseInlineRuns(text: string) {
  const runs: TextRun[] = [];
  const normalizedText = text.replace(/\[([^\]]+)]\([^)]+\)/g, '$1');
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  for (const match of normalizedText.matchAll(pattern)) {
    if (match.index > lastIndex) {
      runs.push(new TextRun(stripLooseMarkdown(normalizedText.slice(lastIndex, match.index))));
    }
    const token = match[0];
    if (token.startsWith('**')) {
      runs.push(new TextRun({ text: stripLooseMarkdown(token.slice(2, -2)), bold: true }));
    } else {
      runs.push(
        new TextRun({
          text: token.slice(1, -1),
          font: 'Consolas',
          shading: { fill: 'E8EEF7' }
        })
      );
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < normalizedText.length) {
    runs.push(new TextRun(stripLooseMarkdown(normalizedText.slice(lastIndex))));
  }
  return runs.length ? runs : [new TextRun(stripLooseMarkdown(normalizedText))];
}

/**
 * 转换 GFM 表格为固定布局 Word 表格，显式写入列宽、单元格宽和重复表头，提升跨平台兼容性。
 * 创建日期：2026-05-07
 * author: sunshengxian
 */
function markdownTableToDocx(lines: string[]) {
  if (lines.length < 2 || !isMarkdownSeparatorLine(lines[1])) {
    return null;
  }
  const parsedRows = lines
    .filter((_, index) => index !== 1)
    .map(splitMarkdownTableRow)
    .filter((cells) => cells.length);
  return buildSpecTable(parsedRows);
}

/**
 * 由二维字符串数组（含表头行）构造固定布局 Word 表格，显式写入列宽与重复表头。
 * 从 markdownTableToDocx 抽出公共建表逻辑，供 Markdown 表格与图表降级表格共用。
 * 行数为空或列数为 0 时返回 null。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
function buildSpecTable(parsedRows: string[][]) {
  const columnCount = Math.max(...parsedRows.map((row) => row.length), 0);
  if (!parsedRows.length || columnCount === 0) {
    return null;
  }
  const cellWidth = Math.max(Math.floor(CONTENT_WIDTH_TWIP / columnCount), 720);
  const columnWidths = Array.from({ length: columnCount }, () => cellWidth);
  const rows = parsedRows.map((cells) => padCells(cells, columnCount));

  return new Table({
    width: { size: CONTENT_WIDTH_TWIP, type: WidthType.DXA },
    columnWidths,
    layout: TableLayoutType.FIXED,
    margins: {
      top: TABLE_CELL_MARGIN_TWIP,
      bottom: TABLE_CELL_MARGIN_TWIP,
      left: TABLE_CELL_MARGIN_TWIP,
      right: TABLE_CELL_MARGIN_TWIP
    },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 1, color: 'CBD5E1' },
      bottom: { style: BorderStyle.SINGLE, size: 1, color: 'CBD5E1' },
      left: { style: BorderStyle.SINGLE, size: 1, color: 'CBD5E1' },
      right: { style: BorderStyle.SINGLE, size: 1, color: 'CBD5E1' },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: 'E2E8F0' },
      insideVertical: { style: BorderStyle.SINGLE, size: 1, color: 'E2E8F0' }
    },
    rows: rows.map(
      (cells, rowIndex) =>
        new TableRow({
          cantSplit: true,
          tableHeader: rowIndex === 0,
          children: cells.map((cell) =>
            new TableCell({
              width: { size: cellWidth, type: WidthType.DXA },
              verticalAlign: VerticalAlignTable.CENTER,
              shading: rowIndex === 0 ? { fill: 'F1F5F9' } : undefined,
              children: [
                new Paragraph({
                  children: parseInlineRuns(cell || ' '),
                  alignment: AlignmentType.LEFT
                })
              ]
            })
          )
        })
    )
  });
}

function padCells(cells: string[], columnCount: number) {
  return [...cells, ...Array.from({ length: Math.max(columnCount - cells.length, 0) }, () => '')];
}

function splitMarkdownTableRow(line: string) {
  return line
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split(/(?<!\\)\|/)
    .map((cell) => cell.replace(/\\\|/g, '|').trim());
}

function isMarkdownTableLine(line: string) {
  const trimmed = line.trim();
  return trimmed.includes('|') && (trimmed.startsWith('|') || trimmed.endsWith('|'));
}

function isMarkdownSeparatorLine(line: string) {
  return splitMarkdownTableRow(line).every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function stripLooseMarkdown(text: string) {
  return text.replace(/[*_~]/g, '').trim();
}

function safeFilename(value: string) {
  const cleaned = value.replace(SAFE_FILENAME_PATTERN, '_').trim();
  return (cleaned || '智能问答回答').slice(0, 80);
}

function formatExportTime() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(
    now.getHours()
  )}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
