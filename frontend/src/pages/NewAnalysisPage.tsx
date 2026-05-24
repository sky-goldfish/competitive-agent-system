import { useMutation } from '@tanstack/react-query';
import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createRun } from '../lib/api';

export default function NewAnalysisPage() {
  const navigate = useNavigate();
  const [value, setValue] = useState('我想分析 AI 会议纪要工具的竞品');
  const mutation = useMutation({
    mutationFn: createRun,
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    mutation.mutate(value.trim());
  }

  return (
    <section className="hero-grid">
      <div className="hero-copy">
        <p className="eyebrow">Human-in-the-loop Competitive Research</p>
        <h1>输入产品或想法，让 Agent 小组生成竞品分析报告</h1>
        <p>
          MVP 会先理解需求并发现候选竞品，等待人工确认后继续采集资料、结构化分析并生成带来源的 Markdown 报告。
        </p>
      </div>
      <form className="chat-card" onSubmit={handleSubmit}>
        <label htmlFor="requirement">产品描述</label>
        <textarea
          id="requirement"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="例如：我想做一个面向销售团队的 AI 会议纪要工具"
          rows={9}
        />
        {mutation.isError ? <p className="error-text">创建失败：{String(mutation.error.message)}</p> : null}
        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Agent 正在理解需求...' : '开始分析'}
        </button>
      </form>
    </section>
  );
}
