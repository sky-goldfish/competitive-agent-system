import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import CompetitorConfirmPanel from '../components/competitors/CompetitorConfirmPanel';
import EvidenceList from '../components/evidence/EvidenceList';
import SourceList from '../components/evidence/SourceList';
import QAResultsPanel from '../components/qa/QAResultsPanel';
import QASummaryBanner from '../components/qa/QASummaryBanner';
import CitationBundleView from '../components/report/CitationBundleView';
import ReportMarkdown from '../components/report/ReportMarkdown';
import AgentTimeline from '../components/timeline/AgentTimeline';
import { answerRunClarification, getCompetitors, getEvidence, getReport, getReportCitationBundle, getReportCitations, getReportVersions, getRun, getSources, getTimeline, regenerateReport } from '../lib/api';
import type { Run, Trace } from '../lib/types';

const statusLabels: Record<string, string> = {
  running: '执行中',
  waiting_for_clarification: '等待需求补充',
  waiting_for_human: '等待人工确认',
  completed: '报告已生成',
  failed: '执行失败',
};

const stageOrder = [
  'requirement_understanding',
  'requirement_clarification',
  'human_confirm_competitors',
  'material_collection',
  'structured_analysis',
  'report_generation',
  'quality_check',
  'completed',
];

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  requirement_clarification: '需求澄清',
  focus_profile: '识别个性化关注点',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
  quality_check: '质量检查',
  completed: '完成',
  failed: '失败',
};

const stageAliases: Record<string, string> = {
  competitor_discovery: 'requirement_understanding',
  target_query_planning: 'requirement_understanding',
  target_search: 'requirement_understanding',
  target_understanding: 'requirement_understanding',
  competitor_query_planning: 'requirement_understanding',
  competitor_search: 'requirement_understanding',
  candidate_extraction: 'requirement_understanding',
  official_site_resolution: 'requirement_understanding',
  material_query_planning: 'material_collection',
  source_search: 'material_collection',
  source_classification: 'material_collection',
  evidence_extraction: 'material_collection',
  coverage_checking: 'material_collection',
};

function normalizeStage(stage: string) {
  return stageAliases[stage] ?? stage;
}

function getStagePath(run: Run, traces: Trace[]) {
  const reached = new Set<string>();
  traces.forEach((trace) => {
    const stage = normalizeStage(trace.stage);
    if (stageOrder.includes(stage)) reached.add(stage);
  });
  reached.add(normalizeStage(run.current_stage));
  if (run.status === 'waiting_for_human') reached.add('human_confirm_competitors');
  if (run.status === 'waiting_for_clarification') reached.add('requirement_clarification');
  if (run.status === 'completed') {
    stageOrder.forEach((stage) => reached.add(stage));
  }
  if (run.status === 'failed') reached.add('failed');

  const highestIndex = Math.max(0, ...stageOrder.map((stage, index) => (reached.has(stage) ? index : -1)));
  const path = stageOrder.slice(0, highestIndex + 1);
  if (run.status === 'failed') path.push('failed');
  return path;
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const id = runId ?? '';
  const queryClient = useQueryClient();
  const [mainTab, setMainTab] = useState<'process' | 'report'>('process');
  const [selectedIteration, setSelectedIteration] = useState<number | undefined>(undefined);
  const [workbenchTab, setWorkbenchTab] = useState<'info' | 'sources' | 'competitors' | 'citations' | 'qa'>('info');
  const [clarificationAnswer, setClarificationAnswer] = useState('');

  const regenerateMutation = useMutation({
    mutationFn: () => regenerateReport(id),
    onSuccess: () => {
      setSelectedIteration(undefined);
      queryClient.invalidateQueries({ queryKey: ['run', id] });
      queryClient.invalidateQueries({ queryKey: ['report', id] });
      queryClient.invalidateQueries({ queryKey: ['report-versions', id] });
      queryClient.invalidateQueries({ queryKey: ['report-citations', id] });
      queryClient.invalidateQueries({ queryKey: ['citation-bundle', id] });
    },
  });
  const clarificationMutation = useMutation({
    mutationFn: () => answerRunClarification(id, clarificationAnswer.trim()),
    onSuccess: () => {
      setClarificationAnswer('');
      queryClient.invalidateQueries({ queryKey: ['run', id] });
      queryClient.invalidateQueries({ queryKey: ['timeline', id] });
    },
  });

  const runQuery = useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id),
    enabled: Boolean(id),
    refetchInterval: (query) => ['running', 'waiting_for_human', 'waiting_for_clarification'].includes(query.state.data?.status ?? '') ? 3000 : false,
  });
  const run = runQuery.data;
  const isActive = run?.status === 'running' || run?.status === 'waiting_for_human' || run?.status === 'waiting_for_clarification';
  const competitorsQuery = useQuery({ queryKey: ['competitors', id], queryFn: () => getCompetitors(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const timelineQuery = useQuery({ queryKey: ['timeline', id], queryFn: () => getTimeline(id), enabled: Boolean(id), refetchInterval: isActive ? 3000 : false });
  const sourcesQuery = useQuery({ queryKey: ['sources', id], queryFn: () => getSources(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const evidenceQuery = useQuery({ queryKey: ['evidence', id], queryFn: () => getEvidence(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const hasReport = run?.status === 'completed' || run?.current_stage === 'report_generation' || run?.current_stage === 'quality_check' || (run?.feedback_loop_count ?? 0) > 0;
  const reportQuery = useQuery({ queryKey: ['report', id, selectedIteration], queryFn: () => getReport(id, selectedIteration), enabled: Boolean(id) && Boolean(hasReport), refetchInterval: isActive ? 3000 : false });
  const reportVersionsQuery = useQuery({ queryKey: ['report-versions', id], queryFn: () => getReportVersions(id), enabled: Boolean(id) && Boolean(hasReport), refetchInterval: isActive ? 3000 : false });
  const displayedReportIteration = reportQuery.data?.iteration;
  const citationsQuery = useQuery({
    queryKey: ['report-citations', id, displayedReportIteration],
    queryFn: () => getReportCitations(id, displayedReportIteration),
    enabled: Boolean(id) && displayedReportIteration != null,
  });
  const hasAnalyses = run?.current_stage === 'structured_analysis' || run?.current_stage === 'report_generation' || run?.current_stage === 'quality_check' || run?.current_stage === 'completed' || run?.status === 'completed' || run?.current_stage === 'material_collection';
  const citationBundleQuery = useQuery({
    queryKey: ['citation-bundle', id],
    queryFn: () => getReportCitationBundle(id),
    enabled: Boolean(id) && hasAnalyses,
    refetchInterval: isActive ? 5000 : false,
  });

  useEffect(() => {
    if (run?.status === 'waiting_for_clarification') setWorkbenchTab('info');
    if (run?.status === 'waiting_for_human') setWorkbenchTab('competitors');
    if (run?.status === 'running' && run.current_stage === 'material_collection') setWorkbenchTab('sources');
  }, [run?.current_stage, run?.status]);

  useEffect(() => {
    if (run?.status === 'completed' && reportQuery.data) {
      setMainTab('report');
    }
  }, [run?.status, reportQuery.data]);

  const traces = timelineQuery.data ?? [];
  const stagePath = useMemo(() => run ? getStagePath(run, traces) : [], [run, traces]);

  if (runQuery.isLoading) return <p className="loading">加载任务中...</p>;
  if (runQuery.isError || !run) return <p className="error-text">任务加载失败。</p>;

  const competitors = competitorsQuery.data ?? [];
  const sources = sourcesQuery.data ?? [];
  const evidence = evidenceQuery.data ?? [];
  const report = reportQuery.data;
  const canShowReport = Boolean(hasReport) && Boolean(report);

  return (
    <div className="workbench-page">
      <nav className="stage-strip" aria-label="任务阶段">
        <div className="stage-path">
          {stagePath.map((stage, index) => (
            <span key={`${stage}-${index}`} className={stage === normalizeStage(run.current_stage) ? 'active' : ''}>
              {stageLabels[stage] ?? stage}
            </span>
          ))}
        </div>
        <span className={`text-status ${run.status}`}>{statusLabels[run.status] ?? run.status}</span>
      </nav>

      {run.error_message ? <p className="error-text workbench-error">{run.error_message}</p> : null}

      <div className="workbench-layout">
        <section className="workbench-main">
          <div className="workspace-tabs">
            <button type="button" className={mainTab === 'process' ? 'active' : ''} onClick={() => setMainTab('process')}>任务过程</button>
            <button type="button" className={mainTab === 'report' ? 'active' : ''} onClick={() => setMainTab('report')}>分析报告</button>
            {run.status === 'completed' ? (
              <button
                type="button"
                className="workspace-regenerate"
                onClick={() => {
                  if (window.confirm('确定要重新生成报告吗？将使用现有的搜索和分析结果重新生成。')) {
                    regenerateMutation.mutate();
                  }
                }}
                disabled={regenerateMutation.isPending}
              >
                {regenerateMutation.isPending ? '生成中...' : '重新生成'}
              </button>
            ) : null}
          </div>

          {mainTab === 'process' ? (
            <AgentTimeline traces={traces} run={run} compactHeader />
          ) : null}

          {mainTab === 'report' ? (
            <div className="report-container">
              {canShowReport ? (
                <div className="report-completion-banner">
                  <div className="completion-icon">✓</div>
                  <div className="completion-content">
                    <h3>分析报告已生成</h3>
                    <p>竞品数：{competitors.length} | 资料采集：{sources.length} | 洞察分析：{evidence.length}</p>
                  </div>
                </div>
              ) : null}
              {Boolean(hasReport) ? <QASummaryBanner runId={id} /> : null}
              {(() => {
                const versions = reportVersionsQuery.data ?? [];
                if (versions.length > 1) {
                  return (
                    <div className="report-version-selector">
                      <span className="report-version-label">报告版本：</span>
                      {versions.map((v) => (
                        <button
                          key={v.id}
                          type="button"
                          className={`report-version-btn ${(selectedIteration ?? versions[versions.length - 1].iteration) === v.iteration ? 'active' : ''}`}
                          onClick={() => setSelectedIteration(v.iteration)}
                        >
                          {v.iteration === 0 ? '初始版本' : `第 ${v.iteration} 轮`}
                        </button>
                      ))}
                    </div>
                  );
                }
                return null;
              })()}
              <article className="report-document">
                {reportQuery.isLoading ? <p className="loading">加载报告中...</p> : null}
                {reportQuery.isError ? <p className="error-text">报告加载失败。</p> : null}
                {canShowReport && report ? (
                  <ReportMarkdown markdown={report.markdown_content} citations={citationsQuery.data ?? []} />
                ) : null}
                {!reportQuery.isLoading && !reportQuery.isError && !canShowReport ? (
                  <div className="empty-state">
                    <p className="empty-state-title">报告尚未生成</p>
                    <p className="empty-state-desc">请先完成竞品确认和资料采集，报告将在分析完成后自动生成。</p>
                  </div>
                ) : null}
              </article>
            </div>
          ) : null}
        </section>

        <aside className="workbench-side">
          <div className="workbench-tabs">
            <button type="button" className={workbenchTab === 'info' ? 'active' : ''} onClick={() => setWorkbenchTab('info')}>任务信息</button>
            <button type="button" className={workbenchTab === 'competitors' ? 'active' : ''} onClick={() => setWorkbenchTab('competitors')}>竞品确认</button>
            <button type="button" className={workbenchTab === 'sources' ? 'active' : ''} onClick={() => setWorkbenchTab('sources')}>搜索结果</button>
            <button type="button" className={workbenchTab === 'citations' ? 'active' : ''} onClick={() => setWorkbenchTab('citations')}>分析汇总</button>
            <button type="button" className={workbenchTab === 'qa' ? 'active' : ''} onClick={() => setWorkbenchTab('qa')}>质量检查</button>
          </div>

          <div className="workbench-pane">
            {workbenchTab === 'info' ? (
              <section className="task-info-pane">
                {run.status === 'waiting_for_clarification' ? (
                  <ClarificationPanel
                    run={run}
                    value={clarificationAnswer}
                    onChange={setClarificationAnswer}
                    onSubmit={() => clarificationMutation.mutate()}
                    isPending={clarificationMutation.isPending}
                    error={clarificationMutation.error}
                    compact
                  />
                ) : null}
                <dl>
                  <div>
                    <dt>任务 ID</dt>
                    <dd>{run.id}</dd>
                  </div>
                  <div>
                    <dt>分析主题</dt>
                    <dd>{run.title}</dd>
                  </div>
                  <div>
                    <dt>需求摘要</dt>
                    <dd>{run.requirement_summary ?? run.user_requirement}</dd>
                  </div>
                  <div>
                    <dt>当前阶段</dt>
                    <dd>{stageLabels[run.current_stage] ?? run.current_stage}</dd>
                  </div>
                </dl>
              </section>
            ) : null}
            {workbenchTab === 'sources' ? (
              <div className="side-stack">
                <SourceList sources={sources} isCollecting={run.status === 'running'} />
                <EvidenceList evidence={evidence} sources={sources} />
              </div>
            ) : null}
            {workbenchTab === 'competitors' ? <CompetitorConfirmPanel run={run} competitors={competitors} /> : null}
            {workbenchTab === 'citations' ? <CitationBundleView bundle={citationBundleQuery.data ?? []} /> : null}
            {workbenchTab === 'qa' ? <QAResultsPanel runId={id} /> : null}
          </div>
        </aside>
      </div>
    </div>
  );
}

function ClarificationPanel({
  run,
  value,
  onChange,
  onSubmit,
  isPending,
  error,
  compact = false,
}: {
  run: Run;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
  error: unknown;
  compact?: boolean;
}) {
  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    onSubmit();
  }

  return (
    <form className={`clarification-panel${compact ? ' compact' : ''}`} onSubmit={handleSubmit}>
      <div className="clarification-header">
        <span>补充关注点</span>
      </div>
      <p>{run.clarification_question ?? '请补充这份报告最需要关注的判断维度。'}</p>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="例如：重点关注本地存储、隐私安全和迁移成本"
        rows={compact ? 4 : 3}
      />
      {error ? <span className="error-text">提交失败：{String((error as Error).message ?? error)}</span> : null}
      <button type="submit" disabled={isPending || !value.trim()}>
        {isPending ? '继续分析中...' : '提交并继续'}
      </button>
    </form>
  );
}
