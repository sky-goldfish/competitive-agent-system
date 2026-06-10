import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { CitationBundleClaim, CitationBundleCompetitor, CitationBundleEvidence } from '../../lib/types';
import SafeAnchor from '../SafeAnchor';

type Props = {
  bundle: CitationBundleCompetitor[];
};

export default function CitationBundleView({ bundle }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [activeClaim, setActiveClaim] = useState<{ competitor: string; claim: CitationBundleClaim } | null>(null);
  const groupedBundle = groupBundleByCompetitor(bundle);

  function toggle(analysisKey: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(analysisKey)) {
        next.delete(analysisKey);
      } else {
        next.add(analysisKey);
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
        <span>{groupedBundle.length} 竞品</span>
      </div>
      <div className="citation-bundle-list">
        {groupedBundle.map((group) => {
          const totalRefs = group.analyses.reduce((sum, analysis) => sum + countEvidenceRefs(analysis), 0);
          return (
            <article key={group.key} className="citation-bundle-competitor">
              <div className="citation-bundle-group-head">
                <span className="citation-bundle-name">
                  {group.competitorName}
                </span>
                <span className="citation-bundle-count">{totalRefs} 来源</span>
              </div>
              <div className="citation-analysis-list">
                {group.analyses.map((analysis, index) => {
                  const analysisKey = bundleCompetitorKey(analysis, index);
                  const isOpen = expanded.has(analysisKey);
                  const analysisRefs = countEvidenceRefs(analysis);
                  return (
                    <div key={analysisKey} className="citation-analysis-item">
                      <button
                        type="button"
                        className={`citation-bundle-trigger ${isOpen ? 'open' : ''}`}
                        onClick={() => toggle(analysisKey)}
                      >
                        <span className="citation-analysis-title">
                          {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                          <strong>{formatAnalysisIteration(analysis.analysis_iteration)}</strong>
                        </span>
                        <span className="citation-bundle-count">{analysisRefs} 来源</span>
                      </button>
                      {isOpen ? (
                        <div className="citation-bundle-claims">
                          {analysis.claims.map((claim) => (
                            <ClaimRow
                              key={`${claim.claim_type}-${index}`}
                              claim={claim}
                              onOpenEvidence={() => setActiveClaim({ competitor: `${group.competitorName} · ${formatAnalysisIteration(analysis.analysis_iteration)}`, claim })}
                            />
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
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
                  <SourceRef key={`${ev.source_url ?? ''}-${index}`} evidence={ev} />
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function bundleCompetitorKey(competitor: CitationBundleCompetitor, _index: number) {
  return `${competitor.competitor_id}-${competitor.analysis_iteration}`;
}

function groupBundleByCompetitor(bundle: CitationBundleCompetitor[]) {
  const groups = new Map<string, { key: string; competitorName: string; analyses: CitationBundleCompetitor[] }>();
  bundle.forEach((item) => {
    const key = item.competitor_id || item.competitor_name;
    const group = groups.get(key);
    if (group) {
      group.analyses.push(item);
    } else {
      groups.set(key, {
        key,
        competitorName: item.competitor_name,
        analyses: [item],
      });
    }
  });
  return Array.from(groups.values()).map((group) => ({
    ...group,
    analyses: mergeAnalysesByIteration(group.analyses).sort((a, b) => a.analysis_iteration - b.analysis_iteration),
  }));
}

function mergeAnalysesByIteration(analyses: CitationBundleCompetitor[]) {
  const byIteration = new Map<number, CitationBundleCompetitor>();
  analyses.forEach((analysis) => {
    const existing = byIteration.get(analysis.analysis_iteration);
    if (!existing) {
      byIteration.set(analysis.analysis_iteration, {
        ...analysis,
        claims: analysis.claims.map((claim) => ({ ...claim, evidence: [...claim.evidence] })),
      });
      return;
    }

    const claimsByType = new Map(existing.claims.map((claim) => [claim.claim_type, claim]));
    analysis.claims.forEach((claim) => {
      const existingClaim = claimsByType.get(claim.claim_type);
      if (existingClaim) {
        existingClaim.text = existingClaim.text || claim.text;
        const seenKeys = new Set(existingClaim.evidence.map((e) => `${e.source_url ?? ''}|${e.summary ?? ''}|${e.quote ?? ''}`));
        for (const ev of claim.evidence) {
          const key = `${ev.source_url ?? ''}|${ev.summary ?? ''}|${ev.quote ?? ''}`;
          if (!seenKeys.has(key)) {
            existingClaim.evidence.push(ev);
            seenKeys.add(key);
          }
        }
      } else {
        existing.claims.push({ ...claim, evidence: [...claim.evidence] });
      }
    });
  });
  return Array.from(byIteration.values());
}

function countEvidenceRefs(competitor: CitationBundleCompetitor) {
  return competitor.claims.reduce((sum, claim) => sum + claim.evidence.length, 0);
}

function formatAnalysisIteration(iteration: number) {
  if (iteration <= 0) return '首次分析';
  return `第${formatChineseOrdinal(iteration)}轮重分析`;
}

function formatChineseOrdinal(value: number): string {
  const labels: Record<number, string> = {
    1: '一', 2: '二', 3: '三', 4: '四', 5: '五',
    6: '六', 7: '七', 8: '八', 9: '九', 10: '十',
    11: '十一', 12: '十二', 13: '十三', 14: '十四', 15: '十五',
    16: '十六', 17: '十七', 18: '十八', 19: '十九', 20: '二十',
  };
  return labels[value] ?? String(value);
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
        <SafeAnchor className="citation-ev-link" href={evidence.source_url}>
          {evidence.source_title ?? evidence.source_url}
        </SafeAnchor>
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
