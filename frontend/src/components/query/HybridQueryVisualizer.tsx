import { Globe, Search, MapPin } from 'lucide-react';

type HybridQuery = {
  query: string;
  purpose: string;
};

type Props = {
  queries: HybridQuery[];
  title?: string;
};

function isEnglishQuery(text: string): boolean {
  const englishChars = text.match(/[a-zA-Z"]/g)?.length ?? 0;
  const totalChars = text.length;
  return totalChars > 0 && englishChars / totalChars > 0.5;
}

export default function HybridQueryVisualizer({ queries, title = "混合检索策略" }: Props) {
  if (!queries || queries.length === 0) {
    return null;
  }

  const globalQueries = queries.filter((q) => isEnglishQuery(q.query));
  const localQueries = queries.filter((q) => !isEnglishQuery(q.query));

  return (
    <section className="hybrid-query-panel">
      <div className="hybrid-query-header">
        <Search size={18} />
        <h3>{title}</h3>
        <span className="query-count-badge">{queries.length} 个搜索词</span>
      </div>

      <div className="hybrid-query-grid">
        {globalQueries.length > 0 ? (
          <div className="query-card global">
            <div className="query-card-header">
              <Globe size={16} />
              <span>全球前沿技术</span>
            </div>
            <ul className="query-list">
              {globalQueries.map((item, idx) => (
                <li key={`global-${idx}`} className="query-item global">
                  <code>{item.query}</code>
                  <span className="query-purpose">{item.purpose}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {localQueries.length > 0 ? (
          <div className="query-card local">
            <div className="query-card-header">
              <MapPin size={16} />
              <span>国内本土竞品</span>
            </div>
            <ul className="query-list">
              {localQueries.map((item, idx) => (
                <li key={`local-${idx}`} className="query-item local">
                  <code>{item.query}</code>
                  <span className="query-purpose">{item.purpose}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <style>{`
        .hybrid-query-panel {
          background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
          border-radius: 12px;
          padding: 16px;
          margin: 12px 0;
          border: 1px solid #e2e8f0;
        }
        .hybrid-query-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 16px;
        }
        .hybrid-query-header h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 600;
          color: #1e293b;
        }
        .query-count-badge {
          margin-left: auto;
          background: #3b82f6;
          color: white;
          padding: 4px 10px;
          border-radius: 20px;
          font-size: 12px;
          font-weight: 500;
        }
        .hybrid-query-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .query-card {
          border-radius: 10px;
          padding: 12px;
        }
        .query-card.global {
          background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
          border: 1px solid #93c5fd;
        }
        .query-card.local {
          background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
          border: 1px solid #86efac;
        }
        .query-card-header {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 10px;
          font-weight: 600;
          font-size: 14px;
        }
        .query-card.global .query-card-header {
          color: #1d4ed8;
        }
        .query-card.local .query-card-header {
          color: #15803d;
        }
        .query-list {
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .query-item {
          padding: 8px 10px;
          border-radius: 8px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .query-item.global {
          background: rgba(255, 255, 255, 0.7);
        }
        .query-item.local {
          background: rgba(255, 255, 255, 0.7);
        }
        .query-item code {
          font-family: 'Monaco', 'Menlo', monospace;
          font-size: 13px;
          color: #0f172a;
          word-break: break-all;
        }
        .query-purpose {
          font-size: 11px;
          color: #64748b;
        }
        @media (max-width: 768px) {
          .hybrid-query-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  );
}
