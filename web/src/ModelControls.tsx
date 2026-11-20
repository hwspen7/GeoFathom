import { useEffect, useState, type FormEvent } from 'react';
import { Activity, Check, KeyRound, Pencil, Plus, Settings2, Trash2 } from 'lucide-react';

import {
  deleteModel, getModelCatalog, probeModel, saveModel, selectDefaultModel,
  type ModelCatalog, type ModelDefinition, type ModelDraft, type ModelProvider,
} from './api';

interface Props {
  modelId: string;
  onChange: (modelId: string) => void;
}

const blank: ModelDraft = {
  id: '', name: '', provider: 'ollama', model: '', base_url: 'http://127.0.0.1:11434',
  credential_env: '', enabled: true,
};

const providerLabels: Record<ModelProvider, string> = {
  ollama: 'Ollama (local)',
  'openai-compatible': 'OpenAI-compatible (local or cloud)',
  groq: 'GroqCloud',
  gemini: 'Google Gemini',
};

function draft(model: ModelDefinition): ModelDraft {
  const { id, name, provider, model: tag, base_url, credential_env, enabled } = model;
  return { id, name, provider, model: tag, base_url, credential_env, enabled };
}

export default function ModelControls({ modelId, onChange }: Props) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [managing, setManaging] = useState(false);
  const [token, setToken] = useState('');
  const [form, setForm] = useState<ModelDraft>(blank);
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState('');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let mounted = true;
    getModelCatalog().then(data => {
      if (!mounted) return;
      setCatalog(data);
      onChange(data.default_id);
    }).catch(() => { if (mounted) setResult('Could not load model directory from FastAPI.'); });
    return () => { mounted = false; };
  }, [onChange]);

  const selected = catalog?.models.find(item => item.id === modelId) ?? null;
  const selectedLabel = selected?.provider === 'ollama' ? 'Local' : 'Cloud / compatible API';

  function updateField<Key extends keyof ModelDraft>(key: Key, value: ModelDraft[Key]) {
    setForm(current => ({ ...current, [key]: value }));
  }

  function chooseProvider(provider: ModelProvider) {
    setForm(current => ({
      ...current,
      provider,
      base_url: provider === 'ollama' ? 'http://127.0.0.1:11434'
        : provider === 'openai-compatible' ? 'https://example.com/v1' : '',
      credential_env: provider === 'groq' ? 'GEOFATHOM_GROQ_API_KEY'
        : provider === 'gemini' ? 'GEOFATHOM_GEMINI_API_KEY'
        : provider === 'openai-compatible' ? '' : '',
    }));
  }

  function chooseModel(next: string) {
    onChange(next);
    setReady(false);
    setResult('');
  }

  async function test() {
    if (!selected) return;
    setResult('');
    setReady(false);
    setTesting(true);
    try {
      const response = await probeModel(selected.id);
      setReady(true);
      setResult('Live response: ' + response.intent.action + ' · ' + response.intent.query);
    } catch (error) {
      setResult(error instanceof Error ? error.message : 'Connection test failed.');
    } finally {
      setTesting(false);
    }
  }

  async function persist(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) {
      setResult('Enter the model administration token configured in the server .env.');
      return;
    }
    setSaving(true);
    setResult('');
    try {
      const data = await saveModel(form, token);
      setCatalog(data);
      onChange(form.id);
      setEditing(false);
      setResult('Model configuration saved in the server catalog.');
    } catch (error) {
      setResult(error instanceof Error ? error.message : 'Could not save model.');
    } finally {
      setSaving(false);
    }
  }

  async function setDefault() {
    if (!selected) return;
    setSaving(true);
    setResult('');
    try {
      setCatalog(await selectDefaultModel(selected.id, token));
      setResult('Default model updated for this workspace.');
    } catch (error) {
      setResult(error instanceof Error ? error.message : 'Could not update default.');
    } finally {
      setSaving(false);
    }
  }

  async function removeSelected() {
    if (!selected || selected.preset) return;
    setSaving(true);
    setResult('');
    try {
      const data = await deleteModel(selected.id, token);
      setCatalog(data);
      onChange(data.default_id);
      setEditing(false);
      setResult('Custom model deleted.');
    } catch (error) {
      setResult(error instanceof Error ? error.message : 'Could not delete model.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="model-settings">
      <div className="model-pick">
        <select aria-label="Choose any configured model" value={selected?.id ?? ''} onChange={event => chooseModel(event.target.value)}>
          {(catalog?.models ?? []).map(item => (
            <option key={item.id} value={item.id} disabled={!item.enabled}>
              {item.name}{item.id === catalog?.default_id ? ' (default)' : ''}
            </option>
          ))}
          {!catalog && <option value="">Loading model directory…</option>}
        </select>
        <button type="button" aria-label="Manage models" title="Manage models" onClick={() => setManaging(value => !value)}>
          <Settings2 size={16} />
        </button>
      </div>

      {selected && (
        <div className="model-status">
          <span>{selectedLabel} · {selected.configured ? 'Configured' : 'Needs setup'}</span>
          <button type="button" onClick={() => void test()} disabled={testing || !selected.configured}>
            <Activity size={13} /> {testing ? 'Checking…' : 'Test API'}
          </button>
        </div>
      )}

      {managing && (
        <div className="model-manager">
          <label className="manager-label" htmlFor="model-admin">Configuration access token</label>
          <input id="model-admin" type="password" autoComplete="off" value={token}
            placeholder="GEOFATHOM_MODEL_ADMIN_TOKEN"
            onChange={event => setToken(event.target.value)} />
          <div className="model-manager-actions">
            <button type="button" onClick={() => {
              setForm({ ...blank });
              setEditing(true);
            }}><Plus size={14} /> Add model</button>
            <button type="button" disabled={!selected} onClick={() => {
              if (selected) { setForm(draft(selected)); setEditing(true); }
            }}><Pencil size={14} /> Edit</button>
            <button type="button" disabled={!selected || saving || !token}
              onClick={() => void setDefault()}><Check size={14} /> Set default</button>
          </div>
          {selected && !selected.preset && (
            <button className="model-danger" type="button" disabled={saving || !token}
              onClick={() => void removeSelected()}><Trash2 size={13} /> Delete selected custom model</button>
          )}

          {editing && (
            <form className="model-editor" onSubmit={persist}>
              <label>Identifier
                <input value={form.id} required minLength={2} maxLength={63}
                  placeholder="my-local-model" onChange={event => updateField('id', event.target.value)} />
              </label>
              <label>Display name
                <input value={form.name} required maxLength={100}
                  placeholder="My model" onChange={event => updateField('name', event.target.value)} />
              </label>
              <label>Provider
                <select value={form.provider} onChange={event => chooseProvider(event.target.value as ModelProvider)}>
                  {(Object.keys(providerLabels) as ModelProvider[]).map(provider =>
                    <option key={provider} value={provider}>{providerLabels[provider]}</option>)}
                </select>
              </label>
              <label>Model identifier / installed tag
                <input value={form.model} required maxLength={180}
                  placeholder="model-id" onChange={event => updateField('model', event.target.value)} />
              </label>
              {(form.provider === 'ollama' || form.provider === 'openai-compatible') && (
                <label>API base URL
                  <input value={form.base_url} required maxLength={500}
                    placeholder="http://127.0.0.1:11434"
                    onChange={event => updateField('base_url', event.target.value)} />
                </label>
              )}
              {form.provider !== 'ollama' && (
                <label>Server-side API key variable
                  <input value={form.credential_env} maxLength={85}
                    placeholder="GEOFATHOM_MODEL_KEY_VENDOR"
                    onChange={event => updateField('credential_env', event.target.value)} />
                </label>
              )}
              <label className="model-check"><input type="checkbox" checked={form.enabled}
                onChange={event => updateField('enabled', event.target.checked)} /> Enabled</label>
              <p className="project-hint">Put any API key under the named variable in the server .env file, not in this form or the repository. Local Ollama needs no key.</p>
              <div className="model-manager-actions">
                <button type="submit" disabled={saving || !token || !form.id || !form.model}>
                  {saving ? 'Saving…' : 'Save model'}
                </button>
                <button type="button" onClick={() => setEditing(false)}>Cancel</button>
              </div>
            </form>
          )}
          <p className="project-hint">The initial three entries are editable presets, not a fixed model limit. Custom entries are stored locally on your FastAPI server.</p>
        </div>
      )}
      {result && <p className={ready ? 'model-test-ready' : 'model-test-error'}>{result}</p>}
    </div>
  );
}
