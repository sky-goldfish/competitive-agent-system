import { useEffect, useState } from 'react';
import { Bot, KeyRound, Moon, Save, Search, Sun } from 'lucide-react';
import { getAPISettings, saveAPISettings, type APISettings, type APISettingsInput } from '../lib/api';

type SettingsTab = 'appearance' | 'api';

const defaultApiForm: APISettingsInput = {
  llm: {
    provider: 'mock',
    ark_api_key: '',
    ark_endpoint_id: '',
    ark_model: 'doubao-seed-2-0-lite',
    ark_base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    openai_api_key: '',
    openai_model: '',
    openai_base_url: 'https://api.openai.com/v1',
    openai_temperature: null,
  },
  search: {
    provider: 'mock',
    tavily_api_key: '',
    bocha_api_key: '',
    enable_mock_search_fallback: true,
  },
};

export default function SettingsPage() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (
    localStorage.getItem('appearance-theme') === 'dark' ? 'dark' : 'light'
  ));
  const [activeTab, setActiveTab] = useState<SettingsTab>('appearance');
  const [apiSettings, setApiSettings] = useState<APISettings | null>(null);
  const [apiForm, setApiForm] = useState<APISettingsInput>(defaultApiForm);
  const [apiLoading, setApiLoading] = useState(false);
  const [apiSaving, setApiSaving] = useState(false);
  const [apiMessage, setApiMessage] = useState('');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('appearance-theme', theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    setApiLoading(true);
    getAPISettings()
      .then((settings) => {
        if (cancelled) return;
        setApiSettings(settings);
        setApiForm(settingsToForm(settings));
      })
      .catch((error: Error) => {
        if (!cancelled) setApiMessage(error.message || '读取 API 设置失败');
      })
      .finally(() => {
        if (!cancelled) setApiLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSaveApiSettings = async () => {
    setApiSaving(true);
    setApiMessage('');
    try {
      const saved = await saveAPISettings(apiForm);
      setApiSettings(saved);
      setApiForm(settingsToForm(saved));
      const llm = providerLabel(saved.llm.effective_provider);
      const search = providerLabel(saved.search.effective_provider);
      setApiMessage(`已保存。当前生效：LLM ${llm}，Search ${search}。`);
    } catch (error) {
      setApiMessage(error instanceof Error ? error.message : '保存 API 设置失败');
    } finally {
      setApiSaving(false);
    }
  };

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
            className={activeTab === 'appearance' ? 'active' : ''}
            onClick={() => setActiveTab('appearance')}
          >
            外观
          </button>
          <button
            type="button"
            className={activeTab === 'api' ? 'active' : ''}
            onClick={() => setActiveTab('api')}
          >
            API 设置
          </button>
        </aside>

        <main className="settings-content">
          {activeTab === 'appearance' ? (
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
          ) : (
            <section className="settings-panel">
              <header className="settings-header">
                <span>API 设置</span>
                <h1>接入模型与搜索</h1>
                <p>填写 LLM 和搜索服务的 API Key 后，新创建的分析任务会使用对应服务。Key 留空并保存时会切回 Mock。</p>
              </header>

              {apiLoading ? (
                <p className="settings-feedback">正在读取当前环境配置...</p>
              ) : (
                <div className="api-settings-grid">
                  <section className="api-settings-card">
                    <div className="api-settings-card-head">
                      <span className="settings-row-icon"><Bot size={17} /></span>
                      <div>
                        <strong>LLM</strong>
                        <span>当前生效：{providerLabel(apiSettings?.llm.effective_provider ?? 'mock')}</span>
                      </div>
                    </div>

                    <label className="settings-field">
                      <span>调用方式</span>
                      <select
                        value={apiForm.llm.provider}
                        onChange={(event) => setApiForm((current) => ({
                          ...current,
                          llm: { ...current.llm, provider: event.target.value },
                        }))}
                      >
                        <option value="mock">Mock</option>
                        <option value="ark">方舟 API</option>
                        <option value="openai">OpenAI 兼容 API</option>
                      </select>
                    </label>

                    <div className="settings-field-group">
                      <div className="settings-field-group-title">
                        <KeyRound size={15} />
                        <span>方舟 API</span>
                      </div>
                      <label className="settings-field">
                        <span>ARK_API_KEY</span>
                        <input
                          type="password"
                          autoComplete="off"
                          value={apiForm.llm.ark_api_key}
                          placeholder={secretPlaceholder(apiSettings?.llm.ark_api_key)}
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, ark_api_key: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="settings-field">
                        <span>ARK_ENDPOINT_ID</span>
                        <input
                          value={apiForm.llm.ark_endpoint_id}
                          placeholder="ep-xxxxxxxx"
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, ark_endpoint_id: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="settings-field">
                        <span>ARK_MODEL</span>
                        <input
                          value={apiForm.llm.ark_model}
                          placeholder="doubao-seed-2-0-lite"
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, ark_model: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="settings-field">
                        <span>ARK_BASE_URL</span>
                        <input
                          value={apiForm.llm.ark_base_url}
                          placeholder="https://ark.cn-beijing.volces.com/api/v3"
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, ark_base_url: event.target.value },
                          }))}
                        />
                      </label>
                    </div>

                    <div className="settings-field-group">
                      <div className="settings-field-group-title">
                        <KeyRound size={15} />
                        <span>OpenAI 兼容 API</span>
                      </div>
                      <label className="settings-field">
                        <span>OPENAI_API_KEY</span>
                        <input
                          type="password"
                          autoComplete="off"
                          value={apiForm.llm.openai_api_key}
                          placeholder={secretPlaceholder(apiSettings?.llm.openai_api_key)}
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, openai_api_key: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="settings-field">
                        <span>OPENAI_MODEL</span>
                        <input
                          value={apiForm.llm.openai_model}
                          placeholder="gpt-4o-mini"
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, openai_model: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="settings-field">
                        <span>OPENAI_BASE_URL</span>
                        <input
                          value={apiForm.llm.openai_base_url}
                          placeholder="https://api.openai.com/v1"
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: { ...current.llm, openai_base_url: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="settings-field">
                        <span>OPENAI_TEMPERATURE</span>
                        <input
                          type="number"
                          min="0"
                          max="2"
                          step="0.1"
                          value={apiForm.llm.openai_temperature ?? ''}
                          placeholder="默认"
                          onChange={(event) => setApiForm((current) => ({
                            ...current,
                            llm: {
                              ...current.llm,
                              openai_temperature: event.target.value === '' ? null : Number(event.target.value),
                            },
                          }))}
                        />
                      </label>
                    </div>
                  </section>

                  <section className="api-settings-card">
                    <div className="api-settings-card-head">
                      <span className="settings-row-icon"><Search size={17} /></span>
                      <div>
                        <strong>Search</strong>
                        <span>当前生效：{providerLabel(apiSettings?.search.effective_provider ?? 'mock')}</span>
                      </div>
                    </div>

                    <label className="settings-field">
                      <span>搜索服务</span>
                      <select
                        value={apiForm.search.provider}
                        onChange={(event) => setApiForm((current) => ({
                          ...current,
                          search: { ...current.search, provider: event.target.value },
                        }))}
                      >
                        <option value="mock">Mock</option>
                        <option value="tavily">Tavily</option>
                        <option value="bocha">Bocha</option>
                      </select>
                    </label>

                    <label className="settings-field">
                      <span>TAVILY_API_KEY</span>
                      <input
                        type="password"
                        autoComplete="off"
                        value={apiForm.search.tavily_api_key}
                        placeholder={secretPlaceholder(apiSettings?.search.tavily_api_key)}
                        onChange={(event) => setApiForm((current) => ({
                          ...current,
                          search: { ...current.search, tavily_api_key: event.target.value },
                        }))}
                      />
                    </label>

                    <label className="settings-field">
                      <span>BOCHA_API_KEY</span>
                      <input
                        type="password"
                        autoComplete="off"
                        value={apiForm.search.bocha_api_key}
                        placeholder={secretPlaceholder(apiSettings?.search.bocha_api_key)}
                        onChange={(event) => setApiForm((current) => ({
                          ...current,
                          search: { ...current.search, bocha_api_key: event.target.value },
                        }))}
                      />
                    </label>

                    <label className="settings-check-row">
                      <input
                        type="checkbox"
                        checked={apiForm.search.enable_mock_search_fallback}
                        onChange={(event) => setApiForm((current) => ({
                          ...current,
                          search: { ...current.search, enable_mock_search_fallback: event.target.checked },
                        }))}
                      />
                      <span>搜索失败或缺少 Key 时允许回退到 Mock</span>
                    </label>

                    <p className="api-settings-note">
                      配置文件：{apiSettings?.env_path ?? 'backend/.env'}
                    </p>
                  </section>
                </div>
              )}

              <div className="settings-actions">
                <button
                  type="button"
                  className="primary-action"
                  onClick={handleSaveApiSettings}
                  disabled={apiLoading || apiSaving}
                >
                  <Save size={16} />
                  {apiSaving ? '保存中' : '保存 API 设置'}
                </button>
                <span>留空保存会把对应服务设为 Mock。</span>
              </div>

              {apiMessage ? <p className="settings-feedback">{apiMessage}</p> : null}
            </section>
          )}
        </main>
      </div>
    </section>
  );
}

function settingsToForm(settings: APISettings): APISettingsInput {
  return {
    llm: {
      provider: settings.llm.provider,
      ark_api_key: '',
      ark_endpoint_id: settings.llm.ark_endpoint_id,
      ark_model: settings.llm.ark_model || 'doubao-seed-2-0-lite',
      ark_base_url: settings.llm.ark_base_url || 'https://ark.cn-beijing.volces.com/api/v3',
      openai_api_key: '',
      openai_model: settings.llm.openai_model,
      openai_base_url: settings.llm.openai_base_url || 'https://api.openai.com/v1',
      openai_temperature: settings.llm.openai_temperature,
    },
    search: {
      provider: settings.search.provider,
      tavily_api_key: '',
      bocha_api_key: '',
      enable_mock_search_fallback: settings.search.enable_mock_search_fallback,
    },
  };
}

function secretPlaceholder(secret?: { configured: boolean; masked: string }) {
  if (!secret?.configured) return '未填写，保存后使用 Mock';
  return `已配置：${secret.masked}，重新输入会覆盖`;
}

function providerLabel(provider: string) {
  const labels: Record<string, string> = {
    mock: 'Mock',
    ark: '方舟 API',
    openai: 'OpenAI 兼容 API',
    tavily: 'Tavily',
    bocha: 'Bocha',
  };
  return labels[provider] ?? provider;
}
