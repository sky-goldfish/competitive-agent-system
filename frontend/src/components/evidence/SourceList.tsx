import type { Source } from '../../lib/types';
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import SafeAnchor from '../SafeAnchor';

type Props = {
  sources: Source[];
  isCollecting?: boolean;
  initialVisibleCount?: number;
};

function parseCollectionIteration(metadataJson: string | null): number | null {
  if (!metadataJson) return null;
  try {
    const meta = JSON.parse(metadataJson) as Record<string, unknown>;
    const val = meta.collection_iteration;
    return typeof val === 'number' ? val : null;
  } catch {
    return null;
  }
}

function parseMetadata(metadataJson: string | null): Record<string, unknown> | null {
  if (!metadataJson) return null;
  try {
    return JSON.parse(metadataJson) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export default function SourceList({ sources, isCollecting = false, initialVisibleCount = 5 }: Props) {
  const [detailSource, setDetailSource] = useState<Source | null>(null);
  const [expanded, setExpanded] = useState(false);
  const visibleSources = expanded ? sources : sources.slice(0, initialVisibleCount);
  const hiddenCount = Math.max(0, sources.length - visibleSources.length);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>来源资料</h2>
        <span>{sources.length} 条来源</span>
      </div>
      <div className="source-list source-list-grid">
        {sources.length === 0 ? (
          <div className="empty-state">
            <p className="empty-state-title">{isCollecting ? '正在采集来源资料...' : '暂无来源资料'}</p>
            <p className="empty-state-desc">{isCollecting ? 'Agent 正在搜索和采集，请稍候。' : '可能采集失败或来源不足，请检查任务状态。'}</p>
          </div>
        ) : null}
        {visibleSources.map((source) => {
          const iteration = parseCollectionIteration(source.metadata_json);
          return (
            <article key={source.id} className="source-item">
              <div className="source-meta-row">
                <span>
                  {source.reference_id != null ? <strong className="source-ref-badge">[{source.reference_id}]</strong> : null}
                  {source.source_type_label ?? source.source_type}
                  {iteration != null && iteration > 0 ? (
                    <span className="source-iteration-badge">第{iteration}轮重采集</span>
                  ) : null}
                </span>
                {source.credibility_score !== null ? <strong>权重 {(source.credibility_score * 100).toFixed(0)}%</strong> : null}
              </div>
              <button type="button" className="summary-title-button" onClick={() => setDetailSource(source)}>{source.title}</button>
            </article>
          );
        })}
        {sources.length > initialVisibleCount ? (
          <button type="button" className="source-list-toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            {expanded ? '收起来源链接' : `展开全部来源链接（还有 ${hiddenCount} 条）`}
          </button>
        ) : null}
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
              {detailSource.reference_id != null ? (
                <div>
                  <dt>报告引用编号</dt>
                  <dd>[{detailSource.reference_id}]</dd>
                </div>
              ) : null}
              {(() => {
                const iter = parseCollectionIteration(detailSource.metadata_json);
                if (iter != null) {
                  return (
                    <div>
                      <dt>采集轮次</dt>
                      <dd>{iter === 0 ? '初始采集' : `第 ${iter} 轮重采集`}</dd>
                    </div>
                  );
                }
                return null;
              })()}
              <div>
                <dt>URL</dt>
                <dd><SafeAnchor href={detailSource.url}>{detailSource.url}</SafeAnchor></dd>
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
