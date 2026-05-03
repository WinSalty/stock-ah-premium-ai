import { requestJson } from './client';
import type { ChatMessageRequest, ChatMessageResponse, ChatSession } from '../types/domain';

export function createChatSession(title = '新的数据问答') {
  return requestJson<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ title })
  });
}

export function sendChatMessage(sessionId: number, payload: ChatMessageRequest) {
  return requestJson<ChatMessageResponse>(`/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}
