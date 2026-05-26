import type { Source } from '../../lib/types';
import { useState } from 'react';

type Props = {
  sources: Source[];
  isCollecting?: boolean;
};

export default function SourceList({ sources, isCollecting = false }: Props) {
  const [detailSource, setDetailSource] = useState<Source | null>(null);

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
            <button type="button" className="summary-title-button" onClick={() => setDetailSource(source)}>{source.title}</button>
          </article>
        ))}
      </div>
      {detailSource ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDetailSource(null)}>
          <div className="competitor-modal" role="dialog" aria-modal="true" aria-labelledby="source-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="source-detail-title">{detailSource.title}</h3>
                <p>{detailSource.source_type_label ?? detailSource.source_type} · 权重 {detailSource.credibility_score !== null ? `${(detailSource.credibility_score * 100).toFixed(0)}%` : '-'}</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setDetailSource(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>URL</dt>
                <dd><a href={detailSource.url} target="_blank" rel="noreferrer">{detailSource.url}</a></dd>
              </div>
              <div>
                <dt>摘要</dt>
                <dd>{detailSource.snippet || '暂无'}</dd>
              </div>
              <div>
                <dt>分类原因</dt>
                <dd>{detailSource.classification_reason ?? '暂无'}</dd>
              </div>
              <div>
                <dt>来源信息</dt>
                <dd>{detailSource.provider} · {detailSource.source_type}</dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </section>
  );
}
