import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Database, Menu, PanelLeftClose, Pin, Plus, Settings, Trash2 } from 'lucide-react';
import HistoryPage from './pages/HistoryPage';
import KnowledgePage from './pages/KnowledgePage';
import NewAnalysisPage from './pages/NewAnalysisPage';
import ReportPage from './pages/ReportPage';
import ObservabilityPage from './pages/ObservabilityPage';
import RunDetailPage from './pages/RunDetailPage';
import SettingsPage from './pages/SettingsPage';
import { listRuns } from './lib/api';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('React error boundary caught:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel" style={{ margin: '2rem auto', maxWidth: 600, textAlign: 'center' }}>
          <h2>页面渲染出错</h2>
          <p className="error-text">{this.state.error.message}</p>
          <button className="primary-link" onClick={() => { this.setState({ error: null }); window.location.href = '/'; }}>
            返回首页
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function NotFoundPage() {
  return (
    <div className="empty-route">
      <h2>页面未找到</h2>
      <p>你访问的页面不存在。</p>
      <Link className="primary-link" to="/">返回首页</Link>
    </div>
  );
}

function AppSidebar() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pinnedRunIds, setPinnedRunIds] = useState<string[]>(() => readStoredList('pinned-history-runs'));
  const [deletedRunIds, setDeletedRunIds] = useState<string[]>(() => readStoredList('deleted-history-runs'));
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: listRuns, refetchInterval: 5000 });
  const runs = runsQuery.data ?? [];
  const visibleRuns = runs
    .filter((run) => !deletedRunIds.includes(run.id))
    .sort((a, b) => {
      const aPinned = pinnedRunIds.includes(a.id);
      const bPinned = pinnedRunIds.includes(b.id);
      if (aPinned !== bPinned) return aPinned ? -1 : 1;
      return 0;
    });
  const sidebarClass = [
    'ai-sidebar',
    collapsed ? 'collapsed' : '',
    drawerOpen ? 'drawer-open' : '',
  ].filter(Boolean).join(' ');

  function togglePin(runId: string) {
    setPinnedRunIds((current) => {
      const next = current.includes(runId) ? current.filter((id) => id !== runId) : [runId, ...current];
      localStorage.setItem('pinned-history-runs', JSON.stringify(next));
      return next;
    });
  }

  function deleteHistoryItem(runId: string) {
    setDeletedRunIds((current) => {
      const next = current.includes(runId) ? current : [...current, runId];
      localStorage.setItem('deleted-history-runs', JSON.stringify(next));
      return next;
    });
    setPinnedRunIds((current) => {
      const next = current.filter((id) => id !== runId);
      localStorage.setItem('pinned-history-runs', JSON.stringify(next));
      return next;
    });
  }

  return (
    <>
      <button type="button" className="mobile-sidebar-trigger" onClick={() => setDrawerOpen(true)} aria-label="打开侧边栏">
        <Menu size={20} />
      </button>
      {drawerOpen ? <button type="button" className="sidebar-scrim" onClick={() => setDrawerOpen(false)} aria-label="关闭侧边栏" /> : null}
      <aside className={sidebarClass}>
        <div className="sidebar-top">
          <button type="button" className="sidebar-icon-button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}>
            {collapsed ? <Menu size={19} /> : <PanelLeftClose size={19} />}
          </button>
          {!collapsed ? <strong className="sidebar-brand">竞品 Agent</strong> : null}
        </div>

        {!collapsed ? (
          <>
            <div className="sidebar-actions">
              <Link className="sidebar-action" to="/" onClick={() => setDrawerOpen(false)}>
                <Plus size={18} />
                <span>新建对话</span>
              </Link>
              <Link className="sidebar-action" to="/settings" onClick={() => setDrawerOpen(false)}>
                <Settings size={18} />
                <span>设置</span>
              </Link>
              <Link className="sidebar-action" to="/knowledge" onClick={() => setDrawerOpen(false)}>
                <Database size={18} />
                <span>知识库</span>
              </Link>
            </div>

            <div className="history-list-wrap">
              <div className="history-list-title">历史竞品检索</div>
              <nav className="sidebar-history" aria-label="历史竞品检索记录">
                {visibleRuns.length === 0 && !runsQuery.isLoading ? <span className="sidebar-empty">暂无历史记录</span> : null}
                {visibleRuns.map((run) => {
                  const active = location.pathname === `/runs/${run.id}` || location.pathname.startsWith(`/runs/${run.id}/`);
                  const pinned = pinnedRunIds.includes(run.id);
                  return (
                    <div
                      key={run.id}
                      className={`history-item ${active ? 'active' : ''} ${pinned ? 'pinned' : ''}`}
                    >
                      <NavLink
                        to={`/runs/${run.id}`}
                        className="history-item-link"
                        onClick={() => setDrawerOpen(false)}
                      >
                        <span className="history-item-main">
                          <span className="history-item-title">{run.title || run.user_requirement}</span>
                          <span className={`history-item-status ${run.status}`}>{pinned ? '已置顶 · ' : ''}{statusText(run.status)}</span>
                        </span>
                      </NavLink>
                      <span className="history-item-actions">
                        <button
                          type="button"
                          className="history-action-button"
                          onClick={(event) => {
                            event.stopPropagation();
                            togglePin(run.id);
                          }}
                          title={pinned ? '取消置顶' : '置顶'}
                        >
                          <Pin size={14} />
                        </button>
                        <button
                          type="button"
                          className="history-action-button danger"
                          onClick={(event) => {
                            event.stopPropagation();
                            deleteHistoryItem(run.id);
                          }}
                          title="从历史列表删除"
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </div>
                  );
                })}
              </nav>
            </div>
          </>
        ) : null}
      </aside>
    </>
  );
}

function statusText(status: string) {
  const map: Record<string, string> = {
    running: '执行中',
    waiting_for_clarification: '待补充',
    waiting_for_human: '待确认',
    completed: '已完成',
    failed: '失败',
  };
  return map[status] ?? status;
}

function readStoredList(key: string) {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? '[]');
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
  } catch (e) {
    console.warn(`Failed to parse localStorage key "${key}":`, e);
    return [];
  }
}

function ThemeSync() {
  useEffect(() => {
    const theme = localStorage.getItem('appearance-theme') === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = theme;
  }, []);
  return null;
}

export default function App() {
  return (
    <ErrorBoundary>
      <ThemeSync />
      <div className="ai-app-shell">
        <AppSidebar />
        <main className="ai-main">
          <Routes>
            <Route path="/" element={<NewAnalysisPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/runs/:runId/report" element={<ReportPage />} />
            <Route path="/runs/:runId/observability" element={<ObservabilityPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>
    </ErrorBoundary>
  );
}
