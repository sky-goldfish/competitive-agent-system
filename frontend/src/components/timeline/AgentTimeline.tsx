import { CheckCircle2, CircleDashed, Clock3, Search, Sparkles, XCircle } from 'lucide-react';
import type { Run, Trace } from '../../lib/types';
import HybridQueryVisualizer from '../query/HybridQueryVisualizer';

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
  completed: '已完成',
  target_query_planning: '规划目标搜索',
  target_search: '搜索目标资料',
  target_understanding: '理解目标对象',
  competitor_query_planning: '规划竞品搜索',
  competitor_search: '搜索候选竞品',
  candidate_extraction: '抽取候选竞品',
  official_site_resolution: '解析官网',
  quart_planning: '规划检索 Quart',
  material_query_planning: '规划资料采集',
  source_search: '搜索来源资料',
  source_classification: '分类来源可信度',
  evidence_extraction: '抽取证据片段',
  coverage_checking: '检查覆盖度',
};

const mainStages = [
  'requirement_understanding',
  'competitor_discovery',
  'human_confirm_competitors',
  'material_collection',
  'structured_analysis',
  'report_generation',
];

const childStageGroups: Record<string, string[]> = {
  competitor_discovery: [
    'target_query_planning',
    'target_search',
    'target_understanding',
    'competitor_query_planning',
    'competitor_search',
    'candidate_extraction',
    'official_site_resolution',
  ],
  material_collection: [
    'quart_planning',
    'material_query_planning',
    'source_search',
    'source_classification',
    'evidence_extraction',
    'coverage_checking',
  ],
};

const childStageToParent = Object.fromEntries(
  Object.entries(childStageGroups).flatMap(([parent, children]) => children.map((child) => [child, parent])),
) as Record<string, string>;

const stageDescriptions: Record<string, string> = {
  requirement_understanding: '识别输入类型、目标产品和分析维度',
  competitor_discovery: '搜索目标对象、理解定位并生成候选竞品',
  human_confirm_competitors: '等待你确认、删除或补充竞品',
  material_collection: '围绕已确认竞品采集公开资料和证据',
  structured_analysis: '按维度整理定位、功能、价格和机会点',
  report_generation: '生成 Markdown 报告并关联来源证据',
  target_query_planning: '为目标产品或产品想法规划搜索关键词',
  target_search: '调用搜索工具采集目标相关公开资料',
  target_understanding: '归纳目标对象的定位、用户和核心能力',
  competitor_query_planning: '基于目标画像规划竞品发现搜索',
  competitor_search: '搜索候选竞品列表、榜单和对比资料',
  candidate_extraction: '从搜索结果中抽取候选竞品并生成推荐理由',
  official_site_resolution: '为候选竞品解析可信官网和证据页面',
  quart_planning: '按竞品关系、产品类型和知识缺口生成检索任务单元',
  material_query_planning: '为已确认竞品按维度规划资料采集关键词',
  source_search: '调用搜索工具召回候选来源网页',
  source_classification: '判断来源类型并估计可信度',
  evidence_extraction: '从来源摘要和正文中抽取可追溯证据',
  coverage_checking: '检查每个竞品的资料覆盖度和缺口',
};

type Props = {
  traces: Trace[];
  run: Run;
  compactHeader?: boolean;
};

function formatDuration(ms: number | null) {
  if (ms == null) return '进行中';
  if (ms < 1000) return `${ms}ms`;
  return `${Math.round(ms / 1000)}s`;
}

function parseApiDate(value: string) {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

function formatElapsedSeconds(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function elapsedFrom(startedAt: string, endedAt?: string | null) {
  const endTime = endedAt ? parseApiDate(endedAt).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((endTime - parseApiDate(startedAt).getTime()) / 1000));
  return formatElapsedSeconds(seconds);
}

function parseHybridQueries(trace: Trace) {
  if (!trace.output_json) return null;
  try {
    const data = JSON.parse(trace.output_json) as Record<string, unknown>;
    if (data.queries && Array.isArray(data.queries)) {
      const queryPurposes = Array.isArray(data.query_purposes) ? data.query_purposes : [];
      const queries = (data.queries as unknown[]).map((q, idx) => ({
        query: typeof q === 'string' ? q : '',
        purpose: typeof queryPurposes[idx] === 'string' ? queryPurposes[idx] : `hybrid_search_${idx}`
      })).filter(item => item.query);
      if (queries.length > 0) return queries;
    }
    if (data.query_count && data.queries && Array.isArray(data.queries)) {
      const queryPurposes = Array.isArray(data.query_purposes) ? data.query_purposes : [];
      const queries = (data.queries as unknown[]).map((q, idx) => ({
        query: typeof q === 'string' ? q : '',
        purpose: typeof queryPurposes[idx] === 'string' ? queryPurposes[idx] : `hybrid_search_${idx}`
      })).filter(item => item.query);
      if (queries.length > 0) return queries;
    }
    return null;
  } catch {
    return null;
  }
}

function parseSummary(trace: Trace) {
  if (!trace.output_json) return [];
  try {
    const data = JSON.parse(trace.output_json) as Record<string, unknown>;
    return Object.entries(data)
      .filter(([key, value]) => key !== 'message' && key !== 'queries' && value !== null && value !== undefined && value !== '')
      .slice(0, 5)
      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`);
  } catch {
    return [];
  }
}

function parseTraceMessage(trace: Trace) {
  if (!trace.input_json) return null;
  try {
    const data = JSON.parse(trace.input_json) as Record<string, unknown>;
    return typeof data.message === 'string' ? data.message : null;
  } catch {
    return null;
  }
}

function getTraceTime(trace: Trace) {
  return new Date(trace.started_at).getTime();
}

function getLatestTrace(traces: Trace[]) {
  return traces.reduce<Trace | undefined>((latest, trace) => {
    if (!latest) return trace;
    return getTraceTime(trace) > getTraceTime(latest) ? trace : latest;
  }, undefined);
}

function getGroupedTraces(traces: Trace[]) {
  const grouped = mainStages.map((stage) => ({
    stage,
    main: traces.find((trace) => trace.stage === stage),
    children: traces.filter((trace) => childStageToParent[trace.stage] === stage),
  }));
  const knownStages = new Set([...mainStages, ...Object.keys(childStageToParent)]);
  const loose = traces.filter((trace) => !knownStages.has(trace.stage)).map((trace) => ({ stage: trace.stage, main: trace, children: [] }));
  return [...grouped, ...loose].filter((group) => group.main || group.children.length > 0);
}

function getGroupStatus(stage: string, main: Trace | undefined, children: Trace[], run: Run) {
  if (main?.status === 'failed' || children.some((trace) => trace.status === 'failed')) return 'failed';
  if (main?.status === 'running' || children.some((trace) => trace.status === 'running') || run.current_stage === stage) return 'running';
  if (main?.status === 'completed' || children.length > 0) return 'completed';
  return 'pending';
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 size={18} />;
  if (status === 'failed') return <XCircle size={18} />;
  if (status === 'pending') return <Clock3 size={18} />;
  return <CircleDashed size={18} />;
}

export default function AgentTimeline({ traces, run, compactHeader = false }: Props) {
  const groups = getGroupedTraces(traces);
  const runningTrace = traces.find((trace) => trace.status === 'running');
  const lastTrace = getLatestTrace(traces);
  const currentStage = runningTrace?.stage ?? run.current_stage;
  const isRunning = run.status === 'running';
  const elapsed = runningTrace
    ? elapsedFrom(runningTrace.started_at)
    : elapsedFrom(run.created_at, run.completed_at);

  return (
    <section className="panel">
      {!compactHeader ? (
        <div className="panel-header">
          <div>
            <h2>Agent Activity</h2>
            <p className="muted">实时展示 Agent 当前阶段、搜索/思考/生成状态</p>
          </div>
          <span>{traces.length} steps</span>
        </div>
      ) : null}

      {isRunning ? (
        <div className="working-banner">
          <Clock3 size={18} />
          <span>Still working... {elapsed} elapsed，当前：{stageLabels[currentStage] ?? currentStage}</span>
        </div>
      ) : null}

      {isRunning && traces.length === 0 ? (
        <div className="agent-empty-state">
          <Sparkles size={20} />
          <div>
            <strong>Starting agent...</strong>
            <p>正在初始化任务，很快会显示第一个执行步骤。</p>
          </div>
        </div>
      ) : null}

      <div className="timeline-groups">
        {groups.map((group) => {
          const latestChild = getLatestTrace(group.children);
          const displayTrace = latestChild ?? group.main;
          const groupStatus = getGroupStatus(group.stage, group.main, group.children, run);
          const summary = group.main ? parseSummary(group.main) : [];
          const message = displayTrace ? parseTraceMessage(displayTrace) : null;
          const completedChildren = group.children.filter((trace) => trace.status === 'completed').length;
          const groupDuration = group.main
            ? formatDuration(group.main.duration_ms)
            : groupStatus === 'running' && displayTrace
              ? elapsedFrom(displayTrace.started_at)
              : `${completedChildren}/${group.children.length}`;
          return (
            <article key={group.stage} className={`timeline-group ${groupStatus}`}>
              <div className={`timeline-icon ${groupStatus}`}>
                <StatusIcon status={groupStatus} />
              </div>
              <div className="tool-call-body">
                <div className="tool-call-title">
                  <strong>{stageLabels[group.stage] ?? group.stage}</strong>
                  <span>{groupStatus === 'running' ? '正在执行' : groupStatus} · {groupDuration}</span>
                </div>
                <p>{message ?? stageDescriptions[group.stage] ?? '执行 Agent 子任务'}</p>
                {summary.length > 0 ? (
                  <ul className="trace-summary compact">
                    {summary.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                ) : null}
                {group.children.length > 0 ? (
                  <div className="timeline-substeps">
                    {group.children.map((trace) => {
                      const childMessage = parseTraceMessage(trace);
                      const childSummary = parseSummary(trace).slice(0, 2);
                      const hybridQueries = parseHybridQueries(trace);
                      return (
                        <div key={trace.id} className={`timeline-substep ${trace.status}`}>
                          <div className={`substep-dot ${trace.status}`} />
                          <div>
                            <div className="substep-title">
                              <strong>{stageLabels[trace.stage] ?? trace.stage}</strong>
                              <span>{trace.status === 'running' ? elapsedFrom(trace.started_at) : formatDuration(trace.duration_ms)}</span>
                            </div>
                            <p>{childMessage ?? stageDescriptions[trace.stage] ?? '执行子步骤'}</p>
                            {hybridQueries ? (
                              <HybridQueryVisualizer 
                                queries={hybridQueries} 
                                title={trace.stage === 'target_query_planning' ? '目标理解混合检索' : '竞品发现混合检索'} 
                              />
                            ) : null}
                            {childSummary.length > 0 ? <p className="muted substep-summary">{childSummary.join(' · ')}</p> : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
                {groupStatus === 'running' ? (
                  <p className="muted inline-progress"><Search size={14} /> 正在调用搜索/模型/分析工具，请稍候...</p>
                ) : null}
                {group.main?.error_message ? <p className="error-text">{group.main.error_message}</p> : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
