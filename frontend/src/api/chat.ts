import { API_BASE_URL, ApiError, getAuthToken, requestJson } from './client';
import type {
  ChartSpec,
  ChatMessageRequest,
  ChatSessionBatchDeleteResponse,
  ChatSession,
  ChatSessionDetail,
  ToolTraceItem
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

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function deleteChatSession(sessionId: number) {
  return fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: authHeaders()
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(response.status, body.detail || response.statusText);
    }
  });
}

export function batchDeleteChatSessions(sessionIds: number[]) {
  return requestJson<ChatSessionBatchDeleteResponse>('/api/chat/sessions/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ session_ids: sessionIds })
  });
}

/** Agent 工具开始执行事件：summary 为面向用户的一句话动作摘要（如"查询：自选股机会"）。 */
export interface ChatToolStartEvent {
  type: 'tool_start';
  tool: string;
  summary: string;
}

/** Agent 工具执行结束事件：summary 为结果摘要（如"返回 30 行"），elapsed_ms 为该步耗时毫秒数。 */
export interface ChatToolResultEvent {
  type: 'tool_result';
  tool: string;
  ok: boolean;
  summary: string;
  elapsed_ms: number;
}

/** 图表登记事件：本阶段前端仅存储 spec 不渲染，阶段 4 接入 ECharts 后按 chart_id 占位渲染。 */
export interface ChatChartEvent {
  type: 'chart';
  chart_id: string;
  spec: ChartSpec;
}

/** 最终回答增量文本事件。 */
export interface ChatDeltaEvent {
  type: 'delta';
  content: string;
}

/** 回答完成事件：answer 为完整回答，charts/tool_trace 为本轮全量汇总（以此为准覆盖流式过程累积值）。 */
export interface ChatDoneEvent {
  type: 'done';
  message_id?: number | null;
  answer: string;
  charts?: ChartSpec[];
  tool_trace?: ToolTraceItem[];
  /** 整轮墙钟耗时毫秒数（提问进入引擎到回答完成，含模型思考与工具执行）。 */
  elapsed_ms?: number | null;
}

/** 回答失败事件：answer 为失败文案（服务端已落库为 assistant 消息）。 */
export interface ChatErrorEvent {
  type: 'error';
  message_id?: number | null;
  answer: string;
}

/**
 * NDJSON 流式事件联合类型（Agent 引擎协议）。
 * 旧协议的 meta 事件与 rows 字段已彻底移除，前端不再兼容。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
export type ChatStreamEvent =
  | ChatToolStartEvent
  | ChatToolResultEvent
  | ChatChartEvent
  | ChatDeltaEvent
  | ChatDoneEvent
  | ChatErrorEvent;

export interface ChatStreamHandlers {
  onToolStart?: (event: ChatToolStartEvent) => void;
  onToolResult?: (event: ChatToolResultEvent) => void;
  onChart?: (event: ChatChartEvent) => void;
  onDelta?: (content: string) => void;
  onDone?: (event: ChatDoneEvent) => void;
  onError?: (event: ChatErrorEvent) => void;
}

/**
 * 流式提交聊天消息（NDJSON，每行一个 JSON 事件）。
 * 边界口径：
 * - 单行 JSON 解析失败时仅 console.warn 后跳过该行，继续读流——网络分片或服务端偶发坏行
 *   不应中断整轮回答（吸收旧评审 B3 的容错要求）；
 * - 收到 error 事件时先回调 onError 让调用方展示已落库的失败文案，流读完后再抛 ApiError，
 *   保证未注册 onError 的调用方（如阈值推荐入口）也能经由异常路径感知失败。
 * 创建日期：2026-05-04
 * 更新日期：2026-06-12（协议对齐 Agent 引擎：tool_start/tool_result/chart 事件，删除 meta/rows）
 * author: sunshengxian
 */
export async function sendChatMessageStream(
  sessionId: number,
  payload: ChatMessageRequest,
  handlers: ChatStreamHandlers
) {
  const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
  let streamError: string | null = null;
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
      let event: ChatStreamEvent;
      try {
        event = JSON.parse(line) as ChatStreamEvent;
      } catch (parseError) {
        // 坏行容错：单行损坏（如代理截断、服务端日志混入）只丢弃该行，不中断整轮流式回答。
        console.warn('跳过无法解析的流式事件行', line, parseError);
        continue;
      }
      if (event.type === 'tool_start') {
        handlers.onToolStart?.(event);
      } else if (event.type === 'tool_result') {
        handlers.onToolResult?.(event);
      } else if (event.type === 'chart') {
        handlers.onChart?.(event);
      } else if (event.type === 'delta') {
        if (event.content) {
          handlers.onDelta?.(event.content);
        }
      } else if (event.type === 'done') {
        handlers.onDone?.(event);
      } else if (event.type === 'error') {
        const errorText = event.answer || '流式响应失败';
        streamError = errorText;
        handlers.onError?.({ ...event, answer: errorText });
      }
    }
  }
  if (streamError) {
    throw new ApiError(response.status, streamError);
  }
}
