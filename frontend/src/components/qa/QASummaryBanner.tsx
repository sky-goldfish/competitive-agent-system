import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldCheck } from 'lucide-react';
import { getQAResults } from '../../lib/api';
import type { QAResult as QAResultType } from '../../lib/types';

const decisionLabels: Record<string, string> = {
  pass: '质检通过',
  pass_with_quality_warning: '质检完成（质量预警）',
  retry_collection: '经重新采集后通过',
  retry_analysis: '经重新分析后通过',
  retry_collection_and_analysis: '经采集与分析后通过',
};

type Props = {
  runId: string;
};

export default function QASummaryBanner({ runId }: Props) {
  const qaQuery = useQuery({
    queryKey: ['qa-results', runId],
    queryFn: () => getQAResults(runId),
    enabled: Boolean(runId),
  });

  const results = qaQuery.data ?? [];
  if (results.length === 0) return null;

  const final = results[results.length - 1];
  const first = results[0];
  const totalIterations = results.length;
  const scorePercent = Math.round(final.overall_score * 100);
  const scoreClass = final.overall_score >= 0.7 ? 'pass' : 'fail';
  const scoreImproved = totalIterations > 1 && final.overall_score > first.overall_score;
  const unresolvedIssues = (final.issue_checklist ?? []).filter((i) => i.status === 'open' || i.status === 'unresolved');
  const unresolvedCritical = unresolvedIssues.filter((i) => i.severity === 'critical').length;
  const hasWarning = final.quality_warning || final.forced_pass || unresolvedIssues.length > 0;

  return (
    <div className={`qa-summary-banner ${scoreClass}`}>
      <div className="qa-banner-icon">
        {final.decision === 'pass' && !hasWarning ? <ShieldCheck size={22} /> : <AlertTriangle size={22} />}
      </div>
      <div className="qa-banner-body">
        <div className="qa-banner-title">
          <strong>{decisionLabels[final.decision] ?? '质检完成'}</strong>
          <span className={`qa-banner-score ${scoreClass}`}>{scorePercent} 分</span>
        </div>
        <p className="qa-banner-detail">
          {totalIterations > 1 ? `经过 ${totalIterations} 轮质检` : '首轮质检通过'}
          {scoreImproved ? `，分数从 ${Math.round(first.overall_score * 100)} 提升至 ${scorePercent}` : ''}
          {unresolvedCritical > 0 ? `（仍有 ${unresolvedCritical} 个严重问题）` : ''}
          {unresolvedIssues.length > 0 && unresolvedCritical === 0 ? `，仍有 ${unresolvedIssues.length} 个未解决问题` : ''}
          {final.forced_pass ? '，已达重试上限' : ''}
        </p>
      </div>
      <div className="qa-banner-badges">
        {results.map((r: QAResultType, i: number) => (
          <span key={r.id} className={`qa-round-pip ${r.overall_score >= 0.7 ? 'pass' : 'fail'}`} title={`第 ${i + 1} 轮: ${Math.round(r.overall_score * 100)} 分`}>
            {r.decision === 'pass' && !r.quality_warning ? <CheckCircle2 size={12} /> : <RefreshCw size={12} />}
          </span>
        ))}
      </div>
    </div>
  );
}
