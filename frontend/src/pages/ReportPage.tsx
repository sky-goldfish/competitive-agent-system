import { useQuery } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import { Link, useParams } from 'react-router-dom';
import EvidenceList from '../components/evidence/EvidenceList';
import SourceList from '../components/evidence/SourceList';
import { getEvidence, getReport, getSources } from '../lib/api';

export default function ReportPage() {
  const { runId } = useParams<{ runId: string }>();
  const id = runId ?? '';
  const reportQuery = useQuery({ queryKey: ['report', id], queryFn: () => getReport(id), enabled: Boolean(id) });
  const sourcesQuery = useQuery({ queryKey: ['sources', id], queryFn: () => getSources(id), enabled: Boolean(id) });
  const evidenceQuery = useQuery({ queryKey: ['evidence', id], queryFn: () => getEvidence(id), enabled: Boolean(id) });

  if (reportQuery.isLoading) return <p className="loading">加载报告中...</p>;
  if (reportQuery.isError || !reportQuery.data) return <p className="error-text">报告尚未生成或加载失败。</p>;

  return (
    <div className="report-layout">
      <article className="panel markdown-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Markdown Report</p>
            <h1>分析报告</h1>
          </div>
          <Link className="primary-link" to={`/runs/${id}`}>返回任务</Link>
        </div>
        <ReactMarkdown>{reportQuery.data.markdown_content}</ReactMarkdown>
      </article>
      <div className="detail-column">
        <SourceList sources={sourcesQuery.data ?? []} />
        <EvidenceList evidence={evidenceQuery.data ?? []} sources={sourcesQuery.data ?? []} />
      </div>
    </div>
  );
}
