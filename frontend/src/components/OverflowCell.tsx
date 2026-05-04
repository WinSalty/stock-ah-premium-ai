import { Tooltip, Typography } from 'antd';
import type { ReactNode } from 'react';
import { formatFieldValue } from '../utils/datetime';

interface OverflowCellProps {
  value: unknown;
  fieldKey?: string;
  mono?: boolean;
  danger?: boolean;
  threshold?: number;
  className?: string;
  emptyText?: ReactNode;
}

/**
 * 表格长字段单行省略，悬浮展示完整内容。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function OverflowCell({
  value,
  fieldKey,
  mono,
  danger,
  threshold = 24,
  className,
  emptyText
}: OverflowCellProps) {
  const text = formatFieldValue(value, fieldKey);
  if (text === '-') {
    return emptyText || <Typography.Text type="secondary">-</Typography.Text>;
  }
  const classes = [
    'overflow-cell-text',
    mono ? 'mono-text' : '',
    danger ? 'danger' : '',
    className || ''
  ].filter(Boolean).join(' ');
  const node = <span className={classes}>{text}</span>;
  if (text.length <= threshold && !text.includes('\n')) {
    return node;
  }
  return (
    <Tooltip
      arrow
      placement="topLeft"
      overlayClassName="overflow-cell-tooltip"
      title={<pre className="overflow-cell-tooltip-content">{text}</pre>}
    >
      {node}
    </Tooltip>
  );
}

export default OverflowCell;
