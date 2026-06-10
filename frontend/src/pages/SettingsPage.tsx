import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';

export default function SettingsPage() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (
    localStorage.getItem('appearance-theme') === 'dark' ? 'dark' : 'light'
  ));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('appearance-theme', theme);
  }, [theme]);

  return (
    <section className="settings-page">
      <div className="settings-shell">
        <aside className="settings-nav" aria-label="设置分类">
          <div className="settings-nav-head">
            <span>设置</span>
            <strong>竞品 Agent</strong>
          </div>
          <button type="button" className="active">
            外观
          </button>
        </aside>

        <main className="settings-content">
          <section className="settings-panel">
            <header className="settings-header">
              <span>外观</span>
              <h1>调整界面显示</h1>
              <p>切换夜间版后会立即应用，并保存在本机浏览器。</p>
            </header>

            <div className="appearance-card">
              <div className="appearance-card-main">
                <span className="settings-row-icon">
                  {theme === 'dark' ? <Moon size={17} /> : <Sun size={17} />}
                </span>
                <div>
                  <strong>夜间版</strong>
                  <span>降低亮度，适合长时间查看报告和资料。</span>
                </div>
              </div>
              <button
                type="button"
                className={`theme-toggle ${theme === 'dark' ? 'active' : ''}`}
                onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
                aria-pressed={theme === 'dark'}
              >
                <span />
              </button>
            </div>
          </section>
        </main>
      </div>
    </section>
  );
}
