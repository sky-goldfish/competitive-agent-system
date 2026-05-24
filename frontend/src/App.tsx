import { Link, Route, Routes } from 'react-router-dom';
import NewAnalysisPage from './pages/NewAnalysisPage';
import ReportPage from './pages/ReportPage';
import RunDetailPage from './pages/RunDetailPage';

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand">竞品分析 Agent 协作系统</Link>
        <span className="badge">MVP Mock</span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<NewAnalysisPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/runs/:runId/report" element={<ReportPage />} />
        </Routes>
      </main>
    </div>
  );
}
