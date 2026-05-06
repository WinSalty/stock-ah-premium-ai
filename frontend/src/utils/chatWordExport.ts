import {
  AlignmentType,
  BorderStyle,
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType
} from 'docx';
import { saveAs } from 'file-saver';
import type { ChatTurnExportItem } from '../types/domain';

const SAFE_FILENAME_PATTERN = /[\\/:*?"<>|]/g;

/**
 * 导出问答回答为 Word 文档。
 * 创建日期：2026-05-05
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
        properties: {},
        children
      }
    ]
  });
  const blob = await Packer.toBlob(document);
  saveAs(blob, `${safeFilename(title || '智能问答回答')}.docx`);
}

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
    blocks.push(
      new Paragraph({
        children: [
          new TextRun({
            text: codeLines.join('\n'),
            font: 'Consolas',
            size: 20
          })
        ],
        shading: { fill: 'F1F5F9' },
        spacing: { before: 80, after: 160 }
      })
    );
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
          children: parseInlineRuns(cleanMarkdownText(heading[2])),
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
          children: parseInlineRuns(cleanMarkdownText(list[1])),
          bullet: { level: 0 },
          spacing: { after: 80 }
        })
      );
      return;
    }
    paragraphLines.push(cleanMarkdownText(line));
  });
  flushParagraph();
  flushTable();
  flushCode();
  return blocks.length ? blocks : [new Paragraph({ text: markdown })];
}

function parseInlineRuns(text: string) {
  const runs: TextRun[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let lastIndex = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > lastIndex) {
      runs.push(new TextRun(cleanMarkdownText(text.slice(lastIndex, match.index))));
    }
    const token = match[0];
    if (token.startsWith('**')) {
      runs.push(new TextRun({ text: cleanMarkdownText(token.slice(2, -2)), bold: true }));
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
  if (lastIndex < text.length) {
    runs.push(new TextRun(cleanMarkdownText(text.slice(lastIndex))));
  }
  return runs.length ? runs : [new TextRun(text)];
}

function markdownTableToDocx(lines: string[]) {
  if (lines.length < 2 || !/^\|?\s*:?-{3,}/.test(lines[1])) {
    return null;
  }
  const rows = lines
    .filter((_, index) => index !== 1)
    .map(splitMarkdownTableRow)
    .filter((cells) => cells.length);
  if (!rows.length) {
    return null;
  }
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
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
          children: cells.map(
            (cell) =>
              new TableCell({
                shading: rowIndex === 0 ? { fill: 'F1F5F9' } : undefined,
                children: [
                  new Paragraph({
                    children: [
                      new TextRun({
                        text: cleanMarkdownText(cell),
                        bold: rowIndex === 0
                      })
                    ],
                    alignment: AlignmentType.LEFT
                  })
                ]
              })
          )
        })
    )
  });
}

function splitMarkdownTableRow(line: string) {
  return line
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function isMarkdownTableLine(line: string) {
  return line.trim().startsWith('|') && line.includes('|');
}

function cleanMarkdownText(text: string) {
  return text
    .replace(/\[([^\]]+)]\([^)]+\)/g, '$1')
    .replace(/[*_~]/g, '')
    .trim();
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
