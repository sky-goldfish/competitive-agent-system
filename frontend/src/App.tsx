import { Component, useState, type ErrorInfo, type ReactNode } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Menu, PanelLeftClose, Plus, Settings } from 'lucide-react';
import HistoryPage from './pages/HistoryPage';
import NewAnalysisPage from './pages/NewAnalysisPage';
import ReportPage from './pages/ReportPage';
import RunDetailPage from './pages/RunDetailPage';
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
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: listRuns, refetchInterval: 5000 });
  const runs = runsQuery.data ?? [];
  const sidebarClass = [
    'ai-sidebar',
    collapsed ? 'collapsed' : '',
    drawerOpen ? 'drawer-open' : '',
  ].filter(Boolean).join(' ');

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
              <button type="button" className="sidebar-action" onClick={() => window.alert('设置暂未开放')}>
                <Settings size={18} />
                <span>设置</span>
              </button>
            </div>

            <div className="history-list-wrap">
              <div className="history-list-title">历史竞品检索</div>
              <nav className="sidebar-history" aria-label="历史竞品检索记录">
                {runs.length === 0 && !runsQuery.isLoading ? <span className="sidebar-empty">暂无历史记录</span> : null}
                {runs.map((run) => {
                  const active = location.pathname.includes(`/runs/${run.id}`);
                  return (
                    <NavLink
                      key={run.id}
                      to={`/runs/${run.id}`}
                      className={`history-item ${active ? 'active' : ''}`}
                      onClick={() => setDrawerOpen(false)}
                    >
                      <span className="history-item-title">{run.title || run.user_requirement}</span>
                      <span className={`history-item-status ${run.status}`}>{statusText(run.status)}</span>
                    </NavLink>
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

export default function App() {
  return (
    <ErrorBoundary>
      <div className="ai-app-shell">
        <AppSidebar />
        <main className="ai-main">
          <Routes>
            <Route path="/" element={<NewAnalysisPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/runs/:runId/report" element={<ReportPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
      </div>
    </ErrorBoundary>
  );
}
