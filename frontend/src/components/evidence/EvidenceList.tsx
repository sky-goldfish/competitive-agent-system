import type { Evidence, Source } from '../../lib/types';
import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import SafeAnchor from '../SafeAnchor';

type Props = {
  evidence: Evidence[];
  sources: Source[];
  initialVisibleCount?: number;
};

export default function EvidenceList({ evidence, sources, initialVisibleCount = 5 }: Props) {
  const [detailEvidence, setDetailEvidence] = useState<Evidence | null>(null);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [listExpanded, setListExpanded] = useState(false);
  const sourceById = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const visibleEvidence = listExpanded ? evidence : evidence.slice(0, initialVisibleCount);
  const hiddenCount = Math.max(0, evidence.length - visibleEvidence.length);

  function toggleExpanded(id: string) {
    setExpandedIds((current) => (
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    ));
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>证据片段</h2>
        <span>{evidence.length} 条证据</span>
      </div>
      <div className="evidence-list">
        {evidence.length === 0 ? (
          <div className="empty-state">
            <p className="empty-state-title">暂无证据片段</p>
            <p className="empty-state-desc">证据将在资料采集完成后自动提取。</p>
          </div>
        ) : null}
        {visibleEvidence.map((item) => {
          const source = sourceById.get(item.source_id);
          const expanded = expandedIds.includes(item.id);
          return (
            <article key={item.id} className={`evidence-item collapsible-evidence ${expanded ? 'expanded' : ''}`}>
              <div className="source-meta-row">
                <span>{item.related_product} · {item.related_dimension}</span>
                <strong>置信度 {item.confidence != null ? `${(item.confidence * 100).toFixed(0)}%` : '-'}</strong>
              </div>
              <div className="evidence-collapse-head">
                <button type="button" className="summary-title-button" onClick={() => setDetailEvidence(item)}>
                  {source?.title ?? item.summary}
                </button>
                <button type="button" className="evidence-toggle" onClick={() => toggleExpanded(item.id)} aria-expanded={expanded}>
                  {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                  {expanded ? '收起' : '展开'}
                </button>
              </div>
              <p className="evidence-summary-preview">{item.summary}</p>
              {expanded ? (
                <div className="evidence-expanded-body">
                  <div>
                    <span>证据片段</span>
                    <blockquote>{item.quote}</blockquote>
                  </div>
                  <button type="button" className="text-link evidence-detail-link" onClick={() => setDetailEvidence(item)}>
                    查看完整详情
                  </button>
                </div>
              ) : null}
            </article>
          );
        })}
        {evidence.length > initialVisibleCount ? (
          <button type="button" className="source-list-toggle" onClick={() => setListExpanded((value) => !value)} aria-expanded={listExpanded}>
            {listExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            {listExpanded ? '收起证据片段' : `展开全部证据片段（还有 ${hiddenCount} 条）`}
          </button>
        ) : null}
      </div>
      {detailEvidence ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDetailEvidence(null)}>
          <div className="competitor-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="evidence-detail-title">{detailEvidence.related_product} · {detailEvidence.related_dimension}</h3>
                <p>置信度 {detailEvidence.confidence != null ? `${(detailEvidence.confidence * 100).toFixed(0)}%` : '-'}</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setDetailEvidence(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>证据摘要</dt>
                <dd>{detailEvidence.summary}</dd>
              </div>
              <div>
                <dt>证据片段</dt>
                <dd>{detailEvidence.quote}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>
                  {(() => { const src = sourceById.get(detailEvidence.source_id); return src ? (
                    <SafeAnchor href={src.url}>
                      {src.title}
                    </SafeAnchor>
                  ) : '暂无'; })()}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </section>
  );
}
