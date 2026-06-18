import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Eye, X } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { getAnalyses, getCompetitors, getEvidence } from '../../lib/api';
import type { Analysis, Competitor, Evidence } from '../../lib/types';

function parseJsonList(value: string): string[] {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) return parsed.map((item) => String(item));
  } catch {
    /* ignore */
  }
  return value ? [value] : [];
}

function compactList(items: string[], fallback = '证据中未涉及'): string {
  return items.length > 0 ? items.join('；') : fallback;
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

type AnalysisWithSub = Analysis & { subIndex?: number };

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="am-field-row">
      <dt className="am-field-label">{label}</dt>
      <dd className="am-field-value">{value || '证据中未涉及'}</dd>
    </div>
  );
}

function AnalysisIterationCard({ analysis, competitorName, evidenceById }: { analysis: AnalysisWithSub; competitorName: string; evidenceById: Map<string, Evidence> }) {
  const features = parseJsonList(analysis.core_features_json);
  const strengths = parseJsonList(analysis.strengths_json);
  const weaknesses = parseJsonList(analysis.weaknesses_json);
  const opportunities = parseJsonList(analysis.opportunities_json);
  const targetUsers = parseJsonList(analysis.target_users);
  const customFocus = parseCustomFocusAnalysis(analysis.custom_focus_analysis_json);
  const linkedEvidence = parseJsonList(analysis.evidence_ids_json)
    .map((id) => evidenceById.get(id))
    .filter(Boolean) as Evidence[];

  const hasSub = analysis.subIndex != null;
  const [evidenceExpanded, setEvidenceExpanded] = useState(false);

  return (
    <div className="am-iteration-card">
      <div className="am-iteration-header">
        <span className="am-iteration-label">
          {analysis.analysis_iteration > 0
            ? `第 ${analysis.analysis_iteration} 轮重分析`
            : '初始分析'}
          {hasSub && <span className="am-sub-index"> #{analysis.subIndex}</span>}
        </span>
      </div>
      <dl className="am-fields">
        <FieldRow label="产品定位" value={analysis.positioning} />
        <FieldRow label="目标用户" value={compactList(targetUsers)} />
        <FieldRow label="核心功能" value={compactList(features)} />
        <FieldRow label="价格与商业模式" value={analysis.pricing_summary} />
        <FieldRow label="优势" value={compactList(strengths)} />
        <FieldRow label="劣势或痛点" value={compactList(weaknesses)} />
        <FieldRow label="机会点" value={compactList(opportunities)} />
        {customFocus.map((item) => (
          <FieldRow
            key={item.focus_key || item.label}
            label={item.label}
            value={`${item.verdict}${item.confidence > 0 ? `（可信度 ${Math.round(item.confidence * 100)}%）` : ''}`}
          />
        ))}
      </dl>
      {linkedEvidence.length > 0 && (
        <div className="am-evidence-section">
          <button
            type="button"
            className="am-evidence-toggle"
            onClick={() => setEvidenceExpanded((v) => !v)}
          >
            <span>关联证据（{linkedEvidence.length} 条）</span>
            {evidenceExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
          {evidenceExpanded && (
            <div className="am-evidence-list">
              {linkedEvidence.map((ev) => (
                <div key={ev.id} className="am-evidence-item">
                  <span className="am-evidence-dim">{ev.related_dimension}</span>
                  <span className="am-evidence-conf">{Math.round(ev.confidence * 100)}%</span>
                  <p className="am-evidence-summary">{ev.summary}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type Props = {
  runId: string;
  onClose: () => void;
};

export default function AnalysisReviewModal({ runId, onClose }: Props) {
  const [activeCompetitorId, setActiveCompetitorId] = useState<string | null>(null);
  const tabsRef = useRef<HTMLDivElement>(null);

  const analysesQuery = useQuery({
    queryKey: ['analyses', runId],
    queryFn: () => getAnalyses(runId),
    enabled: Boolean(runId),
  });

  const competitorsQuery = useQuery({
    queryKey: ['competitors', runId],
    queryFn: () => getCompetitors(runId),
    enabled: Boolean(runId),
  });

  const evidenceQuery = useQuery({
    queryKey: ['evidence', runId],
    queryFn: () => getEvidence(runId),
    enabled: Boolean(runId),
  });

  const analyses = analysesQuery.data ?? [];
  const competitors = competitorsQuery.data ?? [];
  const evidence = evidenceQuery.data ?? [];

  const evidenceById = useMemo(
    () => new Map(evidence.map((e) => [e.id, e])),
    [evidence],
  );

  const competitorById = useMemo(
    () => new Map(competitors.map((c) => [c.id, c])),
    [competitors],
  );

  const analysesByCompetitor = useMemo(() => {
    const map = new Map<string, AnalysisWithSub[]>();
    for (const a of analyses) {
      const cid = a.competitor_id;
      if (!map.has(cid)) map.set(cid, []);
      map.get(cid)!.push(a);
    }
    for (const [, list] of map) {
      list.sort((a, b) => {
        if (a.analysis_iteration !== b.analysis_iteration) {
          return b.analysis_iteration - a.analysis_iteration;
        }
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
      // Assign sub-index within each iteration group (oldest → ①)
      const groups = new Map<number, AnalysisWithSub[]>();
      for (const a of list) {
        const iter = a.analysis_iteration;
        if (!groups.has(iter)) groups.set(iter, []);
        groups.get(iter)!.push(a);
      }
      for (const [, group] of groups) {
        group.reverse(); // oldest first
        if (group.length > 1) {
          group.forEach((a, i) => { a.subIndex = i + 1; });
        }
        group.reverse(); // restore newest first
      }
    }
    return map;
  }, [analyses]);

  const competitorIds = useMemo(() => {
    return [...analysesByCompetitor.keys()];
  }, [analysesByCompetitor]);

  // Auto-select first competitor
  const effectiveCompetitorId = activeCompetitorId && analysesByCompetitor.has(activeCompetitorId)
    ? activeCompetitorId
    : competitorIds[0] ?? null;

  const scrollTabs = (dir: 'left' | 'right') => {
    const el = tabsRef.current;
    if (!el) return;
    el.scrollBy({ left: dir === 'left' ? -200 : 200, behavior: 'smooth' });
  };

  const isLoading = analysesQuery.isLoading || competitorsQuery.isLoading;

  return (
    <div className="qa-modal-overlay" onClick={onClose}>
      <div className="qa-modal" onClick={(e) => e.stopPropagation()}>
        <div className="qa-modal-header">
          <div className="qa-modal-header-left">
            <Eye size={18} />
            <h2>结构化分析详情</h2>
            {analyses.length > 0 && (
              <span className="qa-modal-header-meta">{competitorIds.length} 个竞品 · {analyses.length} 条分析</span>
            )}
          </div>
          <button type="button" className="qa-modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {isLoading ? (
          <div className="qa-modal-body">
            <p className="qa-modal-loading">加载分析数据...</p>
          </div>
        ) : analyses.length === 0 ? (
          <div className="qa-modal-body">
            <p className="qa-modal-empty">暂无结构化分析结果</p>
          </div>
        ) : (
          <>
            <div className="am-tabs-container">
              <button
                type="button"
                className="am-tabs-scroll-btn"
                onClick={() => scrollTabs('left')}
                aria-label="向左滚动"
              >
                <ChevronLeft size={14} />
              </button>
              <div className="qa-modal-tabs am-tabs" ref={tabsRef}>
                {competitorIds.map((cid) => {
                  const comp = competitorById.get(cid);
                  const name = comp?.name ?? cid;
                  const count = analysesByCompetitor.get(cid)?.length ?? 0;
                  return (
                    <button
                      key={cid}
                      type="button"
                      className={`qa-modal-tab ${effectiveCompetitorId === cid ? 'active' : ''}`}
                      onClick={() => setActiveCompetitorId(cid)}
                    >
                      {name}
                      <span className="am-tab-count">{count}</span>
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                className="am-tabs-scroll-btn"
                onClick={() => scrollTabs('right')}
                aria-label="向右滚动"
              >
                <ChevronRight size={14} />
              </button>
            </div>

            <div className="qa-modal-body">
              {effectiveCompetitorId && (
                <div className="am-competitor-content">
                  {(analysesByCompetitor.get(effectiveCompetitorId) ?? []).map((analysis) => (
                    <AnalysisIterationCard
                      key={analysis.id}
                      analysis={analysis}
                      competitorName={competitorById.get(analysis.competitor_id)?.name ?? analysis.competitor_id}
                      evidenceById={evidenceById}
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
