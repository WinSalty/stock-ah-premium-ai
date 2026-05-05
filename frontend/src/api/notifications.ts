import { requestJson } from './client';
import type {
  AlertEvent,
  PushplusBindRequest,
  PushplusBinding,
  PushplusFriend,
  PushplusQrCodeRequest,
  PushplusQrCodeResponse,
  TestPushRequest,
  TestPushResponse
} from '../types/domain';

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
