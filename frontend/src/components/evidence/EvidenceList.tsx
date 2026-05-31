import type { Evidence, Source } from '../../lib/types';
import { useState } from 'react';

type Props = {
  evidence: Evidence[];
  sources: Source[];
};

export default function EvidenceList({ evidence, sources }: Props) {
  const [detailEvidence, setDetailEvidence] = useState<Evidence | null>(null);
  const sourceById = new Map(sources.map((source) => [source.id, source]));

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>证据片段</h2>
        <span>{evidence.length} evidence</span>
      </div>
      <div className="evidence-list">
        {evidence.length === 0 ? (
          <div className="empty-state">
            <p className="empty-state-title">暂无证据片段</p>
            <p className="empty-state-desc">证据将在资料采集完成后自动提取。</p>
          </div>
        ) : null}
        {evidence.map((item) => {
          const source = sourceById.get(item.source_id);
          return (
            <article key={item.id} className="evidence-item">
              <div className="source-meta-row">
                <span>{item.related_product} · {item.related_dimension}</span>
                <strong>置信度 {(item.confidence * 100).toFixed(0)}%</strong>
              </div>
              <button type="button" className="summary-title-button" onClick={() => setDetailEvidence(item)}>
                {source?.title ?? item.summary}
              </button>
            </article>
          );
        })}
      </div>
      {detailEvidence ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDetailEvidence(null)}>
          <div className="competitor-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="evidence-detail-title">{detailEvidence.related_product} · {detailEvidence.related_dimension}</h3>
                <p>置信度 {(detailEvidence.confidence * 100).toFixed(0)}%</p>
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
                  {sourceById.get(detailEvidence.source_id) ? (
                    <a href={sourceById.get(detailEvidence.source_id)!.url} target="_blank" rel="noreferrer">
                      {sourceById.get(detailEvidence.source_id)!.title}
                    </a>
                  ) : '暂无'}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </section>
  );
}
