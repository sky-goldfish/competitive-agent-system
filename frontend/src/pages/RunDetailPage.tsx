import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import CompetitorConfirmPanel from '../components/competitors/CompetitorConfirmPanel';
import SourceList from '../components/evidence/SourceList';
import AgentTimeline from '../components/timeline/AgentTimeline';
import { getCompetitors, getRun, getSources, getTimeline } from '../lib/api';

const statusLabels: Record<string, string> = {
  running: 'Agent 正在执行',
  waiting_for_human: '等待你确认竞品',
  completed: '报告已生成',
  failed: '执行失败',
};

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
  completed: '已完成',
};

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const id = runId ?? '';
  const runQuery = useQuery({ queryKey: ['run', id], queryFn: () => getRun(id), enabled: Boolean(id), refetchInterval: (query) => query.state.data?.status === 'running' ? 1000 : false });
  const competitorsQuery = useQuery({ queryKey: ['competitors', id], queryFn: () => getCompetitors(id), enabled: Boolean(id), refetchInterval: runQuery.data?.status === 'running' ? 1000 : false });
  const timelineQuery = useQuery({ queryKey: ['timeline', id], queryFn: () => getTimeline(id), enabled: Boolean(id), refetchInterval: runQuery.data?.status === 'running' ? 1000 : false });
  const sourcesQuery = useQuery({ queryKey: ['sources', id], queryFn: () => getSources(id), enabled: Boolean(id), refetchInterval: runQuery.data?.status === 'running' ? 1000 : false });

  if (runQuery.isLoading) return <p className="loading">加载任务中...</p>;
  if (runQuery.isError || !runQuery.data) return <p className="error-text">任务加载失败。</p>;

  const run = runQuery.data;
  const competitors = competitorsQuery.data ?? [];
  const traces = timelineQuery.data ?? [];
  const sources = sourcesQuery.data ?? [];
  const shouldShowSources = run.status === 'completed';

  return (
    <div className="detail-grid">
      <section className="panel run-summary">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Run {run.id}</p>
            <h1>{run.title}</h1>
          </div>
          <span className={`status-pill ${run.status}`}>{statusLabels[run.status] ?? run.status}</span>
        </div>
        <p>{run.requirement_summary ?? run.user_requirement}</p>
        <p className="muted">当前阶段：{stageLabels[run.current_stage] ?? run.current_stage}</p>
        {run.error_message ? <p className="error-text">{run.error_message}</p> : null}
        {run.status === 'completed' ? <Link className="primary-link" to={`/runs/${run.id}/report`}>查看报告</Link> : null}
      </section>

      <div className="detail-column">
        <AgentTimeline traces={traces} run={run} />
        {run.status === 'completed' ? (
          <section className="panel report-ready-card">
            <div>
              <h2>报告已生成</h2>
              <p className="muted">竞品分析报告已经完成，可以查看完整 Markdown 报告、来源资料和证据片段。</p>
            </div>
            <Link className="primary-link" to={`/runs/${run.id}/report`}>查看完整报告</Link>
          </section>
        ) : null}
        {shouldShowSources ? <SourceList sources={sources} isCollecting={run.status === 'running'} /> : null}
      </div>
      <div className="detail-column">
        <CompetitorConfirmPanel run={run} competitors={competitors} />
      </div>
    </div>
  );
}
