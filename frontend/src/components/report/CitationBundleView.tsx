import { useState } from 'react';
import type { CitationBundleClaim, CitationBundleCompetitor, CitationBundleEvidence } from '../../lib/types';

type Props = {
  bundle: CitationBundleCompetitor[];
};

export default function CitationBundleView({ bundle }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(bundle.map((c) => c.competitor_id)));
  const [activeClaim, setActiveClaim] = useState<{ competitor: string; claim: CitationBundleClaim } | null>(null);

  function toggle(competitorId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(competitorId)) {
        next.delete(competitorId);
      } else {
        next.add(competitorId);
      }
      return next;
    });
  }

  if (bundle.length === 0) {
    return (
      <section className="panel">
        <div className="panel-header">
          <h2>分析汇总</h2>
        </div>
        <div className="empty-state">
          <p className="empty-state-title">暂无结构化分析</p>
          <p className="empty-state-desc">分析数据将在报告生成后自动展示。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>分析汇总</h2>
        <span>{bundle.length} 竞品</span>
      </div>
      <div className="citation-bundle-list">
        {bundle.map((competitor) => {
          const isOpen = expanded.has(competitor.competitor_id);
          const totalRefs = competitor.claims.reduce((sum, c) => sum + c.evidence.length, 0);
          return (
            <article key={competitor.competitor_id} className="citation-bundle-competitor">
              <button
                type="button"
                className={`citation-bundle-trigger ${isOpen ? 'open' : ''}`}
                onClick={() => toggle(competitor.competitor_id)}
              >
                <span className="citation-bundle-name">
                  {competitor.competitor_name}
                  {competitor.analysis_iteration > 0 ? (
                    <span className="source-iteration-badge">第{competitor.analysis_iteration}轮重分析</span>
                  ) : null}
                </span>
                <span className="citation-bundle-count">{totalRefs} 来源</span>
              </button>
              {isOpen ? (
                <div className="citation-bundle-claims">
                  {competitor.claims.map((claim) => (
                    <ClaimRow
                      key={claim.claim_type}
                      claim={claim}
                      onOpenEvidence={() => setActiveClaim({ competitor: competitor.competitor_name, claim })}
                    />
                  ))}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>

      {activeClaim ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setActiveClaim(null)}>
          <div className="competitor-modal citation-modal" role="dialog" aria-modal="true" aria-labelledby="claim-evidence-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="claim-evidence-title">{activeClaim.competitor} · {activeClaim.claim.label}</h3>
                <p>{activeClaim.claim.evidence.length} 条关联来源</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setActiveClaim(null)}>关闭</button>
            </div>
            <div className="claim-modal-body">
              {activeClaim.claim.text ? (
                <div className="claim-modal-conclusion">
                  <dt>结论</dt>
                  <dd>{activeClaim.claim.text}</dd>
                </div>
              ) : null}
              <div className="claim-modal-evidence-list">
                {activeClaim.claim.evidence.map((ev, index) => (
                  <SourceRef key={ev.source_url ?? index} evidence={ev} />
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ClaimRow({ claim, onOpenEvidence }: { claim: CitationBundleClaim; onOpenEvidence: () => void }) {
  const hasEvidence = claim.evidence.length > 0;
  const hasText = Boolean(claim.text);

  return (
    <div className="citation-claim">
      <div className="citation-claim-header">
        <span className="citation-claim-label">{claim.label}</span>
        {hasEvidence ? (
          <button type="button" className="citation-claim-toggle" onClick={onOpenEvidence}>
            {claim.evidence.length} 条来源
          </button>
        ) : (
          <span className="citation-claim-empty">无来源</span>
        )}
      </div>
      {hasText ? <p className="citation-claim-text">{claim.text}</p> : <p className="citation-claim-text muted">证据中未涉及</p>}
    </div>
  );
}

function SourceRef({ evidence }: { evidence: CitationBundleEvidence }) {
  return (
    <div className="citation-ev-ref">
      <div className="source-meta-row">
        {evidence.related_dimension ? (
          <span className="citation-ev-dim">{evidence.related_dimension}</span>
        ) : null}
        {evidence.source_reference_id !== null ? (
          <strong>来源 [{evidence.source_reference_id}]</strong>
        ) : null}
        {evidence.confidence !== null && evidence.confidence !== undefined ? (
          <span className="citation-ev-confidence">可信度 {Math.round(evidence.confidence * 100)}%</span>
        ) : null}
      </div>
      {evidence.source_url ? (
        <a className="citation-ev-link" href={evidence.source_url} target="_blank" rel="noreferrer">
          {evidence.source_title ?? evidence.source_url}
        </a>
      ) : null}
      {evidence.summary ? (
        <p className="citation-ev-summary">{evidence.summary}</p>
      ) : null}
      {evidence.quote ? (
        <blockquote className="citation-ev-quote">{evidence.quote}</blockquote>
      ) : null}
    </div>
  );
}
