import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import EvidenceList from '../components/evidence/EvidenceList';
import SourceList from '../components/evidence/SourceList';
import CitationBundleView from '../components/report/CitationBundleView';
import ReportMarkdown from '../components/report/ReportMarkdown';
import { getEvidence, getReport, getReportCitationBundle, getReportCitations, getSources, regenerateReport } from '../lib/api';

export default function ReportPage() {
  const { runId } = useParams<{ runId: string }>();
  const id = runId ?? '';
  const queryClient = useQueryClient();
  const reportQuery = useQuery({ queryKey: ['report', id], queryFn: () => getReport(id), enabled: Boolean(id) });
  const displayedReportIteration = reportQuery.data?.iteration;
  const citationsQuery = useQuery({
    queryKey: ['report-citations', id, displayedReportIteration],
    queryFn: () => getReportCitations(id, displayedReportIteration),
    enabled: Boolean(id) && displayedReportIteration != null,
  });
  const sourcesQuery = useQuery({ queryKey: ['sources', id], queryFn: () => getSources(id), enabled: Boolean(id) });
  const evidenceQuery = useQuery({ queryKey: ['evidence', id], queryFn: () => getEvidence(id), enabled: Boolean(id) });
  const citationBundleQuery = useQuery({ queryKey: ['citation-bundle', id, displayedReportIteration], queryFn: () => getReportCitationBundle(id, displayedReportIteration), enabled: Boolean(id) && displayedReportIteration != null });

  const regenerateMutation = useMutation({
    mutationFn: () => regenerateReport(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['report', id] });
      queryClient.invalidateQueries({ queryKey: ['report-citations', id] });
      queryClient.invalidateQueries({ queryKey: ['citation-bundle', id] });
      queryClient.invalidateQueries({ queryKey: ['sources', id] });
    },
  });

  if (reportQuery.isLoading) return <p className="loading">加载报告中...</p>;
  if (reportQuery.isError || !reportQuery.data) return (
    <div style={{ padding: 24 }}>
      <p className="error-text">报告尚未生成或加载失败。</p>
      <button type="button" className="workspace-regenerate" onClick={() => reportQuery.refetch()} style={{ marginTop: 12 }}>
        重试
      </button>
    </div>
  );

  return (
    <div className="report-layout">
      <article className="panel markdown-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Markdown Report</p>
            <h1>分析报告</h1>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Link className="primary-link" to={`/runs/${id}`}>返回任务</Link>
          </div>
        </div>
        <ReportMarkdown markdown={reportQuery.data.markdown_content} citations={citationsQuery.data ?? []} />
      </article>
      <div className="detail-column">
        <CitationBundleView bundle={citationBundleQuery.data ?? []} />
        <SourceList sources={sourcesQuery.data ?? []} />
        <EvidenceList evidence={evidenceQuery.data ?? []} sources={sourcesQuery.data ?? []} />
      </div>
    </div>
  );
}