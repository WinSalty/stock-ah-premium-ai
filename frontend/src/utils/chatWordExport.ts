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
import type { ChatTurnExportItem } from '../types/domain';

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

/**
 * 构造单轮问答导出块，问题、回答分区展示，避免多轮回答混在同一段里。
 * 创建日期：2026-05-07
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
    ...markdownToBlocks(turn.answer)
  ];
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
