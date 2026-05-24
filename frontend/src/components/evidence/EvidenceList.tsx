import type { Evidence, Source } from '../../lib/types';

type Props = {
  evidence: Evidence[];
  sources: Source[];
};

export default function EvidenceList({ evidence, sources }: Props) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>证据片段</h2>
        <span>{evidence.length} evidence</span>
      </div>
      <div className="evidence-list">
        {evidence.length === 0 ? <p className="muted">暂无证据片段。</p> : null}
        {evidence.map((item) => {
          const source = sourceById.get(item.source_id);
          return (
            <article key={item.id} className="evidence-item">
              <span>{item.related_product} · {item.related_dimension} · {(item.confidence * 100).toFixed(0)}%</span>
              <p>{item.summary}</p>
              <blockquote>{item.quote}</blockquote>
              {source ? <a href={source.url} target="_blank" rel="noreferrer">来源：{source.title}</a> : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
