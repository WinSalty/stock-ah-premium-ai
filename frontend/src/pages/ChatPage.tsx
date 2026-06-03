import { Button, Checkbox, Drawer, Form, Input, Popconfirm, Segmented, Skeleton, message } from 'antd';
import { Download, FileText, MessageCircleMore, Plus, Send, SendHorizontal, Trash2 } from 'lucide-react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useEffect, useRef, useState } from 'react';
import PageHeader from '../components/PageHeader';
import LlmProgressNote from '../components/LlmProgressNote';
import {
  batchDeleteChatSessions,
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessageStream
} from '../api/chat';
import type {
  ChatMessageResponse,
  ChatModel,
  ChatSession,
  ChatStoredMessage,
  UserInfo
} from '../types/domain';
import { formatEast8DateTime } from '../utils/datetime';
import { exportChatAnswersToWord } from '../utils/chatWordExport';
import { CHAT_PROGRESS_STEPS } from '../constants/llmProgress';
import { publishXueqiuChatAnswer } from '../api/xueqiuPublish';

interface ChatFormValues {
  question: string;
}

interface ChatTurn {
  id: string;
  messageId?: number | null;
  question: string;
  response?: ChatMessageResponse;
  streaming?: boolean;
  progressText?: string;
}

interface ChatPageProps {
  currentUser: UserInfo;
}

const LAST_SESSION_KEY = 'stock-ah-premium-ai:last-chat-session';

const markdownComponents: Components = {
  table({ children }) {
    return (
      <div className="markdown-table-wrap">
        <table>{children}</table>
      </div>
    );
  }
};

const PRESET_QUESTION_COUNT = 4;
const CHAT_AUTO_SCROLL_THRESHOLD = 96;
const DEFAULT_CHAT_MODEL: ChatModel = 'deepseek-v4-flash';
const CHAT_MODEL_OPTIONS: { label: string; value: ChatModel }[] = [
  { label: 'DeepSeek Flash', value: 'deepseek-v4-flash' },
  { label: 'DeepSeek Pro', value: 'deepseek-v4-pro' },
  { label: 'Qwen 3.6 Flash', value: 'qwen3.6-flash' }
];

const STRUCTURED_ANALYSIS_PRESET_QUESTIONS = [
  '我该买什么股票？',
  '我可以投资哪些股票？',
  '长期持有保守型，帮我推荐不超过 10 只适合价值投资的股票',
  '风险高收益型，帮我从最新打板报告里挑几只晋级观察标的',
  '近十年平均年化大于 10%、ROE 大于 2%、PE 小于 7 的股票有哪些？',
  '招商银行分红再投年度明细是什么样？',
  '分红再投筛选里，哪些股票更适合长期持有？',
  '按分红稳定性、ROE 和低估值帮我筛一批红利复利候选',
  '帮我分析一下招商银行，重点看估值、财务质量、分红和 A/H 价差',
  '帮我分析一下金螳螂，重点看主营业务、现金流和股东质押风险',
  '帮我分析一下中国神华，重点看红利稳定性、现金流和估值安全边际',
  '帮我分析一下格力电器，重点看主营结构、分红能力和长期竞争力',
  '帮我分析一下宁德时代，重点看增长质量、毛利率和资金流是否配合',
  '帮我分析一下比亚迪，重点看利润质量、竞争压力和估值反证条件',
  '帮我分析一下长江电力，重点看现金流、防御属性和分红可持续性',
  '帮我分析一下寒武纪，重点看收入兑现、股东结构和估值风险',
  '招商银行和平安银行谁的财务质量更稳？请给出关键指标和反证条件',
  '我关注的股票里，哪些 A/H 价差更像择边机会而不是套利机会？',
  '当前适合用高股息策略还是成长股策略？请结合估值和现金流给框架',
  '请找出一只股票做完整个股分析报告，覆盖财务、主营、股东和资金流',
  '近几年财务数据里，哪些指标最能说明一家公司的利润质量？',
  '如果一家公司短期资金流入但扣非和现金流不好，应该怎么判断？',
  '股东户数下降、质押比例上升同时出现时，对个股分析意味着什么？',
  '主营业务收入集中度过高时，估值应该打折还是看行业壁垒？',
  'A/H 溢价达到目标阈值后，执行换仓前最应该复核哪些条件？',
  '请给我一个保守型股票组合的筛选框架，重点控制回撤和现金流风险',
  '财报问数模式下，给我展示招商银行最近 24 期财务摘要数据',
  '招商银行十年平均年化收益率是多少？',
  '帮我生成一份股票复盘清单，用于每周跟踪持仓的估值、资金流和反证条件'
];

function randomPresetQuestions(previous: string[] = []) {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const nextQuestions = [...STRUCTURED_ANALYSIS_PRESET_QUESTIONS]
      .sort(() => Math.random() - 0.5)
      .slice(0, PRESET_QUESTION_COUNT);
    if (nextQuestions.some((item, index) => item !== previous[index])) {
      return nextQuestions;
    }
  }
  return [...STRUCTURED_ANALYSIS_PRESET_QUESTIONS].slice(0, PRESET_QUESTION_COUNT);
}

/**
 * 智能问答页面。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
function ChatPage({ currentUser }: ChatPageProps) {
  const [form] = Form.useForm<ChatFormValues>();
  const historyRef = useRef<HTMLElement | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const autoScrollFrameRef = useRef<number | null>(null);
  const isProgrammaticScrollRef = useRef(false);
  const lastTurnCountRef = useRef(0);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [presetQuestions, setPresetQuestions] = useState(randomPresetQuestions);
  const [isSending, setIsSending] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ChatModel>(DEFAULT_CHAT_MODEL);
  const [selectedSessionIds, setSelectedSessionIds] = useState<number[]>([]);
  const [publishingTurnId, setPublishingTurnId] = useState<string | null>(null);
  const [isMobileSessionOpen, setIsMobileSessionOpen] = useState(false);
  const canPublishChatAnswerToXueqiu = currentUser.permissions.includes('chat_xueqiu_publish');

  useEffect(() => {
    void loadInitialSessions();
  }, []);

  useEffect(() => {
    const history = historyRef.current;
    if (!history) {
      return;
    }
    const hasNewTurn = turns.length > lastTurnCountRef.current;
    lastTurnCountRef.current = turns.length;
    if (!hasNewTurn && !isLoadingHistory && !shouldAutoScrollRef.current) {
      return;
    }
    scheduleHistoryAutoScroll(history);
  }, [turns, isLoadingHistory]);

  useEffect(() => {
    return () => {
      if (autoScrollFrameRef.current !== null) {
        window.cancelAnimationFrame(autoScrollFrameRef.current);
      }
    };
  }, []);

  /**
   * 合并流式分片触发的滚动请求，避免程序滚动被 onScroll 误判为用户手动滚动。
   * 创建日期：2026-05-07
   * author: sunshengxian
   */
  const scheduleHistoryAutoScroll = (history: HTMLElement) => {
    if (autoScrollFrameRef.current !== null) {
      return;
    }
    autoScrollFrameRef.current = window.requestAnimationFrame(() => {
      autoScrollFrameRef.current = null;
      isProgrammaticScrollRef.current = true;
      history.scrollTop = history.scrollHeight;
      shouldAutoScrollRef.current = true;
      window.setTimeout(() => {
        isProgrammaticScrollRef.current = false;
      }, 80);
    });
  };

  const onHistoryScroll = () => {
    if (isProgrammaticScrollRef.current) {
      return;
    }
    const history = historyRef.current;
    if (!history) {
      return;
    }
    const distanceToBottom = history.scrollHeight - history.scrollTop - history.clientHeight;
    shouldAutoScrollRef.current = distanceToBottom <= CHAT_AUTO_SCROLL_THRESHOLD;
  };

  const loadInitialSessions = async () => {
    setIsLoadingSessions(true);
    try {
      const items = await listChatSessions();
      setSessions(items);
      // 进入问答页默认停留在新会话草稿，只加载历史列表，不自动恢复旧会话；
      // 用户主动点开历史会话时才读取消息，避免页面一进来就把上次问题接着聊。
      setSession(null);
      setTurns([]);
      setSelectedSessionIds([]);
      setPresetQuestions((questions) => randomPresetQuestions(questions));
      form.resetFields();
      window.localStorage.removeItem(LAST_SESSION_KEY);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '会话加载失败');
    } finally {
      setIsLoadingSessions(false);
    }
  };

  const refreshSessions = async (activeSessionId?: number) => {
    const items = await listChatSessions();
    setSessions(items);
    setSelectedSessionIds((ids) => ids.filter((id) => items.some((item) => item.id === id)));
    if (activeSessionId) {
      const activeSession = items.find((item) => item.id === activeSessionId);
      if (activeSession) {
        setSession(activeSession);
      }
    }
  };

  const openSession = async (sessionId: number, showLoading = true) => {
    if (isSending) {
      return;
    }
    if (showLoading) {
      setIsLoadingHistory(true);
    }
    try {
      const detail = await getChatSession(sessionId);
      shouldAutoScrollRef.current = true;
      setSession(detail);
      setTurns(buildTurns(detail.messages));
      window.localStorage.setItem(LAST_SESSION_KEY, String(detail.id));
      setIsMobileSessionOpen(false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '会话加载失败');
    } finally {
      if (showLoading) {
        setIsLoadingHistory(false);
      }
    }
  };

  const handleNewSession = async () => {
    if (isSending) {
      return;
    }
    try {
      const created = await createChatSession();
      shouldAutoScrollRef.current = true;
      setSession(created);
      setTurns([]);
      setSessions((items) => [created, ...items]);
      setSelectedSessionIds([]);
      window.localStorage.setItem(LAST_SESSION_KEY, String(created.id));
      setPresetQuestions((items) => randomPresetQuestions(items));
      form.resetFields();
      setIsMobileSessionOpen(false);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '新建会话失败');
    }
  };

  const handleDeleteSession = async (sessionId: number) => {
    if (isSending) {
      return;
    }
    try {
      await deleteChatSession(sessionId);
      message.success('会话已删除');
      const items = await listChatSessions();
      setSessions(items);
      setSelectedSessionIds((ids) => ids.filter((id) => id !== sessionId));
      if (session?.id === sessionId) {
        const nextSession = items[0];
        if (nextSession) {
          await openSession(nextSession.id, false);
        } else {
          setSession(null);
          setTurns([]);
          setPresetQuestions((items) => randomPresetQuestions(items));
          window.localStorage.removeItem(LAST_SESSION_KEY);
        }
      } else if (Number(window.localStorage.getItem(LAST_SESSION_KEY)) === sessionId) {
        window.localStorage.removeItem(LAST_SESSION_KEY);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除会话失败');
    }
  };

  const toggleSessionSelection = (sessionId: number, checked: boolean) => {
    setSelectedSessionIds((ids) =>
      checked ? Array.from(new Set([...ids, sessionId])) : ids.filter((id) => id !== sessionId)
    );
  };

  const handleSelectAllSessions = () => {
    setSelectedSessionIds(sessions.map((item) => item.id));
  };

  const handleClearSessionSelection = () => {
    setSelectedSessionIds([]);
  };

  const handleBatchDeleteSessions = async () => {
    if (isSending || selectedSessionIds.length === 0) {
      return;
    }
    try {
      const ids = [...selectedSessionIds];
      const response = await batchDeleteChatSessions(ids);
      message.success(`已删除 ${response.deleted_count} 个会话`);
      const items = await listChatSessions();
      setSessions(items);
      setSelectedSessionIds([]);
      if (session && ids.includes(session.id)) {
        const nextSession = items[0];
        if (nextSession) {
          await openSession(nextSession.id, false);
        } else {
          setSession(null);
          setTurns([]);
          setPresetQuestions((items) => randomPresetQuestions(items));
          window.localStorage.removeItem(LAST_SESSION_KEY);
        }
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量删除会话失败');
    }
  };

  const updateTurn = (id: string, patch: Partial<ChatTurn>) => {
    setTurns((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const updateTurnResponse = (id: string, patch: Partial<ChatMessageResponse>) => {
    setTurns((items) =>
      items.map((item) =>
        item.id === id
          ? {
              ...item,
              response: {
                answer: item.response?.answer || '',
                rows: item.response?.rows || [],
                ...patch
              }
            }
          : item
      )
    );
  };

  const submitQuestion = async (rawQuestion: string) => {
    if (isSending) {
      return;
    }
    const question = rawQuestion.trim();
    if (!question) {
      return;
    }
    const turnId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    let progressIndex = 0;
    let progressTimer: number | null = null;
    shouldAutoScrollRef.current = true;
    setIsSending(true);
    form.setFieldValue('question', '');
    setTurns((items) => [
      ...items,
      {
        id: turnId,
        question,
        response: { answer: '', rows: [] },
        streaming: true,
        progressText: CHAT_PROGRESS_STEPS[0]
      }
    ]);
    try {
      progressTimer = window.setInterval(() => {
        progressIndex = Math.min(progressIndex + 1, CHAT_PROGRESS_STEPS.length - 1);
        updateTurn(turnId, { progressText: CHAT_PROGRESS_STEPS[progressIndex] });
      }, 2600);
      const currentSession = session || (await createChatSession());
      if (!session) {
        setSession(currentSession);
        window.localStorage.setItem(LAST_SESSION_KEY, String(currentSession.id));
      }
      await sendChatMessageStream(
        currentSession.id,
        { question, llm_model: selectedModel },
        {
          onMeta: (event) => {
            updateTurn(turnId, { progressText: '正在生成分析...' });
            updateTurnResponse(turnId, { rows: event.rows || [] });
          },
          onDelta: (content) =>
            setTurns((items) =>
              items.map((item) =>
                item.id === turnId && item.response
                  ? {
                      ...item,
                      progressText: '',
                      response: { ...item.response, answer: `${item.response.answer}${content}` }
                    }
                  : item
              )
            ),
          onDone: (event) => {
            updateTurn(turnId, { streaming: false, progressText: '', messageId: event.message_id });
            updateTurnResponse(turnId, {
              message_id: event.message_id,
              answer: event.answer || '',
              rows: event.rows || []
            });
            void refreshSessions(currentSession.id);
          },
          onError: (event) => {
            updateTurn(turnId, { streaming: false, progressText: '', messageId: event.message_id });
            updateTurnResponse(turnId, {
              message_id: event.message_id,
              answer: event.answer || '问答失败，请稍后再试。',
              rows: event.rows || []
            });
            void refreshSessions(currentSession.id);
            message.error(event.answer || '问答失败');
          }
        }
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '问答失败';
      updateTurn(turnId, { streaming: false, progressText: '' });
      updateTurnResponse(turnId, { answer: errorMessage });
      message.error(errorMessage);
    } finally {
      if (progressTimer !== null) {
        window.clearInterval(progressTimer);
      }
      setIsSending(false);
    }
  };

  const handleSubmit = async (values: ChatFormValues) => {
    await submitQuestion(values.question);
  };

  const exportTurns = async (targetTurns: ChatTurn[], title: string) => {
    const answeredTurns = targetTurns.filter((turn) => turn.response?.answer?.trim());
    if (!answeredTurns.length) {
      message.warning('当前没有可导出的回答内容');
      return;
    }
    await exportChatAnswersToWord(
      title,
      answeredTurns.map((turn) => ({
        question: turn.question,
        answer: turn.response?.answer || ''
      }))
    );
    message.success('Word 文档已下载');
  };

  const publishTurnToXueqiu = async (turn: ChatTurn) => {
    const messageId = turn.messageId || turn.response?.message_id;
    if (!messageId) {
      message.warning('这条回答还没有落库，请等生成完成后再发布');
      return;
    }
    setPublishingTurnId(turn.id);
    try {
      const response = await publishXueqiuChatAnswer({
        message_id: messageId,
        publish: false,
        force: false
      });
      message.success(response.draft_id ? '雪球草稿已保存' : response.message);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存雪球草稿失败');
    } finally {
      setPublishingTurnId(null);
    }
  };

  /**
   * 复用会话管理面板，桌面端渲染为左侧栏，移动端渲染到抽屉中，避免两套删除和批量选择逻辑分叉。
   * 创建日期：2026-05-18
   * author: sunshengxian
   */
  const renderSessionPanel = () => (
    <>
      <div className="chat-sidebar-head">
        <span>会话</span>
        <Button
          type="text"
          size="small"
          aria-label="新建会话"
          title="新建会话"
          icon={<Plus size={16} />}
          onClick={handleNewSession}
          disabled={isSending}
        />
      </div>
      {sessions.length ? (
        <div className="chat-session-bulkbar">
          <span>{selectedSessionIds.length ? `已选 ${selectedSessionIds.length}` : '批量管理'}</span>
          <div>
            <Button type="link" size="small" onClick={handleSelectAllSessions} disabled={isSending}>
              全选
            </Button>
            <Button
              type="link"
              size="small"
              onClick={handleClearSessionSelection}
              disabled={isSending || selectedSessionIds.length === 0}
            >
              清空
            </Button>
            <Popconfirm
              title="批量删除会话"
              description={`确认删除选中的 ${selectedSessionIds.length} 个会话？`}
              okText="删除"
              cancelText="取消"
              onConfirm={() => void handleBatchDeleteSessions()}
              disabled={isSending || selectedSessionIds.length === 0}
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<Trash2 size={14} />}
                disabled={isSending || selectedSessionIds.length === 0}
              />
            </Popconfirm>
          </div>
        </div>
      ) : null}
      <div className="chat-session-list">
        {isLoadingSessions ? <Skeleton active paragraph={{ rows: 5 }} /> : null}
        {!isLoadingSessions && sessions.length === 0 ? (
          <div className="chat-session-empty">暂无会话</div>
        ) : null}
        {sessions.map((item) => (
          <div
            key={item.id}
            className={`chat-session-item${session?.id === item.id ? ' active' : ''}`}
          >
            <Checkbox
              checked={selectedSessionIds.includes(item.id)}
              onChange={(event) => toggleSessionSelection(item.id, event.target.checked)}
              disabled={isSending}
              aria-label={`选择会话 ${item.title}`}
            />
            <button
              type="button"
              className="chat-session-open"
              onClick={() => void openSession(item.id)}
              disabled={isSending}
            >
              <strong>{item.title}</strong>
              <span>{formatEast8DateTime(item.updated_at, { naiveAsEast8: true })}</span>
            </button>
            <Popconfirm
              title="删除会话"
              description="删除后将不再显示该会话"
              okText="删除"
              cancelText="取消"
              onConfirm={() => void handleDeleteSession(item.id)}
              disabled={isSending}
            >
              <Button
                type="text"
                size="small"
                danger
                aria-label="删除会话"
                title="删除会话"
                icon={<Trash2 size={15} />}
                disabled={isSending}
              />
            </Popconfirm>
          </div>
        ))}
      </div>
    </>
  );

  return (
    <main className="page chat-page">
      <PageHeader title="智能问答" />
      <div className="chat-workspace">
        <div className="chat-mobile-topbar">
          <Button
            icon={<MessageCircleMore size={16} />}
            onClick={() => setIsMobileSessionOpen(true)}
            disabled={isSending && isLoadingSessions}
          >
            会话
          </Button>
          <span>{session ? session.title : '新会话'}</span>
          <Button
            type="primary"
            aria-label="新建会话"
            title="新建会话"
            icon={<Plus size={16} />}
            onClick={handleNewSession}
            disabled={isSending}
          />
        </div>
        <aside className="chat-sidebar">{renderSessionPanel()}</aside>
        <Drawer
          title={null}
          placement="left"
          width="88vw"
          open={isMobileSessionOpen}
          onClose={() => setIsMobileSessionOpen(false)}
          className="chat-mobile-session-drawer"
        >
          <div className="chat-mobile-session-panel">{renderSessionPanel()}</div>
        </Drawer>

        <div className="chat-main">
          <div className="chat-main-toolbar">
            <span>{session ? session.title : '未选择会话'}</span>
            <Button
              size="small"
              icon={<FileText size={15} />}
              onClick={() => void exportTurns(turns, session?.title || '智能问答回答')}
              disabled={!turns.some((turn) => turn.response?.answer?.trim())}
            >
              导出当前会话
            </Button>
          </div>
          <section className="chat-history" ref={historyRef} onScroll={onHistoryScroll}>
            {isLoadingHistory ? <Skeleton active paragraph={{ rows: 6 }} /> : null}
            {!isLoadingHistory && turns.length === 0 && !isSending ? (
              <div className="chat-empty-state">
                <div className="question-bank">
                  {presetQuestions.map((item) => (
                    <Button key={item} onClick={() => void submitQuestion(item)} disabled={isSending}>
                      {item}
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}
            {!isLoadingHistory
              ? turns.map((turn) => (
                  <div className="chat-turn" key={turn.id}>
                    <div className="chat-question">{turn.question}</div>
                    <div className="chat-answer">
                      <div className="chat-answer-actions">
                        {canPublishChatAnswerToXueqiu ? (
                          <Popconfirm
                            title="保存雪球草稿"
                            description="将这条回答转换为 HTML 长文并保存到雪球草稿？"
                            okText="保存"
                            cancelText="取消"
                            onConfirm={() => void publishTurnToXueqiu(turn)}
                            disabled={
                              Boolean(turn.streaming) ||
                              !turn.response?.answer?.trim() ||
                              !(turn.messageId || turn.response?.message_id)
                            }
                          >
                            <Button
                              type="text"
                              size="small"
                              icon={<Send size={14} />}
                              loading={publishingTurnId === turn.id}
                              disabled={
                                Boolean(turn.streaming) ||
                                !turn.response?.answer?.trim() ||
                                !(turn.messageId || turn.response?.message_id)
                              }
                            >
                              发布雪球
                            </Button>
                          </Popconfirm>
                        ) : null}
                        <Button
                          type="text"
                          size="small"
                          icon={<Download size={14} />}
                          onClick={() =>
                            void exportTurns([turn], `${session?.title || '智能问答'}-${turn.question}`)
                          }
                          disabled={!turn.response?.answer?.trim()}
                        >
                          导出
                        </Button>
                      </div>
                      <div className="markdown-answer">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={markdownComponents}
                        >
                          {turn.response?.answer || ''}
                        </ReactMarkdown>
                        {turn.streaming && !turn.response?.answer ? (
                          <LlmProgressNote text={turn.progressText} />
                        ) : null}
                        {turn.streaming && turn.response?.answer ? <span className="stream-caret" /> : null}
                      </div>
                    </div>
                  </div>
                ))
              : null}
            {isSending && turns.length === 0 ? <Skeleton active paragraph={{ rows: 4 }} /> : null}
            <div className="chat-history-end" />
          </section>

          <section className="chat-composer">
            <Form form={form} layout="vertical" onFinish={handleSubmit}>
              <Form.Item name="question" rules={[{ required: true, message: '请输入问题' }]}>
                <Input.TextArea
                  rows={3}
                  placeholder="输入投资相关问题"
                  onPressEnter={(event) => {
                    if (!event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      form.submit();
                    }
                  }}
                />
              </Form.Item>
              <div className="composer-actions">
                <Segmented
                  size="small"
                  options={CHAT_MODEL_OPTIONS}
                  value={selectedModel}
                  onChange={(value) => setSelectedModel(value as ChatModel)}
                  disabled={isSending}
                  aria-label="选择问答模型"
                />
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<SendHorizontal size={16} />}
                  loading={isSending}
                  disabled={isSending}
                >
                  发送
                </Button>
              </div>
            </Form>
          </section>
        </div>
      </div>
    </main>
  );
}

function buildTurns(messages: ChatStoredMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  messages.forEach((item) => {
    if (item.role === 'user') {
      turns.push({
        id: `message-${item.id}`,
        question: item.content,
        response: { answer: '', rows: [] }
      });
      return;
    }
    if (item.role === 'assistant') {
      const target = [...turns].reverse().find((turn) => !turn.response?.answer);
      if (target) {
        target.messageId = item.id;
        target.response = { message_id: item.id, answer: item.content, rows: [] };
      }
    }
  });
  return turns.filter((turn) => turn.question || turn.response?.answer);
}

export default ChatPage;
