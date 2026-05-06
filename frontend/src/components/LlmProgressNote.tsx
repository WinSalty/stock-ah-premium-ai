import { Spin } from 'antd';

interface LlmProgressNoteProps {
  text?: string;
  fallback?: string;
  className?: string;
}

/**
 * LLM 等待阶段提示。
 * 创建日期：2026-05-05
 * author: sunshengxian
 */
function LlmProgressNote({ text, fallback = '正在分析...', className = '' }: LlmProgressNoteProps) {
  return (
    <div className={`llm-progress-note${className ? ` ${className}` : ''}`}>
      <Spin size="small" />
      <span>{text || fallback}</span>
    </div>
  );
}

export default LlmProgressNote;
