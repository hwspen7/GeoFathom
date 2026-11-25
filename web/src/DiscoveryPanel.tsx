import { useState, type FormEvent } from 'react';
import { ScanSearch } from 'lucide-react';

import { discoverFeatures, type DiscoveryResponse } from './api';

interface Props {
  viewport: [number, number, number, number] | null;
  busy: boolean;
  onFound: (result: DiscoveryResponse) => void;
}

export default function DiscoveryPanel({ viewport, busy, onFound }: Props) {
  const [category, setCategory] = useState<'building' | 'landuse' | 'water'>('building');
  const [minimum, setMinimum] = useState('1000');
  const [maximum, setMaximum] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!viewport) return;
    setError('');
    setLoading(true);
    try {
      const result = await discoverFeatures({
        bbox: viewport,
        category,
        minimum_area_m2: Number(minimum || 0),
        maximum_area_m2: maximum === '' ? null : Number(maximum),
      });
      onFound(result);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Could not search this area.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="discovery-form">
      <p className="discovery-explainer">Find mapped polygons by area within the current map view. Zoom in before searching.</p>
      <label htmlFor="category">Feature class</label>
      <select id="category" value={category} onChange={event => setCategory(event.target.value as typeof category)}>
        <option value="building">Buildings</option>
        <option value="landuse">Land use</option>
        <option value="water">Water bodies</option>
      </select>
      <div className="area-fields">
        <div><label htmlFor="minimum-area">Min area (m²)</label><input id="minimum-area" type="number" min="0" step="1" value={minimum} onChange={event => setMinimum(event.target.value)} /></div>
        <div><label htmlFor="maximum-area">Max area (m²)</label><input id="maximum-area" type="number" min="0" step="1" placeholder="No limit" value={maximum} onChange={event => setMaximum(event.target.value)} /></div>
      </div>
      <button type="submit" disabled={!viewport || busy || loading} className="discovery-submit">
        <ScanSearch size={15} /> {loading ? 'Searching features…' : 'Find matching areas'}
      </button>
      {error && <p className="discovery-error">{error}</p>}
      <p className="discovery-caution">OpenStreetMap ways only. Results may be incomplete and are not legal parcels.</p>
    </form>
  );
}
