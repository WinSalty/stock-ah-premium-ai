import { API_BASE_URL, ApiError, requestJson } from './client';
import type {
  ChatMessageRequest,
  ChatMessageResponse,
  ChatSession,
  ChatSessionDetail
} from '../types/domain';

export function createChatSession(title = '新的数据问答') {
  return requestJson<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ title })
  });
}

export function listChatSessions() {
  return requestJson<ChatSession[]>('/api/chat/sessions');
}

export function getChatSession(sessionId: number) {
  return requestJson<ChatSessionDetail>(`/api/chat/sessions/${sessionId}`);
}

export function deleteChatSession(sessionId: number) {
  return fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    method: 'DELETE'
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(response.status, body.detail || response.statusText);
    }
  });
}

export function sendChatMessage(sessionId: number, payload: ChatMessageRequest) {
  return requestJson<ChatMessageResponse>(`/api/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

interface ChatStreamEvent {
  type: 'meta' | 'delta' | 'done' | 'error';
  content?: string;
  answer?: string;
  rows?: Record<string, unknown>[];
}

interface ChatStreamHandlers {
  onMeta?: (event: ChatStreamEvent) => void;
  onDelta?: (content: string) => void;
  onDone?: (event: ChatStreamEvent) => void;
  onError?: (event: ChatStreamEvent) => void;
}

/**
 * 流式提交聊天消息。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
export async function sendChatMessageStream(
  sessionId: number,
  payload: ChatMessageRequest,
  handlers: ChatStreamHandlers
) {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || response.statusText);
  }
  if (!response.body) {
    throw new ApiError(response.status, '浏览器不支持流式响应');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const event = JSON.parse(line) as ChatStreamEvent;
      if (event.type === 'meta') {
        handlers.onMeta?.(event);
      } else if (event.type === 'delta' && event.content) {
        handlers.onDelta?.(event.content);
      } else if (event.type === 'done') {
        handlers.onDone?.(event);
      } else if (event.type === 'error') {
        handlers.onError?.(event);
      }
    }
  }
}
