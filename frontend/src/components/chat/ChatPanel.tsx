import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { getChatMessages, sendChatMessage } from '../../lib/api';
import type { ChatMessage } from '../../lib/types';

type Props = {
  runId: string;
  onReportVersionChange: (version: number) => void;
};

export default function ChatPanel({ runId, onReportVersionChange }: Props) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  const messagesQuery = useQuery({
    queryKey: ['chat-messages', runId],
    queryFn: () => getChatMessages(runId),
    enabled: Boolean(runId),
  });

  const sendMutation = useMutation({
    mutationFn: (message: string) => sendChatMessage(runId, message),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', runId] });
      if (data.report_version != null) {
        onReportVersionChange(data.report_version);
        queryClient.invalidateQueries({ queryKey: ['report', runId] });
        queryClient.invalidateQueries({ queryKey: ['report-citations', runId] });
        queryClient.invalidateQueries({ queryKey: ['citation-bundle', runId] });
        queryClient.invalidateQueries({ queryKey: ['sources', runId] });
        queryClient.invalidateQueries({ queryKey: ['evidence', runId] });
        queryClient.invalidateQueries({ queryKey: ['analyses', runId] });
      }
      setInput('');
    },
    onError: (error) => {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', runId] });
      console.error('Chat send failed:', error);
    },
  });

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messagesQuery.data]);

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || sendMutation.isPending) return;
    sendMutation.mutate(msg);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const messages = messagesQuery.data ?? [];

  const actionLabel = (msg: ChatMessage) => {
    if (msg.role !== 'assistant' || !msg.intent) return null;
    if (msg.intent === 'report_redo') return '重新调研';
    if (msg.intent === 'report_edit') return '直接修改';
    return null;
  };

  return (
    <div className="chat-panel panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Dialogue</p>
          <h3>对话修改报告</h3>
        </div>
      </div>

      <div className="chat-message-list" ref={listRef}>
        {messages.length === 0 && (
          <p className="chat-placeholder">
            报告生成完成后，你可以通过对话修改动态对比表格。例如：
            <br />· "增加一个竞品 XXX 的对比列"
            <br />· "把定价策略这个维度删掉"
            <br />· "补充隐私安全维度的对比分析"
            <br />· "移除竞品 YYY，重点对比其余产品"
          </p>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`message-row ${msg.role}`}>
            <div className="message-bubble">
              {msg.content}
              {actionLabel(msg) && (
                <span className="chat-action-tag">{actionLabel(msg)}</span>
              )}
            </div>
          </div>
        ))}
        {sendMutation.isPending && (
          <div className="message-row assistant">
            <div className="message-bubble sending">处理中...</div>
          </div>
        )}
      </div>

      <div className="chat-input-row">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入修改意见，例如：增加竞品XX的对比列 / 删除定价维度 / 补充隐私安全对比..."
          rows={2}
          disabled={sendMutation.isPending}
        />
        <button
          type="button"
          className="chat-send-btn"
          onClick={handleSend}
          disabled={sendMutation.isPending || !input.trim()}
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}