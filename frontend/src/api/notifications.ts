import { requestJson } from './client';
import type {
  AlertEvent,
  AdminPushplusBindRequest,
  PushplusBindRequest,
  PushplusBinding,
  PushplusFriend,
  PushplusMessageLog,
  PushplusQrCodeRequest,
  PushplusQrCodeResponse,
  TestPushRequest,
  TestPushResponse
} from '../types/domain';

export interface PushplusMessageFilters {
  keyword?: string;
  status?: string;
  user_id?: number;
  limit?: number;
}

export function fetchPushplusBinding() {
  return requestJson<PushplusBinding>('/api/notifications/pushplus/binding');
}

export function createPushplusQrCode(payload: PushplusQrCodeRequest) {
  return requestJson<PushplusQrCodeResponse>('/api/notifications/pushplus/qrcode', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function fetchPushplusFriends() {
  return requestJson<PushplusFriend[]>('/api/notifications/pushplus/friends');
}

export function fetchAdminPushplusBindings() {
  return requestJson<PushplusBinding[]>('/api/notifications/admin/pushplus/bindings');
}

export function fetchAdminPushplusMessages(filters: PushplusMessageFilters = {}) {
  const params = new URLSearchParams();
  if (filters.keyword) {
    params.set('keyword', filters.keyword);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }
  if (filters.user_id) {
    params.set('user_id', String(filters.user_id));
  }
  if (filters.limit) {
    params.set('limit', String(filters.limit));
  }
  const query = params.toString();
  return requestJson<PushplusMessageLog[]>(`/api/notifications/admin/pushplus/messages${query ? `?${query}` : ''}`);
}

export function adminBindPushplusFriend(payload: AdminPushplusBindRequest) {
  return requestJson<PushplusBinding>('/api/notifications/admin/pushplus/bindings', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function bindPushplusFriend(payload: PushplusBindRequest) {
  return requestJson<PushplusBinding>('/api/notifications/pushplus/bind', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function unbindPushplusFriend() {
  return requestJson<{ ok: boolean }>('/api/notifications/pushplus/binding', {
    method: 'DELETE'
  });
}

export function sendTestPush(payload: TestPushRequest) {
  return requestJson<TestPushResponse>('/api/notifications/test-push', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function fetchAlertEvents() {
  return requestJson<AlertEvent[]>('/api/notifications/events');
}
