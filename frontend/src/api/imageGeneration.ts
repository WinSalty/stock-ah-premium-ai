import { API_BASE_URL, ApiError, getAuthToken, requestJson } from './client';
import type {
  ImageGenerationAdminQuota,
  ImageGenerationErrorLog,
  ImageGenerationItem,
  ImageGenerationListResponse,
  ImageGenerationQuota
} from '../types/domain';

export const IMAGE_GENERATION_SIZE_OPTIONS = [
  { label: '1K 方图 1024x1024', value: '1024x1024' },
  { label: '2K 方图 2048x2048', value: '2048x2048' },
  { label: '2K 横图 1536x1024', value: '1536x1024' },
  { label: '2K 竖图 1024x1536', value: '1024x1536' },
  { label: '4K 横图 3840x2160', value: '3840x2160' },
  { label: '4K 竖图 2160x3840', value: '2160x3840' }
];

export interface ImageGenerationCreatePayload {
  prompt: string;
  size: string;
  referenceImage?: File | null;
}

export interface ImageGenerationListParams {
  page?: number;
  page_size?: number;
  status?: string;
  user_id?: number;
  keyword?: string;
}

export function fetchImageGenerations(params: ImageGenerationListParams = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<ImageGenerationListResponse>(`/api/image-generation/generations?${search.toString()}`);
}

export function fetchMyImageGenerationQuota() {
  return requestJson<ImageGenerationQuota>('/api/image-generation/quota/me');
}

/**
 * 创建图片生成任务。
 * 创建日期：2026-05-27
 * author: sunshengxian
 */
export async function createImageGeneration(payload: ImageGenerationCreatePayload) {
  const token = getAuthToken();
  const formData = new FormData();
  formData.set('prompt', payload.prompt);
  formData.set('size', payload.size);
  if (payload.referenceImage) {
    formData.set('reference_image', payload.referenceImage);
  }
  const response = await fetch(`${API_BASE_URL}/api/image-generation/generations`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: formData
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || response.statusText);
  }
  return response.json() as Promise<ImageGenerationItem>;
}

export function fetchImageGenerationQuotas() {
  return requestJson<ImageGenerationAdminQuota[]>('/api/image-generation/admin/quotas');
}

export function updateImageGenerationQuota(userId: number, dailyLimit: number) {
  return requestJson<ImageGenerationAdminQuota>(`/api/image-generation/admin/quotas/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ daily_limit: dailyLimit })
  });
}

export function resetImageGenerationQuota(userId: number) {
  return requestJson<ImageGenerationAdminQuota>(`/api/image-generation/admin/quotas/${userId}/reset`, {
    method: 'POST'
  });
}

export function fetchImageGenerationErrorLogs(generationId: number) {
  return requestJson<ImageGenerationErrorLog[]>(
    `/api/image-generation/generations/${generationId}/error-logs`
  );
}

/**
 * 带鉴权读取图片 Blob，避免把图片文件接口暴露成公开静态资源。
 * 创建日期：2026-05-27
 * author: sunshengxian
 */
export async function fetchProtectedImageBlobUrl(path: string) {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  });
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText);
  }
  return URL.createObjectURL(await response.blob());
}
