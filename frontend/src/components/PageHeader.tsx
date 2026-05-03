import { Typography } from 'antd';
import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  extra?: ReactNode;
}

/**
 * 页面标题栏。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function PageHeader({ title, extra }: PageHeaderProps) {
  return (
    <div className="page-header">
      <Typography.Title level={2}>{title}</Typography.Title>
      {extra}
    </div>
  );
}

export default PageHeader;
