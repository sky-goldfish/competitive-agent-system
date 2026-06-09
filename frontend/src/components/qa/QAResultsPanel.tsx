import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Circle, History, RefreshCw, Search, ShieldCheck, XCircle } from 'lucide-react';
import { useState } from 'react';
import { getQAResults } from '../../lib/api';
import type { QAIssue, QAResult as QAResultType, QARetryQuery } from '../../lib/types';

const dimensionLabels: Record<string, string> = {
  evidence_grounding: '证据支撑度',
  citation_accuracy: '引用准确性',
  schema_completeness: 'Schema 完整度',
  coverage_gaps: '覆盖缺口',
  cross_competitor_consistency: '跨竞品一致性',
  factual_plausibility: '事实合理性',
};

const dimensionOrder = [
  'evidence_grounding',
  'citation_accuracy',
  'schema_completeness',
  'coverage_gaps',
  'cross_competitor_consistency',
  'factual_plausibility',
];

const decisionLabels: Record<string, string> = {
  pass: '通过',
  retry_collection: '重新采集',
  retry_analysis: '重新分析',
};

const severityLabels: Record<string, string> = {
  critical: '严重',
  major: '重要',
  minor: '轻微',
};

const slotLabels: Record<string, string> = {
  core_features: '核心功能',
  pricing: '价格与商业模式',
  positioning: '产品定位',
  user_feedback: '用户评价与痛点',
  market_signal: '市场信号',
  risk_opportunity: '风险与机会',
  relationship_evidence: '竞争关系',
};

function roundLabel(iteration: number): string {
  const retryCount = iteration - 1;
  return retryCount > 0
    ? `第 ${iteration} 轮质检（第 ${retryCount} 次重试）`
    : `第 ${iteration} 轮质检`;
}

type Props = {
  runId: string;
};

export default function QAResultsPanel({ runId }: Props) {
  const qaQuery = useQuery({
    queryKey: ['qa-results', runId],
    queryFn: () => getQAResults(runId),
    enabled: Boolean(runId),
  });

  const results = qaQuery.data ?? [];

  if (qaQuery.isLoading) return (
    <section className="panel">
      <div className="panel-header">
        <h2>质量检查</h2>
      </div>
      <p className="loading">加载质检结果...</p>
    </section>
  );
  if (results.length === 0) return (
    <section className="panel">
      <div className="panel-header">
        <h2>质量检查</h2>
      </div>
      <div className="empty-state">
        <p className="empty-state-title">暂无质检结果</p>
        <p className="empty-state-desc">结构化分析完成后会进入质量检查。</p>
      </div>
    </section>
  );

  const dedupedResults = dedupeQAResultsByIteration(results);
  const sorted = [...dedupedResults].sort((a, b) => b.iteration - a.iteration);
  const latest = sorted[0];
  const historical = sorted.slice(1);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>质量检查</h2>
        <span>{results.length} 轮</span>
      </div>
      <div className="qa-results-panel">
        <QACurrentRound result={latest} />
        {historical.length > 0 && (
          <QAHistoricalRounds rounds={historical} />
        )}
      </div>
    </section>
  );
}

function dedupeQAResultsByIteration(results: QAResultType[]) {
  const byIteration = new Map<number, QAResultType>();
  results.forEach((result) => {
    const existing = byIteration.get(result.iteration);
    if (!existing) {
      byIteration.set(result.iteration, result);
    } else {
      const existingTime = new Date(existing.created_at).getTime();
      if (new Date(result.created_at).getTime() >= existingTime) {
        byIteration.set(result.iteration, result);
      }
    }
  });
  return Array.from(byIteration.values());
}

function QACurrentRound({ result }: { result: QAResultType }) {
  const scorePercent = Math.round(result.overall_score * 100);
  const scoreClass = result.overall_score >= 0.7 ? 'pass' : 'fail';
  const hasRetryQueries = result.decision === 'retry_collection' && (result.retry_queries ?? []).length > 0;

  return (
    <div className={`qa-current-round ${scoreClass}`}>
      <div className="qa-iteration-header">
        <div className="qa-iteration-title">
          {result.decision === 'pass' ? <ShieldCheck size={16} /> : <AlertTriangle size={16} />}
          <strong>{roundLabel(result.iteration)}</strong>
        </div>
        <div className={`qa-score-badge ${scoreClass}`}>{scorePercent}分</div>
      </div>

      {result.quality_warning && (
        <div className="qa-quality-warning-banner">
          <AlertTriangle size={14} />
          <span>报告质量较低（{scorePercent}分），系统已达到重试上限自动通过，建议关注上述问题。</span>
        </div>
      )}

      <div className="qa-score-bar-track">
        <div className={`qa-score-bar-fill ${scoreClass}`} style={{ width: `${scorePercent}%` }} />
      </div>

      {Object.keys(result.dimension_scores ?? {}).length > 0 && (
        <div className="qa-dimension-scores">
          {dimensionOrder.map((dimension) => {
            const score = result.dimension_scores[dimension];
            if (score == null) return null;
            const percent = Math.round(score * 100);
            return (
              <div key={dimension} className="qa-dimension-score">
                <span>{dimensionLabels[dimension] ?? dimension}</span>
                <strong>{percent}</strong>
                <div className="qa-dimension-score-track">
                  <div className={percent >= 70 ? 'pass' : 'fail'} style={{ width: `${percent}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="qa-decision-row">
        <DecisionBadge decision={result.decision} hasRetryQueries={hasRetryQueries} queries={result.retry_queries} />
      </div>

      {result.issues.length > 0 && (
        <div className="qa-section">
          <div className="qa-section-header">本轮发现问题</div>
          <div className="qa-issues-list">
            {result.issues.map((issue, i) => (
              <QAIssueItem key={i} issue={issue} />
            ))}
          </div>
        </div>
      )}

      {(result.issue_checklist ?? []).length > 0 && (
        <div className="qa-section">
          <div className="qa-section-header">
            <History size={13} /> 问题追踪
          </div>
          <div className="qa-checklist">
            {result.issue_checklist.map((issue, i) => (
              <div key={issue.id ?? i} className={`qa-checklist-item qa-checklist-${issue.status ?? 'open'}`}>
                <div className="qa-checklist-item-header">
                  {issue.status === 'resolved' ? <CheckCircle2 size={13} className="qa-checklist-resolved-icon" />
                    : issue.status === 'unresolved' ? <AlertTriangle size={13} className="qa-checklist-unresolved-icon" />
                    : <Circle size={13} className="qa-checklist-open-icon" />}
                  <span className={`qa-severity-badge ${issue.severity}`}>{severityLabels[issue.severity] ?? issue.severity}</span>
                  <span className="qa-dimension-badge">{dimensionLabels[issue.dimension] ?? issue.dimension}</span>
                  {issue.competitor_name && issue.competitor_name !== 'report' && issue.competitor_name !== 'system' && (
                    <span className="qa-competitor-badge">{issue.competitor_name}</span>
                  )}
                  <span className={`qa-checklist-status qa-checklist-status-${issue.status ?? 'open'}`}>
                    {issue.status === 'resolved' ? <>✓ 第 {issue.resolved_iteration} 轮已解决</>
                      : issue.status === 'unresolved' ? <>⚠ 未解决（已达重试上限）</>
                      : <>● 未解决</>}
                  </span>
                </div>
                <p className="qa-checklist-desc">{issue.description}</p>
                {issue.resolution_reason && (
                  <p className="qa-checklist-reason">{issue.resolution_reason}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {result.retry_instructions && (
        <div className="qa-section">
          <div className="qa-section-header">改进指引</div>
          <p className="qa-retry-instructions">{result.retry_instructions}</p>
        </div>
      )}
    </div>
  );
}

function QAHistoricalRounds({ rounds }: { rounds: QAResultType[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="qa-historical">
      <button
        type="button"
        className="qa-historical-toggle"
        onClick={() => setExpanded((v) => !v)}
      >
        <History size={14} />
        <span>历史轮次（{rounds.length}）</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded && (
        <div className="qa-historical-list">
          {rounds.map((result) => {
            const scorePercent = Math.round(result.overall_score * 100);
            const scoreClass = result.overall_score >= 0.7 ? 'pass' : 'fail';
            const hasRetryQueries = result.decision === 'retry_collection' && (result.retry_queries ?? []).length > 0;

            return (
              <div key={result.id} className={`qa-historical-card ${scoreClass}`}>
                <div className="qa-historical-header">
                  <span className="qa-historical-label">{roundLabel(result.iteration)}</span>
                  <span className={`qa-score-badge ${scoreClass}`}>{scorePercent}分</span>
                  <DecisionBadge decision={result.decision} hasRetryQueries={hasRetryQueries} queries={result.retry_queries} />
                </div>
                {result.retry_instructions && (
                  <p className="qa-historical-instructions">{result.retry_instructions}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function DecisionBadge({ decision, hasRetryQueries, queries }: { decision: string; hasRetryQueries: boolean; queries?: QARetryQuery[] }) {
  const [showQueries, setShowQueries] = useState(false);

  return (
    <>
      <span
        className={`qa-decision qa-decision-${decision}${hasRetryQueries ? ' qa-decision-clickable' : ''}`}
        onClick={() => hasRetryQueries && setShowQueries(true)}
        title={hasRetryQueries ? '点击查看重新采集关键词' : undefined}
      >
        {decision === 'pass' ? <CheckCircle2 size={13} /> : decision === 'retry_collection' ? <RefreshCw size={13} /> : <XCircle size={13} />}
        {decisionLabels[decision] ?? decision}
        {hasRetryQueries ? <Search size={12} style={{ marginLeft: 2 }} /> : null}
      </span>
      {showQueries && queries ? (
        <RetryQueriesModal queries={queries} onClose={() => setShowQueries(false)} />
      ) : null}
    </>
  );
}

function QAIssueItem({ issue }: { issue: QAIssue }) {
  return (
    <div className={`qa-issue qa-severity-${issue.severity}`}>
      <div className="qa-issue-header">
        <span className={`qa-severity-badge ${issue.severity}`}>{severityLabels[issue.severity] ?? issue.severity}</span>
        <span className="qa-dimension-badge">{dimensionLabels[issue.dimension] ?? issue.dimension}</span>
        {issue.competitor_name && issue.competitor_name !== 'report' && issue.competitor_name !== 'system' && (
          <span className="qa-competitor-badge">{issue.competitor_name}</span>
        )}
      </div>
      <p className="qa-issue-desc">{issue.description}</p>
      {issue.fix_suggestion && <p className="qa-issue-fix">{issue.fix_suggestion}</p>}
    </div>
  );
}

function RetryQueriesModal({ queries, onClose }: { queries: QARetryQuery[]; onClose: () => void }) {
  if (!queries?.length) return null;
  return (
    <div className="retry-queries-overlay" onClick={onClose}>
      <div className="retry-queries-modal" onClick={(e) => e.stopPropagation()}>
        <div className="retry-queries-header">
          <h3><Search size={16} /> 重新采集关键词</h3>
          <button type="button" className="retry-queries-close" onClick={onClose}>&times;</button>
        </div>
        <div className="retry-queries-body">
          <p className="retry-queries-hint">以下关键词由质检 Agent 生成，用于搜索引擎精准补采缺失维度的资料：</p>
          <ul className="retry-queries-list">
            {queries.map((q, i) => (
              <li key={i} className="retry-query-item">
                <div className="retry-query-header">
                  <span className="retry-query-competitor">{q.competitor_name}</span>
                  <span className="retry-query-slot">{slotLabels[q.slot] ?? q.slot}</span>
                </div>
                <code className="retry-query-text">{q.query}</code>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
