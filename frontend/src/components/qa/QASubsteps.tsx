import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { getQAResults } from '../../lib/api';
import type { QAResult as QAResultType, Trace } from '../../lib/types';
import QAResultsPanel from './QAResultsPanel';

type QASubstepKind =
  | 'quality_check'
  | 'material_collection'
  | 'structured_analysis'
  | 'report_generation';

interface QASubstep {
  kind: QASubstepKind;
  status: 'completed' | 'running';
  durationMs: number | null;
  score: number | null;
  decision: string | null;
  issueCount: number | null;
}

interface QARound {
  roundIndex: number;
  substeps: QASubstep[];
  finalScore: number | null;
  finalDecision: string | null;
  issueCount: number | null;
  isCompleted: boolean;
  isCurrent: boolean;
}

const substepLabels: Record<QASubstepKind, string> = {
  quality_check: '检查报告质量',
  material_collection: '重新采集资料',
  structured_analysis: '重新分析',
  report_generation: '更新报告',
};

const decisionShortLabels: Record<string, string> = {
  pass: '通过',
  retry_collection: '重新采集',
  retry_analysis: '重新分析',
};

function formatDuration(ms: number | null): string {
  if (ms == null) return '';
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  return rem > 0 ? `${min}m${rem}s` : `${min}m`;
}

function parseOutputJson(trace: Trace): Record<string, unknown> {
  if (!trace.output_json) return {};
  try {
    return JSON.parse(trace.output_json);
  } catch {
    return {};
  }
}

function buildQARounds(traces: Trace[]): QARound[] {
  const qaTraces: { trace: Trace; index: number }[] = [];
  traces.forEach((t, i) => {
    if (normalizeStageLocal(t.stage) === 'quality_check') {
      qaTraces.push({ trace: t, index: i });
    }
  });

  if (qaTraces.length === 0) return [];

  const rounds: QARound[] = [];
  const isQACompleted = qaTraces.every((qt) => qt.trace.status === 'completed') &&
    qaTraces[qaTraces.length - 1].trace.status === 'completed';

  for (let qi = 0; qi < qaTraces.length; qi++) {
    const { trace: qaTrace, index: qaIdx } = qaTraces[qi];
    const nextQaIdx = qi + 1 < qaTraces.length ? qaTraces[qi + 1].index : traces.length;
    const output = parseOutputJson(qaTrace);

    const substeps: QASubstep[] = [];

    substeps.push({
      kind: 'quality_check',
      status: qaTrace.status === 'completed' ? 'completed' : 'running',
      durationMs: qaTrace.duration_ms,
      score: typeof output.overall_score === 'number' ? Math.round(output.overall_score * 100) : null,
      decision: typeof output.decision === 'string' ? output.decision : null,
      issueCount: typeof output.issue_count === 'number' ? output.issue_count : null,
    });

    const repairStages: QASubstepKind[] = ['material_collection', 'structured_analysis', 'report_generation'];
    for (let ti = qaIdx + 1; ti < nextQaIdx; ti++) {
      const t = traces[ti];
      const norm = normalizeStageLocal(t.stage);
      if (repairStages.includes(norm as QASubstepKind)) {
        substeps.push({
          kind: norm as QASubstepKind,
          status: t.status === 'completed' ? 'completed' : 'running',
          durationMs: t.duration_ms,
          score: null,
          decision: null,
          issueCount: null,
        });
      }
    }

    const isLastRound = qi === qaTraces.length - 1;
    const roundCompleted = qaTrace.status === 'completed';
    const isCurrent = isLastRound && !roundCompleted;

    rounds.push({
      roundIndex: qi + 1,
      substeps,
      finalScore: substeps[0].score,
      finalDecision: substeps[0].decision,
      issueCount: substeps[0].issueCount,
      isCompleted: roundCompleted,
      isCurrent,
    });
  }

  return rounds;
}

function normalizeStageLocal(stage: string): string {
  const aliases: Record<string, string> = {
    quart_planning: 'material_collection',
    material_query_planning: 'material_collection',
    source_search: 'material_collection',
    source_classification: 'material_collection',
    evidence_extraction: 'material_collection',
    coverage_checking: 'material_collection',
  };
  return aliases[stage] ?? stage;
}

function SubstepIcon({ substep }: { substep: QASubstep }) {
  if (substep.status === 'running') {
    return <Loader2 size={14} className="spinning qa-substep-icon running" />;
  }
  if (substep.kind === 'quality_check') {
    if (substep.decision === 'pass') return <CheckCircle2 size={14} className="qa-substep-icon pass" />;
    if (substep.decision) return <AlertTriangle size={14} className="qa-substep-icon retry" />;
    return <CheckCircle2 size={14} className="qa-substep-icon pass" />;
  }
  return <CheckCircle2 size={14} className="qa-substep-icon done" />;
}

function SubstepRow({ substep }: { substep: QASubstep }) {
  const label = substepLabels[substep.kind] ?? substep.kind;

  return (
    <div className={`qa-substep-row ${substep.status}`}>
      <SubstepIcon substep={substep} />
      <span className="qa-substep-label">{label}</span>
      {substep.status === 'completed' && substep.durationMs != null ? (
        <span className="qa-substep-duration">{formatDuration(substep.durationMs)}</span>
      ) : null}
      {substep.kind === 'quality_check' && substep.score != null && substep.status === 'completed' ? (
        <span className={`qa-substep-score ${substep.score >= 70 ? 'pass' : 'fail'}`}>
          {substep.score} 分
        </span>
      ) : null}
      {substep.status === 'running' ? (
        <span className="qa-substep-running-text">
          {substep.kind === 'quality_check' ? '正在质检...' :
           substep.kind === 'material_collection' ? '正在重新采集资料...' :
           substep.kind === 'structured_analysis' ? '正在重新分析...' :
           '正在更新报告...'}
        </span>
      ) : null}
    </div>
  );
}

function DecisionNote({ substep }: { substep: QASubstep }) {
  if (substep.kind !== 'quality_check' || substep.status !== 'completed' || !substep.decision || substep.decision === 'pass') {
    return null;
  }
  const label = decisionShortLabels[substep.decision] ?? substep.decision;
  return (
    <div className="qa-substep-decision-note">
      <AlertTriangle size={13} />
      <span>发现{substep.issueCount != null ? ` ${substep.issueCount} 个问题` : '问题'}，决定{label}</span>
    </div>
  );
}

function QARoundBlock({ round }: { round: QARound }) {
  return (
    <div className={`qa-round-block ${round.isCurrent ? 'current' : ''} ${round.isCompleted ? 'completed' : ''}`}>
      <div className="qa-round-header">
        {round.isCurrent ? (
          <Loader2 size={14} className="spinning" />
        ) : round.finalDecision === 'pass' ? (
          <CheckCircle2 size={14} className="qa-round-icon pass" />
        ) : (
          <RefreshCw size={14} className="qa-round-icon retry" />
        )}
        <span className="qa-round-label">第 {round.roundIndex} 轮质检</span>
        {round.isCompleted && round.finalScore != null ? (
          <span className={`qa-round-score ${round.finalScore >= 70 ? 'pass' : 'fail'}`}>
            {round.finalScore} 分
          </span>
        ) : null}
        {round.isCompleted && round.finalDecision && round.finalDecision !== 'pass' ? (
          <span className="qa-round-decision-tag">{decisionShortLabels[round.finalDecision]}</span>
        ) : null}
      </div>
      <div className="qa-round-substeps">
        {round.substeps.map((substep) => (
          <div key={`${substep.kind}-${substep.status}`}>
            <SubstepRow substep={substep} />
            <DecisionNote substep={substep} />
          </div>
        ))}
      </div>
    </div>
  );
}

function CompletedSummary({ rounds }: { rounds: QARound[] }) {
  const finalRound = rounds[rounds.length - 1];
  const finalScore = finalRound?.finalScore;
  const passed = finalRound?.finalDecision === 'pass';

  return (
    <div className={`qa-completed-summary ${passed ? 'pass' : 'fail'}`}>
      <div className="qa-summary-header">
        {passed ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        <strong>{passed ? '通过' : '未通过'}</strong>
        {finalScore != null ? <span className="qa-summary-score">{finalScore} 分</span> : null}
        <span className="qa-summary-rounds">共 {rounds.length} 轮</span>
      </div>
      <div className="qa-summary-round-list">
        {rounds.map((round) => (
          <div key={round.roundIndex} className="qa-summary-round-item">
            <span className="qa-summary-round-label">第 {round.roundIndex} 轮</span>
            {round.finalScore != null ? (
              <span className={`qa-summary-round-score ${round.finalScore >= 70 ? 'pass' : 'fail'}`}>
                {round.finalScore} 分
              </span>
            ) : null}
            {round.finalDecision === 'pass' ? (
              <span className="qa-summary-round-result pass">通过 ✅</span>
            ) : round.finalDecision ? (
              <span className="qa-summary-round-result retry">{decisionShortLabels[round.finalDecision]}</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

type Props = {
  runId: string;
  traces: Trace[];
  stageStatus: string;
};

export default function QASubsteps({ runId, traces, stageStatus }: Props) {
  const [expanded, setExpanded] = useState(true);
  const qaQuery = useQuery({
    queryKey: ['qa-results', runId],
    queryFn: () => getQAResults(runId),
    enabled: Boolean(runId),
  });

  const qaResults = qaQuery.data ?? [];
  const rounds = useMemo(() => buildQARounds(traces), [traces]);
  const isAllCompleted = rounds.length > 0 && rounds.every((r) => r.isCompleted);
  const finalPassed = rounds.length > 0 && rounds[rounds.length - 1].finalDecision === 'pass';

  if (rounds.length === 0) {
    if (stageStatus === 'running') {
      return (
        <div className="qa-substeps-container">
          <div className="qa-substeps-running-header">
            <Loader2 size={16} className="spinning" />
            <span>正在质检...</span>
          </div>
        </div>
      );
    }
    return null;
  }

  if (isAllCompleted && finalPassed) {
    return (
      <div className="qa-substeps-container">
        <CompletedSummary rounds={rounds} />
        {rounds.length > 1 && (
          <button
            type="button"
            className="qa-expand-toggle"
            onClick={() => setExpanded(!expanded)}
          >
            <span>{expanded ? '收起详情' : '展开详情'}</span>
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        )}
        {expanded && (
          <div className="qa-substeps-rounds">
            {rounds.map((round) => (
              <QARoundBlock key={round.roundIndex} round={round} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="qa-substeps-container">
      <div className="qa-substeps-rounds">
        {rounds.map((round) => (
          <QARoundBlock key={round.roundIndex} round={round} />
        ))}
      </div>
      {!isAllCompleted && qaResults.length > 0 && (
        <button
          type="button"
          className="qa-expand-toggle"
          onClick={() => setExpanded(!expanded)}
        >
          <span>{expanded ? '收起质检详情' : '查看详细质检报告'}</span>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      )}
      {expanded && qaResults.length > 0 && <QAResultsPanel runId={runId} />}
    </div>
  );
}
