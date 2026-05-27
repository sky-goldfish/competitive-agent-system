import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import AnalysisList from '../components/analysis/AnalysisList';
import CompetitorConfirmPanel from '../components/competitors/CompetitorConfirmPanel';
import EvidenceList from '../components/evidence/EvidenceList';
import SourceList from '../components/evidence/SourceList';
import ReportMarkdown from '../components/report/ReportMarkdown';
import AgentTimeline from '../components/timeline/AgentTimeline';
import { getAnalyses, getCompetitors, getEvidence, getReport, getReportCitations, getRun, getSources, getTimeline } from '../lib/api';
import type { Run, Trace } from '../lib/types';

const statusLabels: Record<string, string> = {
  running: '执行中',
  waiting_for_human: '等待人工确认',
  completed: '报告已生成',
  failed: '执行失败',
};

const stageOrder = [
  'requirement_understanding',
  'human_confirm_competitors',
  'material_collection',
  'structured_analysis',
  'report_generation',
  'completed',
];

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
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
  const [mainTab, setMainTab] = useState<'process' | 'report'>('process');
  const [workbenchTab, setWorkbenchTab] = useState<'info' | 'sources' | 'competitors' | 'analysis'>('info');

  const runQuery = useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id),
    enabled: Boolean(id),
    refetchInterval: (query) => ['running', 'waiting_for_human'].includes(query.state.data?.status ?? '') ? 3000 : false,
  });
  const run = runQuery.data;
  const isActive = run?.status === 'running' || run?.status === 'waiting_for_human';
  const competitorsQuery = useQuery({ queryKey: ['competitors', id], queryFn: () => getCompetitors(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const timelineQuery = useQuery({ queryKey: ['timeline', id], queryFn: () => getTimeline(id), enabled: Boolean(id), refetchInterval: isActive ? 3000 : false });
  const sourcesQuery = useQuery({ queryKey: ['sources', id], queryFn: () => getSources(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const evidenceQuery = useQuery({ queryKey: ['evidence', id], queryFn: () => getEvidence(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const analysesQuery = useQuery({ queryKey: ['analyses', id], queryFn: () => getAnalyses(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const reportQuery = useQuery({ queryKey: ['report', id], queryFn: () => getReport(id), enabled: Boolean(id) && run?.status === 'completed' });
  const citationsQuery = useQuery({ queryKey: ['report-citations', id], queryFn: () => getReportCitations(id), enabled: Boolean(id) && run?.status === 'completed' });

  useEffect(() => {
    if (run?.status === 'waiting_for_human') setWorkbenchTab('competitors');
    if (run?.status === 'running' && run.current_stage === 'material_collection') setWorkbenchTab('sources');
  }, [run?.current_stage, run?.status]);

  const traces = timelineQuery.data ?? [];
  const stagePath = useMemo(() => run ? getStagePath(run, traces) : [], [run, traces]);

  if (runQuery.isLoading) return <p className="loading">加载任务中...</p>;
  if (runQuery.isError || !run) return <p className="error-text">任务加载失败。</p>;

  const competitors = competitorsQuery.data ?? [];
  const sources = sourcesQuery.data ?? [];
  const evidence = evidenceQuery.data ?? [];
  const analyses = analysesQuery.data ?? [];
  const report = reportQuery.data;
  const canShowReport = run.status === 'completed' && Boolean(report);

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
            {run.status === 'completed' ? (
              <button type="button" className={mainTab === 'report' ? 'active' : ''} onClick={() => setMainTab('report')}>分析报告</button>
            ) : null}
          </div>

          {mainTab === 'process' ? (
            <AgentTimeline traces={traces} run={run} compactHeader />
          ) : null}

          {mainTab === 'report' ? (
            <article className="report-document">
              {reportQuery.isLoading ? <p className="loading">加载报告中...</p> : null}
              {reportQuery.isError ? <p className="error-text">报告加载失败。</p> : null}
              {canShowReport && report ? (
                <ReportMarkdown markdown={report.markdown_content} citations={citationsQuery.data ?? []} />
              ) : null}
            </article>
          ) : null}
        </section>

        <aside className="workbench-side">
          <div className="workbench-tabs">
            <button type="button" className={workbenchTab === 'info' ? 'active' : ''} onClick={() => setWorkbenchTab('info')}>任务信息</button>
            <button type="button" className={workbenchTab === 'sources' ? 'active' : ''} onClick={() => setWorkbenchTab('sources')}>搜索结果</button>
            <button type="button" className={workbenchTab === 'competitors' ? 'active' : ''} onClick={() => setWorkbenchTab('competitors')}>竞品确认</button>
            <button type="button" className={workbenchTab === 'analysis' ? 'active' : ''} onClick={() => setWorkbenchTab('analysis')}>结构化分析</button>
          </div>

          <div className="workbench-pane">
            {workbenchTab === 'info' ? (
              <section className="task-info-pane">
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
            {workbenchTab === 'analysis' ? <AnalysisList analyses={analyses} competitors={competitors} evidence={evidence} sources={sources} /> : null}
          </div>
        </aside>
      </div>
    </div>
  );
}
