import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { confirmCompetitors } from '../../lib/api';
import type { Competitor, CustomCompetitorInput, Run } from '../../lib/types';

type Props = {
  run: Run;
  competitors: Competitor[];
};

const categoryLabels: Record<string, string> = {
  direct_competitor: '直接竞品',
  indirect_competitor: '间接竞品',
  substitute_solution: '替代方案',
  adjacent_product: '相邻产品',
};

export default function CompetitorConfirmPanel({ run, competitors }: Props) {
  const queryClient = useQueryClient();
  const initialSelected = useMemo(() => {
    const selected = competitors.filter((item) => item.selected).map((item) => item.id);
    return selected.length > 0 ? selected : competitors.slice(0, 3).map((item) => item.id);
  }, [competitors]);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelected);
  const [customName, setCustomName] = useState('');
  const [customWebsite, setCustomWebsite] = useState('');
  const [customCategory, setCustomCategory] = useState('direct_competitor');
  const [customCompetitors, setCustomCompetitors] = useState<CustomCompetitorInput[]>([]);
  const [selectedCustomNames, setSelectedCustomNames] = useState<string[]>([]);
  const [detailCompetitor, setDetailCompetitor] = useState<Competitor | null>(null);
  const [customDetail, setCustomDetail] = useState<CustomCompetitorInput | null>(null);
  const [isCustomModalOpen, setIsCustomModalOpen] = useState(false);

  useEffect(() => {
    setSelectedIds((current) => current.length > 0 ? current : initialSelected);
  }, [initialSelected]);

  const mutation = useMutation({
    mutationFn: () => confirmCompetitors(run.id, selectedIds, customCompetitors.filter((item) => selectedCustomNames.includes(item.name))),
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

  function toggleCustom(name: string) {
    setSelectedCustomNames((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]);
  }

  function addCustomCompetitor() {
    const name = customName.trim();
    if (!name) return;
    setCustomCompetitors((current) => [
      ...current,
      { name, website: customWebsite.trim() || undefined, category: customCategory },
    ]);
    setSelectedCustomNames((current) => current.includes(name) ? current : [...current, name]);
    setCustomName('');
    setCustomWebsite('');
    setCustomCategory('direct_competitor');
    setIsCustomModalOpen(false);
  }

  function removeCustomCompetitor(name: string) {
    setCustomCompetitors((current) => current.filter((item) => item.name !== name));
    setSelectedCustomNames((current) => current.filter((item) => item !== name));
  }

  const selectedTotal = selectedIds.length + selectedCustomNames.length;

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>候选竞品确认</h2>
        <span>{selectedTotal} selected</span>
      </div>
      <div className="competitor-grid">
        {competitors.length === 0 ? (
          <div className="empty-state">
            <p className="empty-state-title">暂无候选竞品</p>
            <p className="empty-state-desc">Agent 尚未完成竞品发现，或未找到匹配的竞品。</p>
          </div>
        ) : null}
        {competitors.map((competitor) => (
          <div key={competitor.id} className={`competitor-card ${selectedIds.includes(competitor.id) ? 'selected' : ''}`}>
            <div className="competitor-select-row">
              <input
                type="checkbox"
                checked={selectedIds.includes(competitor.id)}
                onChange={() => toggle(competitor.id)}
                disabled={run.status !== 'waiting_for_human'}
              />
              <button type="button" className="competitor-title-button" onClick={() => setDetailCompetitor(competitor)}>
                {competitor.name}
              </button>
            </div>
            <div className="competitor-brief">
              <span>{categoryLabels[competitor.category] ?? competitor.category}</span>
              <strong>{(competitor.confidence * 100).toFixed(0)}%</strong>
            </div>
            <button type="button" className="detail-action" onClick={() => setDetailCompetitor(competitor)}>
              查看详情
            </button>
          </div>
        ))}
        {customCompetitors.map((competitor) => (
          <div key={`custom-${competitor.name}`} className={`competitor-card custom ${selectedCustomNames.includes(competitor.name) ? 'selected' : ''}`}>
            <div className="competitor-select-row">
              <input
                type="checkbox"
                checked={selectedCustomNames.includes(competitor.name)}
                onChange={() => toggleCustom(competitor.name)}
                disabled={run.status !== 'waiting_for_human'}
              />
              <button type="button" className="competitor-title-button" onClick={() => setCustomDetail(competitor)}>
                {competitor.name}
              </button>
            </div>
            <div className="competitor-brief">
              <span>{categoryLabels[competitor.category] ?? competitor.category}</span>
              <strong className="custom-confidence">自定义</strong>
            </div>
            <div className="custom-row-actions">
              <button type="button" className="detail-action" onClick={() => setCustomDetail(competitor)}>
                查看详情
              </button>
              {run.status === 'waiting_for_human' ? (
                <button type="button" className="remove-action" onClick={() => removeCustomCompetitor(competitor.name)}>
                  移除
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
      {run.status === 'waiting_for_human' ? (
        <button type="button" className="secondary-action add-custom-trigger" onClick={() => setIsCustomModalOpen(true)}>
          手动新增竞品
        </button>
      ) : null}
      {run.status === 'waiting_for_human' ? (
        <button className="primary-action" onClick={() => mutation.mutate()} disabled={selectedTotal === 0 || mutation.isPending}>
          {mutation.isPending ? '已提交，Agent 正在采集资料...' : '确认竞品并生成报告'}
        </button>
      ) : null}
      {mutation.isError ? <p className="error-text">确认失败：{String(mutation.error.message)}</p> : null}
      {isCustomModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsCustomModalOpen(false)}>
          <div className="competitor-modal small" role="dialog" aria-modal="true" aria-labelledby="custom-competitor-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="custom-competitor-title">手动新增竞品</h3>
                <p>新增后会进入同一候选列表，并随确认一起提交。</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setIsCustomModalOpen(false)}>关闭</button>
            </div>
            <div className="custom-competitor-form">
              <label>
                <span>竞品名称</span>
                <input value={customName} onChange={(event) => setCustomName(event.target.value)} placeholder="例如：飞书知识问答" />
              </label>
              <label>
                <span>官网 URL</span>
                <input value={customWebsite} onChange={(event) => setCustomWebsite(event.target.value)} placeholder="可选" />
              </label>
              <label>
                <span>竞品类型</span>
                <select value={customCategory} onChange={(event) => setCustomCategory(event.target.value)}>
                  <option value="direct_competitor">直接竞品</option>
                  <option value="indirect_competitor">间接竞品</option>
                  <option value="substitute_solution">替代方案</option>
                  <option value="adjacent_product">相邻产品</option>
                </select>
              </label>
              <button type="button" className="primary-action" onClick={addCustomCompetitor}>添加到候选列表</button>
            </div>
          </div>
        </div>
      ) : null}
      {detailCompetitor ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDetailCompetitor(null)}>
          <div className="competitor-modal" role="dialog" aria-modal="true" aria-labelledby="competitor-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="competitor-detail-title">{detailCompetitor.name}</h3>
                <p>{categoryLabels[detailCompetitor.category] ?? detailCompetitor.category} · 置信度 {(detailCompetitor.confidence * 100).toFixed(0)}%</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setDetailCompetitor(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>官网</dt>
                <dd>
                  {detailCompetitor.website ? (
                    <a href={detailCompetitor.website} target="_blank" rel="noreferrer">{detailCompetitor.website}</a>
                  ) : '暂无'}
                </dd>
              </div>
              <div>
                <dt>发现来源</dt>
                <dd>{detailCompetitor.discovery_source}</dd>
              </div>
              <div>
                <dt>推荐说明</dt>
                <dd>{detailCompetitor.description}</dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
      {customDetail ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setCustomDetail(null)}>
          <div className="competitor-modal" role="dialog" aria-modal="true" aria-labelledby="custom-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="custom-detail-title">{customDetail.name}</h3>
                <p>{categoryLabels[customDetail.category] ?? customDetail.category} · 自定义</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setCustomDetail(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>官网</dt>
                <dd>
                  {customDetail.website ? (
                    <a href={customDetail.website} target="_blank" rel="noreferrer">{customDetail.website}</a>
                  ) : '暂无'}
                </dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>用户手动新增</dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </section>
  );
}
