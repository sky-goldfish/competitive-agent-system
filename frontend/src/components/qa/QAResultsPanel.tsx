import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, RefreshCw, Search, ShieldCheck, X, XCircle } from 'lucide-react';
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
        <p className="empty-state-desc">质检数据将在报告生成后自动展示。</p>
      </div>
    </section>
  );

  const sorted = [...results].sort((a, b) => b.iteration - a.iteration);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>质量检查</h2>
        <span>{results.length} 轮</span>
      </div>
      <div className="qa-results-panel">
        {sorted.map((result, index) => (
          <QAIterationCard key={result.id} result={result} index={index} total={sorted.length} prevResult={index < sorted.length - 1 ? sorted[index + 1] : undefined} />
        ))}
      </div>
    </section>
  );
}

function QAIterationCard({ result, index, total, prevResult }: { result: QAResultType; index: number; total: number; prevResult?: QAResultType }) {
  const scorePercent = Math.round(result.overall_score * 100);
  const scoreClass = result.overall_score >= 0.7 ? 'pass' : 'fail';
  const scoreDelta = prevResult ? result.overall_score - prevResult.overall_score : null;
  const [showRetryQueries, setShowRetryQueries] = useState(false);

  const hasRetryQueries = result.decision === 'retry_collection' && (result.retry_queries ?? []).length > 0;

  return (
    <div className={`qa-iteration-card ${scoreClass}`}>
      <div className="qa-iteration-header">
        <div className="qa-iteration-title">
          {result.decision === 'pass' ? <ShieldCheck size={16} /> : <AlertTriangle size={16} />}
          <strong>第 {result.iteration} 轮质检{index === 0 && total > 1 ? '（最终）' : ''}</strong>
        </div>
        <div className={`qa-score-badge ${scoreClass}`}>{scorePercent}分</div>
      </div>

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
        <span
          className={`qa-decision qa-decision-${result.decision}${hasRetryQueries ? ' qa-decision-clickable' : ''}`}
          onClick={() => hasRetryQueries && setShowRetryQueries(true)}
          title={hasRetryQueries ? '点击查看重新采集关键词' : undefined}
        >
          {result.decision === 'pass' ? <CheckCircle2 size={13} /> : result.decision === 'retry_collection' ? <RefreshCw size={13} /> : <XCircle size={13} />}
          {decisionLabels[result.decision] ?? result.decision}
          {hasRetryQueries ? <Search size={12} style={{ marginLeft: 2 }} /> : null}
        </span>
        {scoreDelta !== null && (
          <span className={`qa-score-delta ${scoreDelta > 0 ? 'up' : scoreDelta < 0 ? 'down' : 'flat'}`}>
            {scoreDelta > 0 ? '+' : ''}{Math.round(scoreDelta * 100)} 分
          </span>
        )}
      </div>

      {result.issues.length > 0 && (
        <div className="qa-issues-list">
          {result.issues.map((issue, i) => (
            <QAIssueItem key={i} issue={issue} />
          ))}
        </div>
      )}

      {result.retry_instructions && (
        <div className="qa-retry-instructions">
          <dt>改进指引</dt>
          <dd>{result.retry_instructions}</dd>
        </div>
      )}

      {showRetryQueries && (
        <RetryQueriesModal queries={result.retry_queries} onClose={() => setShowRetryQueries(false)} />
      )}
    </div>
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

const slotLabels: Record<string, string> = {
  core_features: '核心功能',
  pricing: '价格与商业模式',
  positioning: '产品定位',
  user_feedback: '用户评价与痛点',
  market_signal: '市场信号',
  risk_opportunity: '风险与机会',
  relationship_evidence: '竞争关系',
};

function RetryQueriesModal({ queries, onClose }: { queries: QARetryQuery[]; onClose: () => void }) {
  return (
    <div className="retry-queries-overlay" onClick={onClose}>
      <div className="retry-queries-modal" onClick={(e) => e.stopPropagation()}>
        <div className="retry-queries-header">
          <h3><Search size={16} /> 重新采集关键词</h3>
          <button type="button" className="retry-queries-close" onClick={onClose}><X size={16} /></button>
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
