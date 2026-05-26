import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import HistoryPage from './pages/HistoryPage';
import NewAnalysisPage from './pages/NewAnalysisPage';
import ReportPage from './pages/ReportPage';
import RunDetailPage from './pages/RunDetailPage';

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
    <div className="panel" style={{ margin: '2rem auto', maxWidth: 600, textAlign: 'center' }}>
      <h2>404 — 页面未找到</h2>
      <p className="muted">你访问的页面不存在。</p>
      <Link className="primary-link" to="/">返回首页</Link>
    </div>
  );
}

export default function App() {
  function showUnavailable() {
    window.alert('暂未开放');
  }

  return (
    <ErrorBoundary>
      <div className="app-shell">
        <header className="topbar">
          <Link to="/" className="brand">竞品分析 Agent 协作系统</Link>
          <nav className="global-nav" aria-label="主导航">
            <Link to="/history" className="nav-link">分析历史</Link>
            <button type="button" className="nav-link nav-button" onClick={showUnavailable}>问卷调研</button>
            <button type="button" className="nav-link nav-button" onClick={showUnavailable}>访谈记录</button>
            <button type="button" className="nav-link nav-button" onClick={showUnavailable}>知识库</button>
            <div className="user-chip">admin</div>
          </nav>
        </header>
        <main>
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
