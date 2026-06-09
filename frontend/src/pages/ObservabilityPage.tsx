import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, BarChart3, Brain, ChevronDown, ChevronUp, Clock, Loader2, Search, XCircle } from 'lucide-react';
import { getObservability } from '../lib/api';
import type { CallTrace, ObservabilityStage } from '../lib/types';

const stageLabels: Record<string, string> = {
  requirement_understanding: '需求理解',
  focus_profile: '识别关注点',
  competitor_discovery: '竞品发现',
  human_confirm_competitors: '人工确认',
  material_collection: '资料采集',
  structured_analysis: '结构化分析',
  report_generation: '报告生成',
  quality_check: '质量检查',
};

export default function ObservabilityPage() {
  const { runId } = useParams<{ runId: string }>();
  const id = runId ?? '';

  const obsQuery = useQuery({
    queryKey: ['observability', id],
    queryFn: () => getObservability(id),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const isActive = query.state.data?.run?.status === 'running' || query.state.data?.run?.status === 'revising';
      return isActive ? 3000 : false;
    },
  });

  const data = obsQuery.data;
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [expandedCalls, setExpandedCalls] = useState<Set<string>>(new Set());

  if (obsQuery.isLoading) return <p className="loading">加载中...</p>;
  if (obsQuery.isError || !data) return <p className="error-text">加载失败。</p>;

  const { run, stages, stats } = data;

  function toggleStage(stage: string) {
    setSelectedStage((prev) => (prev === stage ? null : stage));
  }

  function toggleCallExpanded(callId: string) {
    setExpandedCalls((prev) => {
      const next = new Set(prev);
      if (next.has(callId)) next.delete(callId);
      else next.add(callId);
      return next;
    });
  }

  function formatDuration(ms: number) {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function formatTokens(count: number | null) {
    if (count == null) return '-';
    if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
    return String(count);
  }

  function formatJson(text: string | null) {
    if (!text) return '（无数据）';
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }

  function statusDot(status: string) {
    if (status === 'running') return <Loader2 size={14} className="spinning" />;
    if (status === 'failed') return <XCircle size={14} className="obs-icon-failed" />;
    return <span className="obs-dot-completed" />;
  }

  const selectedStageData = stages.find((s) => s.stage === selectedStage) ?? null;

  return (
    <div className="observability-page">
      <div className="obs-header">
        <Link to={`/runs/${id}`} className="icon-text-button">
          <ArrowLeft size={16} />
          返回
        </Link>
        <div className="obs-header-info">
          <h1>{run.title}</h1>
          <span className={`obs-status-badge ${run.status}`}>{run.status === 'running' ? '运行中' : run.status === 'completed' ? '已完成' : run.status === 'failed' ? '失败' : run.status}</span>
        </div>
      </div>

      <div className="obs-stats-bar">
        <div className="obs-stat-card">
          <Brain size={18} />
          <div>
            <span className="obs-stat-value">{stats.total_llm_calls}</span>
            <span className="obs-stat-label">LLM 调用</span>
          </div>
        </div>
        <div className="obs-stat-card">
          <Search size={18} />
          <div>
            <span className="obs-stat-value">{stats.total_search_calls}</span>
            <span className="obs-stat-label">搜索调用</span>
          </div>
        </div>
        <div className="obs-stat-card">
          <BarChart3 size={18} />
          <div>
            <span className="obs-stat-value">{formatTokens(stats.total_tokens)}</span>
            <span className="obs-stat-label">Token 消耗</span>
          </div>
        </div>
        <div className="obs-stat-card">
          <Clock size={18} />
          <div>
            <span className="obs-stat-value">{formatDuration(stats.total_duration_ms)}</span>
            <span className="obs-stat-label">总耗时</span>
          </div>
        </div>
      </div>

      <div className="obs-body">
        <aside className="obs-stage-list">
          <h3>分析阶段</h3>
          {stages.length === 0 ? (
            <p className="obs-empty">暂无追踪数据</p>
          ) : (
            stages.map((stage) => (
              <button
                key={stage.stage}
                type="button"
                className={`obs-stage-item ${selectedStage === stage.stage ? 'active' : ''} ${stage.status}`}
                onClick={() => toggleStage(stage.stage)}
              >
                <span className="obs-stage-icon">{statusDot(stage.status)}</span>
                <span className="obs-stage-name">{stageLabels[stage.stage] ?? stage.stage}</span>
                <span className="obs-stage-meta">
                  <span>{formatDuration(stage.duration_ms)}</span>
                  {stage.total_tokens > 0 && <span>{formatTokens(stage.total_tokens)} tokens</span>}
                  <span>{stage.calls.filter((c) => c.call_type === 'llm').length} LLM</span>
                  <span>{stage.calls.filter((c) => c.call_type === 'search').length} 搜索</span>
                </span>
              </button>
            ))
          )}
        </aside>

        <section className="obs-detail-panel">
          {selectedStageData ? (
            <>
              <div className="obs-detail-header">
                <h3>{stageLabels[selectedStageData.stage] ?? selectedStageData.stage}</h3>
                <span className="obs-detail-summary">
                  {formatDuration(selectedStageData.duration_ms)} · {formatTokens(selectedStageData.total_tokens)} tokens · {selectedStageData.calls.length} 次调用
                </span>
              </div>
              <div className="obs-call-list">
                {selectedStageData.calls.length === 0 ? (
                  <p className="obs-empty">此阶段暂无调用记录</p>
                ) : (
                  selectedStageData.calls.map((call) => (
                    <CallTraceItem
                      key={call.id}
                      call={call}
                      expanded={expandedCalls.has(call.id)}
                      onToggle={() => toggleCallExpanded(call.id)}
                    />
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="obs-detail-empty">
              <BarChart3 size={32} />
              <p>选择左侧阶段查看详细调用记录</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function CallTraceItem({ call, expanded, onToggle }: { call: CallTrace; expanded: boolean; onToggle: () => void }) {
  function formatTime(iso: string | null) {
    if (!iso) return '';
    // Backend stores UTC without timezone suffix; force UTC parse
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Shanghai' });
  }

  function formatDuration(ms: number | null) {
    if (ms == null) return '-';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function formatJson(text: string | null) {
    if (!text) return '（无数据）';
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }

  return (
    <div className={`obs-call-item ${call.status} ${expanded ? 'expanded' : ''}`}>
      <button type="button" className="obs-call-summary" onClick={onToggle}>
        <span className="obs-call-time">{formatTime(call.started_at)}</span>
        <span className={`obs-call-type-badge ${call.call_type}`}>
          {call.call_type === 'llm' ? <Brain size={13} /> : <Search size={13} />}
          {call.call_type === 'llm' ? 'LLM' : '搜索'}
        </span>
        <span className="obs-call-provider">{call.provider}</span>
        {call.call_type === 'llm' && call.model ? <span className="obs-call-model">{call.model}</span> : null}
        {call.call_type === 'llm' && call.token_count != null ? (
          <span className="obs-call-tokens">{call.token_count} tokens</span>
        ) : null}
        <span className="obs-call-duration">{formatDuration(call.duration_ms)}</span>
        {call.status === 'failed' ? <XCircle size={14} className="obs-icon-failed" /> : null}
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded ? (
        <div className="obs-call-body">
          <div className="obs-call-section">
            <strong>输入</strong>
            <pre className="obs-json-block">{formatJson(call.input_json)}</pre>
          </div>
          <div className="obs-call-section">
            <strong>输出</strong>
            <pre className="obs-json-block">{formatJson(call.output_json)}</pre>
          </div>
          {call.error_message ? (
            <div className="obs-call-error">
              <strong>错误</strong>
              <p>{call.error_message}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
