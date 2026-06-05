import { Alert, Button, Card, Empty, Form, Input, Modal, Select, Space, Spin, Tag, Typography, Upload, message } from 'antd';
import { Download, ImagePlus, RefreshCw, Sparkles, UploadCloud, X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import PageHeader from '../components/PageHeader';
import {
  IMAGE_GENERATION_SIZE_OPTIONS,
  createImageGeneration,
  fetchImageGenerationErrorLogs,
  fetchImageGenerations,
  fetchMyImageGenerationQuota,
  fetchProtectedImageBlobUrl,
  retryImageGeneration
} from '../api/imageGeneration';
import type { ImageGenerationErrorLog, ImageGenerationItem, UserInfo } from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';

interface ImageGenerationPageProps {
  currentUser: UserInfo;
}

interface ImageGenerationFormValues {
  prompt: string;
  size: string;
}

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '已完成和生成中', value: 'READY,GENERATING' },
  { label: '已完成', value: 'READY' },
  { label: '失败', value: 'FAILED' },
  { label: '生成中', value: 'GENERATING' }
];

/**
 * AI 图片生成页面。
 * 创建日期：2026-05-27
 * author: sunshengxian
 */
function ImageGenerationPage({ currentUser }: ImageGenerationPageProps) {
  const [form] = Form.useForm<ImageGenerationFormValues>();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [referencePreviewUrl, setReferencePreviewUrl] = useState<string | null>(null);
  const [latestRecord, setLatestRecord] = useState<ImageGenerationItem | null>(null);
  const isAdmin = currentUser.role === 'ADMIN';
  const quota = useQuery({
    queryKey: ['image-generation-quota'],
    queryFn: fetchMyImageGenerationQuota
  });
  const generations = useQuery({
    queryKey: ['image-generations', statusFilter, keyword],
    queryFn: () =>
      fetchImageGenerations({
        page: 1,
        page_size: 60,
        status: statusFilter || undefined,
        keyword: keyword || undefined
      }),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.items.some((item) => item.status === 'GENERATING') ? 3000 : false;
    }
  });
  const createMutation = useMutation({
    mutationFn: (values: ImageGenerationFormValues) =>
      createImageGeneration({
        prompt: values.prompt,
        size: values.size || '1024x1024',
        referenceImage: referenceFile
      }),
    onSuccess: (record) => {
      setLatestRecord(record);
      queryClient.invalidateQueries({ queryKey: ['image-generation-quota'] });
      queryClient.invalidateQueries({ queryKey: ['image-generations'] });
      if (record.status === 'READY') {
        message.success('图片已生成并保存');
      } else if (record.status === 'GENERATING') {
        message.success('已开始生成，离开页面后也可以在历史图片里查看进度');
      } else {
        message.warning(record.error_message || '图片生成失败，本次不会计入今日次数');
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '图片生成失败')
  });
  // 失败图片的重试会新建后台任务；成功后刷新历史和额度，让用户离开页面后回来也能看到最新状态。
  const retryMutation = useMutation({
    mutationFn: retryImageGeneration,
    onSuccess: (record) => {
      setLatestRecord(record);
      queryClient.invalidateQueries({ queryKey: ['image-generation-quota'] });
      queryClient.invalidateQueries({ queryKey: ['image-generations'] });
      if (record.status === 'GENERATING') {
        message.success('已重新开始生成，稍后可在历史图片里查看进度');
      } else if (record.status === 'READY') {
        message.success('图片已生成并保存');
      } else {
        message.warning(record.error_message || '图片重试失败，本次不会计入今日次数');
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '图片重试失败')
  });

  useEffect(() => {
    if (!referenceFile) {
      setReferencePreviewUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(referenceFile);
    setReferencePreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [referenceFile]);

  useEffect(() => {
    if (!latestRecord || latestRecord.status !== 'GENERATING') {
      return;
    }
    const refreshedRecord = generations.data?.items.find((item) => item.id === latestRecord.id);
    if (refreshedRecord && refreshedRecord.status !== latestRecord.status) {
      setLatestRecord(refreshedRecord);
    }
  }, [generations.data?.items, latestRecord]);

  const quotaText = useMemo(() => {
    if (!quota.data) {
      return '今日剩余次数读取中';
    }
    return `今日剩余 ${quota.data.remaining_count}/${quota.data.daily_limit} 次`;
  }, [quota.data]);

  const submit = (values: ImageGenerationFormValues) => {
    createMutation.mutate(values);
  };

  const clearReference = () => {
    setReferenceFile(null);
  };

  return (
    <main className="page image-generation-page">
      <PageHeader title="图片生成" />
      <section className="image-generation-hero">
        <div>
          <Typography.Text className="image-generation-kicker">AI Image Studio</Typography.Text>
          <Typography.Title level={2}>用文字和参考图生成你的图片灵感</Typography.Title>
          <Typography.Paragraph>
            输入画面想法，选择适合的比例，生成结果会自动进入你的历史图片，方便随时预览和下载。
          </Typography.Paragraph>
        </div>
        <div className="image-generation-quota-card">
          <Sparkles size={22} />
          <Typography.Text strong>{quotaText}</Typography.Text>
          <Typography.Text type="secondary">默认 1K，可手动选择更高尺寸。</Typography.Text>
        </div>
      </section>
      <section className="panel image-generation-composer">
        <Form
          form={form}
          layout="vertical"
          initialValues={{ size: '1024x1024' }}
          onFinish={submit}
        >
          <Form.Item
            label="图片描述"
            name="prompt"
            rules={[{ required: true, message: '请输入图片描述' }]}
          >
            <Input.TextArea
              rows={5}
              maxLength={4000}
              showCount
              placeholder="例如：帮我生成一张90年小学生上课的真实照片"
            />
          </Form.Item>
          <div className="image-generation-form-grid">
            <Form.Item label="图片尺寸" name="size" rules={[{ required: true, message: '请选择图片尺寸' }]}>
              <Select options={IMAGE_GENERATION_SIZE_OPTIONS} />
            </Form.Item>
            <Form.Item label="参考图（可选）">
              <Upload
                accept="image/png,image/jpeg,image/webp"
                maxCount={1}
                showUploadList={false}
                beforeUpload={(file) => {
                  setReferenceFile(file);
                  return false;
                }}
              >
                <Button icon={<UploadCloud size={16} />}>选择参考图</Button>
              </Upload>
            </Form.Item>
          </div>
          {referencePreviewUrl ? (
            <div className="image-reference-preview">
              <img src={referencePreviewUrl} alt="参考图预览" />
              <div>
                <Typography.Text strong>{referenceFile?.name}</Typography.Text>
                <Typography.Text type="secondary">参考图会帮助生成结果贴近原图的构图、色彩或主体风格。</Typography.Text>
              </div>
              <Button type="text" icon={<X size={16} />} onClick={clearReference} />
            </div>
          ) : null}
          <Alert
            type="info"
            showIcon
            className="image-generation-note"
            message="上传参考图可以帮助画面延续构图、色彩或主体风格；不需要参考时，直接用文字描述也可以生成。"
          />
          <Button
            type="primary"
            htmlType="submit"
            icon={<ImagePlus size={16} />}
            loading={createMutation.isPending}
          >
            生成并保存图片
          </Button>
        </Form>
        <LatestImagePreview record={latestRecord} loading={createMutation.isPending} />
      </section>
      <section className="panel">
        <div className="query-result-head image-generation-history-head">
          <div>
            <div className="panel-title">历史图片</div>
            <Typography.Text type="secondary">
              {isAdmin ? '在这里查看近期生成的图片和提示词。' : '这里会保留你最近生成的图片和提示词。'}
            </Typography.Text>
          </div>
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="搜索提示词或用户"
              onSearch={setKeyword}
              className="image-generation-search"
            />
            <Select value={statusFilter} options={statusOptions} onChange={setStatusFilter} className="status-select" />
            <Button icon={<RefreshCw size={16} />} onClick={() => generations.refetch()}>
              刷新
            </Button>
          </Space>
        </div>
        {generations.isLoading ? (
          <div className="image-generation-loading">
            <Spin />
          </div>
        ) : generations.data?.items.length ? (
          <div className="image-gallery-grid">
            {generations.data.items.map((item) => (
              <ImageGalleryCard
                key={item.id}
                item={item}
                showUser={isAdmin}
                showErrorDetails={isAdmin}
                retrying={retryMutation.isPending && retryMutation.variables === item.id}
                onRetry={(record) => retryMutation.mutate(record.id)}
              />
            ))}
          </div>
        ) : (
          <Empty description="暂无图片记录" />
        )}
      </section>
    </main>
  );
}

function LatestImagePreview({ record, loading }: { record: ImageGenerationItem | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="image-generation-preview pending">
        <Spin />
        <Typography.Text>图片生成可能需要几十秒到数分钟，请稍等。</Typography.Text>
      </div>
    );
  }
  if (!record) {
    return (
      <div className="image-generation-preview empty">
        <ImagePlus size={42} />
        <Typography.Text type="secondary">生成完成后会在这里预览最新图片。</Typography.Text>
      </div>
    );
  }
  return (
    <div className="image-generation-preview">
      <ImageGalleryCard item={record} compact />
    </div>
  );
}

function ImageGalleryCard({
  item,
  showUser = false,
  compact = false,
  showErrorDetails = false,
  retrying = false,
  onRetry
}: {
  item: ImageGenerationItem;
  showUser?: boolean;
  compact?: boolean;
  showErrorDetails?: boolean;
  retrying?: boolean;
  onRetry?: (item: ImageGenerationItem) => void;
}) {
  const mediaRef = useRef<HTMLDivElement | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [shouldLoadImage, setShouldLoadImage] = useState(compact);
  const [isImagePreviewOpen, setIsImagePreviewOpen] = useState(false);
  const [errorLogs, setErrorLogs] = useState<ImageGenerationErrorLog[]>([]);
  const [isErrorModalOpen, setIsErrorModalOpen] = useState(false);
  const [isLoadingErrorLogs, setIsLoadingErrorLogs] = useState(false);

  useEffect(() => {
    if (compact || item.status !== 'READY' || !item.image_url) {
      setShouldLoadImage(compact);
      return;
    }
    const mediaElement = mediaRef.current;
    if (!mediaElement) {
      return;
    }
    if (!('IntersectionObserver' in window)) {
      setShouldLoadImage(true);
      return;
    }
    // 历史图库可能同时有几十张高清图；只在卡片接近视口时拉取 Blob，
    // 避免用户刚进入页面就并发下载所有原图导致首屏迟迟不出图。
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShouldLoadImage(true);
          observer.disconnect();
        }
      },
      { rootMargin: '240px' }
    );
    observer.observe(mediaElement);
    return () => observer.disconnect();
  }, [compact, item.image_url, item.status]);

  useEffect(() => {
    let isMounted = true;
    if (!item.image_url || !shouldLoadImage) {
      setImageUrl(null);
      return;
    }
    fetchProtectedImageBlobUrl(item.image_url)
      .then((url) => {
        if (isMounted) {
          setImageUrl(url);
        } else {
          URL.revokeObjectURL(url);
        }
      })
      .catch(() => setImageUrl(null));
    return () => {
      isMounted = false;
    };
  }, [item.image_url, shouldLoadImage]);

  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [imageUrl]);

  const download = async () => {
    if (!item.image_url) {
      return;
    }
    const blobUrl = await fetchProtectedImageBlobUrl(item.image_url);
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = `ai-image-${item.id}.png`;
    link.click();
    URL.revokeObjectURL(blobUrl);
  };

  const openErrorLogs = async () => {
    setIsErrorModalOpen(true);
    setIsLoadingErrorLogs(true);
    try {
      setErrorLogs(await fetchImageGenerationErrorLogs(item.id));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '错误详情读取失败');
      setErrorLogs([]);
    } finally {
      setIsLoadingErrorLogs(false);
    }
  };

  const openImagePreview = () => {
    if (item.status === 'READY' && imageUrl) {
      setIsImagePreviewOpen(true);
    }
  };

  return (
    <Card className={`image-gallery-card${compact ? ' compact' : ''}`} bodyStyle={{ padding: 0 }}>
      <div
        ref={mediaRef}
        className={`image-gallery-media${item.status === 'READY' ? ' clickable' : ''}`}
        onClick={openImagePreview}
      >
        {item.status === 'READY' && imageUrl ? (
          <img src={imageUrl} alt={item.prompt} />
        ) : item.status === 'READY' ? (
          <Spin />
        ) : item.status === 'FAILED' ? (
          <div className="image-gallery-failed">生成失败</div>
        ) : (
          <Spin />
        )}
      </div>
      <div className="image-gallery-body">
        <Space size={[6, 6]} wrap>
          <Tag color={item.status === 'READY' ? 'green' : item.status === 'FAILED' ? 'red' : 'blue'}>
            {formatStatus(item.status)}
          </Tag>
          <Tag>{item.size}</Tag>
          {item.generation_mode === 'IMAGE_REFERENCE' ? <Tag color="cyan">参考图</Tag> : null}
        </Space>
        <Typography.Paragraph ellipsis={{ rows: 2 }} className="image-gallery-prompt">
          {item.prompt}
        </Typography.Paragraph>
        {item.error_message ? (
          <Typography.Text type="danger" className="image-gallery-error">
            {item.error_message}
          </Typography.Text>
        ) : null}
        <div className="image-gallery-meta">
          {showUser ? <span>{item.display_name || item.username || item.user_id}</span> : null}
          <span>{formatEast8DateTime(item.created_at, { naiveAsEast8: true })}</span>
        </div>
        {item.status === 'READY' ? (
          <Button size="small" icon={<Download size={14} />} onClick={download}>
            下载
          </Button>
        ) : null}
        {item.status === 'FAILED' && onRetry ? (
          <Button
            size="small"
            icon={<RefreshCw size={14} />}
            loading={retrying}
            onClick={() => onRetry(item)}
          >
            重试
          </Button>
        ) : null}
        {showErrorDetails && item.status === 'FAILED' ? (
          <Button size="small" onClick={openErrorLogs}>
            错误详情
          </Button>
        ) : null}
      </div>
      <Modal
        title={`图片 #${item.id}`}
        open={isImagePreviewOpen}
        onCancel={() => setIsImagePreviewOpen(false)}
        footer={
          item.status === 'READY' ? (
            <Button icon={<Download size={14} />} onClick={download}>
              下载
            </Button>
          ) : null
        }
        width="min(96vw, 1200px)"
        centered
      >
        {imageUrl ? (
          <div className="image-preview-modal-body">
            <img src={imageUrl} alt={item.prompt} />
          </div>
        ) : (
          <div className="image-generation-loading">
            <Spin />
          </div>
        )}
      </Modal>
      <Modal
        title={`图片 #${item.id} 错误详情`}
        open={isErrorModalOpen}
        onCancel={() => setIsErrorModalOpen(false)}
        footer={null}
        width={760}
      >
        {isLoadingErrorLogs ? (
          <div className="image-generation-loading">
            <Spin />
          </div>
        ) : errorLogs.length ? (
          <Space direction="vertical" size={12} className="image-error-log-list">
            {errorLogs.map((log) => (
              <div key={log.id} className="image-error-log-item">
                <Space size={[6, 6]} wrap>
                  <Tag>{log.phase}</Tag>
                  <Tag>{log.error_type}</Tag>
                  {log.status_code ? <Tag color="orange">HTTP {log.status_code}</Tag> : null}
                  {log.retry_count ? <Tag color="blue">重试 {log.retry_count} 次</Tag> : null}
                </Space>
                <Typography.Text type="secondary">
                  {formatEast8DateTime(log.created_at, { naiveAsEast8: true })}
                </Typography.Text>
                <Typography.Paragraph className="image-error-log-detail">
                  {log.detail_message}
                </Typography.Paragraph>
              </div>
            ))}
          </Space>
        ) : (
          <Empty description="暂无错误详情" />
        )}
      </Modal>
    </Card>
  );
}

function formatStatus(status: string) {
  const statusMap: Record<string, string> = {
    READY: '已完成',
    FAILED: '失败',
    GENERATING: '生成中'
  };
  return statusMap[status] || status;
}

export default ImageGenerationPage;
