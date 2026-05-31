import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { deleteRun, listRuns } from '../lib/api';

const statusLabels: Record<string, string> = {
  running: '执行中',
  waiting_for_human: '待确认',
  completed: '已完成',
  failed: '失败',
};

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
  completed: '完成',
};

function formatTime(value: string) {
  return new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString();
}

export default function HistoryPage() {
  const queryClient = useQueryClient();
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: listRuns, refetchInterval: 5000 });
  const runs = runsQuery.data ?? [];

  const deleteMutation = useMutation({
    mutationFn: deleteRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['runs'] }),
  });

  function handleDelete(runId: string, title: string) {
    if (window.confirm(`确定要删除「${title}」吗？此操作不可恢复。`)) {
      deleteMutation.mutate(runId);
    }
  }

  return (
    <section className="history-page">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Analysis History</p>
          <h1>分析历史</h1>
        </div>
        <Link className="primary-link" to="/">新建分析</Link>
      </div>

      {runsQuery.isLoading ? <p className="loading">加载历史任务中...</p> : null}
      {runsQuery.isError ? <p className="error-text">历史任务加载失败。</p> : null}

      <div className="history-table-wrap">
        <table className="history-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>状态</th>
              <th>阶段</th>
              <th>创建时间</th>
              <th>完成时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 && !runsQuery.isLoading ? (
              <tr>
                <td colSpan={6}>暂无历史任务。</td>
              </tr>
            ) : null}
            {runs.map((run) => (
              <tr key={run.id}>
                <td>
                  <Link to={`/runs/${run.id}`}>{run.title}</Link>
                  <span>{run.user_requirement}</span>
                </td>
                <td><span className={`text-status ${run.status}`}>{statusLabels[run.status] ?? run.status}</span></td>
                <td>{stageLabels[run.current_stage] ?? run.current_stage}</td>
                <td>{formatTime(run.created_at)}</td>
                <td>{run.completed_at ? formatTime(run.completed_at) : '-'}</td>
                <td>
                  <button
                    type="button"
                    className="delete-action"
                    onClick={() => handleDelete(run.id, run.title)}
                    disabled={deleteMutation.isPending}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
