import { useMutation } from '@tanstack/react-query';
import { FormEvent, KeyboardEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUp } from 'lucide-react';
import { createRun } from '../lib/api';

export default function NewAnalysisPage() {
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const mutation = useMutation({
    mutationFn: createRun,
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });
  const canSubmit = value.trim().length > 0 && !mutation.isPending;

  function submit() {
    if (!canSubmit) return;
    mutation.mutate(value.trim());
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <section className="chat-home">
      <div className="chat-home-inner">
        <h1>突然有idea？快来找竞品</h1>
        <p>
          输入产品、功能或创业想法，Agent 会发现候选竞品、采集公开资料，并生成带来源的 Markdown 报告。
        </p>
        <ol className="analysis-flow" aria-label="竞品分析流程">
          <li>
            <strong>理解需求</strong>
          </li>
          <li>
            <strong>发现竞品</strong>
          </li>
          <li>
            <strong>人工确认</strong>
          </li>
          <li>
            <strong>生成报告</strong>
          </li>
        </ol>
        <form className="prompt-composer" onSubmit={handleSubmit}>
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="请输入产品描述，例如：我想做一个面向销售团队的 AI 会议纪要工具"
            rows={5}
            aria-label="产品或想法描述"
          />
          <div className="composer-footer">
            <span>{mutation.isPending ? 'Agent 正在理解需求...' : 'Enter 提交 · Shift + Enter 换行'}</span>
            <button type="submit" className="send-button" disabled={!canSubmit} aria-label="提交分析">
              <ArrowUp size={18} />
            </button>
          </div>
        </form>
        {mutation.isError ? <p className="error-text">创建失败：{String(mutation.error.message)}</p> : null}
      </div>
    </section>
  );
}
