import type { Source } from '../../lib/types';

type Props = {
  sources: Source[];
  isCollecting?: boolean;
};

export default function SourceList({ sources, isCollecting = false }: Props) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>来源资料</h2>
        <span>{sources.length} sources</span>
      </div>
      <div className="source-list source-list-grid">
        {sources.length === 0 ? <p className="muted">{isCollecting ? 'Agent 正在采集来源资料...' : '暂无来源资料，可能采集失败或来源不足。'}</p> : null}
        {sources.map((source) => (
          <article key={source.id} className="source-item">
            <div className="source-meta-row">
              <span>{source.source_type_label ?? source.source_type}</span>
              {source.credibility_score !== null ? <strong>权重 {(source.credibility_score * 100).toFixed(0)}%</strong> : null}
            </div>
            <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
            <p>{source.snippet}</p>
            {source.classification_reason ? <p className="source-classification">{source.classification_reason}</p> : null}
            <span>{source.provider} · {source.source_type}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
