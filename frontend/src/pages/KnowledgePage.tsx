import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Database, ExternalLink, RefreshCw, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import SafeAnchor from '../components/SafeAnchor';
import { getKnowledgeItems, listRuns, rebuildKnowledgeFromRun, type KnowledgeSearchInput } from '../lib/api';
import type { KnowledgeItem } from '../lib/types';

const dimensions = ['产品定位', '核心功能', '价格与商业模式', '用户评价与痛点'];

function formatTime(value: string) {
  try {
    const hasTz = /[Zz+\-]\d{0,4}$/.test(value.trim());
    return new Date(hasTz ? value : `${value}Z`).toLocaleString();
  } catch {
    return value;
  }
}

function sourceLabel(item: KnowledgeItem) {
  if (item.source_type === 'official_docs') return '官方文档';
  if (item.source_type === 'official_site') return '官网';
  if (item.source_type === 'official_pricing_page') return '价格页';
  if (item.source_type === 'review_site') return '评价站';
  if (item.source_type === 'knowledge_base') return '知识库';
  return item.source_type || '未知来源';
}

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<KnowledgeSearchInput>({ q: '', productName: '', dimension: '', limit: 40 });
  const [filters, setFilters] = useState<KnowledgeSearchInput>({ limit: 40 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [rebuildOpen, setRebuildOpen] = useState(false);

  const knowledgeQuery = useQuery({
    queryKey: ['knowledge-items', filters],
    queryFn: () => getKnowledgeItems(filters),
  });
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: listRuns, refetchInterval: 8000 });

  const items = knowledgeQuery.data ?? [];
  const selectedItem = useMemo(
    () => items.find((item) => item.id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );
  const completedRuns = (runsQuery.data ?? []).filter((run) => run.status === 'completed');

  useEffect(() => {
    if (selectedId && !items.some((item) => item.id === selectedId)) {
      setSelectedId(null);
    }
  }, [items, selectedId]);

  const rebuildMutation = useMutation({
    mutationFn: rebuildKnowledgeFromRun,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-items'] });
      setRebuildOpen(false);
      window.alert(`已沉淀 ${result.created_count} 条，更新 ${result.updated_count} 条，跳过 ${result.skipped_count} 条。`);
    },
    onError: (error) => {
      window.alert(error instanceof Error ? error.message : '重建失败');
    },
  });

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilters({
      q: draft.q,
      productName: draft.productName,
      dimension: draft.dimension,
      limit: 40,
    });
  }

  function handleRebuild() {
    const runId = selectedRunId.trim();
    if (!runId) {
      window.alert('请选择一个已完成任务。');
      return;
    }
    rebuildMutation.mutate(runId);
  }

  return (
    <section className="knowledge-page">
      <div className="section-heading knowledge-heading">
        <div>
          <p className="eyebrow">Knowledge Store</p>
          <h1>知识库</h1>
        </div>
        <div className="knowledge-heading-actions">
          <button type="button" className="knowledge-small-action" onClick={() => setRebuildOpen(true)}>
            <RefreshCw size={15} />
            沉淀历史任务
          </button>
          <div className="knowledge-heading-stat">
            <Database size={18} />
            <span>{items.length} 条当前结果</span>
          </div>
        </div>
      </div>

      <form className="knowledge-toolbar" onSubmit={submitSearch}>
        <label>
          <span>关键词</span>
          <input
            value={draft.q ?? ''}
            onChange={(event) => setDraft((current) => ({ ...current, q: event.target.value }))}
            placeholder="功能、定价、痛点或来源关键词"
          />
        </label>
        <label>
          <span>产品</span>
          <input
            value={draft.productName ?? ''}
            onChange={(event) => setDraft((current) => ({ ...current, productName: event.target.value }))}
            placeholder="例如 Slack"
          />
        </label>
        <label>
          <span>维度</span>
          <select
            value={draft.dimension ?? ''}
            onChange={(event) => setDraft((current) => ({ ...current, dimension: event.target.value }))}
          >
            <option value="">全部维度</option>
            {dimensions.map((dimension) => (
              <option key={dimension} value={dimension}>{dimension}</option>
            ))}
          </select>
        </label>
        <button type="submit" className="primary-link">
          <Search size={16} />
          查询
        </button>
      </form>

      {rebuildOpen ? (
        <div className="knowledge-modal-backdrop" role="presentation" onClick={() => setRebuildOpen(false)}>
          <section
            className="knowledge-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="knowledge-rebuild-title"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="knowledge-modal-header">
              <div>
                <span>Knowledge Sync</span>
                <h2 id="knowledge-rebuild-title">沉淀历史任务</h2>
              </div>
              <button type="button" className="knowledge-modal-close" onClick={() => setRebuildOpen(false)} aria-label="关闭弹窗">
                ×
              </button>
            </header>
            <div className="knowledge-rebuild">
              <div>
                <strong>选择已完成任务</strong>
                <span>把该 run 的高置信证据写入知识库；重复沉淀会更新已有知识。</span>
              </div>
              <select value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}>
                <option value="">选择已完成任务</option>
                {completedRuns.map((run) => (
                  <option key={run.id} value={run.id}>{run.title || run.id}</option>
                ))}
              </select>
              <button type="button" className="secondary-action" onClick={handleRebuild} disabled={rebuildMutation.isPending}>
                <RefreshCw size={16} />
                {rebuildMutation.isPending ? '沉淀中' : '沉淀'}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {knowledgeQuery.isLoading ? <p className="loading">加载知识库中...</p> : null}
      {knowledgeQuery.isError ? <p className="error-text">知识库加载失败。</p> : null}

      <div className="knowledge-layout">
        <div className="knowledge-list" aria-label="知识点列表">
          {items.length === 0 && !knowledgeQuery.isLoading ? (
            <div className="empty-state">
              <span className="empty-state-title">暂无知识点</span>
              <span className="empty-state-desc">完成一次竞品分析，或选择历史任务手动沉淀。</span>
            </div>
          ) : null}
          {items.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`knowledge-item ${selectedItem?.id === item.id ? 'active' : ''}`}
              onClick={() => setSelectedId(item.id)}
            >
              <span className="knowledge-item-top">
                <strong>{item.product_name}</strong>
                <span>{item.dimension}</span>
              </span>
              <span className="knowledge-item-claim">{item.summary || item.claim}</span>
              <span className="knowledge-item-meta">
                <span>{sourceLabel(item)}</span>
                <span>{Math.round(item.confidence * 100)}%</span>
                <span>{formatTime(item.updated_at)}</span>
              </span>
            </button>
          ))}
        </div>

        <aside className="knowledge-detail">
          {selectedItem ? (
            <>
              <div className="knowledge-detail-head">
                <span>{selectedItem.dimension}</span>
                <h2>{selectedItem.product_name}</h2>
              </div>
              <div className="knowledge-detail-section">
                <strong>知识摘要</strong>
                <p>{selectedItem.summary || '暂无摘要。'}</p>
              </div>
              <div className="knowledge-detail-section">
                <strong>证据片段</strong>
                <p>{selectedItem.claim}</p>
              </div>
              <div className="knowledge-detail-grid">
                <div>
                  <span>置信度</span>
                  <strong>{Math.round(selectedItem.confidence * 100)}%</strong>
                </div>
                <div>
                  <span>来源类型</span>
                  <strong>{sourceLabel(selectedItem)}</strong>
                </div>
                <div>
                  <span>更新时间</span>
                  <strong>{formatTime(selectedItem.updated_at)}</strong>
                </div>
              </div>
              <div className="knowledge-detail-links">
                {selectedItem.source_url ? (
                  <SafeAnchor href={selectedItem.source_url}>
                    <ExternalLink size={15} />
                    {selectedItem.source_title || selectedItem.source_url}
                  </SafeAnchor>
                ) : null}
                {selectedItem.run_id ? (
                  <Link to={`/runs/${selectedItem.run_id}`}>查看关联任务</Link>
                ) : null}
              </div>
            </>
          ) : (
            <div className="empty-state">
              <span className="empty-state-title">选择一条知识</span>
              <span className="empty-state-desc">右侧会展示证据、来源和关联任务。</span>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
