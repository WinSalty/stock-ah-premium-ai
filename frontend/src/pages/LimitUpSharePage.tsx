import { Result, Skeleton, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { fetchPublicLimitUpReport } from '../api/limitUpPush';
import { formatEast8DateTime } from '../utils/datetime';

interface LimitUpSharePageProps {
  token: string;
}

/**
 * 打板报告临时分享公开查看页。
 * 创建日期：2026-05-09
 * author: sunshengxian
 */
function LimitUpSharePage({ token }: LimitUpSharePageProps) {
  const report = useQuery({
    queryKey: ['limit-up-public-share', token],
    queryFn: () => fetchPublicLimitUpReport(token),
    retry: false
  });

  if (report.isLoading) {
    return (
      <main className="limit-up-share-page">
        <section className="limit-up-share-shell">
          <Skeleton active paragraph={{ rows: 8 }} />
        </section>
      </main>
    );
  }

  if (report.isError || !report.data) {
    return (
      <main className="limit-up-share-page">
        <Result status="404" title="分享链接不可用" subTitle="链接可能已过期或已被撤销。" />
      </main>
    );
  }

  return (
    <main className="limit-up-share-page">
      <section className="limit-up-share-shell">
        <div className="limit-up-share-head">
          <Typography.Title level={2}>{report.data.title}</Typography.Title>
          <Typography.Text type="secondary">
            交易日 {report.data.trade_date} · 生成 {formatEast8DateTime(report.data.generated_at)} ·{' '}
            {report.data.permanent ? '永久有效' : `有效至 ${formatEast8DateTime(report.data.expires_at)}`}
          </Typography.Text>
        </div>
        <article className="limit-up-share-content" dangerouslySetInnerHTML={{ __html: report.data.content_html }} />
      </section>
    </main>
  );
}

export default LimitUpSharePage;
