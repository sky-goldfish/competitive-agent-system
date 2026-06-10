import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Database, Moon, Search, ShieldCheck, SlidersHorizontal, Sun, Trash2 } from 'lucide-react';
import { clearKnowledgeItems } from '../lib/api';

const analysisItems = [
  { icon: Search, label: '竞品发现范围', value: '相似产品 + 替代方案' },
  { icon: SlidersHorizontal, label: '默认分析深度', value: '标准：3-5 个竞品' },
  { icon: ShieldCheck, label: '来源优先级', value: '官网、文档、公开报道优先' },
];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [activeSection, setActiveSection] = useState<'analysis' | 'knowledge' | 'appearance'>('analysis');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (
    localStorage.getItem('appearance-theme') === 'dark' ? 'dark' : 'light'
  ));
  const [knowledgeMessage, setKnowledgeMessage] = useState<string | null>(null);

  const clearKnowledgeMutation = useMutation({
    mutationFn: clearKnowledgeItems,
    onSuccess: (result) => {
      setKnowledgeMessage(`已清空知识库，删除 ${result.deleted_count} 条知识。`);
      queryClient.invalidateQueries({ queryKey: ['knowledge-items'] });
    },
    onError: (error) => {
      setKnowledgeMessage(error instanceof Error ? error.message : '清空知识库失败。');
    },
  });

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
          <button
            type="button"
            className={activeSection === 'analysis' ? 'active' : ''}
            onClick={() => setActiveSection('analysis')}
          >
            分析偏好配置
          </button>
          <button
            type="button"
            className={activeSection === 'knowledge' ? 'active' : ''}
            onClick={() => setActiveSection('knowledge')}
          >
            知识库
          </button>
          <button
            type="button"
            className={activeSection === 'appearance' ? 'active' : ''}
            onClick={() => setActiveSection('appearance')}
          >
            外观
          </button>
        </aside>

        <main className="settings-content">
          {activeSection === 'analysis' ? (
            <section className="settings-panel">
              <header className="settings-header">
                <span>分析偏好配置</span>
                <h1>配置默认竞品研究方式</h1>
                <p>这些选项先作为前端默认偏好展示，后续可以接入真实保存逻辑。</p>
              </header>

              <div className="settings-list">
                {analysisItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <div className="settings-row" key={item.label}>
                      <span className="settings-row-icon">
                        <Icon size={17} />
                      </span>
                      <div>
                        <strong>{item.label}</strong>
                        <span>{item.value}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : activeSection === 'knowledge' ? (
            <section className="settings-panel">
              <header className="settings-header">
                <span>知识库</span>
                <h1>管理沉淀知识</h1>
                <p>清空知识库只会删除已沉淀的知识点，不会删除历史任务、来源证据或报告。</p>
              </header>

              <div className="knowledge-settings-card">
                <div className="appearance-card-main">
                  <span className="settings-row-icon">
                    <Database size={17} />
                  </span>
                  <div>
                    <strong>清空知识库</strong>
                    <span>用于重新构建历史知识，或清理演示数据。新的分析完成后仍会自动沉淀。</span>
                  </div>
                </div>
                <button
                  type="button"
                  className="settings-danger-action"
                  disabled={clearKnowledgeMutation.isPending}
                  onClick={() => {
                    if (window.confirm('确定要清空知识库吗？历史任务和报告不会删除，但已沉淀知识会被移除。')) {
                      setKnowledgeMessage(null);
                      clearKnowledgeMutation.mutate();
                    }
                  }}
                >
                  <Trash2 size={16} />
                  {clearKnowledgeMutation.isPending ? '清空中' : '清空知识库'}
                </button>
              </div>
              {knowledgeMessage ? <p className="settings-feedback">{knowledgeMessage}</p> : null}
            </section>
          ) : (
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
          )}
        </main>
      </div>
    </section>
  );
}
