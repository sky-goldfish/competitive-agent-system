import { useMemo, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { CitationMapItem } from '../../lib/types';
import { safeHref } from '../../lib/utils';
import SafeAnchor from '../SafeAnchor';

type Props = {
  markdown: string;
  citations: CitationMapItem[];
};

const STANDALONE_CITATION_RE = /\[\[(\d+)\]\](?!\()/g;
const COMPOUND_CITATION_RE = /\[\[([0-9]{1,2}(?:[,，、\s]+[0-9]{1,2})+)\]\]/g;

function preprocessCitations(markdown: string): string {
  let result = markdown.replace(COMPOUND_CITATION_RE, (_match, inner: string) => {
    const nums = inner.split(/[,，、\s]+/).filter((s: string) => /^\d+$/.test(s.trim()));
    return nums.map((n: string) => `[[${n.trim()}]]`).join(' ');
  });
  result = result.replace(STANDALONE_CITATION_RE, '[[$1]](#citation-$1)');
  return result;
}

export default function ReportMarkdown({ markdown, citations }: Props) {
  const [activeCitation, setActiveCitation] = useState<CitationMapItem | null>(null);
  const citationByReference = useMemo(() => new Map(citations.map((item) => [item.reference_id, item])), [citations]);
  const processedMarkdown = useMemo(() => preprocessCitations(markdown), [markdown]);

  return (
    <>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="table-scroll-wrapper">
              <table>{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead>{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr>{children}</tr>,
          th: ({ children, align }) => (
            <th style={align && align !== 'char' ? { textAlign: align } : undefined}>{children}</th>
          ),
          td: ({ children, align }) => (
            <td style={align && align !== 'char' ? { textAlign: align } : undefined}>{children}</td>
          ),
          a: ({ href, children }) => {
            const referenceId = citationReferenceId(href, children);
            const citation = referenceId ? citationByReference.get(referenceId) : undefined;
            if (citation) {
              return (
                <button type="button" className="citation-link" onClick={() => setActiveCitation(citation)}>
                  [{referenceId}]
                </button>
              );
            }
            const hrefSafe = safeHref(href);
            return (
              <SafeAnchor href={hrefSafe}>{children}</SafeAnchor>
            );
          },
        }}
      >
        {processedMarkdown}
      </ReactMarkdown>

      {activeCitation ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setActiveCitation(null)}>
          <div className="competitor-modal citation-modal" role="dialog" aria-modal="true" aria-labelledby="citation-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="citation-detail-title">引用 [{activeCitation.reference_id}]</h3>
                <p>{activeCitation.source.source_type_label ?? activeCitation.source.source_type} · 权重 {safeToFixed(activeCitation.source.credibility_score)}</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setActiveCitation(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>来源资料</dt>
                <dd>
                  <SafeAnchor href={activeCitation.source.url}>
                    {activeCitation.source.title}
                  </SafeAnchor>
                </dd>
              </div>
              <div>
                <dt>来源摘要</dt>
                <dd>{activeCitation.source.snippet || '暂无摘要'}</dd>
              </div>
              <div>
                <dt>关联证据</dt>
                <dd>
                  {activeCitation.evidence?.length > 0 ? (
                    <div className="citation-evidence-list">
                      {activeCitation.evidence?.map((item) => (
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
                  {activeCitation.analyses?.length > 0 ? activeCitation.analyses.map((item) => (
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

function safeToFixed(value: number | null | undefined): string {
  if (value == null) return '未知';
  const num = Number(value);
  if (Number.isNaN(num)) return '未知';
  return num.toFixed(2);
}

function citationReferenceId(href: string | undefined, children: ReactNode): number | null {
  if (href?.startsWith('#citation-')) {
    const id = Number(href.slice('#citation-'.length));
    return Number.isNaN(id) ? null : id;
  }
  const text = flattenText(children).trim();
  const match = text.match(/^\[\[?(\d+)\]?\]$/);
  return match ? Number(match[1]) : null;
}

function flattenText(value: ReactNode): string {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(flattenText).join('');
  }
  if (typeof value === 'object' && 'props' in value) {
    return flattenText((value as { props: { children?: ReactNode } }).props.children);
  }
  return '';
}
