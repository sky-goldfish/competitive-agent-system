import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clipboard, Download, Loader2, MessageSquare, RotateCcw, Send, XCircle } from 'lucide-react';
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
  getReport,
  getReportCitationBundle,
  getReportCitations,
  getReportVersions,
  getRun,
  getSources,
  getTimeline,
  regenerateReport,
  sendChatMessage,
} from '../lib/api';
import type { ChatMessage, CitationBundleCompetitor, Competitor, Evidence, Run, Source, Trace } from '../lib/types';

const stageOrder = [
  'requirement_understanding',
  'competitor_discovery',
  'human_confirm_competitors',
  'material_collection',
  'structured_analysis',
  'report_generation',
  'quality_check',
];

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
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
  competitor_discovery: '发现候选竞品并给出推荐理由。',
  human_confirm_competitors: '等待你确认保留哪些竞品，也可以手动新增。',
  material_collection: '围绕已确认竞品采集公开资料、来源和证据。',
  structured_analysis: '把资料整理为定位、功能、价格、优势和机会点。',
  report_generation: '生成带来源引用的 Markdown 竞品分析报告。',
  quality_check: '检查来源覆盖、引用准确性和报告完整度。',
};

const statusLabels: Record<string, string> = {
  running: '执行中',
  waiting_for_clarification: '等待补充信息',
  waiting_for_human: '等待确认竞品',
  completed: '报告已完成',
  failed: '执行失败',
};

const stageAliases: Record<string, string> = {
  focus_profile: 'requirement_understanding',
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

function getStageStatus(stage: string, run: Run, traces: Trace[]) {
  if (run.status === 'failed' && normalizeStage(run.current_stage) === stage) return 'failed';
  if (run.status === 'completed') return 'completed';
  if (run.status === 'waiting_for_human' && stage === 'human_confirm_competitors') return 'running';
  if (run.status === 'waiting_for_clarification' && stage === 'requirement_understanding') return 'running';
  if (normalizeStage(run.current_stage) === stage && run.status === 'running') return 'running';
  const stageIndex = stageOrder.indexOf(stage);
  const currentIndex = stageOrder.indexOf(normalizeStage(run.current_stage));
  if (traces.some((trace) => normalizeStage(trace.stage) === stage && trace.status === 'failed')) return 'failed';
  if (traces.some((trace) => normalizeStage(trace.stage) === stage && trace.status === 'completed')) return 'completed';
  if (currentIndex > stageIndex) return 'completed';
  return 'pending';
}

function isStageVisible(status: string) {
  return status !== 'pending';
}

function getStageDetail(stage: string, run: Run, counts: { competitors: number; sources: number; evidence: number; hasReport: boolean }) {
  if (stage === 'requirement_understanding') {
    return run.requirement_summary ? `已形成需求摘要：${run.requirement_summary}` : '正在提炼目标产品、用户场景和分析维度。';
  }
  if (stage === 'competitor_discovery') {
    return counts.competitors > 0 ? `已发现 ${counts.competitors} 个候选竞品，等待进入确认或继续处理。` : '正在搜索同类产品、替代方案和竞品线索。';
  }
  if (stage === 'human_confirm_competitors') {
    if (run.status === 'waiting_for_human') return `已发现 ${counts.competitors} 个候选竞品，请在下方确认保留对象。`;
    return counts.competitors > 0 ? `已锁定 ${counts.competitors} 个竞品，后续资料采集会围绕这些对象展开。` : '等待候选竞品生成后确认。';
  }
  if (stage === 'material_collection') {
    return counts.sources > 0 ? `已采集 ${counts.sources} 条来源，并抽取 ${counts.evidence} 条证据。` : '正在按竞品和分析维度采集公开资料。';
  }
  if (stage === 'structured_analysis') {
    return counts.evidence > 0 ? `基于 ${counts.evidence} 条证据整理定位、功能、价格、优劣势和机会点。` : '正在把采集资料转换为结构化分析。';
  }
  if (stage === 'report_generation') {
    return counts.hasReport ? 'Markdown 报告已生成，可在右侧查看、复制或下载。' : '正在生成带来源引用的 Markdown 报告。';
  }
  if (stage === 'quality_check') {
    return counts.hasReport ? '已对报告进行来源覆盖、引用准确性和完整度检查。' : '报告生成后会进入质量检查。';
  }
  return stageDescriptions[stage] ?? '正在执行当前分析节点。';
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
  const [revealedStageCount, setRevealedStageCount] = useState(0);
  const [stagesCollapsed, setStagesCollapsed] = useState(true);
  const [manualStageCollapse, setManualStageCollapse] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [processingStage, setProcessingStage] = useState<'idle' | 'classifying' | 'searching' | 'analyzing' | 'editing' | 'generating' | 'done'>('idle');
  const [completedSteps, setCompletedSteps] = useState<string[]>([]);
  const [activeWorkflowKind, setActiveWorkflowKind] = useState<'edit' | 'redo'>('edit');
  const chatListRef = useRef<HTMLDivElement>(null);

  const runQuery = useQuery({
    queryKey: ['run', id],
    queryFn: () => getRun(id),
    enabled: Boolean(id),
    refetchInterval: (query) => ['running', 'waiting_for_human', 'waiting_for_clarification'].includes(query.state.data?.status ?? '') ? 3000 : false,
  });
  const run = runQuery.data;
  const isActive = run?.status === 'running' || run?.status === 'waiting_for_human' || run?.status === 'waiting_for_clarification';

  useEffect(() => {
    if (run?.status === 'completed' && id) {
      getChatMessages(id).then(setChatMessages).catch(() => {});
    }
  }, [id, run?.status]);

  useEffect(() => {
    if (chatListRef.current) {
      chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
    }
  }, [chatMessages, processingStage, completedSteps.length]);

  const timelineQuery = useQuery({ queryKey: ['timeline', id], queryFn: () => getTimeline(id), enabled: Boolean(id), refetchInterval: isActive ? 3000 : false });
  const competitorsQuery = useQuery({ queryKey: ['competitors', id], queryFn: () => getCompetitors(id), enabled: Boolean(id), refetchInterval: isActive ? 5000 : false });
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
    mutationFn: async (message: string) => {
      const userMsg: ChatMessage = {
        id: `temp-${Date.now()}`,
        run_id: id,
        role: 'user',
        content: message,
        intent: null,
        action_type: null,
        report_version: null,
        metadata_json: null,
        created_at: new Date().toISOString(),
      };
      setChatMessages((prev) => [...prev, userMsg]);
      setCompletedSteps([]);
      setActiveWorkflowKind('edit');
      setProcessingStage('classifying');
      return sendChatMessage(id, message);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['chat-messages', id] });
      queryClient.invalidateQueries({ queryKey: ['run', id] });
      queryClient.invalidateQueries({ queryKey: ['report', id] });
      queryClient.invalidateQueries({ queryKey: ['report-versions', id] });
      queryClient.invalidateQueries({ queryKey: ['report-citations', id] });
      queryClient.invalidateQueries({ queryKey: ['citation-bundle', id] });
      queryClient.invalidateQueries({ queryKey: ['sources', id] });
      queryClient.invalidateQueries({ queryKey: ['evidence', id] });
      setProcessingStage('idle');
      setCompletedSteps([]);
      setActiveWorkflowKind(data.intent === 'report_redo' ? 'redo' : 'edit');
      setChatMessages((prev) => [...prev, data.message]);
      setChatInput('');
      if (data.report_version != null) {
        setSelectedIteration(data.report_version);
      }
    },
    onError: () => {
      setProcessingStage('idle');
      setCompletedSteps([]);
    },
  });

  useEffect(() => {
    if (run?.status === 'completed') setMobileTab('report');
  }, [run?.status]);

  const traces = timelineQuery.data ?? [];
  const competitors = competitorsQuery.data ?? [];
  const sources = sourcesQuery.data ?? [];
  const evidence = evidenceQuery.data ?? [];
  const report = reportQuery.data;
  const reportVersions = reportVersionsQuery.data ?? [];
  const latestReportIteration = reportVersions.length ? reportVersions[reportVersions.length - 1].iteration : undefined;
  const completed = run?.status === 'completed' && Boolean(report);
  const canSendChat = Boolean(report) && !chatSendMutation.isPending && Boolean(chatInput.trim());
  const stageCounts = useMemo(() => ({
    competitors: competitors.length,
    sources: sources.length,
    evidence: evidence.length,
    hasReport: Boolean(report),
  }), [competitors.length, evidence.length, report, sources.length]);
  const stages = useMemo(() => run
    ? (stageOrder
      .map((stage) => ({ stage, status: getStageStatus(stage, run, traces) }))
      .filter(({ status }) => isStageVisible(status))
      .length > 0
        ? stageOrder
          .map((stage) => ({ stage, status: getStageStatus(stage, run, traces) }))
          .filter(({ status }) => isStageVisible(status))
        : [{ stage: 'requirement_understanding', status: 'running' }])
    : [], [run, traces]);
  const revealedStages = stages.slice(0, revealedStageCount);
  const nextStage = stages[revealedStageCount];

  useEffect(() => {
    setRevealedStageCount(0);
    setManualStageCollapse(false);
  }, [id]);

  useEffect(() => {
    if (!run || revealedStageCount >= stages.length) return undefined;
    const timer = window.setTimeout(() => {
      setRevealedStageCount((count) => Math.min(count + 1, stages.length));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [revealedStageCount, run, stages.length]);

  useEffect(() => {
    setRevealedStageCount((count) => Math.min(count, stages.length));
  }, [stages.length]);

  useEffect(() => {
    if (!run || manualStageCollapse) return;
    if (run.status === 'running' || run.status === 'waiting_for_human' || run.status === 'waiting_for_clarification') {
      setStagesCollapsed(false);
      return;
    }
    if (run.status === 'completed' || run.status === 'failed') {
      setStagesCollapsed(true);
    }
  }, [manualStageCollapse, run?.status]);

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
          <p>{statusLabels[run.status] ?? run.status}</p>
        </div>
        {run.status === 'completed' ? (
          <button type="button" className="icon-text-button" onClick={() => regenerateMutation.mutate()} disabled={regenerateMutation.isPending}>
            <RotateCcw size={16} />
            {regenerateMutation.isPending ? '生成中' : '重新生成'}
          </button>
        ) : null}
      </div>

      <div className="message-stream" ref={chatListRef}>
        <article className="message-row user">
          <div className="message-bubble">{run.user_requirement}</div>
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
            <div className="message-bubble">{answer}</div>
          </article>
        ))}
        {stages.length > 0 ? (
          <article className="message-row assistant">
            <div className="stage-collapse-card">
              <button
                type="button"
                className="stage-collapse-toggle"
                onClick={() => {
                  setManualStageCollapse(true);
                  setStagesCollapsed(!stagesCollapsed);
                }}
              >
                <div className="stage-collapse-title">
                  <CheckCircle2 size={16} />
                  <strong>分析过程</strong>
                  <span className="stage-collapse-summary">
                    {revealedStages.map(({ stage, status }) => status === 'completed' ? `${stageLabels[stage] ?? stage} ✓` : `...`).join(' → ')}
                  </span>
                </div>
                {stagesCollapsed ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
              </button>
              {!stagesCollapsed ? (
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
                      hasReport={Boolean(hasReport)}
                      citationBundle={citationBundleQuery.data ?? []}
                      runId={id}
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
              ) : null}
            </div>
          </article>
        ) : null}
        {run.status === 'completed' ? (
          <article className="message-row assistant">
            <div className="assistant-card report-done-card">
              <div className="assistant-card-title">
                <CheckCircle2 size={17} />
                <strong>报告已生成</strong>
              </div>
              <p>
                第一轮分析已完成。右侧可查看完整报告，下方可以继续对话修改报告。
              </p>
              <button
                type="button"
                className="chat-view-report-btn"
                onClick={() => {
                  setSelectedIteration(latestReportIteration ?? undefined);
                  setMobileTab('report');
                  setReportCollapsed(false);
                }}
              >
                查看报告
              </button>
            </div>
          </article>
        ) : null}

        {chatMessages.length > 0 ? (
          <div className="chat-round-divider">
            <span>对话修改</span>
          </div>
        ) : null}
        {(chatMessages ?? []).map((msg: ChatMessage) => (
          msg.role === 'user' ? (
            <article key={msg.id} className="message-row user">
              <div className="message-bubble">{msg.content}</div>
            </article>
          ) : (
            <article key={msg.id} className="message-row assistant">
              <div className="assistant-card">
                <div className="assistant-card-title">
                  <CheckCircle2 size={17} />
                  <strong>
                    {msg.intent === 'report_redo' ? '已重新调研并更新报告' : '已修改报告'}
                  </strong>
                </div>
                <AgentWorkflowBlock message={msg} />
                <p>{msg.content}</p>
                {msg.report_version ? (
                  <button
                    type="button"
                    className="chat-view-report-btn"
                    onClick={() => {
                      setSelectedIteration(msg.report_version!);
                      setMobileTab('report');
                      setReportCollapsed(false);
                    }}
                  >
                    查看报告 V{msg.report_version}
                  </button>
                ) : null}
              </div>
            </article>
          )
        ))}
        {processingStage !== 'idle' ? (
          <article className="message-row assistant chat-process-group">
            <div className="agent-workflow-card live">
              <div className="agent-workflow-title">
                <Loader2 size={15} />
                  <strong>Agent 正在规划修订流程</strong>
              </div>
              <div className="agent-workflow-list">
                {completedSteps.map((step) => (
                  <div key={step} className="agent-workflow-step done">
                    <CheckCircle2 size={14} />
                    <span>{step}</span>
                  </div>
                ))}
                {processingStage !== 'done' ? (
                  <div className="agent-workflow-step running">
                    <Loader2 size={14} />
                    <span>
                      {processingStage === 'classifying' && '让大模型判断修改类型并生成修订方案'}
                      {processingStage === 'searching' && (activeWorkflowKind === 'redo' ? '搜索/补充新资料' : '准备修改上下文')}
                      {processingStage === 'analyzing' && '重新分析竞品'}
                      {processingStage === 'editing' && '编辑报告内容'}
                      {processingStage === 'generating' && '生成新报告'}
                    </span>
                  </div>
                ) : null}
              </div>
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
          chatSendMutation.mutate(msg);
        }}
      >
        <textarea
          className="conversation-input"
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              const msg = chatInput.trim();
              if (!canSendChat) return;
              chatSendMutation.mutate(msg);
            }
          }}
          placeholder={report ? '继续对话：删除定价章节 / 增加用户评价对比 / 重新调研某个方向...' : '报告生成后可继续对话修改'}
          rows={2}
          disabled={chatSendMutation.isPending}
        />
        <button type="submit" className="conversation-send-btn" disabled={!canSendChat}>
          <Send size={18} />
        </button>
      </form>
    </section>
  );

  const reportColumn = (
    <section className="report-panel">
      <div className="report-toolbar">
        <div>
          <h2>{report?.title ?? '竞品分析报告'}</h2>
          <p>{report ? `第 ${report.iteration} 版 · ${report.summary}` : '报告生成后会显示在这里'}</p>
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
      {reportVersions.length > 1 ? (
        <div className="report-version-selector">
          <span className="report-version-label">报告版本</span>
          {reportVersions.map((version) => (
            <button
              key={version.id}
              type="button"
              className={`report-version-btn ${(selectedIteration ?? latestReportIteration) === version.iteration ? 'active' : ''}`}
              onClick={() => setSelectedIteration(version.iteration)}
            >
              {version.iteration === 0 ? '初始版本' : `第 ${version.iteration} 轮`}
            </button>
          ))}
        </div>
      ) : null}
      <article className="report-document conversational-report">
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
    </section>
  );

  return (
    <div className={`analysis-workspace ${completed ? 'completed' : ''} ${reportCollapsed ? 'report-collapsed' : ''}`}>
      <div className="mobile-result-tabs">
        <button type="button" className={mobileTab === 'process' ? 'active' : ''} onClick={() => setMobileTab('process')}>过程</button>
        <button type="button" className={mobileTab === 'report' ? 'active' : ''} onClick={() => setMobileTab('report')}>报告</button>
      </div>
      <div className="analysis-split">
        <div className={`process-slot ${mobileTab === 'process' ? 'mobile-active' : ''}`}>{processColumn}</div>
        {completed || hasReport ? <div className={`report-slot ${mobileTab === 'report' ? 'mobile-active' : ''}`}>{reportColumn}</div> : null}
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
        <CheckCircle2 size={15} />
        <strong>Agent 工作流</strong>
      </div>
      <div className="agent-workflow-list">
        {steps.map((step, index) => (
          <div key={`${step.title}-${index}`} className="agent-workflow-step done">
            <CheckCircle2 size={14} />
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
  runId,
  clarification,
}: {
  stage: string;
  status: string;
  run: Run;
  counts: { competitors: number; sources: number; evidence: number; hasReport: boolean };
  competitors: Competitor[];
  sources: Source[];
  evidence: Evidence[];
  hasReport: boolean;
  citationBundle: CitationBundleCompetitor[];
  runId: string;
  clarification: {
    value: string;
    onChange: (value: string) => void;
    onSubmit: (answer: string) => void;
    isPending: boolean;
    error: unknown;
  };
}) {
  const showClarification = stage === 'requirement_understanding' && run.status === 'waiting_for_clarification';
  const showCompetitorConfirm = stage === 'human_confirm_competitors' && (run.status === 'waiting_for_human' || competitors.length > 0);
  const showSources = stage === 'material_collection' && (sources.length > 0 || evidence.length > 0);
  const showCitations = stage === 'structured_analysis' && citationBundle.length > 0;
  const showQA = stage === 'quality_check' && hasReport;

  return (
    <article className="message-row assistant stage-message-row">
      <div className={`stage-message-card ${status}`}>
        <div className="stage-message-head">
          <div className="stage-status-icon">{statusIcon(status)}</div>
          <div>
            <h3>{stageLabels[stage] ?? stage}</h3>
            <span>{statusText(status)}</span>
          </div>
        </div>
        <p>{getStageDetail(stage, run, counts)}</p>

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
            <SourceList sources={sources} isCollecting={run.status === 'running'} />
            <EvidenceList evidence={evidence} sources={sources} />
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
            <QAResultsPanel runId={runId} />
          </div>
        ) : null}
      </div>
    </article>
  );
}

function statusIcon(status: string) {
  if (status === 'completed') return <CheckCircle2 size={18} />;
  if (status === 'failed') return <XCircle size={18} />;
  if (status === 'running') return <Loader2 size={18} />;
  return <span className="pending-dot" />;
}

function statusText(status: string) {
  const map: Record<string, string> = {
    completed: '已完成',
    running: '进行中',
    failed: '失败',
    pending: '待开始',
  };
  return map[status] ?? status;
}
