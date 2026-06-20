import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  History,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
  XCircle,
} from 'lucide-react';
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
  pass_with_quality_warning: '质量预警通过',
  retry_collection: '重新采集',
  retry_analysis: '重新分析',
  retry_collection_and_analysis: '重新采集+分析',
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

type RoundGroup = {
  round: QAResultType;
  verifications: QAResultType[];
};

function groupQAResults(results: QAResultType[]): RoundGroup[] {
  const fullChecks = results.filter((r) => r.check_phase === 'full_check');
  const verifications = results.filter((r) => r.check_phase === 'issue_verification');

  const groups: RoundGroup[] = [];
  for (let i = 0; i < fullChecks.length; i++) {
    const round = fullChecks[i];
    const nextFullCheckIteration = fullChecks[i + 1]?.iteration ?? Infinity;
    const roundVerifications = verifications.filter(
      (v) => v.iteration > round.iteration && v.iteration < nextFullCheckIteration,
    );
    groups.push({ round, verifications: roundVerifications });
  }
  return groups;
}

function ScoreBar({ score, className = '' }: { score: number; className?: string }) {
  const pct = Math.round(score * 100);
  const cls = score >= 0.7 ? 'pass' : 'fail';
  return (
    <div className={`qa-modal-score-bar track ${className}`}>
      <div className={`qa-modal-score-bar fill ${cls}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function DimensionScoreRow({ dimension, score }: { dimension: string; score: number }) {
  const pct = Math.round(score * 100);
  const cls = pct >= 70 ? 'pass' : 'fail';
  return (
    <div className="qa-modal-dim-row">
      <span className="qa-modal-dim-label">{dimensionLabels[dimension] ?? dimension}</span>
      <strong className={`qa-modal-dim-value ${cls}`}>{pct}</strong>
      <div className="qa-modal-dim-track">
        <div className={`qa-modal-dim-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function IssueItem({ issue, showStatus = true }: { issue: QAIssue; showStatus?: boolean }) {
  const isRuleBased = issue.id?.startsWith('det_');
  return (
    <div className={`qa-modal-issue severity-${issue.severity}`}>
      <div className="qa-modal-issue-head">
        <span className={`qa-severity-badge ${issue.severity}`}>
          {severityLabels[issue.severity] ?? issue.severity}
        </span>
        <span className="qa-dimension-badge">{dimensionLabels[issue.dimension] ?? issue.dimension}</span>
        {issue.competitor_name && issue.competitor_name !== 'report' && issue.competitor_name !== 'system' && (
          <span className="qa-competitor-badge">{issue.competitor_name}</span>
        )}
        <span className={`qa-source-badge ${isRuleBased ? 'rule' : 'llm'}`}>
          {isRuleBased ? '规则' : 'LLM'}
        </span>
        {showStatus && issue.status && (
          <span className={`qa-modal-issue-status qa-modal-issue-status-${issue.status}`}>
            {issue.status === 'resolved'
              ? <><CheckCircle2 size={11} /> 第{issue.resolved_iteration}轮已解决</>
              : issue.status === 'unresolved'
              ? <><AlertTriangle size={11} /> 未解决（达上限）</>
              : <><Circle size={11} /> 未解决</>}
          </span>
        )}
      </div>
      <p className="qa-modal-issue-desc">{issue.description}</p>
      {issue.fix_suggestion && <p className="qa-modal-issue-fix">建议：{issue.fix_suggestion}</p>}
      {issue.resolution_reason && (
        <p className="qa-modal-issue-reason">{issue.resolution_reason}</p>
      )}
    </div>
  );
}

function RetryQueriesSection({ queries }: { queries: QARetryQuery[] }) {
  const [show, setShow] = useState(false);
  if (!queries?.length) return null;
  return (
    <div className="qa-modal-retry-queries">
      <button type="button" className="qa-modal-link-btn" onClick={() => setShow((v) => !v)}>
        <Search size={13} /> 重采关键词（{queries.length} 条）
        {show ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {show && (
        <ul className="qa-modal-query-list">
          {queries.map((q, i) => (
            <li key={i}>
              <span className="qa-modal-query-meta">
                <span>{q.competitor_name}</span>
                <span className="qa-modal-query-slot">{slotLabels[q.slot] ?? q.slot}</span>
              </span>
              <code>{q.query}</code>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FullCheckTab({ group }: { group: RoundGroup }) {
  const r = group.verifications[group.verifications.length - 1] ?? group.round;
  const scorePct = Math.round(r.overall_score * 100);
  const cls = r.overall_score >= 0.7 ? 'pass' : 'fail';
  const unresolvedIssues = (r.issue_checklist ?? []).filter((issue) => issue.status === 'open' || issue.status === 'unresolved');

  return (
    <div className="qa-modal-round-body">
      <div className="qa-modal-round-summary">
        <div className="qa-modal-round-summary-left">
          {r.decision === 'pass' && !r.quality_warning
            ? <ShieldCheck size={18} className={cls} />
            : <AlertTriangle size={18} className={cls} />}
          <strong>全面检查</strong>
          <span className={`qa-modal-score-pill ${cls}`}>{scorePct} 分</span>
          <span className={`qa-modal-decision qa-modal-decision-${r.decision}`}>
            {r.decision === 'pass' ? <CheckCircle2 size={13} />
              : r.decision === 'pass_with_quality_warning' ? <AlertTriangle size={13} />
              : r.decision === 'retry_collection' || r.decision === 'retry_analysis' || r.decision === 'retry_collection_and_analysis' ? <RefreshCw size={13} />
              : <XCircle size={13} />}
            {decisionLabels[r.decision] ?? r.decision}
          </span>
        </div>
        {r.forced_pass && (
          <span className="qa-modal-forced-tag">
            <AlertTriangle size={12} /> 已达上限，强制通过
          </span>
        )}
      </div>

      {(r.quality_warning || r.forced_pass || unresolvedIssues.length > 0) && (
        <div className="qa-modal-warning">
          <AlertTriangle size={13} />
          结构化分析质量存在风险（{scorePct}分）{r.forced_pass ? '，系统已达到重试上限' : ''}{unresolvedIssues.length > 0 ? `，仍有 ${unresolvedIssues.length} 个问题未解决` : ''}。
        </div>
      )}

      <ScoreBar score={r.overall_score} />

      {Object.keys(r.dimension_scores ?? {}).length > 0 && (
        <div className="qa-modal-dims">
          {dimensionOrder.map((dim) => {
            const s = r.dimension_scores[dim];
            if (s == null) return null;
            return <DimensionScoreRow key={dim} dimension={dim} score={s} />;
          })}
        </div>
      )}

      {r.issues.length > 0 && (
        <div className="qa-modal-section">
          <h4>发现 {r.issues.length} 个问题</h4>
          {r.issues.map((issue: QAIssue, i: number) => (
            <IssueItem key={issue.id ?? i} issue={issue} showStatus={false} />
          ))}
        </div>
      )}

      <RetryQueriesSection queries={r.retry_queries} />

      {r.retry_instructions && (
        <div className="qa-modal-section">
          <h4>改进指引</h4>
          <p className="qa-modal-instructions">{r.retry_instructions}</p>
        </div>
      )}

      {group.verifications.length > 0 && (
        <div className="qa-modal-section">
          <h4>
            <History size={13} /> 专项复核（{group.verifications.length} 次）
          </h4>
          {group.verifications.map((v, i) => {
            const vPct = Math.round(v.overall_score * 100);
            const vCls = v.overall_score >= 0.7 ? 'pass' : 'fail';
            return (
              <div key={v.id} className="qa-modal-verification">
                <div className="qa-modal-verification-head">
                  <span className="qa-modal-verification-label">复核-{i + 1}</span>
                  <span className={`qa-modal-score-pill small ${vCls}`}>{vPct} 分</span>
                  <span className={`qa-modal-decision qa-modal-decision-${v.decision}`}>
                    {v.decision === 'pass' ? <CheckCircle2 size={11} /> : <RefreshCw size={11} />}
                    {decisionLabels[v.decision] ?? v.decision}
                  </span>
                </div>
                {v.issues.length > 0 && (
                  <div className="qa-modal-verification-issues">
                    {v.issues.map((issue: QAIssue, j: number) => (
                      <IssueItem key={issue.id ?? j} issue={issue} showStatus={false} />
                    ))}
                  </div>
                )}
                {v.retry_instructions && (
                  <p className="qa-modal-verification-instructions">{v.retry_instructions}</p>
                )}
                {v.retry_queries?.length > 0 && <RetryQueriesSection queries={v.retry_queries} />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ChecklistTab({ groups }: { groups: RoundGroup[] }) {
  // Collect all checklist items, deduplicating by id (keep last occurrence = most recent status)
  const idMap = new Map<string, QAIssue>();
  for (const g of groups) {
    const items = (g.round.issue_checklist ?? []).slice();
    for (const v of g.verifications) {
      items.push(...(v.issue_checklist ?? []));
      for (const issue of v.issues) {
        if (issue.status && issue.id && !items.find((i) => i.id === issue.id)) {
          items.push(issue);
        }
      }
    }
    for (const item of items) {
      if (item.id) idMap.set(item.id, item);
    }
  }
  const allChecklists = Array.from(idMap.values());

  if (allChecklists.length === 0) {
    return (
      <div className="qa-modal-round-body">
        <p className="qa-modal-empty">暂无问题追踪记录。所有轮次的全面检查均未生成待追踪问题。</p>
      </div>
    );
  }

  const resolved = allChecklists.filter((i) => i.status === 'resolved');
  const open = allChecklists.filter((i) => i.status === 'open' || !i.status);
  const unresolved = allChecklists.filter((i) => i.status === 'unresolved');

  return (
    <div className="qa-modal-round-body">
      <div className="qa-modal-checklist-summary">
        <div className="qa-modal-checklist-stat resolved">
          <CheckCircle2 size={15} />
          <span>已解决 {resolved.length}</span>
        </div>
        <div className="qa-modal-checklist-stat open">
          <Circle size={15} />
          <span>未解决 {open.length}</span>
        </div>
        {unresolved.length > 0 && (
          <div className="qa-modal-checklist-stat unresolved">
            <AlertTriangle size={15} />
            <span>达上限未解决 {unresolved.length}</span>
          </div>
        )}
      </div>

      {allChecklists.map((issue: QAIssue, i: number) => (
        <IssueItem key={`cl-${issue.id ?? i}`} issue={issue} showStatus />
      ))}
    </div>
  );
}

type Props = {
  runId: string;
  onClose: () => void;
};

export default function QAReviewModal({ runId, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<'checklist' | number>('checklist');

  const qaQuery = useQuery({
    queryKey: ['qa-results', runId],
    queryFn: () => getQAResults(runId),
    enabled: Boolean(runId),
  });

  const results = qaQuery.data ?? [];
  const groups = groupQAResults(results);

  return (
    <div className="qa-modal-overlay" onClick={onClose}>
      <div className="qa-modal" onClick={(e) => e.stopPropagation()}>
        <div className="qa-modal-header">
          <div className="qa-modal-header-left">
            <ShieldCheck size={18} />
            <h2>质检详情</h2>
            {groups.length > 0 && (
              <span className="qa-modal-header-meta">共 {groups.length} 轮全面检查</span>
            )}
          </div>
          <button type="button" className="qa-modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {qaQuery.isLoading ? (
          <div className="qa-modal-body">
            <p className="qa-modal-loading">加载质检结果...</p>
          </div>
        ) : results.length === 0 ? (
          <div className="qa-modal-body">
            <p className="qa-modal-empty">暂无质检结果</p>
          </div>
        ) : (
          <>
            <div className="qa-modal-tabs">
              <button
                type="button"
                className={`qa-modal-tab ${activeTab === 'checklist' ? 'active' : ''}`}
                onClick={() => setActiveTab('checklist')}
              >
                <History size={13} />
                Issue 追踪清单
              </button>
              {groups.map((g, i) => (
                <button
                  key={g.round.id}
                  type="button"
                  className={`qa-modal-tab ${activeTab === i ? 'active' : ''}`}
                  onClick={() => setActiveTab(i)}
                >
                  {g.round.decision === 'pass' || g.round.decision === 'pass_with_quality_warning'
                    ? <CheckCircle2 size={13} />
                    : <RefreshCw size={13} />}
                  第 {i + 1} 轮
                  <span className={`qa-modal-tab-score ${Math.round(g.round.overall_score * 100) >= 70 ? 'pass' : 'fail'}`}>
                    {Math.round(g.round.overall_score * 100)}
                  </span>
                </button>
              ))}
            </div>

            <div className="qa-modal-body">
              {activeTab === 'checklist' ? (
                <ChecklistTab groups={groups} />
              ) : (
                groups[activeTab] && <FullCheckTab group={groups[activeTab]} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
