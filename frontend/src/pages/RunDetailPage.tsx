import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AlertCircle, BarChart3, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clipboard, Download, Loader2, MessageSquare, RefreshCw, RotateCcw, Send, XCircle } from 'lucide-react';
import CompetitorConfirmPanel from '../components/competitors/CompetitorConfirmPanel';
import EvidenceList from '../components/evidence/EvidenceList';
import SourceList from '../components/evidence/SourceList';
import QAResultsPanel from '../components/qa/QAResultsPanel';
import QASummaryBanner from '../components/qa/QASummaryBanner';
import CitationBundleView from '../components/report/CitationBundleView';
import ReportMarkdown from '../components/report/ReportMarkdown';
import {
  answerRunClarification,
  getChatMessages,
  getCompetitors,
  getEvidence,
  getQAResults,
  getReport,
  getReportCitationBundle,
  getReportCitations,
  getReportVersions,
  getRevisionTimeline,
  getRevisions,
  getRun,
  getSources,
  getTimeline,
  regenerateReport,
  sendChatMessage,
} from '../lib/api';
import type { ChatMessage, CitationBundleCompetitor, Competitor, Evidence, QAResult, Report as AppReport, Revision, RevisionTrace, Run, Source, Trace } from '../lib/types';

const stageOrder = [
  'requirement_understanding',
  'focus_profile',
  'competitor_discovery',
  'human_confirm_competitors',
  'material_collection',
  'structured_analysis',
  'report_generation',
  'quality_check',
];

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  focus_profile: '识别关注点',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
  quality_check: '质量检查',
  completed: '完成',
  failed: '失败',
};

const stageDescriptions: Record<string, string> = {
  requirement_understanding: '理解产品、目标用户、分析维度和搜索方向。',
  focus_profile: '识别用户关注重点，必要时发起澄清。',
  competitor_discovery: '发现候选竞品并给出推荐理由。',
  human_confirm_competitors: '等待你确认保留哪些竞品，也可以手动新增。',
  material_collection: '围绕已确认竞品采集公开资料、来源和证据。',
  structured_analysis: '把资料整理为定位、功能、价格、优势和机会点。',
  report_generation: '生成带来源引用的 Markdown 竞品分析报告。',
  quality_check: '检查来源覆盖、引用准确性和报告完整度。',
};

const statusLabels: Record<string, string> = {
  running: '执行中',
  revising: '修订中',
  waiting_for_clarification: '待你处理',
  waiting_for_human: '待你处理',
  completed: '报告已完成',
  failed: '执行失败',
};

const stageAliases: Record<string, string> = {
  requirement_clarification: 'focus_profile',
  target_query_planning: 'competitor_discovery',
  target_search: 'competitor_discovery',
  target_understanding: 'competitor_discovery',
  competitor_query_planning: 'competitor_discovery',
  competitor_search: 'competitor_discovery',
  candidate_extraction: 'competitor_discovery',
  official_site_resolution: 'competitor_discovery',
  quart_planning: 'material_collection',
  material_query_planning: 'material_collection',
  source_search: 'material_collection',
  source_classification: 'material_collection',
  evidence_extraction: 'material_collection',
  coverage_checking: 'material_collection',
};

function normalizeStage(stage: string) {
  return stageAliases[stage] ?? stage;
}

function getStageStatus(stage: string, run: Run, traces: Trace[], reportVersions: AppReport[] = []) {
  if (run.status === 'failed' && normalizeStage(run.current_stage) === stage) return 'failed';
  if (run.status === 'completed') return 'completed';
  if (run.status === 'waiting_for_human' && stage === 'human_confirm_competitors') return 'waiting';
  if (run.status === 'waiting_for_clarification' && stage === 'focus_profile') return 'waiting';
  
  const stageIndex = stageOrder.indexOf(stage);
  const currentIndex = stageOrder.indexOf(normalizeStage(run.current_stage));
  const isRunning = run.status === 'running';

  // Check for retry state
  const isPastStage = currentIndex > stageIndex;
  const isCurrentStage = normalizeStage(run.current_stage) === stage;
  
  if (isRunning && (isCurrentStage || isPastStage)) {
    // If it's a past stage but we are still running, check if it was completed before
    // but now we might be in a feedback loop.
    const stageTraces = traces.filter((trace) => normalizeStage(trace.stage) === stage);
    const wasCompleted = stageTraces.some(t => t.status === 'completed');
    
    if (isCurrentStage) {
      if (stage === 'report_generation' && reportVersions.length > 0) {
        const latestReport = reportVersions[reportVersions.length - 1];
        const runningTraces = traces.filter((trace) => normalizeStage(trace.stage) === 'report_generation' && trace.status === 'running');
        const runningTrace = runningTraces[runningTraces.length - 1];
        if (!runningTrace) return 'completed';
        if (new Date(latestReport.created_at).getTime() >= new Date(runningTrace.started_at).getTime()) return 'completed';
      }
      return wasCompleted ? 'completed-retry' : 'running';
    }
    
    if (isPastStage) {
      return 'completed';
    }
  }

  if (isRunning && stageIndex > currentIndex) return 'pending';

  const stageTraces = traces.filter((trace) => normalizeStage(trace.stage) === stage);
  const latestTrace = stageTraces[stageTraces.length - 1];
  if (latestTrace?.status === 'failed') return 'failed';
  if (latestTrace?.status === 'completed') return 'completed';
  return 'pending';
}

function isStageVisible(status: string) {
  return status !== 'pending';
}

function getStageDetail(stage: string, run: Run, counts: { competitors: number; selectedCompetitors: number; sources: number; evidence: number; hasReport: boolean }) {
  const iterationPrefix = run.feedback_loop_count && run.feedback_loop_count > 0 ? `[第 ${run.feedback_loop_count + 1} 轮分析] ` : '';
  
  if (stage === 'requirement_understanding') {
    return run.requirement_summary ? `已形成需求摘要：${run.requirement_summary}` : '正在提炼目标产品、用户场景和分析维度。';
  }
  if (stage === 'focus_profile') {
    return run.clarification_question ? '已识别到需要补充关注重点，请回答下方问题。' : '正在识别本次报告需要重点关注的维度。';
  }
  if (stage === 'competitor_discovery') {
    return counts.competitors > 0 ? `已发现 ${counts.competitors} 个候选竞品，等待进入确认或继续处理。` : '正在搜索同类产品、替代方案和竞品线索。';
  }
  if (stage === 'human_confirm_competitors') {
    if (run.status === 'waiting_for_human') return `已发现 ${counts.competitors} 个候选竞品，请在下方确认保留对象。`;
    return counts.selectedCompetitors > 0 ? `已锁定 ${counts.selectedCompetitors} 个竞品，后续资料采集会围绕这些对象展开。` : '等待候选竞品生成后确认。';
  }
  if (stage === 'material_collection') {
    return counts.sources > 0 ? `${iterationPrefix}已采集 ${counts.sources} 条来源，并抽取 ${counts.evidence} 条证据。` : '正在按竞品和分析维度采集公开资料。';
  }
  if (stage === 'structured_analysis') {
    return counts.evidence > 0 ? `${iterationPrefix}基于 ${counts.evidence} 条证据整理定位、功能、价格、优劣势和机会点。` : '正在把采集资料转换为结构化分析。';
  }
  if (stage === 'report_generation') {
    return counts.hasReport ? `${iterationPrefix}Markdown 报告已生成，可在右侧查看、复制或下载。` : '正在生成带来源引用的 Markdown 报告。';
  }
  if (stage === 'quality_check') {
    return counts.hasReport ? `${iterationPrefix}已对报告进行来源覆盖、引用准确性和完整度检查。` : '报告生成后会进入质量检查。';
  }
  return stageDescriptions[stage] ?? '正在执行当前分析节点。';
}

function safeParseJson<T>(value: string | null | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function isQueuedChatMessage(message: ChatMessage) {
  const metadata = safeParseJson<Record<string, unknown>>(message.metadata_json, {});
  return Boolean(metadata.queued) && !metadata.processed;
}

function isPendingChatMessage(message: ChatMessage) {
  const metadata = safeParseJson<Record<string, unknown>>(message.metadata_json, {});
  return Boolean((metadata.queued || metadata.processing) && !metadata.processed)
    || (typeof metadata.revision_id === 'string' && metadata.revision_status !== 'completed' && metadata.revision_status !== 'failed');
}

function isRevisionSystemMessage(message: ChatMessage) {
  if (message.role !== 'assistant') return false;
  if (message.intent === 'revision_processing' || message.intent === 'revision_completed') return true;
  return false;
}

function formatReportVersion(iteration: number | null | undefined) {
  return `第 ${(iteration ?? 0) + 1} 版`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getReportStatusLabel(run: Run | undefined, report: { iteration: number } | undefined, qaResults: QAResult[], traces: Trace[]) {
  if (!report) return '';
  const isQualityChecking = run?.status === 'running' && normalizeStage(run.current_stage) === 'quality_check';
  const hasReportGenerationTrace = traces.some((trace) => normalizeStage(trace.stage) === 'report_generation' && trace.status === 'completed');
  const latestQA = qaResults[qaResults.length - 1];
  if (run?.status === 'revising') return '修订中';
  if (isQualityChecking || (run?.status === 'running' && hasReportGenerationTrace && !latestQA)) return '正在质检';
  if (latestQA?.decision === 'pass') return '质检通过';
  if (latestQA?.decision === 'retry_collection') return '质检要求补采资料';
  if (latestQA?.decision === 'retry_analysis') return '质检要求重分析';
  if (run?.status === 'running') return '报告已生成，等待质检';
  if (run?.status === 'completed') return '报告已生成';
  if (run?.status === 'failed') return '任务已中断';
  return '报告已生成';
}

function getReportStatusTone(statusLabel: string) {
  if (statusLabel.includes('通过')) return 'pass';
  if (statusLabel.includes('重') || statusLabel.includes('中断')) return 'retry';
  if (statusLabel.includes('质检') || statusLabel.includes('等待')) return 'checking';
  return 'ready';
}

function getQALabel(result: QAResult | undefined) {
  if (!result) return '待质检';
  if (result.decision === 'pass') return `质检通过 · ${Math.round(result.overall_score * 100)} 分`;
  if (result.decision === 'retry_collection') return `需补采 · ${Math.round(result.overall_score * 100)} 分`;
  if (result.decision === 'retry_analysis') return `需重分析 · ${Math.round(result.overall_score * 100)} 分`;
  return `质检完成 · ${Math.round(result.overall_score * 100)} 分`;
}

function getQATone(result: QAResult | undefined) {
  if (!result) return 'checking';
  return result.decision === 'pass' ? 'pass' : 'retry';
}

function ReportDiffBanner({ current, previous }: { current: AppReport; previous?: AppReport }) {
  if (!previous) return null;
  
  const currentNames = current.competitor_names ?? [];
  const previousNames = previous.competitor_names ?? [];
  
  const added = currentNames.filter(n => !previousNames.includes(n));
  const removed = previousNames.filter(n => !currentNames.includes(n));
  
  if (added.length === 0 && removed.length === 0) return null;
  
  return (
    <div className="report-diff-banner">
      <div className="diff-stats">
        {added.length > 0 && (
          <span className="diff-added">
            <CheckCircle2 size={12} /> 新增竞品：{added.join('、')}
          </span>
        )}
        {removed.length > 0 && (
          <span className="diff-removed">
            <XCircle size={12} /> 移除竞品：{removed.join('、')}
          </span>
        )}
      </div>
    </div>
  );
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const id = runId ?? '';
  const queryClient = useQueryClient();
  const [clarificationAnswer, setClarificationAnswer] = useState('');
  const [submittedAnswers, setSubmittedAnswers] = useState<string[]>([]);
  const [selectedIteration, setSelectedIteration] = useState<number | undefined>(undefined);
  const [reportCollapsed, setReportCollapsed] = useState(false);
  const [mobileTab, setMobileTab] = useState<'process' | 'report'>('process');
  const [resultView, setResultView] = useState<'report' | 'evidence'>('report');
  const [revealedStageCount, setRevealedStageCount] = useState(0);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [processingStage, setProcessingStage] = useState<'idle' | 'classifying' | 'searching' | 'analyzing' | 'editing' | 'generating' | 'done'>('idle');
  const [completedSteps, setCompletedSteps] = useState<string[]>([]);
  const [activeWorkflowKind, setActiveWorkflowKind] = useState<'edit' | 'redo'>('edit');
  const chatListRef = useRef<HTMLDivElement>(null);
  const reportPanelRef = useRef<HTMLElement>(null);
  const reportDocumentRef = useRef<HTMLElement>(null);
  const currentRunIdRef = useRef(id);

  const runQuery = useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id),
    enabled: Boolean(id),
    refetchInterval: (query) => ['running', 'revising', 'waiting_for_human', 'waiting_for_clarification'].includes(query.state.data?.status ?? '') ? 3000 : false,
  });
  const run = runQuery.data;
  const isActive = run?.status === 'running' || run?.status === 'revising' || run?.status === 'waiting_for_human' || run?.status === 'waiting_for_clarification';

  useEffect(() => {
    currentRunIdRef.current = id;
    setChatInput('');
    setChatMessages([]);
    setProcessingStage('idle');
    setCompletedSteps([]);
    setActiveWorkflowKind('edit');
    if (!id) return undefined;
    let cancelled = false;
    getChatMessages(id)
      .then((messages) => {
        if (!cancelled && currentRunIdRef.current === id) setChatMessages(messages);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (chatListRef.current) {
      chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
    }
  }, [chatMessages, processingStage, completedSteps.length]);

  const timelineQuery = useQuery({ queryKey: ['timeline', id], queryFn: () => getTimeline(id), enabled: Boolean(id), refetchInterval: isActive ? 3000 : false });
  const revisionsQuery = useQuery({
    queryKey: ['revisions', id],
    queryFn: () => getRevisions(id),
    enabled: Boolean(id),
    refetchInterval: isActive ? 3000 : (query) => query.state.data?.some((revision) => revision.status === 'queued' || revision.status === 'running') ? 3000 : false,
  });
  const isRevisionRunning = run?.status === 'revising' || (revisionsQuery.data ?? []).some((r) => r.status === 'queued' || r.status === 'running');
  const competitorsQuery = useQuery({ queryKey: ['competitors', id], queryFn: () => getCompetitors(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const sourcesQuery = useQuery({ queryKey: ['sources', id], queryFn: () => getSources(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const evidenceQuery = useQuery({ queryKey: ['evidence', id], queryFn: () => getEvidence(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
  const traces = timelineQuery.data ?? [];
  const reportGenerated = traces.some((trace) => normalizeStage(trace.stage) === 'report_generation' && trace.status === 'completed');
  const shouldFetchReport = Boolean(reportGenerated);
  const reportQuery = useQuery({ queryKey: ['report', id, selectedIteration], queryFn: () => getReport(id, selectedIteration), enabled: Boolean(id) && Boolean(shouldFetchReport), refetchInterval: isActive ? 3000 : false });
  const reportVersionsQuery = useQuery({ queryKey: ['report-versions', id], queryFn: () => getReportVersions(id), enabled: Boolean(id) && Boolean(shouldFetchReport), refetchInterval: isActive ? 3000 : false });
  const qaResultsQuery = useQuery({
    queryKey: ['qa-results', id],
    queryFn: () => getQAResults(id),
    enabled: Boolean(id) && Boolean(shouldFetchReport),
    refetchInterval: isActive ? 3000 : false,
  });
  const displayedReportIteration = reportQuery.data?.iteration;
  const citationsQuery = useQuery({
    queryKey: ['report-citations', id, displayedReportIteration],
    queryFn: () => getReportCitations(id, displayedReportIteration),
    enabled: Boolean(id) && displayedReportIteration != null,
  });
  const citationBundleQuery = useQuery({
    queryKey: ['citation-bundle', id],
    queryFn: () => getReportCitationBundle(id),
    enabled: Boolean(id) && Boolean(run),
    refetchInterval: isActive ? 5000 : false,
  });

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
    mutationFn: (answer: string) => answerRunClarification(id, answer),
    onSuccess: (_, answer) => {
      setSubmittedAnswers((current) => [...current, answer]);
      setClarificationAnswer('');
      queryClient.invalidateQueries({ queryKey: ['run', id] });
      queryClient.invalidateQueries({ queryKey: ['timeline', id] });
    },
  });

  const chatSendMutation = useMutation({
    mutationFn: async ({ runId, message }: { runId: string; message: string }) => {
      const userMsg: ChatMessage = {
        id: `temp-${Date.now()}`,
        run_id: runId,
        role: 'user',
        content: message,
        intent: null,
        action_type: null,
        report_version: null,
        metadata_json: null,
        created_at: new Date().toISOString(),
      };
      if (currentRunIdRef.current === runId) {
        setChatMessages((prev) => [...prev, userMsg]);
        setCompletedSteps([]);
        setActiveWorkflowKind('edit');
        setProcessingStage('classifying');
      }
      return sendChatMessage(runId, message);
    },
    onSuccess: (data) => {
      const responseRunId = data.message.run_id;
      queryClient.invalidateQueries({ queryKey: ['chat-messages', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['revisions', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['run', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['report', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['report-versions', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['report-citations', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['citation-bundle', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['sources', responseRunId] });
      queryClient.invalidateQueries({ queryKey: ['evidence', responseRunId] });
      if (currentRunIdRef.current !== responseRunId) return;
      setProcessingStage('idle');
      setCompletedSteps([]);
      setActiveWorkflowKind(data.intent === 'report_redo' ? 'redo' : 'edit');
      setChatInput('');
      getChatMessages(responseRunId).then((messages) => {
        if (currentRunIdRef.current === responseRunId) setChatMessages(messages);
      }).catch(() => {});
      getRevisions(responseRunId).then((revs) => {
        if (currentRunIdRef.current === responseRunId) queryClient.setQueryData(['revisions', responseRunId], revs);
      }).catch(() => {});
    },
    onError: (error, variables) => {
      if (currentRunIdRef.current !== variables.runId) return;
      setProcessingStage('idle');
      setCompletedSteps([]);
      const message = error instanceof Error ? error.message : '发送失败，请稍后重试。';
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        run_id: variables.runId,
        role: 'assistant',
        content: `发送失败：${message}`,
        intent: 'error',
        action_type: 'error',
        report_version: reportQuery.data?.iteration ?? null,
        metadata_json: null,
        created_at: new Date().toISOString(),
      };
      setChatMessages((prev) => [...prev, errorMsg]);
    },
  });

  useEffect(() => {
    const shouldPollChat = isActive || chatMessages.some(isPendingChatMessage) || (revisionsQuery.data ?? []).some((revision) => revision.status === 'queued' || revision.status === 'running');
    if (!id || !shouldPollChat) return undefined;
    const hadRunningRevision = (revisionsQuery.data ?? []).some((revision) => revision.status === 'queued' || revision.status === 'running');
    const timer = window.setInterval(() => {
      if (chatSendMutation.isPending) return;
      getChatMessages(id)
        .then((messages) => {
          if (currentRunIdRef.current === id) setChatMessages(messages);
        })
        .catch(() => {});
      getRevisions(id)
        .then((revs) => {
          if (currentRunIdRef.current !== id) return;
          queryClient.setQueryData(['revisions', id], revs);
          const nowHasRunning = revs.some((r) => r.status === 'queued' || r.status === 'running');
          if (hadRunningRevision && !nowHasRunning) {
            const completedRevision = [...revs].reverse().find((r) => r.status === 'completed' && r.target_report_iteration != null);
            if (completedRevision && completedRevision.target_report_iteration != null) {
              setSelectedIteration(completedRevision.target_report_iteration);
            }
            queryClient.invalidateQueries({ queryKey: ['report-versions', id] });
            queryClient.invalidateQueries({ queryKey: ['report', id] });
            queryClient.invalidateQueries({ queryKey: ['report-citations', id] });
            queryClient.invalidateQueries({ queryKey: ['citation-bundle', id] });
            queryClient.invalidateQueries({ queryKey: ['sources', id] });
            queryClient.invalidateQueries({ queryKey: ['evidence', id] });
            queryClient.invalidateQueries({ queryKey: ['competitors', id] });
            queryClient.invalidateQueries({ queryKey: ['run', id] });
          }
        })
        .catch(() => {});
    }, 3000);
    return () => window.clearInterval(timer);
  }, [chatMessages, chatSendMutation.isPending, id, isActive, revisionsQuery.data, queryClient]);

  useEffect(() => {
    if (!reportQuery.data) return;
    setMobileTab('report');
    setResultView('report');
    setReportCollapsed(false);
    window.requestAnimationFrame(() => {
      reportPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (reportDocumentRef.current) {
        reportDocumentRef.current.scrollTop = 0;
      }
    });
  }, [reportQuery.data]);

  useEffect(() => {
    if (!reportQuery.isError || !reportVersionsQuery.data?.length) return;
    const latestIteration = reportVersionsQuery.data[reportVersionsQuery.data.length - 1].iteration;
    if (selectedIteration !== latestIteration && latestIteration != null) {
      setSelectedIteration(latestIteration);
    }
  }, [reportQuery.isError, reportVersionsQuery.data, selectedIteration]);

  const competitors = competitorsQuery.data ?? [];
  const sources = sourcesQuery.data ?? [];
  const evidence = evidenceQuery.data ?? [];
  const report = reportQuery.data;
  const reportVersions = reportVersionsQuery.data ?? [];
  const qaResults = qaResultsQuery.data ?? [];
  const latestQAResult = qaResults[qaResults.length - 1];
  const retryQAResults = qaResults.filter((result) => result.decision !== 'pass');
  const latestReportIteration = reportVersions.length ? reportVersions[reportVersions.length - 1].iteration : undefined;
  const completed = Boolean(report) && processingStage === 'idle' && !chatSendMutation.isPending && !isRevisionRunning;
  const shouldShowReportPanel = Boolean(report);
  const isFailedWithReport = Boolean(report) && run?.status === 'failed';
  const reportStatusLabel = getReportStatusLabel(run, report, qaResults, traces);
  const reportStatusTone = getReportStatusTone(reportStatusLabel);
  const isOptimizingReport = reportStatusTone === 'checking';
  const reportStatusDetail = report
    ? [
        retryQAResults.length > 0 ? `已根据质检重试 ${retryQAResults.length} 次` : null,
      ].filter(Boolean).join(' · ')
    : '报告生成后会显示在这里';
  const currentVersion = selectedIteration ?? latestReportIteration;
  const latestReportVersion = reportVersions.find((version) => version.iteration === latestReportIteration);
  const selectedReportVersion = reportVersions.find((version) => version.iteration === currentVersion);
  const versionQaByIteration = useMemo(() => {
    const map = new Map<number, QAResult>();
    qaResults.forEach((result) => {
      const reportIteration = Math.max(0, result.iteration - 1);
      map.set(reportIteration, result);
    });
    return map;
  }, [qaResults]);

  const viewReport = (iteration?: number) => {
    setSelectedIteration(iteration);
    setMobileTab('report');
    setResultView('report');
    setReportCollapsed(false);
    window.requestAnimationFrame(() => {
      reportPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      reportPanelRef.current?.focus({ preventScroll: true });
      if (reportDocumentRef.current) {
        reportDocumentRef.current.scrollTop = 0;
      }
    });
  };
  const canSendChat = Boolean(report) && !chatSendMutation.isPending && Boolean(chatInput.trim());
  const revisions = revisionsQuery.data ?? [];
  const activeRevision = revisions.find((r) => r.status === 'queued' || r.status === 'running');
  const stageCounts = useMemo(() => ({
    competitors: competitors.length,
    selectedCompetitors: competitors.filter((c) => c.selected).length,
    sources: sources.length,
    evidence: evidence.length,
    hasReport: Boolean(report),
  }), [competitors.length, evidence.length, report, sources.length]);
  const stages = useMemo(() => {
    if (!run) return [];
    if (completed) {
      return stageOrder
        .filter((stage) => traces.some((trace) => normalizeStage(trace.stage) === stage && trace.status === 'completed') || stage === 'report_generation')
        .map((stage) => ({ stage, status: 'completed' }));
    }
    const visibleStages = stageOrder
      .map((stage) => ({ stage, status: getStageStatus(stage, run, traces, reportVersions) }))
      .filter(({ status }) => isStageVisible(status));
    return visibleStages.length > 0 ? visibleStages : [{ stage: 'requirement_understanding', status: 'running' }];
  }, [completed, run, traces, reportVersions]);
  const shouldAnimateStages = run?.status !== 'completed' && run?.status !== 'failed';
  const visibleStageCount = shouldAnimateStages ? revealedStageCount : stages.length;
  const revealedStages = stages.slice(0, visibleStageCount);
  const nextStage = shouldAnimateStages ? stages[revealedStageCount] : undefined;

  useEffect(() => {
    setRevealedStageCount(0);
    setSelectedIteration(undefined);
    setReportCollapsed(false);
    setResultView('report');
    setMobileTab('process');
  }, [id]);

  useEffect(() => {
    if (!run || !shouldAnimateStages) {
      setRevealedStageCount(stages.length);
      return undefined;
    }
    if (revealedStageCount >= stages.length) return undefined;
    const timer = window.setTimeout(() => {
      setRevealedStageCount((count) => Math.min(count + 1, stages.length));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [revealedStageCount, run, shouldAnimateStages, stages.length]);

  useEffect(() => {
    setRevealedStageCount((count) => Math.min(count, stages.length));
  }, [stages.length]);

  if (runQuery.isLoading) return <p className="loading">加载任务中...</p>;
  if (runQuery.isError || !run) return <p className="error-text">任务加载失败。</p>;

  function submitClarification(answer: string) {
    const trimmed = answer.trim();
    if (!trimmed) return;
    clarificationMutation.mutate(trimmed);
  }

  function copyMarkdown() {
    if (!report?.markdown_content) return;
    navigator.clipboard.writeText(report.markdown_content);
  }

  function downloadMarkdown() {
    if (!report?.markdown_content) return;
    const blob = new Blob([report.markdown_content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${report.title || 'competitive-analysis-report'}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const processColumn = (
    <section className="conversation-panel">
      <div className="conversation-header">
        <div>
          <h1>{run.title}</h1>
          <p>{isRevisionRunning ? '正在修订报告...' : report ? reportStatusDetail : (statusLabels[run.status] ?? run.status)}</p>
        </div>
        {completed ? (
          <button type="button" className="icon-text-button" onClick={() => regenerateMutation.mutate()} disabled={regenerateMutation.isPending}>
            <RotateCcw size={16} />
            {regenerateMutation.isPending ? '生成中' : '重新生成'}
          </button>
        ) : null}
        <a href={`/runs/${id}/observability`} target="_blank" rel="noopener noreferrer" className="icon-text-button" title="在新标签页中查看可观测详情">
          <BarChart3 size={16} />
          查看详情
        </a>
      </div>

      <div className="message-stream" ref={chatListRef}>
        <article className="message-row user">
          <div className="message-bubble">
            <span className="message-speaker">你的需求</span>
            <span>{run.user_requirement}</span>
          </div>
        </article>
        <article className="message-row assistant">
          <div className="assistant-card">
            <div className="assistant-card-title">
              <MessageSquare size={17} />
              <strong>Agent 小组已接收任务</strong>
            </div>
            <p>{run.requirement_summary ?? '正在理解需求、识别目标对象和分析重点。'}</p>
          </div>
        </article>
{submittedAnswers.map((answer, index) => (
          <article className="message-row user" key={`${answer}-${index}`}>
            <div className="message-bubble">
              <span className="message-speaker">你的补充</span>
              <span>{answer}</span>
            </div>
          </article>
        ))}
        {stages.length > 0 ? (
          <article className="message-row assistant">
            <div className="stage-collapse-card">
              <div className="stage-collapse-toggle stage-collapse-static">
                <div className="stage-collapse-title">
                  <CheckCircle2 size={16} />
                  <strong>分析过程</strong>
                </div>
              </div>
              <div className="dialogue-stage-list">
                {revealedStages.map(({ stage, status }) => (
                  <StageDialogueCard
                    key={stage}
                    stage={stage}
                    status={status}
                    run={run}
                    counts={stageCounts}
                    competitors={competitors}
                    sources={sources}
                    evidence={evidence}
                    hasReport={Boolean(report)}
                    citationBundle={citationBundleQuery.data ?? []}
                    traces={traces}
                    runId={id}
                    selectedIteration={selectedIteration ?? latestReportIteration}
                    clarification={{
                      value: clarificationAnswer,
                      onChange: setClarificationAnswer,
                      onSubmit: submitClarification,
                      isPending: clarificationMutation.isPending,
                      error: clarificationMutation.error,
                    }}
                  />
                ))}
                {nextStage ? (
                  <article className="thinking-card">
                    <Loader2 size={17} />
                    <span>Agent 正在思考：{stageLabels[nextStage.stage] ?? nextStage.stage}</span>
                  </article>
                ) : null}
              </div>
            </div>
          </article>
        ) : null}
        {completed ? (
          <article className="message-row assistant">
            <div className="assistant-card report-done-card">
              <div className="assistant-card-title">
                <CheckCircle2 size={17} />
                <strong>{reportStatusLabel}</strong>
              </div>
              <p>
                当前展示 {report ? formatReportVersion(report.iteration) : '最新报告'}。报告区已准备好，你可以查看完整报告，也可以继续对话修改。
              </p>
              <div className="chat-card-actions">
                <button
                  type="button"
                  className="chat-view-report-btn"
                  onClick={() => viewReport(latestReportIteration)}
                >
                  查看完整报告
                </button>
                <Link className="chat-view-report-btn secondary" to={`/runs/${id}/report`}>
                  打开完整报告页
                </Link>
              </div>
            </div>
          </article>
        ) : null}

        {chatMessages.length > 0 ? (
          <div className="chat-round-divider">
            <span>对话修改</span>
          </div>
        ) : null}
        {(chatMessages ?? []).filter((msg) => !isRevisionSystemMessage(msg)).map((msg: ChatMessage) => {
          const msgRevision = (revisions ?? []).find((r) => r.chat_user_message_id === msg.id);
          const isRevisionResult = Boolean(msg.metadata_json && safeParseJson<Record<string, unknown>>(msg.metadata_json, {}).revision_id);
          const assistantRevision = isRevisionResult
            ? (revisions ?? []).find((r) => r.id === safeParseJson<Record<string, unknown>>(msg.metadata_json, {}).revision_id)
            : null;
          const showRevisionSummary = assistantRevision && assistantRevision.status === 'completed' && assistantRevision.summary;
          const reportVersion = msg.report_version ?? assistantRevision?.target_report_iteration ?? undefined;
          return (
            <div key={msg.id}>
              {msg.role === 'user' ? (
                <article className="message-row user">
                  <div className="message-bubble">
                    <span className="message-speaker">你</span>
                    <span>{msg.content}</span>
                    {isQueuedChatMessage(msg) ? <span className="queued-message-tag">等待质检结束后处理</span> : null}
                  </div>
                </article>
              ) : (
                <article className="message-row assistant">
                  <div className="assistant-card">
                    <div className="assistant-card-title">
                      <CheckCircle2 size={17} />
                      <strong>
                        {msg.intent === 'queued_revision'
                          ? '反馈已排队'
                          : msg.intent === 'report_redo'
                            ? '已重新调研并更新报告'
                            : msg.intent === 'revision_failed'
                              ? '修订失败'
                              : '已修改报告'}
                      </strong>
                    </div>
                    {!isRevisionResult ? <AgentWorkflowBlock message={msg} /> : null}
                    {/* If msg.content is identical to revision.summary, only show the styled summary box */}
                    {msg.content !== assistantRevision?.summary ? <p>{msg.content}</p> : null}
                    {showRevisionSummary ? (
                      <div className="revision-summary-box">
                        <strong>修改总结</strong>
                        <p>{assistantRevision!.summary}</p>
                      </div>
                    ) : null}
                    {reportVersion != null ? (
                      <button
                        type="button"
                        className="chat-view-report-btn"
                        onClick={() => viewReport(reportVersion)}
                      >
                        查看{formatReportVersion(reportVersion)}
                      </button>
                    ) : null}
                  </div>
                </article>
              )}
              {msgRevision ? (
                <article className="message-row assistant chat-process-group">
                  <RevisionWorkflowCard revision={msgRevision} />
                </article>
              ) : null}
            </div>
          );
        })}
        {(() => {
          const renderedRevisionIds = new Set(
            (chatMessages ?? [])
              .map((msg) => (revisions ?? []).find((r) => r.chat_user_message_id === msg.id))
              .filter(Boolean)
              .map((r) => r!.id)
          );
          const orphanRevisions = (revisions ?? []).filter((r) => !renderedRevisionIds.has(r.id));
          return orphanRevisions.map((revision) => (
            <div key={revision.id}>
              <article className="message-row assistant chat-process-group">
                <RevisionWorkflowCard revision={revision} />
              </article>
              {revision.status === 'completed' && revision.summary ? (
                <article className="message-row assistant">
                  <div className="assistant-card">
                    <div className="revision-summary-box">
                      <strong>修改总结</strong>
                      <p>{revision.summary}</p>
                    </div>
                    {revision.target_report_iteration != null ? (
                      <button
                        type="button"
                        className="chat-view-report-btn"
                        onClick={() => viewReport(revision.target_report_iteration!)}
                      >
                        查看{formatReportVersion(revision.target_report_iteration)}
                      </button>
                    ) : null}
                  </div>
                </article>
              ) : null}
            </div>
          ));
        })()}
        {chatSendMutation.isPending ? (
          <article className="message-row assistant">
            <div className="thinking-card">
              <Loader2 size={17} />
              <span>正在创建修订任务...</span>
            </div>
          </article>
        ) : null}
        {run.error_message ? (
          <article className="message-row assistant">
            <div className="error-card">
              <XCircle size={18} />
              <div>
                <strong>执行出现问题</strong>
                <p>{run.error_message}</p>
              </div>
            </div>
          </article>
        ) : null}
      </div>

      <form
        className="conversation-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          const msg = chatInput.trim();
          if (!canSendChat) return;
          chatSendMutation.mutate({ runId: id, message: msg });
        }}
      >
        <div className="conversation-input-shell">
          <textarea
            className="conversation-input"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const msg = chatInput.trim();
                if (!canSendChat) return;
                chatSendMutation.mutate({ runId: id, message: msg });
              }
            }}
            placeholder={report ? '继续对话：删除定价章节 / 增加用户评价对比 / 重新调研某个方向...' : '报告生成后可继续对话修改'}
            rows={2}
            disabled={chatSendMutation.isPending}
          />
        </div>
        <button type="submit" className="conversation-send-btn" disabled={!canSendChat}>
          <Send size={18} />
        </button>
      </form>
    </section>
  );

  const reportColumn = (
    <section className="report-panel" ref={reportPanelRef} tabIndex={-1}>
      <div className="report-toolbar">
        <div>
          <h2>
            {report?.title ?? '竞品分析报告'}
            {report && retryQAResults.length > 0 ? (
              <small>质检曾触发 {retryQAResults.length} 次重试，当前展示的是 {formatReportVersion(report.iteration)}。</small>
            ) : null}
          </h2>
          <p className="report-status-line">
            {isRevisionRunning && <Loader2 size={12} className="animate-spin" />}
            {report ? [reportStatusDetail, report.summary].filter(Boolean).join(' · ') : '报告生成后会显示在这里'}
          </p>
          {isOptimizingReport ? (
            <p className="report-intervention-hint">Agent 正在质检这份报告。你也可以通过左侧对话人工介入修改。</p>
          ) : null}
          {isFailedWithReport ? (
            <p className="report-intervention-hint">任务已中断，当前展示的是最近一次成功生成的报告版本。你可以通过左侧对话继续修改。</p>
          ) : null}
        </div>
        <div className="report-tools">
          <button type="button" className="icon-button" onClick={copyMarkdown} disabled={!report} title="复制 Markdown">
            <Clipboard size={17} />
          </button>
          <button type="button" className="icon-button" onClick={downloadMarkdown} disabled={!report} title="下载 Markdown">
            <Download size={17} />
          </button>
          <button type="button" className="icon-button" onClick={() => setReportCollapsed((value) => !value)} title={reportCollapsed ? '展开报告区域' : '收起报告区域'}>
            {reportCollapsed ? <ChevronLeft size={17} /> : <ChevronRight size={17} />}
          </button>
        </div>
      </div>
      <div className="result-view-body">
        {resultView === 'report' ? (
          <>
            {reportVersions.length > 1 ? (
              <div className="report-version-selector">
                <span className="report-version-label">报告版本</span>
                {reportVersions.map((version) => (
                  <button
                    key={version.id}
                    type="button"
                    className={`report-version-btn ${currentVersion === version.iteration ? 'active' : ''}`}
                    onClick={() => setSelectedIteration(version.iteration)}
                  >
                    <span className="report-version-title">
                      {formatReportVersion(version.iteration)}
                      {version.iteration === latestReportIteration ? <em>最新</em> : <em>历史</em>}
                    </span>
                    <span className="report-version-meta">{formatDateTime(version.created_at)}</span>
                    <span className={`report-version-qa ${getQATone(versionQaByIteration.get(version.iteration))}`}>
                      {getQALabel(versionQaByIteration.get(version.iteration))}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
            {selectedIteration !== undefined && latestReportIteration !== undefined && selectedIteration !== latestReportIteration ? (
              <div className="historical-version-banner">
                <div>
                  <strong>正在查看历史版本</strong>
                  <span>
                    {formatReportVersion(selectedIteration)}
                    {selectedReportVersion ? ` · ${formatDateTime(selectedReportVersion.created_at)}` : ''}
                    。最新版本是 {formatReportVersion(latestReportIteration)}
                    {latestReportVersion ? ` · ${formatDateTime(latestReportVersion.created_at)}` : ''}。
                  </span>
                </div>
                <button type="button" onClick={() => setSelectedIteration(undefined)}>切换至最新版本</button>
              </div>
            ) : null}
            {report && (
              <ReportDiffBanner
                current={report}
                previous={reportVersions.find(v => v.iteration === report.iteration - 1)}
              />
            )}
            <article className="report-document conversational-report" ref={reportDocumentRef}>
              {reportQuery.isLoading ? <p className="loading">加载报告中...</p> : null}
              {reportQuery.isError ? <p className="error-text">报告加载失败。</p> : null}
              {report ? <ReportMarkdown markdown={report.markdown_content} citations={citationsQuery.data ?? []} /> : null}
              {!reportQuery.isLoading && !reportQuery.isError && !report ? (
                <div className="empty-state">
                  <p className="empty-state-title">报告尚未生成</p>
                  <p className="empty-state-desc">完成竞品确认后，Agent 会继续采集资料并生成报告。</p>
                </div>
              ) : null}
            </article>
          </>
        ) : (
          <div className="result-insights">
            <QASummaryBanner runId={id} />
            <CitationBundleView bundle={citationBundleQuery.data ?? []} />
            <div className="result-insights-grid">
              <SourceList sources={sources} />
              <EvidenceList evidence={evidence} sources={sources} />
            </div>
          </div>
        )}
      </div>
      <div className="result-view-tabs">
        <button type="button" className={resultView === 'report' ? 'active' : ''} onClick={() => setResultView('report')}>
          报告
        </button>
        <button type="button" className={resultView === 'evidence' ? 'active' : ''} onClick={() => setResultView('evidence')}>
          证据与分析
        </button>
      </div>
    </section>
  );

  return (
    <div className={`analysis-workspace ${completed ? 'completed' : ''} ${report ? 'has-report' : ''} ${reportCollapsed ? 'report-collapsed' : ''}`}>
      <div className="mobile-result-tabs">
        <button type="button" className={mobileTab === 'process' ? 'active' : ''} onClick={() => setMobileTab('process')}>过程</button>
        <button type="button" className={mobileTab === 'report' ? 'active' : ''} onClick={() => setMobileTab('report')}>报告</button>
      </div>
      <div className="analysis-split">
        <div className={`process-slot ${mobileTab === 'process' ? 'mobile-active' : ''}`}>{processColumn}</div>
        {shouldShowReportPanel ? <div className={`report-slot ${mobileTab === 'report' ? 'mobile-active' : ''}`}>{reportColumn}</div> : null}
      </div>
    </div>
  );
}

function ClarificationCard({
  question,
  value,
  onChange,
  onSubmit,
  isPending,
  error,
}: {
  question: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (answer: string) => void;
  isPending: boolean;
  error: unknown;
}) {
  const presets = ['重点关注价格与商业模式', '重点关注产品功能差异', '重点关注用户痛点和评价'];

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit(value);
  }

  return (
    <form className="clarification-dialog-card" onSubmit={handleSubmit}>
      <div>
        <strong>需要补充信息</strong>
        <p>{question}</p>
      </div>
      <div className="choice-row">
        {presets.map((item) => (
          <button type="button" key={item} className={value === item ? 'selected' : ''} onClick={() => onChange(item)}>
            {item}
          </button>
        ))}
      </div>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="也可以直接输入你最关心的维度"
        rows={4}
      />
      {error ? <span className="error-text">提交失败：{String((error as Error).message ?? error)}</span> : null}
      <div className="dialog-actions">
        <button type="button" className="secondary-action" onClick={() => onSubmit('跳过补充，按默认维度继续分析。')} disabled={isPending}>
          跳过
        </button>
        <button type="submit" disabled={!value.trim() || isPending}>
          {isPending ? '继续分析中...' : '确认并继续'}
        </button>
      </div>
    </form>
  );
}

function RevisionWorkflowCard({ revision }: { revision: Revision }) {
  const [timeline, setTimeline] = useState<RevisionTrace[]>([]);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    getRevisionTimeline(revision.id).then(setTimeline).catch(() => {});
    if (revision.status === 'queued' || revision.status === 'running') {
      const timer = window.setInterval(() => {
        getRevisionTimeline(revision.id).then((data) => {
          setTimeline(data);
        }).catch(() => {});
      }, 3000);
      return () => window.clearInterval(timer);
    }
    return undefined;
  }, [revision.id, revision.status]);

  const revisionStageLabels: Record<string, string> = {
    revision_workflow: '修订流程',
    revision_intent: '判断修改类型',
    revision_search_plan: '生成搜索 Query',
    revision_competitor_update: '处理竞品',
    revision_material_collection: '收集新资料',
    revision_competitor_analysis: '分析竞品',
    revision_plan: '生成修订计划',
    revision_report_generation: '生成新报告',
    revision_report_validation: '校验报告正文',
    revision_summary: '生成修改总结',
  };

  const isActive = revision.status === 'queued' || revision.status === 'running';
  const isFailed = revision.status === 'failed';

  const traceSummary = (trace: RevisionTrace) => {
    if (!trace.output_json) return null;
    const output = safeParseJson<{ summary?: string; query_count?: number; competitors?: string[]; source_count?: number; workflow_steps?: Array<{ title?: string; detail?: string }> }>(trace.output_json, {});
    if (output.summary) return output.summary;
    if (output.query_count != null) return `生成 ${output.query_count} 条 query`;
    if (output.competitors?.length) return `新增：${output.competitors.join('、')}`;
    return null;
  };

  const effectiveTraces: Array<{ id: string; stage: string; status: string; error_message?: string | null; output_json?: string | null; summary?: string | null }> =
    (() => {
      if (timeline.length === 1 && timeline[0].stage === 'revision_workflow') {
        const output = safeParseJson<{ workflow_steps?: Array<{ title?: string; detail?: string }> }>(timeline[0].output_json, {});
        const steps = output.workflow_steps ?? [];
        return steps.map((step, i) => ({
          id: `${revision.id}-legacy-${i}`,
          stage: step.title ?? '',
          status: timeline[0].status,
          summary: step.detail ?? null,
        }));
      }
      return timeline.map((t) => ({
        ...t,
        status: isFailed && t.status === 'running' ? 'failed' : t.status,
      }));
    })();

  return (
    <div className="agent-workflow-card">
      <button
        type="button"
        onClick={() => !isActive && setCollapsed(!collapsed)}
        className={`agent-workflow-title${!isActive ? ' clickable' : ''}`}
      >
        {isActive ? <Loader2 size={16} /> : isFailed ? <XCircle size={16} /> : <CheckCircle2 size={16} />}
        <strong>{isActive ? '修订流程' : isFailed ? '修订失败' : '修订完成'}</strong>
        {!isActive ? (collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />) : null}
      </button>
      {(!collapsed || isActive) ? (
        <>
          <div className="agent-workflow-list">
            {effectiveTraces.map((trace, i) => (
              <div key={`${trace.id}-${i}`} className={`agent-workflow-step ${trace.status}`}>
                {trace.status === 'completed' ? <CheckCircle2 size={16} /> : trace.status === 'failed' ? <XCircle size={16} /> : <Loader2 size={16} />}
                <div>
                  <span>{revisionStageLabels[trace.stage] ?? trace.stage}</span>
                  {trace.summary ? <p>{trace.summary}</p> : traceSummary(timeline.find((t) => t.id === trace.id) ?? ({} as RevisionTrace)) ? <p>{traceSummary(timeline.find((t) => t.id === trace.id) ?? ({} as RevisionTrace))}</p> : null}
                  {trace.status === 'failed' && trace.error_message ? <p className="agent-workflow-error">{trace.error_message}</p> : null}
                </div>
              </div>
            ))}
            {effectiveTraces.length === 0 && isActive ? (
              <div className="agent-workflow-step running">
                <Loader2 size={16} />
                <span>准备修订流程</span>
              </div>
            ) : null}
          </div>
          {isFailed && revision.error_message ? (
            <div className="revision-summary-box failed">
              <strong>错误原因</strong>
              <p>{revision.error_message}</p>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function AgentWorkflowBlock({ message }: { message: ChatMessage }) {
  if (!message.metadata_json) return null;
  let metadata: { workflow_steps?: Array<{ title?: string; detail?: string }>; revision_summary?: string; action_details?: Record<string, unknown>; new_queries?: Array<{ query?: string; competitor_name?: string }> } = {};
  try {
    metadata = JSON.parse(message.metadata_json);
  } catch {
    return null;
  }
  const steps = metadata.workflow_steps ?? [];
  if (!steps.length) return null;

  return (
    <div className="agent-workflow-card">
      <div className="agent-workflow-title">
        <CheckCircle2 size={16} />
        <strong>Agent 工作流</strong>
      </div>
      <div className="agent-workflow-list">
        {steps.map((step, index) => (
          <div key={`${step.title}-${index}`} className="agent-workflow-step done">
            <CheckCircle2 size={16} />
            <div>
              <span>{step.title}</span>
              {step.detail ? <p>{step.detail}</p> : null}
            </div>
          </div>
        ))}
      </div>
      {metadata.new_queries?.length ? (
        <div className="agent-query-list">
          {metadata.new_queries.slice(0, 3).map((item, index) => (
            <span key={`${item.query}-${index}`}>{item.competitor_name ? `${item.competitor_name}: ` : ''}{item.query}</span>
          ))}
        </div>
      ) : null}
      {metadata.revision_summary ? (
        <div className="revision-summary-box">
          <strong>修改总结</strong>
          <p>{metadata.revision_summary}</p>
        </div>
      ) : null}
    </div>
  );
}

function RequirementUnderstandingBlock({ output, running }: { output: Record<string, unknown>; running: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const hasOutput = Object.keys(output).length > 0;
  if (!hasOutput && running) {
    return (
      <div className="stage-embedded-block requirement-understanding-block">
        <div className="embedded-block-title">
          <strong>正在识别</strong>
          <span>结构化需求</span>
        </div>
        <div className="requirement-chip-grid">
          {['分析对象', '产品赛道', '目标用户', '核心能力', '分析维度', '搜索方向'].map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      </div>
    );
  }
  if (!hasOutput) return null;

  const target = stringValue(output.target_product) || stringValue(output.product_description) || '未明确';
  const category = stringValue(output.possible_market_category) || stringValue(output.domain) || '未明确';
  const summary = stringValue(output.summary);
  const targetUsers = listValue(output.target_users);
  const capabilities = listValue(output.core_capabilities);
  const dimensions = listValue(output.analysis_dimensions);
  const queries = listValue(output.queries);
  const confidence = typeof output.confidence === 'number' ? output.confidence : undefined;
  const compactUsers = targetUsers.slice(0, 3).join('、') || '待确认';
  const compactCapabilities = capabilities.slice(0, 3).join('、') || '待确认';

  return (
    <div className="stage-embedded-block requirement-understanding-block">
      <div className="requirement-compact-head">
        <div>
          <strong>{target}</strong>
          <span>{category}</span>
        </div>
        <button type="button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? '收起' : '详情'}
        </button>
      </div>
      <p className="requirement-compact-line">
        目标用户：{compactUsers}；核心能力：{compactCapabilities}
      </p>
      {expanded ? (
        <div className="requirement-result-list compact-detail">
          {summary ? <RequirementResultItem label="需求摘要" value={summary} /> : null}
          {dimensions.length ? <RequirementResultItem label="分析维度" value={dimensions.join('、')} /> : null}
          {queries.length ? <RequirementResultItem label="搜索方向" value={queries.slice(0, 4).join(' / ')} /> : null}
          {confidence != null ? <RequirementResultItem label="识别置信度" value={`${Math.round(confidence * 100)}%`} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function RequirementResultItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="requirement-result-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function focusProfileOutputFromTraces(traces: Trace[]) {
  const focusTrace = traces.find((trace) => trace.stage === 'focus_profile' && trace.status === 'completed');
  return safeParseJson<Record<string, unknown>>(focusTrace?.output_json, {});
}

function FocusProfileBlock({ output, question }: { output: Record<string, unknown>; question: string | null }) {
  const explicit = focusListValue(output.explicit_focuses);
  const inferred = focusListValue(output.inferred_focuses);
  const focuses = [...explicit, ...inferred].slice(0, 4);
  const assumptions = listValue(output.assumptions).slice(0, 2);

  if (question) {
    return (
      <div className="stage-embedded-block focus-profile-block">
        <div className="embedded-block-title">
          <strong>需要确认关注点</strong>
          <span>人工补充</span>
        </div>
        <p className="focus-profile-question">{question}</p>
      </div>
    );
  }

  if (!focuses.length && !assumptions.length) {
    return (
      <div className="stage-embedded-block focus-profile-block">
        <p className="requirement-compact-line">正在判断这份报告需要重点关注哪些维度。</p>
      </div>
    );
  }

  return (
    <div className="stage-embedded-block focus-profile-block">
      <div className="embedded-block-title">
        <strong>关注点</strong>
        <span>用于指导搜索和分析</span>
      </div>
      {focuses.length ? (
        <div className="requirement-chip-grid">
          {focuses.map((focus) => <span key={focus}>{focus}</span>)}
        </div>
      ) : null}
    </div>
  );
}

function focusListValue(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => typeof item === 'object' && item !== null && 'label' in item ? String((item as { label?: unknown }).label ?? '') : String(item))
    .filter(Boolean);
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function listValue(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function StageDialogueCard({
  stage,
  status,
  run,
  counts,
  competitors,
  sources,
  evidence,
  hasReport,
  citationBundle,
  traces,
  runId,
  selectedIteration,
  clarification,
}: {
  stage: string;
  status: string;
  run: Run;
  counts: { competitors: number; selectedCompetitors: number; sources: number; evidence: number; hasReport: boolean };
  competitors: Competitor[];
  sources: Source[];
  evidence: Evidence[];
  hasReport: boolean;
  citationBundle: CitationBundleCompetitor[];
  traces: Trace[];
  runId: string;
  selectedIteration?: number;
  clarification: {
    value: string;
    onChange: (value: string) => void;
    onSubmit: (answer: string) => void;
    isPending: boolean;
    error: unknown;
  };
}) {
  const [qaExpanded, setQaExpanded] = useState(false);
  const showClarification = stage === 'focus_profile' && run.status === 'waiting_for_clarification';
  const showCompetitorConfirm = stage === 'human_confirm_competitors' && (run.status === 'waiting_for_human' || competitors.length > 0);
  const showSources = stage === 'material_collection' && (sources.length > 0 || evidence.length > 0);
  const showCitations = stage === 'structured_analysis' && citationBundle.length > 0;
  const showQA = stage === 'quality_check' && hasReport;
  const requirementTrace = traces.find((trace) => normalizeStage(trace.stage) === 'requirement_understanding' && trace.status === 'completed');
  const requirementOutput = safeParseJson<Record<string, unknown>>(requirementTrace?.output_json, {});
  const focusOutput = focusProfileOutputFromTraces(traces);

  const isHighlighted = (stage === 'report_generation' || stage === 'quality_check') && 
                       selectedIteration !== undefined && 
                       run.feedback_loop_count !== undefined &&
                       (selectedIteration === run.feedback_loop_count - 1 || (run.status === 'running' && stage === 'report_generation' && selectedIteration === run.feedback_loop_count));

  return (
    <article className={`message-row assistant stage-message-row ${isHighlighted ? 'highlight-version' : ''}`}>
      <div className={`stage-message-card ${status}`}>
        <div className="stage-message-head">
          <div className="stage-status-icon">{statusIcon(status)}</div>
          <div>
            <h3>{stageLabels[stage] ?? stage}</h3>
            <span>{statusText(status)}</span>
          </div>
        </div>
        <p>{getStageDetail(stage, run, counts)}</p>

        {stage === 'requirement_understanding' ? (
          <RequirementUnderstandingBlock output={requirementOutput} running={status === 'running'} />
        ) : null}
        {stage === 'focus_profile' ? (
          <FocusProfileBlock output={focusOutput} question={run.clarification_question} />
        ) : null}

        {showClarification ? (
          <ClarificationCard
            question={run.clarification_question ?? '请补充这份报告最需要关注的判断维度。'}
            value={clarification.value}
            onChange={clarification.onChange}
            onSubmit={clarification.onSubmit}
            isPending={clarification.isPending}
            error={clarification.error}
          />
        ) : null}

        {showCompetitorConfirm ? (
          <div className="stage-embedded-block">
            <div className="embedded-block-title">
              <strong>候选竞品选择</strong>
              {run.status === 'waiting_for_human' ? <span>需要确认</span> : <span>已确认</span>}
            </div>
            <CompetitorConfirmPanel run={run} competitors={competitors} />
          </div>
        ) : null}

        {showSources ? (
          <div className="stage-embedded-block resource-grid">
            <SourceList sources={sources} isCollecting={run.status === 'running'} initialVisibleCount={3} />
            <EvidenceList evidence={evidence} sources={sources} initialVisibleCount={3} />
          </div>
        ) : null}

        {showCitations ? (
          <div className="stage-embedded-block">
            <CitationBundleView bundle={citationBundle} />
          </div>
        ) : null}

        {showQA ? (
          <div className="stage-embedded-block">
            <QASummaryBanner runId={runId} />
            <button
              type="button"
              className="qa-expand-toggle"
              onClick={() => setQaExpanded(!qaExpanded)}
            >
              <span>{qaExpanded ? '收起质检详情' : '查看详细质检报告'}</span>
              {qaExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {qaExpanded && <QAResultsPanel runId={runId} />}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function statusIcon(status: string) {
  if (status === 'completed') return <CheckCircle2 size={18} />;
  if (status === 'completed-retry') return (
    <div className="status-icon-stack">
      <CheckCircle2 size={18} className="base-icon" />
      <RefreshCw size={10} className="overlay-icon" />
    </div>
  );
  if (status === 'failed') return <XCircle size={18} />;
  if (status === 'running' || status === 'revising') return <Loader2 size={18} className="spinning" />;
  if (status === 'waiting') return <AlertCircle size={18} className="waiting-icon" />;
  return <span className="pending-dot" />;
}

function statusText(status: string) {
  const map: Record<string, string> = {
    completed: '已完成',
    'completed-retry': '已完成 (正在修正)',
    running: '进行中',
    waiting: '待你处理',
    failed: '失败',
    pending: '待开始',
  };
  return map[status] ?? status;
}
