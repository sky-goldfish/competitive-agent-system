import { useMemo, useState } from 'react';
import type { Analysis, Competitor, Evidence, Source } from '../../lib/types';

type Props = {
  analyses: Analysis[];
  competitors: Competitor[];
  evidence: Evidence[];
  sources: Source[];
};

function parseJsonList(value: string): string[] {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) return parsed.map((item) => String(item));
  } catch {
    // Fall through to plain string display.
  }
  return value ? [value] : [];
}

function compactList(items: string[], fallback = '证据中未涉及') {
  return items.length > 0 ? items.slice(0, 3).join('、') : fallback;
}

type CustomFocusAnalysis = {
  focus_key: string;
  label: string;
  verdict: string;
  evidence_ids: string[];
  confidence: number;
};

function parseCustomFocusAnalysis(value: string): CustomFocusAnalysis[] {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
      .map((item) => ({
        focus_key: String(item.focus_key ?? ''),
        label: String(item.label ?? ''),
        verdict: String(item.verdict ?? '证据中未涉及'),
        evidence_ids: Array.isArray(item.evidence_ids) ? item.evidence_ids.map((id) => String(id)) : [],
        confidence: Number(item.confidence ?? 0),
      }))
      .filter((item) => item.label);
  } catch {
    return [];
  }
}

export default function AnalysisList({ analyses, competitors, evidence, sources }: Props) {
  const [detailAnalysis, setDetailAnalysis] = useState<Analysis | null>(null);
  const competitorById = useMemo(() => new Map(competitors.map((item) => [item.id, item])), [competitors]);
  const evidenceById = useMemo(() => new Map(evidence.map((item) => [item.id, item])), [evidence]);
  const sourceById = useMemo(() => new Map(sources.map((item) => [item.id, item])), [sources]);

  function getLinkedEvidence(analysis: Analysis) {
    const ids = parseJsonList(analysis.evidence_ids_json);
    const directMatches = ids.map((id) => evidenceById.get(id)).filter(Boolean) as Evidence[];
    if (directMatches.length > 0) return directMatches;
    return evidence.filter((item) => item.related_product === competitorById.get(analysis.competitor_id)?.name);
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>结构化分析</h2>
        <span>{analyses.length} analyses</span>
      </div>
      <div className="analysis-list">
        {analyses.length === 0 ? <p className="muted">暂无结构化分析。</p> : null}
        {analyses.map((analysis) => {
          const competitor = competitorById.get(analysis.competitor_id);
          const features = parseJsonList(analysis.core_features_json);
          const strengths = parseJsonList(analysis.strengths_json);
          const weaknesses = parseJsonList(analysis.weaknesses_json);
          const customFocusAnalysis = parseCustomFocusAnalysis(analysis.custom_focus_analysis_json);
          const linkedEvidence = getLinkedEvidence(analysis);
          return (
            <article key={analysis.id} className="analysis-item">
              <div className="source-meta-row">
                <span>
                  {competitor?.name ?? analysis.competitor_id}
                  {analysis.analysis_iteration > 0 ? (
                    <span className="source-iteration-badge">第{analysis.analysis_iteration}轮重分析</span>
                  ) : null}
                </span>
                <strong>{linkedEvidence.length} evidence</strong>
              </div>
              <button type="button" className="summary-title-button" onClick={() => setDetailAnalysis(analysis)}>
                {analysis.positioning}
              </button>
              <p className="analysis-compact">功能：{compactList(features)}</p>
              <p className="analysis-compact">优势：{compactList(strengths)}</p>
              <p className="analysis-compact">风险：{compactList(weaknesses)}</p>
              {customFocusAnalysis.length > 0 ? (
                <p className="analysis-compact">动态字段：{customFocusAnalysis.map((item) => item.label).slice(0, 3).join('、')}</p>
              ) : null}
            </article>
          );
        })}
      </div>

      {detailAnalysis ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDetailAnalysis(null)}>
          <div className="competitor-modal" role="dialog" aria-modal="true" aria-labelledby="analysis-detail-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="analysis-detail-title">
                  {competitorById.get(detailAnalysis.competitor_id)?.name ?? detailAnalysis.competitor_id}
                  {detailAnalysis.analysis_iteration > 0 ? (
                    <span className="source-iteration-badge" style={{ marginLeft: 8 }}>第{detailAnalysis.analysis_iteration}轮重分析</span>
                  ) : null}
                </h3>
                <p>结构化分析 · {getLinkedEvidence(detailAnalysis).length} 条关联证据</p>
              </div>
              <button type="button" className="modal-close" onClick={() => setDetailAnalysis(null)}>关闭</button>
            </div>
            <dl className="competitor-detail-list">
              <div>
                <dt>产品定位</dt>
                <dd>{detailAnalysis.positioning}</dd>
              </div>
              <div>
                <dt>目标用户</dt>
                <dd>{compactList(parseJsonList(detailAnalysis.target_users))}</dd>
              </div>
              <div>
                <dt>核心功能</dt>
                <dd>{compactList(parseJsonList(detailAnalysis.core_features_json))}</dd>
              </div>
              <div>
                <dt>价格与商业模式</dt>
                <dd>{detailAnalysis.pricing_summary}</dd>
              </div>
              <div>
                <dt>优势</dt>
                <dd>{compactList(parseJsonList(detailAnalysis.strengths_json))}</dd>
              </div>
              <div>
                <dt>劣势或痛点</dt>
                <dd>{compactList(parseJsonList(detailAnalysis.weaknesses_json))}</dd>
              </div>
              <div>
                <dt>机会点</dt>
                <dd>{compactList(parseJsonList(detailAnalysis.opportunities_json))}</dd>
              </div>
              {parseCustomFocusAnalysis(detailAnalysis.custom_focus_analysis_json).map((item) => (
                <div key={item.focus_key || item.label}>
                  <dt>{item.label}</dt>
                  <dd>
                    {item.verdict}
                    {item.confidence > 0 ? (
                      <span className="source-iteration-badge" style={{ marginLeft: 8 }}>可信度 {Math.round(item.confidence * 100)}%</span>
                    ) : null}
                  </dd>
                </div>
              ))}
              <div>
                <dt>关联证据</dt>
                <dd>
                  <div className="linked-evidence-list">
                    {getLinkedEvidence(detailAnalysis).length === 0 ? <span>暂无可匹配证据</span> : null}
                    {getLinkedEvidence(detailAnalysis).map((item) => {
                      const source = sourceById.get(item.source_id);
                      return (
                        <div key={item.id} className="linked-evidence-item">
                          <strong>{item.related_dimension} · {(item.confidence * 100).toFixed(0)}%</strong>
                          <p>{item.summary}</p>
                          {source ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : null}
                        </div>
                      );
                    })}
                  </div>
                </dd>
              </div>
            </dl>
          </div>
        </div>
      ) : null}
    </section>
  );
}
