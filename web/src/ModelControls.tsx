import { useState } from 'react';
import { Activity, Cloud, KeyRound } from 'lucide-react';

import { probeModel, type Capabilities } from './api';

type Profile = 'default' | 'analysis';

interface Props {
  capabilities: Capabilities | null;
  profile: Profile;
  onChange: (profile: Profile) => void;
}

export default function ModelControls({ capabilities, profile, onChange }: Props) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState('');
  const [ready, setReady] = useState(false);
  const configured = profile === 'default'
    ? Boolean(capabilities?.llm_configured)
    : Boolean(capabilities?.analysis_configured);

  function select(next: Profile) {
    onChange(next);
    setResult('');
    setReady(false);
  }

  async function test() {
    setResult('');
    setTesting(true);
    setReady(false);
    try {
      const response = await probeModel(profile);
      setResult('Live API response received: ' + response.intent.action + ' · ' + response.intent.query);
      setReady(true);
    } catch (error) {
      setResult(error instanceof Error ? error.message : 'Model API test failed.');
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="model-settings">
      <div className="model-switch">
        <button type="button" className={profile === 'default' ? 'selected' : ''} onClick={() => select('default')}>
          {capabilities?.llm_model || 'GPT-OSS 120B'}
        </button>
        <button type="button" className={profile === 'analysis' ? 'selected' : ''} onClick={() => select('analysis')}>
          {capabilities?.analysis_model || 'Gemini 3.8 Flash'}
        </button>
      </div>
      <div className="model-status">
        {configured
          ? <span><Cloud size={13} /> Model configured (not yet checked)</span>
          : <span><KeyRound size={13} /> Add API key to server .env</span>}
        <button type="button" onClick={() => void test()} disabled={!configured || testing}>
          <Activity size={13} /> {testing ? 'Checking…' : 'Test API'}
        </button>
      </div>
      {result && <p className={ready ? 'model-test-ready' : 'model-test-error'}>{result}</p>}
    </div>
  );
}
