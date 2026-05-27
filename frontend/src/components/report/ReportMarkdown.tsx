import { useMemo, useState, type AnchorHTMLAttributes, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { CitationMapItem } from '../../lib/types';

type Props = {
  markdown: string;
  citations: CitationMapItem[];
};

export default function ReportMarkdown({ markdown, citations }: Props) {
  const [activeCitation, setActiveCitation] = useState<CitationMapItem | null>(null);
  const citationByReference = useMemo(() => new Map(citations.map((item) => [item.reference_id, item])), [citations]);

  return (
    <>
      <ReactMarkdown
        components={{
          a: ({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode }) => {
            const referenceId = citationReferenceId(children);
            const citation = referenceId ? citationByReference.get(referenceId) : undefined;
            if (citation) {
              return (
                <button type="button" className="citation-link" onClick={() => setActiveCitation(citation)}>
                  [{referenceId}]
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" {...props}>
                {children}
              </a>
            );
          },
        }}
      >
        {markdown}
      </ReactMarkdown>

      {activeCitation ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setActiveCitation(null)}>
          <div className="competitor-modal citation-modal" role="dialog" aria-modal="true" aria-labelledby="citation-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="citation-detail-title">引用 [{activeCitation.reference_id}]</h3>
                <p>{activeCitation.source.source_type_label ?? activeCitation.source.source_type} · 权重 {activeCitation.source.credibility_score?.toFixed(2) ?? '未知'}</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setActiveCitation(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>来源资料</dt>
                <dd>
                  <a href={activeCitation.source.url} target="_blank" rel="noreferrer">
                    {activeCitation.source.title}
                  </a>
                </dd>
              </div>
              <div>
                <dt>来源摘要</dt>
                <dd>{activeCitation.source.snippet || '暂无摘要'}</dd>
              </div>
              <div>
                <dt>关联证据</dt>
                <dd>
                  {activeCitation.evidence.length > 0 ? (
                    <div className="citation-evidence-list">
                      {activeCitation.evidence.map((item) => (
                        <article key={item.id}>
                          <strong>{item.related_product} · {item.related_dimension}</strong>
                          <p>{item.summary}</p>
                          <blockquote>{item.quote}</blockquote>
                        </article>
                      ))}
                    </div>
                  ) : '暂无关联证据'}
                </dd>
              </div>
              <div>
                <dt>关联分析</dt>
                <dd>
                  {activeCitation.analyses.length > 0 ? activeCitation.analyses.map((item) => (
                    <span className="citation-analysis-pill" key={item.id}>
                      {item.competitor_name || item.competitor_id} · {item.claim_types.slice(0, 3).join(' / ')}
                    </span>
                  )) : '暂无关联分析'}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </>
  );
}

function citationReferenceId(children: ReactNode): number | null {
  const text = flattenText(children).trim();
  const match = text.match(/^\[(\d+)\]$/);
  return match ? Number(match[1]) : null;
}

function flattenText(value: ReactNode): string {
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(flattenText).join('');
  }
  return '';
}
