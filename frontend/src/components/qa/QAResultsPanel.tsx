import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import { getQAResults } from '../../lib/api';
import type { QAIssue, QAResult as QAResultType } from '../../lib/types';

const dimensionLabels: Record<string, string> = {
  evidence_grounding: '证据支撑度',
  citation_accuracy: '引用准确性',
  schema_completeness: 'Schema 完整度',
  coverage_gaps: '覆盖缺口',
  cross_competitor_consistency: '跨竞品一致性',
  factual_plausibility: '事实合理性',
};

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

      <div className="qa-decision-row">
        <span className={`qa-decision qa-decision-${result.decision}`}>
          {result.decision === 'pass' ? <CheckCircle2 size={13} /> : result.decision === 'retry_collection' ? <RefreshCw size={13} /> : <XCircle size={13} />}
          {decisionLabels[result.decision] ?? result.decision}
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
