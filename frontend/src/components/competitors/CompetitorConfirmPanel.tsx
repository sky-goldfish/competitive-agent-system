import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { confirmCompetitors } from '../../lib/api';
import type { Competitor, CustomCompetitorInput, Run } from '../../lib/types';

type Props = {
  run: Run;
  competitors: Competitor[];
};

export default function CompetitorConfirmPanel({ run, competitors }: Props) {
  const queryClient = useQueryClient();
  const initialSelected = useMemo(() => competitors.slice(0, 3).map((item) => item.id), [competitors]);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelected);
  const [customName, setCustomName] = useState('');
  const [customWebsite, setCustomWebsite] = useState('');
  const [customCategory, setCustomCategory] = useState('direct_competitor');
  const [customCompetitors, setCustomCompetitors] = useState<CustomCompetitorInput[]>([]);

  useEffect(() => {
    setSelectedIds((current) => current.length > 0 ? current : initialSelected);
  }, [initialSelected]);

  const mutation = useMutation({
    mutationFn: () => confirmCompetitors(run.id, selectedIds, customCompetitors),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['run', run.id] }),
        queryClient.invalidateQueries({ queryKey: ['timeline', run.id] }),
        queryClient.invalidateQueries({ queryKey: ['competitors', run.id] }),
        queryClient.invalidateQueries({ queryKey: ['sources', run.id] }),
        queryClient.invalidateQueries({ queryKey: ['report', run.id] }),
      ]);
    },
  });

  function toggle(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function addCustomCompetitor() {
    const name = customName.trim();
    if (!name) return;
    setCustomCompetitors((current) => [
      ...current,
      { name, website: customWebsite.trim() || undefined, category: customCategory },
    ]);
    setCustomName('');
    setCustomWebsite('');
    setCustomCategory('direct_competitor');
  }

  function removeCustomCompetitor(name: string) {
    setCustomCompetitors((current) => current.filter((item) => item.name !== name));
  }

  const selectedTotal = selectedIds.length + customCompetitors.length;

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>候选竞品确认</h2>
        <span>{selectedTotal} selected</span>
      </div>
      <div className="competitor-grid">
        {competitors.map((competitor) => (
          <button
            key={competitor.id}
            type="button"
            className={`competitor-card ${selectedIds.includes(competitor.id) ? 'selected' : ''}`}
            onClick={() => toggle(competitor.id)}
            disabled={run.status !== 'waiting_for_human'}
          >
            <strong>{competitor.name}</strong>
            <span>{competitor.category} · {(competitor.confidence * 100).toFixed(0)}%</span>
            <p>{competitor.description}</p>
          </button>
        ))}
      </div>
      {run.status === 'waiting_for_human' ? (
        <div className="custom-competitor-box">
          <h3>手动新增竞品</h3>
          <input value={customName} onChange={(event) => setCustomName(event.target.value)} placeholder="竞品名称，例如：飞书知识问答" />
          <input value={customWebsite} onChange={(event) => setCustomWebsite(event.target.value)} placeholder="官网 URL，可选" />
          <select value={customCategory} onChange={(event) => setCustomCategory(event.target.value)}>
            <option value="direct_competitor">直接竞品</option>
            <option value="indirect_competitor">间接竞品</option>
            <option value="substitute_solution">替代方案</option>
            <option value="adjacent_product">相邻产品</option>
          </select>
          <button type="button" className="secondary-action" onClick={addCustomCompetitor}>添加到确认列表</button>
          {customCompetitors.length > 0 ? (
            <ul className="custom-competitor-list">
              {customCompetitors.map((item) => (
                <li key={item.name}>
                  <span>{item.name} · {item.category}</span>
                  <button type="button" onClick={() => removeCustomCompetitor(item.name)}>移除</button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {run.status === 'waiting_for_human' ? (
        <button className="primary-action" onClick={() => mutation.mutate()} disabled={selectedTotal === 0 || mutation.isPending}>
          {mutation.isPending ? '已提交，Agent 正在采集资料...' : '确认竞品并生成报告'}
        </button>
      ) : (
        <p className="muted">竞品已确认，后续 Agent 已继续执行。</p>
      )}
      {mutation.isError ? <p className="error-text">确认失败：{String(mutation.error.message)}</p> : null}
    </section>
  );
}
